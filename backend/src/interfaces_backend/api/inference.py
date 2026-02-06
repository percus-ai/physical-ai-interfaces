"""Inference control API."""

from __future__ import annotations

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
from interfaces_backend.api.teleop import has_running_local_teleop
from interfaces_backend.services.profile_settings import (
    build_inference_camera_aliases,
    build_inference_joint_names,
    get_active_profile_settings,
)
from interfaces_backend.services.inference_runtime import get_inference_runtime_manager

router = APIRouter(prefix="/api/inference", tags=["inference"])


def _manager():
    return get_inference_runtime_manager()


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
    if has_running_local_teleop():
        raise HTTPException(status_code=409, detail="Teleop session is running. Stop teleop first.")

    _, profile_class, settings = await get_active_profile_settings()
    joint_names = build_inference_joint_names(profile_class, settings)
    if not joint_names:
        raise HTTPException(status_code=400, detail="No inference joints configured in active profile")
    camera_key_aliases = build_inference_camera_aliases(profile_class, settings)

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

    return InferenceRunnerStartResponse(session_id=session_id, message="inference worker started")


@router.post("/runner/stop", response_model=InferenceRunnerStopResponse)
async def stop_inference_runner(request: InferenceRunnerStopRequest):
    try:
        stopped = _manager().stop(session_id=request.session_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to stop inference worker: {exc}") from exc

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
