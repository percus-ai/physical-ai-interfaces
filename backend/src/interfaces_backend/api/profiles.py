"""VLAbor profile selection API."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from interfaces_backend.models.profile import (
    ProfileDeviceStatusArm,
    ProfileDeviceStatusCamera,
    VlaborActiveProfileResponse,
    VlaborActiveProfileStatusResponse,
    VlaborProfileSelectRequest,
    VlaborProfilesResponse,
    VlaborProfileSummary,
    VlaborStatusResponse,
)
from interfaces_backend.services.vlabor_profiles import (
    extract_status_arm_specs,
    extract_status_camera_specs,
    get_active_profile_spec,
    list_vlabor_profiles,
    set_active_profile_spec,
)
from interfaces_backend.services.vlabor_runtime import (
    VlaborCommandError,
    restart_vlabor,
    stream_vlabor_script,
)
from interfaces_backend.utils.docker_compose import (
    build_compose_command,
    get_vlabor_compose_file,
    get_vlabor_env_file,
)
from percus_ai.db import get_current_user_id

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _require_user_id() -> str:
    try:
        return get_current_user_id()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Login required") from exc


def _get_vlabor_compose_cmd(*, strict: bool) -> tuple[list[str], Path]:
    compose_file = get_vlabor_compose_file()
    if strict and not compose_file.exists():
        raise HTTPException(status_code=500, detail=f"{compose_file} not found")
    return build_compose_command(compose_file, get_vlabor_env_file()), compose_file


def _get_vlabor_status() -> dict:
    compose_cmd, compose_file = _get_vlabor_compose_cmd(strict=False)
    if not compose_file.exists():
        return {"status": "unknown", "service": "vlabor"}

    result = subprocess.run(
        [*compose_cmd, "ps", "--format", "json", "vlabor"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {"status": "unknown", "service": "vlabor"}
    try:
        data = json.loads(result.stdout)
    except Exception:
        return {"status": "unknown", "service": "vlabor"}

    entry = None
    if isinstance(data, list):
        entry = data[0] if data else None
    elif isinstance(data, dict):
        entry = data

    if not entry:
        return {"status": "unknown", "service": "vlabor"}

    state_raw = (entry.get("State") or "").lower()
    status_value = "unknown"
    if "restarting" in state_raw:
        status_value = "restarting"
    elif "running" in state_raw:
        status_value = "running"
    elif "exited" in state_raw or "stopped" in state_raw:
        status_value = "stopped"
    hostname = socket.gethostname()
    dashboard_url = f"http://{hostname}.local:8888"

    return {
        "status": status_value,
        "service": "vlabor",
        "state": entry.get("State"),
        "status_detail": entry.get("Status"),
        "running_for": entry.get("RunningFor"),
        "created_at": entry.get("CreatedAt"),
        "container_id": entry.get("ID"),
        "dashboard_url": dashboard_url,
    }


def _fetch_ros2_topics() -> list[str]:
    compose_cmd, compose_file = _get_vlabor_compose_cmd(strict=False)
    if not compose_file.exists():
        return []
    cmd = [
        *compose_cmd,
        "exec",
        "-T",
        "vlabor",
        "bash",
        "-lc",
        "source /opt/ros/humble/setup.sh && ros2 topic list",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


async def _stream_script_to_websocket(
    websocket: WebSocket,
    *,
    script_name: str,
    args: list[str],
    timeout: int,
) -> tuple[bool, str | None]:
    queue: asyncio.Queue[dict[str, str] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _run() -> None:
        for event in stream_vlabor_script(script_name, args, timeout=timeout):
            loop.call_soon_threadsafe(queue.put_nowait, event)
        loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

    loop.run_in_executor(None, _run)

    saw_complete = False
    exit_code = ""
    error_message: str | None = None
    while True:
        event = await queue.get()
        if event is None:
            break
        await websocket.send_json(event)
        event_type = str(event.get("type") or "").strip().lower()
        if event_type == "complete":
            saw_complete = True
            exit_code = str(event.get("exit_code") or "").strip()
        elif event_type == "error":
            error_message = str(event.get("message") or "Unknown error").strip()

    if error_message:
        return False, error_message
    if not saw_complete:
        return False, "VLAbor script finished without completion status"
    if exit_code != "0":
        return False, f"exit code={exit_code or 'unknown'}"
    return True, None


@router.get("", response_model=VlaborProfilesResponse)
async def list_profiles():
    _require_user_id()
    profiles = list_vlabor_profiles()
    active = await get_active_profile_spec()
    items = [
        VlaborProfileSummary(
            name=profile.name,
            description=profile.description,
            updated_at=profile.updated_at,
            source_path=profile.source_path,
        )
        for profile in profiles
    ]
    return VlaborProfilesResponse(
        profiles=items,
        active_profile_name=active.name if active else None,
        total=len(items),
    )


@router.get("/active", response_model=VlaborActiveProfileResponse)
async def get_active_profile():
    _require_user_id()
    active = await get_active_profile_spec()
    return VlaborActiveProfileResponse(
        profile_name=active.name,
        profile_snapshot=active.snapshot,
    )


@router.put("/active", response_model=VlaborActiveProfileResponse)
async def set_active_profile(request: VlaborProfileSelectRequest):
    _require_user_id()
    previous = await get_active_profile_spec()
    active = await set_active_profile_spec(request.profile_name)
    try:
        await asyncio.to_thread(restart_vlabor, profile=active.name, strict=True)
    except VlaborCommandError as exc:
        rollback_messages: list[str] = []
        try:
            await set_active_profile_spec(previous.name)
            rollback_messages.append(f"active profile reverted to {previous.name}")
        except Exception as rollback_exc:  # noqa: BLE001 - API detail
            rollback_messages.append(f"failed to revert active profile: {rollback_exc}")

        try:
            rollback_result = await asyncio.to_thread(
                restart_vlabor,
                profile=previous.name,
                strict=False,
            )
            if rollback_result.returncode == 0:
                rollback_messages.append("VLAbor runtime rollback succeeded")
            else:
                detail = (rollback_result.stderr or rollback_result.stdout).strip()
                if not detail:
                    detail = f"exit code={rollback_result.returncode}"
                rollback_messages.append(f"VLAbor runtime rollback failed: {detail}")
        except Exception as rollback_exc:  # noqa: BLE001 - API detail
            rollback_messages.append(f"failed to run runtime rollback: {rollback_exc}")

        detail = f"Failed to restart VLAbor with profile {active.name}: {exc}"
        if rollback_messages:
            detail = f"{detail} ({'; '.join(rollback_messages)})"
        raise HTTPException(status_code=500, detail=detail) from exc

    return VlaborActiveProfileResponse(
        profile_name=active.name,
        profile_snapshot=active.snapshot,
    )


@router.get("/active/status", response_model=VlaborActiveProfileStatusResponse)
async def get_active_profile_status():
    _require_user_id()
    active = await get_active_profile_spec()
    topics = _fetch_ros2_topics()
    topic_set = set(topics)

    cameras = []
    for spec in extract_status_camera_specs(active.snapshot):
        name = str(spec.get("name") or "").strip()
        if not name:
            continue
        expected_topics = [str(item).strip() for item in (spec.get("topics") or []) if str(item).strip()]
        if not expected_topics:
            expected_topics = [f"/{name}/image_raw", f"/{name}/image_raw/compressed"]
        connected_topic = next((item for item in expected_topics if item in topic_set), None)
        cameras.append(
            ProfileDeviceStatusCamera(
                name=name,
                label=str(spec.get("label") or "").strip() or name,
                enabled=bool(spec.get("enabled", True)),
                connected=bool(connected_topic),
                connected_topic=connected_topic,
                topics=expected_topics,
            )
        )

    arms = []
    for spec in extract_status_arm_specs(active.snapshot):
        namespace = str(spec.get("name") or "").strip()
        if not namespace:
            continue
        expected_topics = [str(item).strip() for item in (spec.get("topics") or []) if str(item).strip()]
        if not expected_topics:
            expected_topics = [f"/{namespace}/joint_states", f"/{namespace}/joint_states_single"]
        connected_topic = next((item for item in expected_topics if item in topic_set), None)
        arms.append(
            ProfileDeviceStatusArm(
                name=namespace,
                label=str(spec.get("label") or "").strip() or namespace,
                role=str(spec.get("role") or "").strip() or None,
                enabled=bool(spec.get("enabled", True)),
                connected=bool(connected_topic),
                connected_topic=connected_topic,
                topics=expected_topics,
            )
        )

    return VlaborActiveProfileStatusResponse(
        profile_name=active.name,
        profile_snapshot=active.snapshot,
        cameras=cameras,
        arms=arms,
        topics=topics,
    )


@router.get("/vlabor/status", response_model=VlaborStatusResponse)
async def get_vlabor_status():
    return VlaborStatusResponse(**_get_vlabor_status())


@router.websocket("/ws/vlabor/restart")
async def websocket_restart_vlabor(websocket: WebSocket):
    """Stream VLAbor restart progress in real-time.

    Messages:
      {"type": "log", "line": "..."}
      {"type": "complete", "exit_code": "0"}
      {"type": "error", "message": "..."}
    """
    await websocket.accept()
    try:
        requested_profile = str(websocket.query_params.get("profile") or "").strip()
        profile_name = requested_profile
        if requested_profile:
            available = {profile.name for profile in list_vlabor_profiles()}
            if requested_profile not in available:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"VLAbor profile not found: {requested_profile}",
                    }
                )
                return
        else:
            active = await get_active_profile_spec()
            profile_name = active.name
        await websocket.send_json(
            {"type": "log", "line": f"Restarting VLAbor with profile: {profile_name}"}
        )
        args: list[str] = [profile_name] if profile_name else []
        await _stream_script_to_websocket(
            websocket,
            script_name="restart",
            args=args,
            timeout=300,
        )
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/vlabor/switch-profile")
async def websocket_switch_profile(websocket: WebSocket):
    """Switch active profile and stream VLAbor restart logs."""
    await websocket.accept()
    try:
        requested_profile = str(websocket.query_params.get("profile") or "").strip()
        if not requested_profile:
            await websocket.send_json(
                {"type": "error", "message": "profile query parameter is required"}
            )
            return

        available = {profile.name for profile in list_vlabor_profiles()}
        if requested_profile not in available:
            await websocket.send_json(
                {"type": "error", "message": f"VLAbor profile not found: {requested_profile}"}
            )
            return

        previous = await get_active_profile_spec()
        await websocket.send_json(
            {
                "type": "log",
                "line": f"Switching active profile: {previous.name} -> {requested_profile}",
            }
        )

        active = await set_active_profile_spec(requested_profile)
        await websocket.send_json(
            {"type": "log", "line": f"Restarting VLAbor with profile: {active.name}"}
        )
        switched, switch_detail = await _stream_script_to_websocket(
            websocket,
            script_name="restart",
            args=[active.name],
            timeout=300,
        )
        if switched:
            return

        await websocket.send_json(
            {
                "type": "log",
                "line": (
                    f"Switch failed ({switch_detail or 'unknown'}). "
                    f"Rolling back to profile: {previous.name}"
                ),
            }
        )
        try:
            await set_active_profile_spec(previous.name)
            await websocket.send_json(
                {"type": "log", "line": f"Active profile reverted to: {previous.name}"}
            )
        except Exception as exc:  # noqa: BLE001 - send precise API detail
            await websocket.send_json(
                {"type": "error", "message": f"Failed to revert active profile: {exc}"}
            )
            return

        await websocket.send_json(
            {"type": "log", "line": f"Restarting VLAbor with rollback profile: {previous.name}"}
        )
        rollback_ok, rollback_detail = await _stream_script_to_websocket(
            websocket,
            script_name="restart",
            args=[previous.name],
            timeout=300,
        )
        if not rollback_ok:
            await websocket.send_json(
                {"type": "error", "message": f"Rollback restart failed: {rollback_detail}"}
            )
            return
        await websocket.send_json(
            {
                "type": "error",
                "message": f"Failed to switch profile to {active.name}: {switch_detail}",
            }
        )
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
