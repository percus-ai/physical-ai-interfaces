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
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from interfaces_backend.services.vlabor_runtime import (
    VlaborCommandError,
    start_vlabor as run_vlabor_start,
    stop_vlabor as run_vlabor_stop,
)
from interfaces_backend.services.vlabor_profiles import (
    extract_arm_namespaces,
    extract_camera_specs,
    get_active_profile_spec,
    resolve_profile_spec,
    save_session_profile_binding,
)
from interfaces_backend.services.lerobot_runtime import (
    LerobotCommandError,
    get_lerobot_service_state,
    start_lerobot,
    stop_lerobot,
)
from percus_ai.observability import ArmId, CommOverheadReporter, PointId, resolve_ids
from percus_ai.db import get_current_user_id, get_supabase_async_client, upsert_with_owner
from percus_ai.storage.naming import generate_dataset_id, validate_dataset_name
from percus_ai.storage.paths import get_datasets_dir, get_user_config_path
from percus_ai.storage.r2_db_sync import R2DBSyncService
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recording", tags=["recording"])

_RECORDER_URL = os.environ.get("LEROBOT_RECORDER_URL", "http://127.0.0.1:8082")
_sync_service: Optional[R2DBSyncService] = None
_PENDING_SESSIONS_DIRNAME = ".pending_sessions"
_COMM_REPORTER = CommOverheadReporter("backend")


class RecordingSessionCreateRequest(BaseModel):
    dataset_name: str = Field(..., description="Dataset display name")
    task: str = Field(..., description="Task description")
    profile: Optional[str] = Field(None, description="Optional VLAbor profile name")
    num_episodes: int = Field(1, ge=1, description="Number of episodes")
    episode_time_s: float = Field(60.0, gt=0, description="Episode length in seconds")
    reset_time_s: float = Field(10.0, ge=0, description="Reset wait time in seconds")


class RecordingSessionStartRequest(BaseModel):
    dataset_id: str = Field(..., description="Dataset ID (UUID)")


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
    profile_name: Optional[str] = None
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


def _pending_sessions_dir() -> Path:
    directory = get_datasets_dir() / _PENDING_SESSIONS_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _pending_session_path(dataset_id: str) -> Path:
    return _pending_sessions_dir() / f"{dataset_id}.json"


