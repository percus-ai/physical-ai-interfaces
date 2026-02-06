"""Inference API request/response models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class InferenceModelInfo(BaseModel):
    """Inference-ready model summary."""

    model_id: str = Field(..., description="Model ID")
    name: str = Field(..., description="Display name")
    policy_type: Optional[str] = Field(None, description="LeRobot policy type")
    source: str = Field("local", description="Model source")
    size_mb: float = Field(0.0, description="Directory size in MB")
    is_loaded: bool = Field(False, description="Selected by active worker")
    is_local: bool = Field(True, description="Model exists on local disk")


class InferenceModelsResponse(BaseModel):
    models: list[InferenceModelInfo] = Field(default_factory=list)


class InferenceDeviceInfo(BaseModel):
    device: str
    available: bool = True
    memory_total_mb: Optional[float] = None
    memory_free_mb: Optional[float] = None


class InferenceDeviceCompatibilityResponse(BaseModel):
    devices: list[InferenceDeviceInfo] = Field(default_factory=list)
    recommended: str = Field("cpu", description="Recommended device")


class InferenceRunnerStatus(BaseModel):
    active: bool = False
    session_id: Optional[str] = None
    task: Optional[str] = None
    queue_length: int = 0
    last_error: Optional[str] = None


class GpuHostStatus(BaseModel):
    status: str = Field("stopped", description="running | idle | stopped | error")
    session_id: Optional[str] = None
    pid: Optional[int] = None
    last_error: Optional[str] = None


class InferenceRunnerStatusResponse(BaseModel):
    runner_status: InferenceRunnerStatus
    gpu_host_status: GpuHostStatus


class InferenceRunnerStartRequest(BaseModel):
    model_id: str
    device: Optional[str] = None
    task: Optional[str] = None


class InferenceRunnerStartResponse(BaseModel):
    session_id: str
    message: str = "inference worker started"


class InferenceRunnerStopRequest(BaseModel):
    session_id: Optional[str] = None


class InferenceRunnerStopResponse(BaseModel):
    success: bool
    session_id: Optional[str] = None
    message: str = ""


class InferenceSetTaskRequest(BaseModel):
    session_id: str
    task: str


class InferenceSetTaskResponse(BaseModel):
    success: bool
    session_id: str
    task: str
    applied_from_step: Optional[int] = None
