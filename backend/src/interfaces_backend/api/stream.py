"""SSE endpoints for WebUI state streaming."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from interfaces_backend.api.inference import get_inference_runner_status
from interfaces_backend.api.operate import get_operate_status
from interfaces_backend.api.profiles import get_active_profile_status, get_vlabor_status
from interfaces_backend.api.training import get_job, get_job_metrics
from interfaces_backend.services.dataset_lifecycle import UPLOAD_TOPIC, get_dataset_lifecycle
from interfaces_backend.services.model_sync_jobs import (
    MODEL_SYNC_JOB_TOPIC,
    get_model_sync_jobs_service,
)
from interfaces_backend.services.realtime_events import get_realtime_event_bus
from interfaces_backend.services.realtime_producers import (
    ProducerBuilder,
    get_realtime_producer_hub,
)
from interfaces_backend.services.recorder_status_stream import (
    RECORDING_STATUS_TOPIC,
    get_recorder_status_stream,
)
from interfaces_backend.services.session_control_events import (
    SESSION_CONTROL_TOPIC,
    normalize_session_kind,
    session_control_channel_key,
)
from interfaces_backend.services.startup_operations import (
    STARTUP_OPERATION_TOPIC,
    get_startup_operations_service,
)
from interfaces_backend.utils.sse import sse_queue_response
from percus_ai.db import get_current_user_id

router = APIRouter(prefix="/api/stream", tags=["stream"])

PROFILE_ACTIVE_TOPIC = "profiles.active"
PROFILE_VLABOR_TOPIC = "profiles.vlabor"
OPERATE_STATUS_TOPIC = "operate.status"
TRAINING_JOB_TOPIC = "training.job"


def _require_user_id() -> str:
    try:
        return get_current_user_id()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Login required") from exc


async def _stream_with_shared_producer(
    request: Request,
    *,
    topic: str,
    key: str,
    build_payload: ProducerBuilder,
    interval: float,
    idle_ttl: float = 30.0,
):
    bus = get_realtime_event_bus()
    hub = get_realtime_producer_hub()
    subscription = bus.subscribe(topic, key)
    await hub.publish_once(topic=topic, key=key, build_payload=build_payload)
    hub.ensure_polling(
        topic=topic,
        key=key,
        build_payload=build_payload,
        interval=interval,
        idle_ttl=idle_ttl,
    )
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/profiles/active")
async def stream_active_profile(request: Request):
    _require_user_id()

    async def build_payload() -> dict:
        status = await get_active_profile_status()
        return status.model_dump(mode="json")

    return await _stream_with_shared_producer(
        request,
        topic=PROFILE_ACTIVE_TOPIC,
        key="global",
        build_payload=build_payload,
        interval=5.0,
        idle_ttl=45.0,
    )


@router.get("/profiles/vlabor")
async def stream_vlabor_status(request: Request):
    _require_user_id()

    async def build_payload() -> dict:
        status = await get_vlabor_status()
        return status.model_dump(mode="json")

    return await _stream_with_shared_producer(
        request,
        topic=PROFILE_VLABOR_TOPIC,
        key="global",
        build_payload=build_payload,
        interval=2.0,
        idle_ttl=45.0,
    )


@router.get("/recording/sessions/{session_id}")
async def stream_recording_session(request: Request, session_id: str):
    _require_user_id()
    recorder_stream = get_recorder_status_stream()
    recorder_stream.ensure_started()
    bus = get_realtime_event_bus()
    subscription = bus.subscribe(RECORDING_STATUS_TOPIC, session_id)
    await bus.publish(
        RECORDING_STATUS_TOPIC,
        session_id,
        await recorder_stream.build_session_snapshot(session_id),
    )
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/recording/sessions/{session_id}/upload-status")
async def stream_recording_upload_status(request: Request, session_id: str):
    _require_user_id()
    bus = get_realtime_event_bus()
    lifecycle = get_dataset_lifecycle()
    subscription = bus.subscribe(UPLOAD_TOPIC, session_id)
    await bus.publish(UPLOAD_TOPIC, session_id, lifecycle.get_dataset_upload_status(session_id))
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


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

    return await _stream_with_shared_producer(
        request,
        topic=OPERATE_STATUS_TOPIC,
        key="global",
        build_payload=build_payload,
        interval=2.0,
        idle_ttl=45.0,
    )


@router.get("/startup/operations/{operation_id}")
async def stream_startup_operation(request: Request, operation_id: str):
    user_id = _require_user_id()
    operations = get_startup_operations_service()
    snapshot = operations.get(user_id=user_id, operation_id=operation_id)
    bus = get_realtime_event_bus()
    subscription = bus.subscribe(STARTUP_OPERATION_TOPIC, operation_id)
    await bus.publish(STARTUP_OPERATION_TOPIC, operation_id, snapshot.model_dump(mode="json"))
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/storage/model-sync/jobs/{job_id}")
async def stream_model_sync_job(request: Request, job_id: str):
    user_id = _require_user_id()
    jobs = get_model_sync_jobs_service()
    snapshot = jobs.get(user_id=user_id, job_id=job_id)
    bus = get_realtime_event_bus()
    subscription = bus.subscribe(MODEL_SYNC_JOB_TOPIC, job_id)
    await bus.publish(MODEL_SYNC_JOB_TOPIC, job_id, snapshot.model_dump(mode="json"))
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/sessions/{session_kind}/{session_id}/events")
async def stream_session_control_events(request: Request, session_kind: str, session_id: str):
    _require_user_id()
    try:
        normalized_kind = normalize_session_kind(session_kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    normalized_session_id = session_id.strip() or "global"

    bus = get_realtime_event_bus()
    subscription = bus.subscribe(
        SESSION_CONTROL_TOPIC,
        session_control_channel_key(
            session_kind=normalized_kind,
            session_id=normalized_session_id,
        ),
    )
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/training/jobs/{job_id}")
async def stream_training_job(request: Request, job_id: str, limit: int = 2000):
    _require_user_id()

    async def build_payload() -> dict:
        job_detail = await get_job(job_id)
        metrics = await get_job_metrics(job_id=job_id, response=Response(), limit=limit)
        return {
            "job_detail": job_detail.model_dump(mode="json"),
            "metrics": metrics.model_dump(mode="json"),
        }

    return await _stream_with_shared_producer(
        request,
        topic=TRAINING_JOB_TOPIC,
        key=job_id,
        build_payload=build_payload,
        interval=5.0,
        idle_ttl=60.0,
    )
