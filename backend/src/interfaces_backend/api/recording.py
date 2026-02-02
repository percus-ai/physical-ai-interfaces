"""Recording API router (lerobot_session_recorder WebAPI bridge)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from percus_ai.db import get_current_user_id, get_supabase_async_client, upsert_with_owner
from percus_ai.profiles import ProfileRegistry
from percus_ai.profiles.models import ProfileInstance
from percus_ai.storage.naming import generate_dataset_id, validate_dataset_name
from percus_ai.storage.paths import get_datasets_dir, get_project_root, get_user_config_path
from percus_ai.storage.r2_db_sync import R2DBSyncService
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recording", tags=["recording"])

_RECORDER_URL = os.environ.get("LEROBOT_RECORDER_URL", "http://127.0.0.1:8082")
_sync_service: Optional[R2DBSyncService] = None


class RecordingSessionStartRequest(BaseModel):
    dataset_name: str = Field(..., description="Dataset display name")
    task: str = Field(..., description="Task description")
    num_episodes: int = Field(1, ge=1, description="Number of episodes")
    episode_time_s: float = Field(60.0, gt=0, description="Episode length in seconds")
    reset_time_s: float = Field(10.0, ge=0, description="Reset wait time in seconds")


class RecordingSessionStopRequest(BaseModel):
    dataset_id: Optional[str] = Field(None, description="Dataset ID (UUID)")
    save_current: bool = Field(True, description="Save current episode before stopping")


class RecordingSessionActionResponse(BaseModel):
    success: bool
    message: str
    dataset_id: Optional[str] = None
    status: Optional[Dict[str, Any]] = None


class RecordingSessionStatusResponse(BaseModel):
    dataset_id: Optional[str] = None
    status: Dict[str, Any]


class RecordingInfo(BaseModel):
    recording_id: str
    dataset_name: str
    profile_instance_id: Optional[str] = None
    created_at: Optional[str] = None
    episode_count: int = 0
    size_bytes: int = 0


class RecordingListResponse(BaseModel):
    recordings: List[RecordingInfo]
    total: int


class RecordingValidateResponse(BaseModel):
    recording_id: str
    is_valid: bool
    errors: List[str] = []
    warnings: List[str] = []


def _require_user_id() -> str:
    try:
        return get_current_user_id()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Login required") from exc


def _get_sync_service() -> R2DBSyncService:
    global _sync_service
    if _sync_service is None:
        _sync_service = R2DBSyncService()
    return _sync_service


def _load_user_config() -> dict:
    path = get_user_config_path()
    if not path.exists():
        return {"auto_upload_after_recording": True}
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    sync = raw.get("sync", {})
    return {
        "auto_upload_after_recording": sync.get("auto_upload_after_recording", True),
    }


def _start_recorder() -> None:
    repo_root = get_project_root()
    compose_file = repo_root / "docker-compose.ros2.yml"
    if not compose_file.exists():
        raise HTTPException(status_code=500, detail="docker-compose.ros2.yml not found")
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "up", "-d"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"lerobot-ros2 start failed: {result.stderr.strip()}")


def _get_compose_service_state(service: str) -> dict:
    repo_root = get_project_root()
    compose_file = repo_root / "docker-compose.ros2.yml"
    if not compose_file.exists():
        return {}
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "ps", "--format", "json", service],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout:
        return {}
    try:
        data = json.loads(result.stdout)
    except Exception:
        return {}
    if isinstance(data, list):
        return data[0] if data else {}
    if isinstance(data, dict):
        return data
    return {}


def _ensure_recorder_running() -> None:
    try:
        _call_recorder("/api/session/status")
        return
    except HTTPException as exc:
        if exc.status_code != 503:
            raise

    _start_recorder()
    service_state = _get_compose_service_state("lerobot-ros2")
    if service_state:
        state_raw = (service_state.get("State") or "").lower()
        if "running" not in state_raw:
            detail = service_state.get("Status") or service_state.get("State") or "unknown"
            raise HTTPException(status_code=503, detail=f"lerobot-ros2 not running: {detail}")
    deadline = time.time() + 60
    last_error: Optional[HTTPException] = None
    while time.time() < deadline:
        try:
            _call_recorder("/api/session/status")
            return
        except HTTPException as exc:
            last_error = exc
            if exc.status_code != 503:
                raise
        time.sleep(1)

    detail = "Recorder unreachable after start"
    if last_error and last_error.detail:
        detail = f"{detail}: {last_error.detail}"
    raise HTTPException(status_code=503, detail=detail)


def _call_recorder(path: str, payload: Optional[dict] = None) -> dict:
    url = f"{_RECORDER_URL}{path}"
    data = None
    headers = {}
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else str(exc)
        raise HTTPException(status_code=exc.code, detail=detail) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=503, detail=f"Recorder unreachable: {exc}") from exc
    try:
        return json.loads(body) if body else {}
    except json.JSONDecodeError:
        return {"raw": body}


def _row_to_profile_instance(row: dict) -> ProfileInstance:
    return ProfileInstance(
        id=row.get("id"),
        class_id=row.get("class_id"),
        class_version=row.get("class_version") or 1,
        name=row.get("name") or "active",
        variables=row.get("variables") or {},
        metadata=row.get("metadata") or {},
        thumbnail_key=row.get("thumbnail_key"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _resolve_profile_settings(profile_class, instance: ProfileInstance) -> dict:
    settings: dict = {}
    if profile_class.defaults:
        settings.update(profile_class.defaults)
    if instance.variables:
        settings.update(instance.variables)
    return settings


def _render_value(value, settings: dict):
    if isinstance(value, str) and "${" in value:
        rendered = value
        for key, val in settings.items():
            rendered = rendered.replace(f"${{{key}}}", str(val))
        return rendered
    return value


def _extract_camera_specs(profile_class, settings: dict) -> list[dict]:
    cameras = []
    profile = profile_class.profile or {}
    actions = profile.get("actions") or []
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("type") != "include":
            continue
        package = action.get("package")
        if package not in ("fv_camera", "fv_realsense"):
            continue
        args = action.get("args") or {}
        node_name = _render_value(args.get("node_name"), settings) or ""
        enabled_raw = action.get("enabled", True)
        enabled = bool(_render_value(enabled_raw, settings))
        if not node_name:
            continue
        cameras.append({
            "name": node_name,
            "package": package,
            "enabled": enabled,
        })
    return cameras


def _build_recorder_cameras(profile_class, instance: ProfileInstance) -> tuple[list[dict], dict]:
    settings = _resolve_profile_settings(profile_class, instance)
    specs = _extract_camera_specs(profile_class, settings)
    cameras: list[dict] = []
    for spec in specs:
        if not spec.get("enabled", True):
            continue
        name = spec.get("name")
        if not name:
            continue
        if spec.get("package") == "fv_realsense":
            topic = f"/{name}/color/image_raw/compressed"
        else:
            topic = f"/{name}/image_raw/compressed"
        cameras.append({"name": name, "topic": topic})
    return cameras, settings


def _build_arm_namespaces(settings: dict) -> list[str]:
    namespaces: list[str] = []
    if bool(settings.get("left_arm_enabled", True)):
        namespaces.append("left_arm")
    if bool(settings.get("right_arm_enabled", True)):
        namespaces.append("right_arm")
    return namespaces


async def _resolve_profile_instance(profile_instance_id: Optional[str]) -> ProfileInstance:
    client = await get_supabase_async_client()
    if profile_instance_id:
        rows = (
            await client.table("profile_instances")
            .select("*")
            .eq("id", profile_instance_id)
            .limit(1)
            .execute()
        ).data or []
    else:
        rows = (
            await client.table("profile_instances")
            .select("*")
            .eq("is_active", True)
            .limit(1)
            .execute()
        ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Profile instance not found")
    return _row_to_profile_instance(rows[0])


async def _upsert_dataset_record(
    dataset_id: str,
    dataset_name: str,
    task: str,
    profile_instance: ProfileInstance,
    status: str,
) -> None:
    payload = {
        "id": dataset_id,
        "name": dataset_name,
        "dataset_type": "recorded",
        "source": "local",
        "status": status,
        "task_detail": task,
        "profile_instance_id": profile_instance.id,
        "profile_snapshot": profile_instance.snapshot(),
    }
    await upsert_with_owner("datasets", "id", payload)


async def _update_dataset_stats(dataset_id: str) -> None:
    dataset_root = get_datasets_dir() / dataset_id
    if not dataset_root.exists():
        return
    meta = LeRobotDatasetMetadata(dataset_id, root=dataset_root)
    size_bytes = sum(p.stat().st_size for p in dataset_root.rglob("*") if p.is_file())
    payload = {
        "id": dataset_id,
        "episode_count": meta.total_episodes,
        "size_bytes": size_bytes,
        "status": "active",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await upsert_with_owner("datasets", "id", payload)


@router.post("/session/start", response_model=RecordingSessionActionResponse)
async def start_session(request: RecordingSessionStartRequest):
    _require_user_id()

    is_valid, errors = validate_dataset_name(request.dataset_name)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid dataset name: {'; '.join(errors)}")

    _ensure_recorder_running()

    dataset_id = generate_dataset_id()
    profile_instance = await _resolve_profile_instance(None)
    try:
        profile_class = await ProfileRegistry().get_class(profile_instance.class_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Profile class not found") from exc

    cameras, settings = _build_recorder_cameras(profile_class, profile_instance)
    if not cameras:
        raise HTTPException(status_code=400, detail="No enabled cameras in active profile")

    payload = {
        "dataset_id": dataset_id,
        "dataset_name": request.dataset_name,
        "task": request.task,
        "num_episodes": request.num_episodes,
        "episode_time_s": request.episode_time_s,
        "reset_time_s": request.reset_time_s,
        "cameras": cameras,
        "metadata": {
            "num_episodes": request.num_episodes,
            "episode_time_s": request.episode_time_s,
            "reset_time_s": request.reset_time_s,
            "profile_instance_id": profile_instance.id,
            "profile_class_id": profile_instance.class_id,
        },
    }
    arm_namespaces = _build_arm_namespaces(settings)
    if arm_namespaces:
        payload["arm_namespaces"] = arm_namespaces

    result = _call_recorder("/api/session/start", payload)
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder start failed")

    await _upsert_dataset_record(
        dataset_id, request.dataset_name, request.task, profile_instance, "recording"
    )

    return RecordingSessionActionResponse(
        success=True,
        message="Recording session started",
        dataset_id=dataset_id,
        status=result,
    )


@router.post("/session/stop", response_model=RecordingSessionActionResponse)
async def stop_session(request: RecordingSessionStopRequest):
    _require_user_id()
    result = _call_recorder("/api/session/stop", {"save_current": request.save_current})
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder stop failed")

    dataset_id = request.dataset_id or result.get("dataset_id")
    if dataset_id:
        await _update_dataset_stats(dataset_id)

        user_config = _load_user_config()
        if user_config.get("auto_upload_after_recording", True):
            try:
                sync_service = _get_sync_service()
                await sync_service.upload_dataset_with_progress(dataset_id, None)
            except Exception as exc:
                logger.error("Auto-upload failed for %s: %s", dataset_id, exc)

    return RecordingSessionActionResponse(
        success=True,
        message="Recording session stopped",
        dataset_id=dataset_id,
        status=result,
    )


@router.post("/session/pause", response_model=RecordingSessionActionResponse)
async def pause_session():
    _require_user_id()
    result = _call_recorder("/api/session/pause", {})
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder pause failed")
    return RecordingSessionActionResponse(success=True, message="Recording paused", status=result)


@router.post("/session/resume", response_model=RecordingSessionActionResponse)
async def resume_session():
    _require_user_id()
    result = _call_recorder("/api/session/resume", {})
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder resume failed")
    return RecordingSessionActionResponse(success=True, message="Recording resumed", status=result)


@router.post("/episode/redo", response_model=RecordingSessionActionResponse)
async def redo_episode():
    _require_user_id()
    result = _call_recorder("/api/episode/redo", {})
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder redo failed")
    return RecordingSessionActionResponse(
        success=True,
        message="Episode redo requested",
        dataset_id=result.get("dataset_id"),
        status=result,
    )


@router.post("/episode/cancel", response_model=RecordingSessionActionResponse)
async def cancel_episode():
    _require_user_id()
    result = _call_recorder("/api/episode/cancel", {})
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder episode cancel failed")
    return RecordingSessionActionResponse(success=True, message="Episode cancelled", status=result)


@router.post("/session/cancel", response_model=RecordingSessionActionResponse)
async def cancel_session(dataset_id: Optional[str] = None):
    _require_user_id()
    result = _call_recorder("/api/session/stop", {"save_current": False})
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder cancel failed")

    if dataset_id:
        client = await get_supabase_async_client()
        await client.table("datasets").update({"status": "archived"}).eq("id", dataset_id).execute()

    return RecordingSessionActionResponse(success=True, message="Recording cancelled", dataset_id=dataset_id, status=result)


@router.get("/sessions/{session_id}/status", response_model=RecordingSessionStatusResponse)
async def get_session_status(session_id: str):
    _require_user_id()
    status = _call_recorder("/api/session/status")
    active_id = status.get("dataset_id")
    if not active_id or active_id != session_id:
        return RecordingSessionStatusResponse(
            dataset_id=session_id,
            status={
                "state": "inactive",
                "active_dataset_id": active_id,
            },
        )
    return RecordingSessionStatusResponse(dataset_id=active_id, status=status)


async def _list_recordings() -> List[dict]:
    client = await get_supabase_async_client()
    rows = (
        await client.table("datasets")
        .select("id,name,profile_instance_id,episode_count,size_bytes,created_at,dataset_type,status")
        .eq("dataset_type", "recorded")
        .execute()
    ).data or []
    return [row for row in rows if row.get("status") != "archived"]


@router.get("/recordings", response_model=RecordingListResponse)
async def list_recordings():
    recordings_data = await _list_recordings()
    recordings = [
        RecordingInfo(
            recording_id=r.get("id"),
            dataset_name=r.get("name"),
            profile_instance_id=r.get("profile_instance_id"),
            created_at=r.get("created_at"),
            episode_count=r.get("episode_count") or 0,
            size_bytes=r.get("size_bytes") or 0,
        )
        for r in recordings_data
        if r.get("id")
    ]
    return RecordingListResponse(recordings=recordings, total=len(recordings))


@router.get("/recordings/{recording_id:path}", response_model=RecordingInfo)
async def get_recording(recording_id: str):
    client = await get_supabase_async_client()
    rows = (
        await client.table("datasets")
        .select("id,name,profile_instance_id,episode_count,size_bytes,created_at")
        .eq("id", recording_id)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")
    row = rows[0]
    return RecordingInfo(
        recording_id=row.get("id"),
        dataset_name=row.get("name"),
        profile_instance_id=row.get("profile_instance_id"),
        created_at=row.get("created_at"),
        episode_count=row.get("episode_count") or 0,
        size_bytes=row.get("size_bytes") or 0,
    )


@router.get("/recordings/{recording_id:path}/validate", response_model=RecordingValidateResponse)
async def validate_recording(recording_id: str):
    recording_path = get_datasets_dir() / recording_id
    if not recording_path.exists():
        raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")

    errors = []
    meta_file = recording_path / "meta" / "info.json"
    if not meta_file.exists():
        errors.append("meta/info.json missing")

    data_dir = recording_path / "data"
    if not data_dir.exists():
        errors.append("data directory missing")

    return RecordingValidateResponse(
        recording_id=recording_id,
        is_valid=len(errors) == 0,
        errors=errors,
    )


@router.delete("/recordings/{recording_id:path}")
async def delete_recording(recording_id: str):
    recording_path = get_datasets_dir() / recording_id
    if recording_path.exists():
        for _ in range(3):
            try:
                for child in recording_path.iterdir():
                    if child.is_dir():
                        for sub in child.rglob("*"):
                            if sub.is_file():
                                sub.unlink(missing_ok=True)
                        child.rmdir()
                    else:
                        child.unlink(missing_ok=True)
                recording_path.rmdir()
                break
            except Exception:
                continue
    client = await get_supabase_async_client()
    await client.table("datasets").delete().eq("id", recording_id).execute()
    return {"recording_id": recording_id, "message": "Recording deleted"}