def _save_pending_session(dataset_id: str, payload: dict) -> None:
    path = _pending_session_path(dataset_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_pending_session(dataset_id: str) -> dict:
    path = _pending_session_path(dataset_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Pending session not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Pending session data corrupted") from exc


def _delete_pending_session(dataset_id: str) -> None:
    path = _pending_session_path(dataset_id)
    if path.exists():
        path.unlink()


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


def _start_vlabor_for_session(profile_name: Optional[str] = None) -> None:
    try:
        run_vlabor_start(profile=profile_name)
    except VlaborCommandError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start VLAbor container: {exc}") from exc


def _stop_vlabor_for_session() -> None:
    try:
        run_vlabor_stop()
    except VlaborCommandError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to stop VLAbor container: {exc}") from exc


def _start_recorder() -> None:
    try:
        start_lerobot(strict=True)
    except LerobotCommandError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _stop_recorder() -> None:
    """Stop lerobot-ros2 containers (best-effort)."""
    result = stop_lerobot(strict=False)
    if result.returncode != 0:
        logger.warning("lerobot-ros2 stop failed: %s", result.stderr.strip())


def _ensure_recorder_running() -> None:
    try:
        _call_recorder("/api/session/status")
        return
    except HTTPException as exc:
        if exc.status_code != 503:
            raise

    _start_recorder()
    service_state = get_lerobot_service_state("lerobot-ros2")
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
    session_hint = None
    if isinstance(payload, dict):
        session_hint = str(payload.get("dataset_id") or payload.get("session_id") or "").strip() or None
    session_id, trace_id = resolve_ids(session_hint, None)
    timer = _COMM_REPORTER.timed(
        point_id=PointId.CP_02,
        session_id=session_id,
        trace_id=trace_id,
        arm=ArmId.NONE,
        payload_bytes=len(data) if data is not None else 0,
        tags={"method": method, "path": path},
    )
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body_bytes = resp.read()
            timer.success(extra_tags={"status_code": resp.status, "response_bytes": len(body_bytes)})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else str(exc)
        timer.error(detail, extra_tags={"status_code": exc.code})
        raise HTTPException(status_code=exc.code, detail=detail) from exc
    except urllib.error.URLError as exc:
        timer.error(str(exc), extra_tags={"status_code": 503})
        raise HTTPException(status_code=503, detail=f"Recorder unreachable: {exc}") from exc
    body = body_bytes.decode("utf-8")
    try:
        return json.loads(body) if body else {}
    except json.JSONDecodeError:
        return {"raw": body}


def _build_recorder_cameras(profile_snapshot: dict) -> list[dict]:
    cameras: list[dict] = []
    for spec in extract_camera_specs(profile_snapshot):
        if not bool(spec.get("enabled", True)):
            continue
        name = str(spec.get("name") or "").strip()
        topic = str(spec.get("topic") or "").strip()
        if not name or not topic:
            continue
        cameras.append({"name": name, "topic": topic})
    return cameras


def _build_arm_namespaces(profile_snapshot: dict) -> list[str]:
    return extract_arm_namespaces(profile_snapshot)


def _extract_profile_name(profile_snapshot: Optional[dict]) -> Optional[str]:
    if not isinstance(profile_snapshot, dict):
        return None
    name = profile_snapshot.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    profile = profile_snapshot.get("profile")
    if isinstance(profile, dict):
        name = profile.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


async def _upsert_dataset_record(
    dataset_id: str,
    dataset_name: str,
    task: str,
    profile_snapshot: Optional[dict],
    status: str,
) -> None:
    payload = {
        "id": dataset_id,
        "name": dataset_name,
        "dataset_type": "recorded",
        "source": "local",
        "status": status,
        "task_detail": task,
        "profile_instance_id": None,
        "profile_snapshot": profile_snapshot,
    }
    await upsert_with_owner("datasets", "id", payload)


async def _update_dataset_stats(dataset_id: str) -> None:
    dataset_root = get_datasets_dir() / dataset_id
    if not dataset_root.exists():
        return
    episode_count = 0
    meta_path = dataset_root / "meta" / "info.json"
    if meta_path.exists():
        try:
            info = json.loads(meta_path.read_text(encoding="utf-8"))
            episode_count = int(info.get("total_episodes") or 0)
        except Exception as exc:
            logger.warning("Failed to read dataset info.json for %s: %s", dataset_id, exc)
    else:
        try:
            meta = LeRobotDatasetMetadata(dataset_id, root=dataset_root)
            episode_count = int(meta.total_episodes)
        except Exception as exc:
            logger.warning("Failed to read dataset metadata for %s: %s", dataset_id, exc)
    size_bytes = sum(p.stat().st_size for p in dataset_root.rglob("*") if p.is_file())
    payload = {
        "id": dataset_id,
        "episode_count": episode_count,
        "size_bytes": size_bytes,
        "status": "active",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await upsert_with_owner("datasets", "id", payload)


@router.post("/session/create", response_model=RecordingSessionActionResponse)
async def create_session(request: RecordingSessionCreateRequest):
    _require_user_id()

    is_valid, errors = validate_dataset_name(request.dataset_name)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid dataset name: {'; '.join(errors)}")

    dataset_id = generate_dataset_id()
    profile = resolve_profile_spec(request.profile) if request.profile else await get_active_profile_spec()
    cameras = _build_recorder_cameras(profile.snapshot)
    if not cameras:
        raise HTTPException(status_code=400, detail="No enabled cameras in active profile")
    _start_vlabor_for_session(profile.name)

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
            "profile_name": profile.name,
            "profile_snapshot": profile.snapshot,
        },
    }
    arm_namespaces = _build_arm_namespaces(profile.snapshot)
    if arm_namespaces:
        payload["arm_namespaces"] = arm_namespaces

    _save_pending_session(dataset_id, payload)

    await _upsert_dataset_record(
        dataset_id,
        request.dataset_name,
        request.task,
        profile.snapshot,
        "ready",
    )
    await save_session_profile_binding(session_kind="recording", session_id=dataset_id, profile=profile)

    return RecordingSessionActionResponse(
        success=True,
        message="Recording session created",
        dataset_id=dataset_id,
    )


@router.post("/session/start", response_model=RecordingSessionActionResponse)
async def start_session(request: RecordingSessionStartRequest):
    _require_user_id()

    _ensure_recorder_running()

    payload = _load_pending_session(request.dataset_id)
    result = _call_recorder("/api/session/start", payload)
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder start failed")

    metadata = payload.get("metadata") or {}
    profile_snapshot = metadata.get("profile_snapshot")
    await _upsert_dataset_record(
        payload.get("dataset_id") or request.dataset_id,
        payload.get("dataset_name") or request.dataset_id,
        payload.get("task") or "",
        profile_snapshot if isinstance(profile_snapshot, dict) else None,
        "recording",
    )
    _delete_pending_session(request.dataset_id)

    return RecordingSessionActionResponse(
        success=True,
        message="Recording session started",
        dataset_id=payload.get("dataset_id") or request.dataset_id,
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

    _stop_vlabor_for_session()
    _stop_recorder()

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


@router.post("/episode/redo-previous", response_model=RecordingSessionActionResponse)
async def redo_previous_episode():
    _require_user_id()
    status = _call_recorder("/api/session/status")
    state = status.get("state")
    dataset_id = status.get("dataset_id")
    if not dataset_id:
        raise HTTPException(status_code=400, detail="No active session")
    if state == "paused":
        raise HTTPException(status_code=400, detail="Cannot redo while paused")

    if state == "recording":
        cancel = _call_recorder("/api/episode/cancel", {})
        if not cancel.get("success", False):
            raise HTTPException(
                status_code=500, detail=cancel.get("error") or "Recorder episode cancel failed"
            )
        deadline = time.time() + 5.0
        while time.time() < deadline:
            status = _call_recorder("/api/session/status")
            state = status.get("state")
            if state not in ("recording", "paused"):
                break
            time.sleep(0.1)

    result = _call_recorder("/api/episode/redo", {})
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder redo failed")

    return RecordingSessionActionResponse(
        success=True,
        message="Previous episode will be re-recorded",
        dataset_id=dataset_id,
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
    result = {"success": True, "message": "Recording cancelled", "dataset_id": dataset_id}
    if dataset_id:
        active_id = None
        active_state = None
        try:
            status = _call_recorder("/api/session/status")
            active_id = status.get("dataset_id")
            active_state = status.get("state")
        except HTTPException:
            status = {}
        if active_id and active_id == dataset_id and active_state not in ("idle", "completed"):
            result = _call_recorder("/api/session/stop", {"save_current": False})
            if not result.get("success", False):
                raise HTTPException(status_code=500, detail=result.get("error") or "Recorder cancel failed")
        client = await get_supabase_async_client()
        await client.table("datasets").update({"status": "archived"}).eq("id", dataset_id).execute()
        _delete_pending_session(dataset_id)
    else:
        result = _call_recorder("/api/session/stop", {"save_current": False})
        if not result.get("success", False):
            raise HTTPException(status_code=500, detail=result.get("error") or "Recorder cancel failed")

    _stop_vlabor_for_session()
    _stop_recorder()

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
        .select("id,name,profile_snapshot,episode_count,size_bytes,created_at,dataset_type,status")
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
            profile_name=_extract_profile_name(r.get("profile_snapshot")),
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
        .select("id,name,profile_snapshot,episode_count,size_bytes,created_at")
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
        profile_name=_extract_profile_name(row.get("profile_snapshot")),
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
