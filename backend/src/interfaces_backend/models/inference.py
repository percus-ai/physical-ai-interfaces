"""Inference API request/response models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class InferenceModelInfo(BaseModel):
    """Inference-ready model summary."""

    model_id: str = Field(..., description="Model ID")
    name: str = Field(..., description="Display name")
    policy_type: Optional[str] = Field(None, description="LeRobot policy type")
    source: str = Field("local", description="Model source")
    size_mb: float = Field(0.0, description="Directory size in MB")
    is_loaded: bool = Field(False, description="Selected by active worker")
    is_local: bool = Field(True, description="Model exists on local disk")
    task_candidates: list[str] = Field(
        default_factory=list,
        description="Task candidates derived from active related datasets",
    )


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
    recording_dataset_id: Optional[str] = None
    recording_active: bool = False
    awaiting_continue_confirmation: bool = False
    batch_size: int = 20
    episode_count: int = 0
    num_episodes: int = 0
    episode_time_s: float = 0.0
    reset_time_s: float = 0.0
    denoising_steps: Optional[int] = None


class InferenceModelSyncStatus(BaseModel):
    active: bool = False
    status: str = Field("idle", description="idle | checking | syncing | completed | cancelled | error")
    model_id: Optional[str] = None
    message: Optional[str] = None
    progress_percent: float = 0.0
    total_files: int = 0
    files_done: int = 0
    total_bytes: int = 0
    transferred_bytes: int = 0
    current_file: Optional[str] = None
    error: Optional[str] = None
    updated_at: Optional[str] = None


class GpuHostStatus(BaseModel):
    status: str = Field("stopped", description="running | idle | stopped | error")
    session_id: Optional[str] = None
    pid: Optional[int] = None
    last_error: Optional[str] = None


class InferenceRunnerStatusResponse(BaseModel):
    runner_status: InferenceRunnerStatus
    gpu_host_status: GpuHostStatus
    model_sync: InferenceModelSyncStatus = Field(default_factory=InferenceModelSyncStatus)


class PiInferenceOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    denoising_steps: Optional[int] = Field(
        None,
        ge=1,
        description="Number of denoising steps for pi0/pi05 inference",
    )


class InferencePolicyOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pi0: Optional[PiInferenceOptions] = None
    pi05: Optional[PiInferenceOptions] = None


class InferenceRunnerStartRequest(BaseModel):
    model_id: str
    device: Optional[str] = None
    task: Optional[str] = None
    policy_options: Optional[InferencePolicyOptions] = None


class InferenceRunnerStopRequest(BaseModel):
    session_id: Optional[str] = None


class InferenceRunnerStopResponse(BaseModel):
    success: bool
    session_id: Optional[str] = None
    message: str = ""


class InferenceRunnerSettingsApplyRequest(BaseModel):
    task: Optional[str] = None
    episode_time_s: Optional[float] = Field(None, gt=0)
    reset_time_s: Optional[float] = Field(None, ge=0)
    denoising_steps: Optional[int] = Field(None, ge=1)


class InferenceRunnerSettingsApplyResponse(BaseModel):
    success: bool
    message: str = ""
    task: Optional[str] = None
    episode_time_s: Optional[float] = None
    reset_time_s: Optional[float] = None
    denoising_steps: Optional[int] = None


class InferenceRecordingDecisionRequest(BaseModel):
    continue_recording: bool


class InferenceRecordingDecisionResponse(BaseModel):
    success: bool
    message: str = ""
    recording_dataset_id: Optional[str] = None
    awaiting_continue_confirmation: bool = False


class InferenceRunnerControlResponse(BaseModel):
    success: bool
    message: str = ""
    paused: bool = False
    teleop_enabled: bool = False
    recorder_state: Optional[str] = None


class InferenceSetTaskRequest(BaseModel):
    session_id: str
    task: str


class InferenceSetTaskResponse(BaseModel):
    success: bool
    session_id: str
    task: str
    applied_from_step: Optional[int] = None
