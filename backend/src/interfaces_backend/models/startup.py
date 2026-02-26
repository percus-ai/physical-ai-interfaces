"""Startup operation API models."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

StartupOperationKind = Literal["inference_start", "recording_create"]
StartupOperationState = Literal["queued", "running", "completed", "failed"]


class StartupOperationDetail(BaseModel):
    files_done: int = 0
    total_files: int = 0
    transferred_bytes: int = 0
    total_bytes: int = 0
    current_file: Optional[str] = None


class StartupOperationAcceptedResponse(BaseModel):
    operation_id: str
    message: str = "accepted"


class StartupOperationStatusResponse(BaseModel):
    operation_id: str
    kind: StartupOperationKind
    state: StartupOperationState
    phase: str = "queued"
    progress_percent: float = 0.0
    message: Optional[str] = None
    target_session_id: Optional[str] = None
    error: Optional[str] = None
    detail: StartupOperationDetail = Field(default_factory=StartupOperationDetail)
    updated_at: Optional[str] = None
