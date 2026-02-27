"""In-memory model sync job tracking for storage sync operations."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException

from interfaces_backend.models.storage import (
    ModelSyncJobAcceptedResponse,
    ModelSyncJobCancelResponse,
    ModelSyncJobDetail,
    ModelSyncJobListResponse,
    ModelSyncJobState,
    ModelSyncJobStatus,
)
from interfaces_backend.services.realtime_events import get_realtime_event_bus

MODEL_SYNC_JOB_TOPIC = "storage.model_sync.job"
_ACTIVE_STATES: set[ModelSyncJobState] = {"queued", "running"}
_TERMINAL_STATES: set[ModelSyncJobState] = {"completed", "failed", "cancelled"}
_DEFAULT_TTL_SECONDS = 1800

ProgressCallback = Callable[[dict[str, Any]], None]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _JobRecord:
    job_id: str
    user_id: str
    model_id: str
    state: ModelSyncJobState = "queued"
    progress_percent: float = 0.0
    message: str | None = None
    error: str | None = None
    detail: ModelSyncJobDetail = field(default_factory=ModelSyncJobDetail)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_response(self) -> ModelSyncJobStatus:
        return ModelSyncJobStatus(
            job_id=self.job_id,
            model_id=self.model_id,
            state=self.state,
            progress_percent=self.progress_percent,
            message=self.message,
            error=self.error,
            detail=self.detail.model_copy(deep=True),
            created_at=self.created_at.isoformat(),
            updated_at=self.updated_at.isoformat(),
        )


class ModelSyncJobsService:
    def __init__(self, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._jobs: dict[str, _JobRecord] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancel_events: dict[str, threading.Event] = {}

    def create(self, *, user_id: str, model_id: str) -> ModelSyncJobAcceptedResponse:
        with self._lock:
            self._cleanup_locked()
            for job in self._jobs.values():
                if job.user_id == user_id and job.state in _ACTIVE_STATES:
                    raise HTTPException(status_code=409, detail="A model sync job is already in progress")

            job_id = uuid4().hex
            now = _utcnow()
            self._jobs[job_id] = _JobRecord(
                job_id=job_id,
                user_id=user_id,
                model_id=model_id,
                state="queued",
                message="モデル同期ジョブを受け付けました。",
                created_at=now,
                updated_at=now,
            )
            self._cancel_events[job_id] = threading.Event()
            snapshot = self._jobs[job_id].to_response()
        self._publish(snapshot)
        return ModelSyncJobAcceptedResponse(
            job_id=job_id,
            model_id=model_id,
            state="queued",
            message="accepted",
        )

    def attach_task(self, *, user_id: str, job_id: str, task: asyncio.Task[None]) -> None:
        with self._lock:
            record = self._get_for_user_locked(user_id=user_id, job_id=job_id)
            if record.state in _TERMINAL_STATES:
                return
            self._tasks[job_id] = task

    def release_runtime_handles(self, *, job_id: str) -> None:
        with self._lock:
            self._tasks.pop(job_id, None)
            record = self._jobs.get(job_id)
            if record is not None and record.state in _TERMINAL_STATES:
                self._cancel_events.pop(job_id, None)

    def list(self, *, user_id: str, include_terminal: bool = False) -> ModelSyncJobListResponse:
        with self._lock:
            self._cleanup_locked()
            jobs = []
            for job in self._jobs.values():
                if job.user_id != user_id:
                    continue
                if not include_terminal and job.state in _TERMINAL_STATES:
                    continue
                jobs.append(job.to_response())
        jobs.sort(key=lambda job: str(job.updated_at or ""), reverse=True)
        return ModelSyncJobListResponse(jobs=jobs)

    def get(self, *, user_id: str, job_id: str) -> ModelSyncJobStatus:
        with self._lock:
            self._cleanup_locked()
            return self._get_for_user_locked(user_id=user_id, job_id=job_id).to_response()

    def get_cancel_event(self, *, job_id: str) -> threading.Event | None:
        with self._lock:
            return self._cancel_events.get(job_id)

    def cancel(self, *, user_id: str, job_id: str) -> ModelSyncJobCancelResponse:
        with self._lock:
            self._cleanup_locked()
            record = self._get_for_user_locked(user_id=user_id, job_id=job_id)
            if record.state in _TERMINAL_STATES:
                return ModelSyncJobCancelResponse(
                    job_id=record.job_id,
                    accepted=False,
                    state=record.state,
                    message="Job is already finished.",
                )
            cancel_event = self._cancel_events.get(job_id)
            if cancel_event is None:
                cancel_event = threading.Event()
                self._cancel_events[job_id] = cancel_event
            cancel_event.set()
            if record.state == "queued":
                record.state = "cancelled"
                record.progress_percent = 0.0
                record.message = "モデル同期を中断しました。"
                record.error = None
            else:
                record.message = "モデル同期の中断を要求しました。"
            record.updated_at = _utcnow()
            snapshot = record.to_response()
        self._publish(snapshot)
        return ModelSyncJobCancelResponse(
            job_id=snapshot.job_id,
            accepted=True,
            state=snapshot.state,
            message=snapshot.message or "Cancel requested.",
        )

    def set_running(
        self,
        *,
        job_id: str,
        progress_percent: float,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._update(
            job_id=job_id,
            state="running",
            progress_percent=progress_percent,
            message=message,
            error=None,
            detail=detail,
        )

    def complete(self, *, job_id: str, message: str) -> None:
        self._update(
            job_id=job_id,
            state="completed",
            progress_percent=100.0,
            message=message,
            error=None,
        )

    def fail(self, *, job_id: str, message: str, error: str) -> None:
        self._update(
            job_id=job_id,
            state="failed",
            progress_percent=100.0,
            message=message,
            error=error,
        )

    def cancelled(self, *, job_id: str, message: str = "モデル同期を中断しました。") -> None:
        self._update(
            job_id=job_id,
            state="cancelled",
            message=message,
            error=None,
        )

    def build_progress_callback(self, *, job_id: str) -> ProgressCallback:
        def _callback(progress: dict[str, Any]) -> None:
            event_type = str(progress.get("type") or "")
            if event_type == "cancelled":
                self.cancelled(job_id=job_id, message=str(progress.get("message") or "モデル同期を中断しました。"))
                return
            if event_type == "complete":
                self.complete(job_id=job_id, message=str(progress.get("message") or "モデル同期が完了しました。"))
                return
            if event_type == "error":
                self.fail(
                    job_id=job_id,
                    message=str(progress.get("message") or "モデル同期に失敗しました。"),
                    error=str(progress.get("error") or "unknown error"),
                )
                return
            message = str(progress.get("message") or "モデルを同期中です...")
            progress_percent = self._to_float(progress.get("progress_percent"))
            detail = {
                "files_done": self._to_int(progress.get("files_done")),
                "total_files": self._to_int(progress.get("total_files")),
                "transferred_bytes": self._to_int(
                    progress.get("bytes_done_total", progress.get("bytes_transferred"))
                ),
                "total_bytes": self._to_int(progress.get("total_size")),
                "current_file": str(progress.get("current_file")) if progress.get("current_file") else None,
            }
            if progress_percent is None:
                progress_percent = self._compute_progress_percent(
                    total_files=detail["total_files"],
                    files_done=detail["files_done"],
                    total_bytes=detail["total_bytes"],
                    transferred_bytes=detail["transferred_bytes"],
                )
            self.set_running(
                job_id=job_id,
                progress_percent=progress_percent,
                message=message,
                detail=detail,
            )

        return _callback

    def _update(
        self,
        *,
        job_id: str,
        state: ModelSyncJobState | None = None,
        progress_percent: float | None = None,
        message: str | None = None,
        error: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        snapshot: ModelSyncJobStatus | None = None
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            if record.state in _TERMINAL_STATES:
                return
            if state is not None:
                record.state = state
            if progress_percent is not None:
                record.progress_percent = self._clamp_progress(progress_percent)
            if message is not None:
                record.message = message
            record.error = error
            if detail:
                payload = record.detail.model_dump(mode="python")
                payload.update(detail)
                record.detail = ModelSyncJobDetail.model_validate(payload)
            record.updated_at = _utcnow()
            snapshot = record.to_response()
            if record.state in _TERMINAL_STATES:
                self._tasks.pop(job_id, None)
                self._cancel_events.pop(job_id, None)
        if snapshot is not None:
            self._publish(snapshot)

    def _publish(self, snapshot: ModelSyncJobStatus) -> None:
        get_realtime_event_bus().publish_threadsafe(
            MODEL_SYNC_JOB_TOPIC,
            snapshot.job_id,
            snapshot.model_dump(mode="json"),
        )

    def _cleanup_locked(self) -> None:
        cutoff = _utcnow() - timedelta(seconds=self._ttl_seconds)
        stale_job_ids = [
            job_id
            for job_id, job in self._jobs.items()
            if job.state in _TERMINAL_STATES and job.updated_at < cutoff
        ]
        for job_id in stale_job_ids:
            self._jobs.pop(job_id, None)
            self._tasks.pop(job_id, None)
            self._cancel_events.pop(job_id, None)

    def _get_for_user_locked(self, *, user_id: str, job_id: str) -> _JobRecord:
        record = self._jobs.get(job_id)
        if record is None or record.user_id != user_id:
            raise HTTPException(status_code=404, detail=f"Model sync job not found: {job_id}")
        return record

    @staticmethod
    def _clamp_progress(value: float) -> float:
        return min(max(float(value), 0.0), 100.0)

    @staticmethod
    def _to_int(value: object) -> int:
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_float(value: object) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _compute_progress_percent(
        cls,
        *,
        total_files: int,
        files_done: int,
        total_bytes: int,
        transferred_bytes: int,
    ) -> float:
        if total_bytes > 0:
            ratio = transferred_bytes / total_bytes
        elif total_files > 0:
            ratio = files_done / total_files
        else:
            ratio = 0.0
        return round(cls._clamp_progress(ratio * 100.0), 2)


_service: ModelSyncJobsService | None = None


def get_model_sync_jobs_service() -> ModelSyncJobsService:
    global _service
    if _service is None:
        _service = ModelSyncJobsService()
    return _service


def reset_model_sync_jobs_service() -> None:
    global _service
    _service = None
