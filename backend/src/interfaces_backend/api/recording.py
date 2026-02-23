"""Recording API router (lerobot_session_recorder WebAPI bridge)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from interfaces_backend.services.recorder_bridge import get_recorder_bridge
from interfaces_backend.services.dataset_lifecycle import get_dataset_lifecycle
from interfaces_backend.services.recording_session import get_recording_session_manager
from interfaces_backend.services.session_control_events import (
    publish_session_control_event_safely,
)
from interfaces_backend.services.session_manager import require_user_id
from interfaces_backend.services.startup_operations import get_startup_operations_service
from interfaces_backend.models.startup import StartupOperationAcceptedResponse
from percus_ai.db import get_supabase_async_client
from percus_ai.storage.naming import validate_dataset_name
from percus_ai.storage.paths import get_datasets_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recording", tags=["recording"])


async def _emit_recording_control_event(
    *,
    action: str,
    phase: str,
    session_id: str | None = None,
    operation_id: str | None = None,
    success: bool | None = None,
    message: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    await publish_session_control_event_safely(
        session_kind="recording",
        action=action,
        phase=phase,
        session_id=session_id,
        operation_id=operation_id,
        success=success,
        message=message,
        details=details,
    )


# -- Request / Response models ------------------------------------------------


class RecordingSessionCreateRequest(BaseModel):
    dataset_name: str = Field(..., description="Dataset display name")
    task: str = Field(..., description="Task description")
    profile: Optional[str] = Field(None, description="Optional VLAbor profile name")
    num_episodes: int = Field(1, ge=1, description="Number of episodes")
    episode_time_s: float = Field(60.0, gt=0, description="Episode length in seconds")
    reset_time_s: float = Field(10.0, ge=0, description="Reset wait time in seconds")
    continue_from_dataset_id: Optional[str] = Field(
        None,
        description="Continue recording from an existing dataset ID",
    )


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


class RecordingSessionUpdateRequest(BaseModel):
    task: Optional[str] = None
    episode_time_s: Optional[float] = Field(None, gt=0)
    reset_time_s: Optional[float] = Field(None, ge=0)
    num_episodes: Optional[int] = Field(None, ge=1)


class RecordingUploadStatusResponse(BaseModel):
    dataset_id: str
    status: str = "idle"
    phase: str = "idle"
    progress_percent: float = 0.0
    message: str = ""
    files_done: int = 0
    total_files: int = 0
    current_file: Optional[str] = None
    error: Optional[str] = None
    updated_at: Optional[str] = None


class RecordingInfo(BaseModel):
    recording_id: str
    dataset_name: str
    task: str = ""
    profile_name: Optional[str] = None
    created_at: Optional[str] = None
    episode_count: int = 0
    target_total_episodes: int = 0
    remaining_episodes: int = 0
    episode_time_s: float = 0.0
    reset_time_s: float = 0.0
    continuable: bool = False
    continue_block_reason: Optional[str] = None
    size_bytes: int = 0
    is_local: bool = False


class RecordingListResponse(BaseModel):
    recordings: List[RecordingInfo]
    total: int


class RecordingValidateResponse(BaseModel):
    recording_id: str
    is_valid: bool
    errors: List[str] = []
    warnings: List[str] = []


class RecordingContinuePlanResponse(BaseModel):
    recording_id: str
    dataset_name: str
    task: str
    profile_name: Optional[str] = None
    episode_count: int = 0
    target_total_episodes: int = 0
    remaining_episodes: int = 0
    episode_time_s: float = 0.0
    reset_time_s: float = 0.0
    continuable: bool = False
    reason: Optional[str] = None


# -- helpers ------------------------------------------------------------------


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


def _to_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_continue_plan_from_row(row: dict) -> RecordingContinuePlanResponse:
    recording_id = str(row.get("id") or "").strip()
    dataset_name = str(row.get("name") or "").strip()
    task = str(row.get("task_detail") or "").strip()
    profile_name = _extract_profile_name(row.get("profile_snapshot"))
    episode_count = max(_to_int(row.get("episode_count"), default=0), 0)
    target_total_episodes = max(_to_int(row.get("target_total_episodes"), default=0), 0)
    episode_time_s = _to_float(row.get("episode_time_s"), default=0.0)
    reset_time_s = _to_float(row.get("reset_time_s"), default=0.0)
    remaining_episodes = max(target_total_episodes - episode_count, 0)

    continuable = True
    reason: str | None = None

    if str(row.get("dataset_type") or "") != "recorded":
        continuable = False
        reason = "recorded データセットのみ継続できます"
    elif str(row.get("status") or "").lower() == "archived":
        continuable = False
        reason = "アーカイブ済みデータセットです"
    elif target_total_episodes <= 0:
        continuable = False
        reason = "目標エピソード総数が設定されていません"
    elif remaining_episodes <= 0:
        continuable = False
        reason = "残りエピソードがありません"
    elif episode_time_s <= 0:
        continuable = False
        reason = "エピソード秒数が設定されていません"
    elif reset_time_s < 0:
        continuable = False
        reason = "リセット待機秒数の設定が不正です"
    elif not (get_datasets_dir() / recording_id).exists():
        continuable = False
        reason = "ローカルデータセットが見つかりません"

    return RecordingContinuePlanResponse(
        recording_id=recording_id,
        dataset_name=dataset_name,
        task=task,
        profile_name=profile_name,
        episode_count=episode_count,
        target_total_episodes=target_total_episodes,
        remaining_episodes=remaining_episodes,
        episode_time_s=episode_time_s,
        reset_time_s=reset_time_s,
        continuable=continuable,
        reason=reason,
    )


async def _fetch_recording_row(recording_id: str) -> dict:
    client = await get_supabase_async_client()
    rows = (
        await client.table("datasets")
        .select(
            "id,name,task_detail,profile_snapshot,episode_count,target_total_episodes,episode_time_s,reset_time_s,size_bytes,created_at,dataset_type,status"
        )
        .eq("id", recording_id)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")
    return rows[0]


# -- Session endpoints --------------------------------------------------------


async def _run_recording_create_operation(
    operation_id: str,
    request: RecordingSessionCreateRequest,
) -> None:
    operations = get_startup_operations_service()
    progress_callback = operations.build_progress_callback(operation_id)
    manager = get_recording_session_manager()
    try:
        if request.continue_from_dataset_id:
            state = await _create_continue_session(
                manager=manager,
                recording_id=request.continue_from_dataset_id,
                episode_time_s=request.episode_time_s,
                reset_time_s=request.reset_time_s,
                progress_callback=progress_callback,
            )
        else:
            state = await manager.create(
                profile=request.profile,
                dataset_name=request.dataset_name,
                task=request.task,
                num_episodes=request.num_episodes,
                target_total_episodes=request.num_episodes,
                episode_time_s=request.episode_time_s,
                reset_time_s=request.reset_time_s,
                progress_callback=progress_callback,
            )
        operations.complete(
            operation_id=operation_id,
            target_session_id=state.id,
            message="録画セッションの準備が完了しました。",
        )
    except HTTPException as exc:
        operations.fail(
            operation_id=operation_id,
            message="録画セッションの準備に失敗しました。",
            error=str(exc.detail),
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to UI
        logger.exception("recording startup operation failed: %s", operation_id)
        operations.fail(
            operation_id=operation_id,
            message="録画セッションの準備に失敗しました。",
            error=str(exc),
        )


async def _create_continue_session(
    *,
    manager,
    recording_id: str,
    episode_time_s: float | None = None,
    reset_time_s: float | None = None,
    progress_callback=None,
):
    row = await _fetch_recording_row(recording_id)
    plan = _build_continue_plan_from_row(row)
    if not plan.continuable:
        raise HTTPException(status_code=400, detail=plan.reason or "Recording cannot continue")
    return await manager.create(
        session_id=plan.recording_id,
        profile=plan.profile_name,
        dataset_name=plan.dataset_name,
        task=plan.task,
        num_episodes=plan.remaining_episodes,
        target_total_episodes=plan.target_total_episodes,
        episode_time_s=plan.episode_time_s if episode_time_s is None else episode_time_s,
        reset_time_s=plan.reset_time_s if reset_time_s is None else reset_time_s,
        progress_callback=progress_callback,
    )


@router.post(
    "/session/create",
    response_model=StartupOperationAcceptedResponse,
    status_code=202,
)
async def create_session(request: RecordingSessionCreateRequest):
    user_id = require_user_id()

    if request.continue_from_dataset_id:
        row = await _fetch_recording_row(request.continue_from_dataset_id)
        plan = _build_continue_plan_from_row(row)
        if not plan.continuable:
            raise HTTPException(status_code=400, detail=plan.reason or "Recording cannot continue")
    else:
        is_valid, errors = validate_dataset_name(request.dataset_name)
        if not is_valid:
            raise HTTPException(status_code=400, detail=f"Invalid dataset name: {'; '.join(errors)}")
    operation = get_startup_operations_service().create(
        user_id=user_id,
        kind="recording_create",
    )
    asyncio.create_task(_run_recording_create_operation(operation.operation_id, request))
    await _emit_recording_control_event(
        action="session_create",
        phase="accepted",
        session_id=request.continue_from_dataset_id or "global",
        operation_id=operation.operation_id,
        success=True,
        message="Recording session create operation accepted.",
        details={
            "dataset_name": request.dataset_name,
            "continue_from_dataset_id": request.continue_from_dataset_id,
        },
    )
    return operation


@router.post("/session/start", response_model=RecordingSessionActionResponse)
async def start_session(request: RecordingSessionStartRequest):
    require_user_id()
    mgr = get_recording_session_manager()
    resumed = False
    if mgr.status(request.dataset_id) is None:
        await _create_continue_session(
            manager=mgr,
            recording_id=request.dataset_id,
        )
        resumed = True

    state = await mgr.start(request.dataset_id)
    response = RecordingSessionActionResponse(
        success=True,
        message="Recording session resumed" if resumed else "Recording session started",
        dataset_id=state.id,
        status=state.extras.get("recorder_result"),
    )
    await _emit_recording_control_event(
        action="session_start",
        phase="completed",
        session_id=state.id,
        success=True,
        message=response.message,
        details={"resumed": resumed},
    )
    return response


@router.post("/session/stop", response_model=RecordingSessionActionResponse)
async def stop_session(request: RecordingSessionStopRequest):
    require_user_id()
    mgr = get_recording_session_manager()

    dataset_id = request.dataset_id
    if not dataset_id:
        active = mgr.any_active()
        if active:
            dataset_id = active.id

    if dataset_id:
        state = await mgr.stop(dataset_id, save_current=request.save_current)
        response = RecordingSessionActionResponse(
            success=True,
            message="Recording session stopped",
            dataset_id=state.id,
            status=state.extras.get("recorder_result"),
        )
        await _emit_recording_control_event(
            action="session_stop",
            phase="completed",
            session_id=state.id,
            success=True,
            message=response.message,
            details={"save_current": request.save_current},
        )
        return response

    # No tracked session — stop recorder directly (best-effort)
    recorder = get_recorder_bridge()
    result = recorder.stop(save_current=request.save_current)
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder stop failed")
    response = RecordingSessionActionResponse(
        success=True,
        message="Recording session stopped",
        status=result,
    )
    await _emit_recording_control_event(
        action="session_stop",
        phase="completed",
        session_id="global",
        success=True,
        message=response.message,
        details={"save_current": request.save_current, "mode": "recorder_fallback"},
    )
    return response


@router.post("/session/pause", response_model=RecordingSessionActionResponse)
async def pause_session():
    require_user_id()
    recorder = get_recorder_bridge()
    result = recorder.pause()
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder pause failed")
    dataset_id = str(result.get("dataset_id") or "").strip() or "global"
    response = RecordingSessionActionResponse(success=True, message="Recording paused", status=result)
    await _emit_recording_control_event(
        action="session_pause",
        phase="completed",
        session_id=dataset_id,
        success=True,
        message=response.message,
    )
    return response


@router.post("/session/resume", response_model=RecordingSessionActionResponse)
async def resume_session():
    require_user_id()
    recorder = get_recorder_bridge()
    result = recorder.resume()
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder resume failed")
    dataset_id = str(result.get("dataset_id") or "").strip() or "global"
    response = RecordingSessionActionResponse(success=True, message="Recording resumed", status=result)
    await _emit_recording_control_event(
        action="session_resume",
        phase="completed",
        session_id=dataset_id,
        success=True,
        message=response.message,
    )
    return response


@router.post("/session/update", response_model=RecordingSessionActionResponse)
async def update_session(request: RecordingSessionUpdateRequest):
    require_user_id()
    payload: dict[str, Any] = {}
    if request.task is not None:
        task = request.task.strip()
        if not task:
            raise HTTPException(status_code=400, detail="task must not be empty")
        payload["task"] = task
    if request.episode_time_s is not None:
        payload["episode_time_s"] = float(request.episode_time_s)
    if request.reset_time_s is not None:
        payload["reset_time_s"] = float(request.reset_time_s)
    if request.num_episodes is not None:
        payload["num_episodes"] = int(request.num_episodes)
    if not payload:
        raise HTTPException(status_code=400, detail="No update fields provided")

    recorder = get_recorder_bridge()
    result = recorder.update(payload)
    if not result.get("success", False):
        raise HTTPException(
            status_code=500,
            detail=result.get("error") or result.get("message") or "Recorder update failed",
        )

    dataset_id = str(result.get("dataset_id") or "").strip() or None
    if dataset_id:
        db_updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if "task" in payload:
            db_updates["task_detail"] = payload["task"]
        if "episode_time_s" in payload:
            db_updates["episode_time_s"] = payload["episode_time_s"]
        if "reset_time_s" in payload:
            db_updates["reset_time_s"] = payload["reset_time_s"]
        if "num_episodes" in payload:
            db_updates["target_total_episodes"] = payload["num_episodes"]
        try:
            client = await get_supabase_async_client()
            await client.table("datasets").update(db_updates).eq("id", dataset_id).execute()
        except Exception as exc:
            logger.warning("Failed to persist recording settings update: %s", exc)

    response = RecordingSessionActionResponse(
        success=True,
        message=str(result.get("message") or "Recording session updated"),
        dataset_id=dataset_id,
        status=result.get("status") if isinstance(result.get("status"), dict) else result,
    )
    await _emit_recording_control_event(
        action="session_update",
        phase="completed",
        session_id=dataset_id or "global",
        success=True,
        message=response.message,
        details=payload,
    )
    return response


@router.post("/episode/redo", response_model=RecordingSessionActionResponse)
async def redo_episode():
    require_user_id()
    recorder = get_recorder_bridge()
    result = recorder.redo_episode()
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder redo failed")
    response = RecordingSessionActionResponse(
        success=True,
        message="Episode redo requested",
        dataset_id=result.get("dataset_id"),
        status=result,
    )
    await _emit_recording_control_event(
        action="episode_redo",
        phase="completed",
        session_id=str(result.get("dataset_id") or "").strip() or "global",
        success=True,
        message=response.message,
    )
    return response


@router.post("/episode/redo-previous", response_model=RecordingSessionActionResponse)
async def redo_previous_episode():
    require_user_id()
    recorder = get_recorder_bridge()
    status = recorder.status()
    state = status.get("state")
    dataset_id = status.get("dataset_id")
    if not dataset_id:
        raise HTTPException(status_code=400, detail="No active session")
    if state == "paused":
        raise HTTPException(status_code=400, detail="Cannot redo while paused")

    if state == "recording":
        cancel = recorder.cancel_episode()
        if not cancel.get("success", False):
            raise HTTPException(
                status_code=500, detail=cancel.get("error") or "Recorder episode cancel failed"
            )
        deadline = time.time() + 5.0
        while time.time() < deadline:
            status = recorder.status()
            state = status.get("state")
            if state not in ("recording", "paused"):
                break
            time.sleep(0.1)

    result = recorder.redo_episode()
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder redo failed")

    response = RecordingSessionActionResponse(
        success=True,
        message="Previous episode will be re-recorded",
        dataset_id=dataset_id,
        status=result,
    )
    await _emit_recording_control_event(
        action="episode_redo_previous",
        phase="completed",
        session_id=str(dataset_id or "").strip() or "global",
        success=True,
        message=response.message,
    )
    return response


@router.post("/episode/cancel", response_model=RecordingSessionActionResponse)
async def cancel_episode():
    require_user_id()
    recorder = get_recorder_bridge()
    result = recorder.cancel_episode()
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder episode cancel failed")
    dataset_id = str(result.get("dataset_id") or "").strip() or "global"
    response = RecordingSessionActionResponse(success=True, message="Episode cancelled", status=result)
    await _emit_recording_control_event(
        action="episode_cancel",
        phase="completed",
        session_id=dataset_id,
        success=True,
        message=response.message,
    )
    return response


@router.post(
    "/episode/next",
    response_model=RecordingSessionActionResponse,
    status_code=202,
)
async def next_episode():
    require_user_id()
    recorder = get_recorder_bridge()
    result = recorder.next_episode()
    if not result.get("success", False):
        raise HTTPException(
            status_code=500,
            detail=result.get("error") or "Recorder next episode failed",
        )
    response = RecordingSessionActionResponse(
        success=True,
        message=str(result.get("message") or "Episode transition accepted"),
        dataset_id=result.get("dataset_id"),
        status=result,
    )
    await _emit_recording_control_event(
        action="episode_next",
        phase="completed",
        session_id=str(result.get("dataset_id") or "").strip() or "global",
        success=True,
        message=response.message,
    )
    return response


@router.post("/session/cancel", response_model=RecordingSessionActionResponse)
async def cancel_session(dataset_id: Optional[str] = None):
    require_user_id()
    mgr = get_recording_session_manager()
    recorder = get_recorder_bridge()
    result: dict = {}

    if dataset_id:
        session = mgr.status(dataset_id)
        if session:
            state = await mgr.stop(dataset_id, save_current=False, cancel=True)
            result = state.extras.get("recorder_result", {})
        else:
            # Not tracked — check recorder directly
            try:
                rec_status = recorder.status()
                active_id = rec_status.get("dataset_id")
                active_state = rec_status.get("state")
                if active_id == dataset_id and active_state not in ("idle", "completed"):
                    result = recorder.stop(save_current=False)
                    if not result.get("success", False):
                        raise HTTPException(
                            status_code=500, detail=result.get("error") or "Recorder cancel failed"
                        )
            except HTTPException as exc:
                if exc.status_code != 503:
                    raise
        client = await get_supabase_async_client()
        await client.table("datasets").update({"status": "archived"}).eq("id", dataset_id).execute()
    else:
        result = recorder.stop(save_current=False)
        if not result.get("success", False):
            raise HTTPException(status_code=500, detail=result.get("error") or "Recorder cancel failed")

    response = RecordingSessionActionResponse(
        success=True,
        message="Recording cancelled",
        dataset_id=dataset_id,
        status=result,
    )
    await _emit_recording_control_event(
        action="session_cancel",
        phase="completed",
        session_id=(dataset_id or "").strip() or "global",
        success=True,
        message=response.message,
    )
    return response


@router.get("/sessions/{session_id}/status", response_model=RecordingSessionStatusResponse)
async def get_session_status(session_id: str):
    require_user_id()
    recorder = get_recorder_bridge()
    status = recorder.status()
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


@router.get(
    "/sessions/{session_id}/upload-status",
    response_model=RecordingUploadStatusResponse,
)
async def get_session_upload_status(session_id: str):
    require_user_id()
    lifecycle = get_dataset_lifecycle()
    status = lifecycle.get_dataset_upload_status(session_id)
    return RecordingUploadStatusResponse(**status)


# -- Recording management endpoints (DB / filesystem) ------------------------


async def _list_recordings() -> list[dict]:
    client = await get_supabase_async_client()
    rows = (
        await client.table("datasets")
        .select(
            "id,name,task_detail,profile_snapshot,episode_count,target_total_episodes,episode_time_s,reset_time_s,size_bytes,created_at,dataset_type,status"
        )
        .eq("dataset_type", "recorded")
        .execute()
    ).data or []
    return [row for row in rows if row.get("status") != "archived"]


@router.get("/recordings", response_model=RecordingListResponse)
async def list_recordings():
    recordings_data = await _list_recordings()
    recordings: list[RecordingInfo] = []
    for row in recordings_data:
        if not row.get("id"):
            continue
        plan = _build_continue_plan_from_row(row)
        recordings.append(
            RecordingInfo(
                recording_id=str(row.get("id")),
                dataset_name=str(row.get("name") or row.get("id")),
                task=str(row.get("task_detail") or ""),
                profile_name=_extract_profile_name(row.get("profile_snapshot")),
                created_at=row.get("created_at"),
                episode_count=row.get("episode_count") or 0,
                target_total_episodes=plan.target_total_episodes,
                remaining_episodes=plan.remaining_episodes,
                episode_time_s=plan.episode_time_s,
                reset_time_s=plan.reset_time_s,
                continuable=plan.continuable,
                continue_block_reason=plan.reason,
                size_bytes=row.get("size_bytes") or 0,
                is_local=(get_datasets_dir() / str(row.get("id"))).exists(),
            )
        )
    return RecordingListResponse(recordings=recordings, total=len(recordings))


@router.get(
    "/recordings/{recording_id:path}/continue-plan",
    response_model=RecordingContinuePlanResponse,
)
async def get_recording_continue_plan(recording_id: str):
    row = await _fetch_recording_row(recording_id)
    return _build_continue_plan_from_row(row)


@router.get("/recordings/{recording_id:path}", response_model=RecordingInfo)
async def get_recording(recording_id: str):
    row = await _fetch_recording_row(recording_id)
    plan = _build_continue_plan_from_row(row)
    return RecordingInfo(
        recording_id=str(row.get("id")),
        dataset_name=str(row.get("name") or row.get("id")),
        task=str(row.get("task_detail") or ""),
        profile_name=_extract_profile_name(row.get("profile_snapshot")),
        created_at=row.get("created_at"),
        episode_count=row.get("episode_count") or 0,
        target_total_episodes=plan.target_total_episodes,
        remaining_episodes=plan.remaining_episodes,
        episode_time_s=plan.episode_time_s,
        reset_time_s=plan.reset_time_s,
        continuable=plan.continuable,
        continue_block_reason=plan.reason,
        size_bytes=row.get("size_bytes") or 0,
        is_local=(get_datasets_dir() / str(row.get("id"))).exists(),
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
