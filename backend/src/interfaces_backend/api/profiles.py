"""VLAbor profile selection API."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException

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
    extract_arm_namespaces,
    extract_camera_specs,
    get_active_profile_spec,
    list_vlabor_profiles,
    set_active_profile_spec,
)
from interfaces_backend.services.vlabor_runtime import VlaborCommandError, restart_vlabor
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
    return {
        "status": status_value,
        "service": "vlabor",
        "state": entry.get("State"),
        "status_detail": entry.get("Status"),
        "running_for": entry.get("RunningFor"),
        "created_at": entry.get("CreatedAt"),
        "container_id": entry.get("ID"),
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
    active = await set_active_profile_spec(request.profile_name)
    await asyncio.to_thread(restart_vlabor, profile=active.name, strict=False)
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
    for spec in extract_camera_specs(active.snapshot):
        name = str(spec.get("name") or "").strip()
        if not name:
            continue
        topic = str(spec.get("topic") or "").strip()
        expected_topics = [topic] if topic else [f"/{name}/image_raw", f"/{name}/image_raw/compressed"]
        connected = any(item in topic_set for item in expected_topics)
        cameras.append(
            ProfileDeviceStatusCamera(
                name=name,
                enabled=bool(spec.get("enabled", True)),
                connected=connected,
                topics=expected_topics,
            )
        )

    arms = []
    for namespace in extract_arm_namespaces(active.snapshot):
        expected = f"/{namespace}/joint_states"
        connected = expected in topic_set or f"/{namespace}/joint_states_single" in topic_set
        arms.append(
            ProfileDeviceStatusArm(
                name=namespace,
                enabled=True,
                connected=connected,
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


@router.post("/vlabor/restart")
async def restart_vlabor_container():
    _require_user_id()
    active = await get_active_profile_spec()
    try:
        await asyncio.to_thread(restart_vlabor, profile=active.name, strict=True)
    except VlaborCommandError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"success": True, "message": f"VLAbor restarted with profile {active.name}"}
