"""Inference control API."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

import yaml
from fastapi import APIRouter, HTTPException

from interfaces_backend.models.inference import (
    InferenceDeviceCompatibilityResponse,
    InferenceModelsResponse,
    InferenceRunnerStartRequest,
    InferenceRunnerStartResponse,
    InferenceRunnerStatusResponse,
    InferenceRunnerStopRequest,
    InferenceRunnerStopResponse,
    InferenceSetTaskRequest,
    InferenceSetTaskResponse,
)
from interfaces_backend.services.vlabor_profiles import (
    build_inference_camera_aliases,
    build_inference_joint_names,
    extract_arm_namespaces,
    extract_camera_specs,
    get_active_profile_spec,
    save_session_profile_binding,
)
from interfaces_backend.services.inference_runtime import get_inference_runtime_manager
from interfaces_backend.services.lerobot_runtime import (
    LerobotCommandError,
    start_lerobot,
    stop_lerobot,
)
from interfaces_backend.services.vlabor_runtime import (
    VlaborCommandError,
    start_vlabor as run_vlabor_start,
    stop_vlabor as run_vlabor_stop,
)
from percus_ai.storage.r2_db_sync import R2DBSyncService
from percus_ai.storage.naming import generate_dataset_id
from percus_ai.storage.paths import get_user_config_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inference", tags=["inference"])

_RECORDER_URL = os.environ.get("LEROBOT_RECORDER_URL", "http://127.0.0.1:8082")

_sync_service: R2DBSyncService | None = None
_inference_dataset_id: str | None = None


def _manager():
    return get_inference_runtime_manager()


def _get_sync_service() -> R2DBSyncService:
    global _sync_service
    if _sync_service is None:
        _sync_service = R2DBSyncService()
    return _sync_service


def _start_vlabor_for_session(profile_name: str | None = None) -> None:
    try:
        run_vlabor_start(profile=profile_name)
    except VlaborCommandError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start VLAbor container: {exc}") from exc


def _stop_vlabor_for_session() -> None:
    try:
        run_vlabor_stop()
    except VlaborCommandError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to stop VLAbor container: {exc}") from exc


def _start_lerobot_for_session() -> None:
    try:
        start_lerobot(strict=True)
    except LerobotCommandError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start lerobot stack: {exc}") from exc


def _stop_lerobot_for_session() -> None:
    result = stop_lerobot(strict=False)
    if result.returncode != 0:
        logger.warning("lerobot stack stop failed: %s", result.stderr.strip())


def _call_recorder(path: str, payload: dict | None = None) -> dict:
    """Make an HTTP call to the lerobot session recorder service."""
    url = f"{_RECORDER_URL}{path}"
    data = None
    headers: dict[str, str] = {}
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


def _load_user_config() -> dict:
    path = get_user_config_path()
    if not path.exists():
        return {"auto_upload_after_recording": True}
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    sync = raw.get("sync", {})
    return {"auto_upload_after_recording": sync.get("auto_upload_after_recording", True)}


def _build_inference_recorder_cameras(profile_snapshot: dict) -> list[dict]:
    """Build camera list for recorder from profile snapshot."""
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


async def _auto_upload_inference_dataset(dataset_id: str) -> None:
    """Upload the inference evaluation dataset to R2."""
    user_config = _load_user_config()
    if not user_config.get("auto_upload_after_recording", True):
        logger.info("Auto-upload disabled by user config; skipping for %s", dataset_id)
        return
    try:
        await _get_sync_service().upload_dataset_with_progress(dataset_id, None)
        logger.info("Auto-upload completed for inference dataset %s", dataset_id)
    except Exception:
        logger.error("Auto-upload failed for inference dataset %s", dataset_id, exc_info=True)


@router.get("/models", response_model=InferenceModelsResponse)
async def list_models():
    return InferenceModelsResponse(models=_manager().list_models())


@router.get("/device-compatibility", response_model=InferenceDeviceCompatibilityResponse)
async def get_device_compatibility():
    return _manager().get_device_compatibility()


@router.get("/runner/status", response_model=InferenceRunnerStatusResponse)
async def get_inference_runner_status():
    return _manager().get_status()


@router.get("/runner/diagnostics")
async def get_inference_runner_diagnostics():
    return _manager().get_diagnostics()


@router.post("/runner/start", response_model=InferenceRunnerStartResponse)
async def start_inference_runner(request: InferenceRunnerStartRequest):
    active_profile = await get_active_profile_spec()
    joint_names = build_inference_joint_names(active_profile.snapshot)
    if not joint_names:
        raise HTTPException(status_code=400, detail="No inference joints configured in active profile")
    camera_key_aliases = build_inference_camera_aliases(active_profile.snapshot)
    _start_vlabor_for_session(active_profile.name)
    _start_lerobot_for_session()

    # Ensure model is downloaded from R2 and cached locally
    sync_result = await _get_sync_service().ensure_model_local(request.model_id, auto_download=True)
    if not sync_result.success:
        raise HTTPException(status_code=404, detail=f"Model not available: {sync_result.message}")

    try:
        session_id = _manager().start(
            model_id=request.model_id,
            device=request.device,
            task=request.task,
            joint_names=joint_names,
            camera_key_aliases=camera_key_aliases,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        message = str(exc)
        if "already running" in message:
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start inference worker: {exc}") from exc
    await save_session_profile_binding(
        session_kind="inference",
        session_id=session_id,
        profile=active_profile,
    )

    # Start simultaneous recording during inference (best-effort)
    global _inference_dataset_id
    dataset_id = generate_dataset_id()
    cameras = _build_inference_recorder_cameras(active_profile.snapshot)
    arm_namespaces = extract_arm_namespaces(active_profile.snapshot)

    recorder_payload: dict = {
        "dataset_id": dataset_id,
        "dataset_name": f"eval-{session_id[:8]}",
        "task": request.task or "",
        "num_episodes": 1,
        "episode_time_s": 86400,
        "reset_time_s": 0,
        "cameras": cameras,
    }
    if arm_namespaces:
        recorder_payload["arm_namespaces"] = arm_namespaces

    try:
        result = _call_recorder("/api/session/start", recorder_payload)
        if result.get("success"):
            _inference_dataset_id = dataset_id
            logger.info("Started inference recording: dataset_id=%s", dataset_id)
        else:
            logger.warning("Recorder start returned failure (non-critical): %s", result)
    except Exception:
        logger.warning("Failed to start inference recording (non-critical)", exc_info=True)

    return InferenceRunnerStartResponse(session_id=session_id, message="inference worker started")


@router.post("/runner/stop", response_model=InferenceRunnerStopResponse)
async def stop_inference_runner(request: InferenceRunnerStopRequest):
    global _inference_dataset_id
    dataset_id = _inference_dataset_id
    _inference_dataset_id = None

    try:
        stopped = _manager().stop(session_id=request.session_id)
        _stop_vlabor_for_session()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to stop inference worker: {exc}") from exc

    # Stop inference recording and auto-upload
    if dataset_id:
        try:
            _call_recorder("/api/session/stop", {"save_current": True})
            logger.info("Stopped inference recording: dataset_id=%s", dataset_id)
        except Exception:
            logger.warning("Failed to stop inference recording", exc_info=True)
        await _auto_upload_inference_dataset(dataset_id)

    _stop_lerobot_for_session()

    return InferenceRunnerStopResponse(
        success=True,
        session_id=request.session_id,
        message="inference worker stopped" if stopped else "inference worker already stopped",
    )


@router.post("/runner/task", response_model=InferenceSetTaskResponse)
async def set_inference_task(request: InferenceSetTaskRequest):
    task = request.task.strip()
    if not task:
        raise HTTPException(status_code=400, detail="task must not be empty")

    try:
        applied_from_step = _manager().set_task(session_id=request.session_id, task=task)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update task: {exc}") from exc

    return InferenceSetTaskResponse(
        success=True,
        session_id=request.session_id,
        task=task,
        applied_from_step=applied_from_step,
    )
