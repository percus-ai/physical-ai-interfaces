"""SSE endpoints for WebUI state streaming."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from interfaces_backend.api.inference import get_inference_runner_status
from interfaces_backend.api.operate import get_operate_status
from interfaces_backend.api.profiles import get_active_profile_status, get_vlabor_status
from interfaces_backend.api.recording import get_session_status
from interfaces_backend.api.training import get_job, get_job_metrics
from interfaces_backend.services.startup_operations import get_startup_operations_service
from interfaces_backend.utils.sse import sse_response
from percus_ai.db import get_current_user_id

router = APIRouter(prefix="/api/stream", tags=["stream"])


def _require_user_id() -> str:
    try:
        return get_current_user_id()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Login required") from exc


@router.get("/profiles/active")
async def stream_active_profile(request: Request):
    _require_user_id()
    async def build_payload() -> dict:
        status = await get_active_profile_status()
        return status.model_dump(mode="json")

    return sse_response(request, build_payload, interval=5.0)


@router.get("/profiles/vlabor")
async def stream_vlabor_status(request: Request):
    _require_user_id()
    async def build_payload() -> dict:
        status = await get_vlabor_status()
        return status.model_dump(mode="json")

    return sse_response(request, build_payload, interval=2.0)


@router.get("/recording/sessions/{session_id}")
async def stream_recording_session(request: Request, session_id: str):
    _require_user_id()
    async def build_payload() -> dict:
        status = await get_session_status(session_id)
        return status.model_dump(mode="json")

    return sse_response(request, build_payload, interval=1.5)


@router.get("/operate/status")
async def stream_operate_status(request: Request):
    _require_user_id()
    async def build_payload() -> dict:
        vlabor_status = await get_vlabor_status()
        inference_runner_status = await get_inference_runner_status()
        operate_status = await get_operate_status()

        return {
            "vlabor_status": vlabor_status.model_dump(mode="json"),
            "inference_runner_status": inference_runner_status.model_dump(mode="json"),
            "operate_status": operate_status.model_dump(mode="json"),
        }

    return sse_response(request, build_payload, interval=2.0)


@router.get("/startup/operations/{operation_id}")
async def stream_startup_operation(request: Request, operation_id: str):
    user_id = _require_user_id()
    operations = get_startup_operations_service()
    operations.get(user_id=user_id, operation_id=operation_id)

    async def build_payload() -> dict:
        status = operations.get(user_id=user_id, operation_id=operation_id)
        return status.model_dump(mode="json")

    return sse_response(request, build_payload, interval=0.25)


@router.get("/training/jobs/{job_id}")
async def stream_training_job(request: Request, job_id: str, limit: int = 2000):
    _require_user_id()
    async def build_payload() -> dict:
        job_detail = await get_job(job_id)
        metrics = await get_job_metrics(job_id, limit=limit)
        return {
            "job_detail": job_detail.model_dump(mode="json"),
            "metrics": metrics.model_dump(mode="json"),
        }

    return sse_response(request, build_payload, interval=5.0)
