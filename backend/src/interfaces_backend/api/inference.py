"""Inference control API."""

from __future__ import annotations

import logging

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
from interfaces_backend.services.inference_runtime import get_inference_runtime_manager
from interfaces_backend.services.inference_session import get_inference_session_manager
from interfaces_backend.services.lerobot_runtime import stop_lerobot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inference", tags=["inference"])


@router.get("/models", response_model=InferenceModelsResponse)
async def list_models():
    return InferenceModelsResponse(models=get_inference_runtime_manager().list_models())


@router.get("/device-compatibility", response_model=InferenceDeviceCompatibilityResponse)
async def get_device_compatibility():
    return get_inference_runtime_manager().get_device_compatibility()


@router.get("/runner/status", response_model=InferenceRunnerStatusResponse)
async def get_inference_runner_status():
    return get_inference_runtime_manager().get_status()


@router.get("/runner/diagnostics")
async def get_inference_runner_diagnostics():
    return get_inference_runtime_manager().get_diagnostics()


@router.post("/runner/start", response_model=InferenceRunnerStartResponse)
async def start_inference_runner(request: InferenceRunnerStartRequest):
    mgr = get_inference_session_manager()
    state = await mgr.create(
        model_id=request.model_id,
        device=request.device,
        task=request.task,
    )
    return InferenceRunnerStartResponse(
        session_id=state.extras["worker_session_id"],
        message="inference worker started",
    )


@router.post("/runner/stop", response_model=InferenceRunnerStopResponse)
async def stop_inference_runner(request: InferenceRunnerStopRequest):
    mgr = get_inference_session_manager()
    active = mgr.any_active()

    if active:
        state = await mgr.stop(active.id, session_id=request.session_id)
        stopped = state.extras.get("stopped", False)
    else:
        # Fallback: stop runtime directly (e.g., after server restart)
        runtime = get_inference_runtime_manager()
        try:
            stopped = runtime.stop(session_id=request.session_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to stop inference worker: {exc}"
            ) from exc
        stop_lerobot(strict=False)

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
        applied_from_step = get_inference_runtime_manager().set_task(
            session_id=request.session_id, task=task
        )
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
