"""In-memory startup operation tracking for long-running start actions."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException

from interfaces_backend.models.startup import (
    StartupOperationAcceptedResponse,
    StartupOperationDetail,
    StartupOperationKind,
    StartupOperationState,
    StartupOperationStatusResponse,
)
from interfaces_backend.services.realtime_events import get_realtime_event_bus

_ACTIVE_STATES: set[StartupOperationState] = {"queued", "running"}
_TERMINAL_STATES: set[StartupOperationState] = {"completed", "failed"}
_DEFAULT_TTL_SECONDS = 1800
STARTUP_OPERATION_TOPIC = "startup.operation"

ProgressCallback = Callable[[str, float, str, dict[str, Any] | None], None]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


@dataclass
class _OperationRecord:
    operation_id: str
    user_id: str
    kind: StartupOperationKind
    state: StartupOperationState = "queued"
    phase: str = "queued"
    progress_percent: float = 0.0
    message: str | None = None
    target_session_id: str | None = None
    error: str | None = None
    detail: StartupOperationDetail = field(default_factory=StartupOperationDetail)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_response(self) -> StartupOperationStatusResponse:
        return StartupOperationStatusResponse(
            operation_id=self.operation_id,
            kind=self.kind,
            state=self.state,
            phase=self.phase,
            progress_percent=self.progress_percent,
            message=self.message,
            target_session_id=self.target_session_id,
            error=self.error,
            detail=self.detail.model_copy(deep=True),
            updated_at=self.updated_at.isoformat(),
        )


class StartupOperationsService:
    def __init__(self, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._operations: dict[str, _OperationRecord] = {}

    def create(self, *, user_id: str, kind: StartupOperationKind) -> StartupOperationAcceptedResponse:
        with self._lock:
            self._cleanup_locked()
            for op in self._operations.values():
                if op.user_id == user_id and op.kind == kind and op.state in _ACTIVE_STATES:
                    raise HTTPException(
                        status_code=409,
                        detail=f"{kind} startup is already in progress",
                    )
            operation_id = uuid4().hex
            self._operations[operation_id] = _OperationRecord(
                operation_id=operation_id,
                user_id=user_id,
                kind=kind,
                message="処理を開始しました。",
            )
            record = self._operations[operation_id].to_response()
        self._publish_status(record)
        return StartupOperationAcceptedResponse(operation_id=operation_id, message="accepted")

    def get(self, *, user_id: str, operation_id: str) -> StartupOperationStatusResponse:
        with self._lock:
            self._cleanup_locked()
            record = self._operations.get(operation_id)
            if record is None or record.user_id != user_id:
                raise HTTPException(status_code=404, detail=f"Operation not found: {operation_id}")
            return record.to_response()

    def set_running(
        self,
        *,
        operation_id: str,
        phase: str,
        progress_percent: float,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._update(
            operation_id=operation_id,
            state="running",
            phase=phase,
            progress_percent=progress_percent,
            message=message,
            detail=detail,
            error=None,
        )

    def complete(
        self,
        *,
        operation_id: str,
        target_session_id: str,
        message: str = "完了しました。",
    ) -> None:
        self._update(
            operation_id=operation_id,
            state="completed",
            phase="done",
            progress_percent=100.0,
            message=message,
            target_session_id=target_session_id,
            error=None,
        )

    def fail(
        self,
        *,
        operation_id: str,
        message: str,
        error: str,
    ) -> None:
        self._update(
            operation_id=operation_id,
            state="failed",
            phase="error",
            message=message,
            error=error,
        )

    def build_progress_callback(self, operation_id: str) -> ProgressCallback:
        def _callback(phase: str, progress_percent: float, message: str, detail: dict[str, Any] | None = None) -> None:
            self.set_running(
                operation_id=operation_id,
                phase=phase,
                progress_percent=progress_percent,
                message=message,
                detail=detail,
            )

        return _callback

    def _update(
        self,
        *,
        operation_id: str,
        state: StartupOperationState | None = None,
        phase: str | None = None,
        progress_percent: float | None = None,
        message: str | None = None,
        target_session_id: str | None = None,
        error: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        response: StartupOperationStatusResponse | None = None
        with self._lock:
            record = self._operations.get(operation_id)
            if record is None:
                return
            if state is not None:
                record.state = state
            if phase is not None:
                record.phase = phase
            if progress_percent is not None:
                record.progress_percent = max(0.0, min(100.0, float(progress_percent)))
            if message is not None:
                record.message = message
            if target_session_id is not None:
                record.target_session_id = target_session_id
            record.error = error
            if detail:
                detail_payload = record.detail.model_dump(mode="python")
                detail_payload.update(detail)
                record.detail = StartupOperationDetail.model_validate(detail_payload)
            record.updated_at = _utcnow()
            response = record.to_response()
        if response is not None:
            self._publish_status(response)

    @staticmethod
    def _publish_status(status: StartupOperationStatusResponse) -> None:
        get_realtime_event_bus().publish_threadsafe(
            STARTUP_OPERATION_TOPIC,
            status.operation_id,
            status.model_dump(mode="json"),
        )

    def _cleanup_locked(self) -> None:
        cutoff = _utcnow() - timedelta(seconds=self._ttl_seconds)
        stale_ids = [
            op_id
            for op_id, op in self._operations.items()
            if op.state in _TERMINAL_STATES and op.updated_at < cutoff
        ]
        for op_id in stale_ids:
            self._operations.pop(op_id, None)


_service: StartupOperationsService | None = None


def get_startup_operations_service() -> StartupOperationsService:
    global _service
    if _service is None:
        _service = StartupOperationsService()
    return _service


def reset_startup_operations_service() -> None:
    global _service
    _service = None
