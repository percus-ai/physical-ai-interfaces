"""Inference control API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from fastapi import APIRouter, HTTPException

from interfaces_backend.models.inference import (
    InferenceDeviceCompatibilityResponse,
    InferenceModelInfo,
    InferenceModelsResponse,
    InferenceRunnerStartRequest,
    InferenceRunnerStatusResponse,
    InferenceRunnerStopRequest,
    InferenceRunnerStopResponse,
    InferenceSetTaskRequest,
    InferenceSetTaskResponse,
)
from interfaces_backend.models.startup import StartupOperationAcceptedResponse
from interfaces_backend.services.inference_runtime import get_inference_runtime_manager
from interfaces_backend.services.inference_session import get_inference_session_manager
from interfaces_backend.services.session_manager import require_user_id
from interfaces_backend.services.startup_operations import get_startup_operations_service
from interfaces_backend.services.dataset_lifecycle import get_dataset_lifecycle
from percus_ai.db import get_supabase_async_client
from percus_ai.storage.paths import get_models_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inference", tags=["inference"])


def _to_size_mb(size_bytes: object) -> float:
    try:
        value = float(size_bytes or 0)
    except (TypeError, ValueError):
        value = 0.0
    return round(max(value, 0.0) / (1024 * 1024), 2)


async def _list_db_models() -> list[InferenceModelInfo]:
    try:
        client = await get_supabase_async_client()
        rows = (
            await client.table("models")
            .select("id,name,policy_type,size_bytes,source,status")
            .eq("status", "active")
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("Failed to load models from DB: %s", exc)
        return []

    models_dir = get_models_dir()
    db_models: list[InferenceModelInfo] = []
    for row in rows:
        model_id = str(row.get("id") or "").strip()
        if not model_id:
            continue
        local_exists = (models_dir / model_id).exists()
        name = str(row.get("name") or model_id).strip() or model_id
        policy_type = row.get("policy_type")
        source = str(row.get("source") or ("local" if local_exists else "r2")).strip() or "r2"
        db_models.append(
            InferenceModelInfo(
                model_id=model_id,
                name=name,
                policy_type=policy_type if isinstance(policy_type, str) and policy_type else None,
                source=source,
                size_mb=_to_size_mb(row.get("size_bytes")),
                is_loaded=False,
                is_local=local_exists,
            )
        )
    return db_models


def _merge_models(
    db_models: Sequence[InferenceModelInfo],
    runtime_models: Sequence[InferenceModelInfo],
) -> list[InferenceModelInfo]:
    merged: dict[str, InferenceModelInfo] = {item.model_id: item for item in db_models}
    for local in runtime_models:
        existing = merged.get(local.model_id)
        if existing is None:
            merged[local.model_id] = local
            continue
        merged[local.model_id] = InferenceModelInfo(
            model_id=existing.model_id,
            name=existing.name or local.name,
            policy_type=local.policy_type or existing.policy_type,
            source=existing.source or local.source,
            size_mb=local.size_mb if local.size_mb > 0 else existing.size_mb,
            is_loaded=bool(existing.is_loaded or local.is_loaded),
            is_local=bool(existing.is_local or local.is_local),
        )

    return sorted(
        merged.values(),
        key=lambda item: (
            not item.is_loaded,
            not item.is_local,
            (item.name or item.model_id).lower(),
        ),
    )


@router.get("/models", response_model=InferenceModelsResponse)
async def list_models():
    runtime_models = get_inference_runtime_manager().list_models()
    db_models = await _list_db_models()
    models = _merge_models(db_models, runtime_models)
    return InferenceModelsResponse(models=models)


@router.get("/device-compatibility", response_model=InferenceDeviceCompatibilityResponse)
async def get_device_compatibility():
    return get_inference_runtime_manager().get_device_compatibility()


@router.get("/runner/status", response_model=InferenceRunnerStatusResponse)
async def get_inference_runner_status():
    runtime_status = get_inference_runtime_manager().get_status()
    model_sync = get_dataset_lifecycle().get_model_sync_status()
    return InferenceRunnerStatusResponse(
        runner_status=runtime_status.runner_status,
        gpu_host_status=runtime_status.gpu_host_status,
        model_sync=model_sync,
    )


@router.get("/runner/diagnostics")
async def get_inference_runner_diagnostics():
    return get_inference_runtime_manager().get_diagnostics()


async def _run_inference_start_operation(
    operation_id: str,
    *,
    model_id: str,
    device: str | None,
    task: str | None,
) -> None:
    operations = get_startup_operations_service()
    progress_callback = operations.build_progress_callback(operation_id)
    manager = get_inference_session_manager()
    try:
        state = await manager.create(
            model_id=model_id,
            device=device,
            task=task,
            progress_callback=progress_callback,
        )
        operations.complete(
            operation_id=operation_id,
            target_session_id=state.extras["worker_session_id"],
            message="推論セッションの準備が完了しました。",
        )
    except HTTPException as exc:
        operations.fail(
            operation_id=operation_id,
            message="推論セッションの準備に失敗しました。",
            error=str(exc.detail),
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to UI
        logger.exception("inference startup operation failed: %s", operation_id)
        operations.fail(
            operation_id=operation_id,
            message="推論セッションの準備に失敗しました。",
            error=str(exc),
        )


@router.post(
    "/runner/start",
    response_model=StartupOperationAcceptedResponse,
    status_code=202,
)
async def start_inference_runner(request: InferenceRunnerStartRequest):
    user_id = require_user_id()
    operation = get_startup_operations_service().create(
        user_id=user_id,
        kind="inference_start",
    )
    asyncio.create_task(
        _run_inference_start_operation(
            operation.operation_id,
            model_id=request.model_id,
            device=request.device,
            task=request.task,
        )
    )
    return operation


@router.post("/runner/stop", response_model=InferenceRunnerStopResponse)
async def stop_inference_runner(request: InferenceRunnerStopRequest):
    mgr = get_inference_session_manager()
    active = mgr.any_active()

    if active:
        state = await mgr.stop(active.id)
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
