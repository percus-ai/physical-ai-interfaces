"""Training job models."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Training job status."""

    STARTING = "starting"
    DEPLOYING = "deploying"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    TERMINATED = "terminated"


class TrainingMode(str, Enum):
    """Training mode."""

    TRAIN = "train"
    RESUME_HUB = "resume_hub"
    RESUME_LOCAL = "resume_local"


class JobInfo(BaseModel):
    """Training job information."""

    job_id: str
    instance_id: str
    ip: Optional[str] = None
    status: JobStatus
    config_name: str
    mode: TrainingMode

    # SSH connection info
    ssh_user: str = "root"
    ssh_private_key: str = "~/.ssh/id_rsa"
    remote_base_dir: str = "/root"

    # Checkpoint
    checkpoint_repo_id: Optional[str] = None

    # Timestamps
    created_at: datetime
    updated_at: datetime

    # GPU info
    gpu_model: Optional[str] = None
    gpus_per_instance: Optional[int] = None

    # Completion info
    exit_code: Optional[int] = None
    completed_at: Optional[datetime] = None

    class Config:
        use_enum_values = True


class JobListResponse(BaseModel):
    """Response for job list endpoint."""

    jobs: list[JobInfo]
    total: int


class JobDetailResponse(BaseModel):
    """Response for job detail endpoint."""

    job: JobInfo
    remote_status: Optional[str] = None
    progress: Optional[dict] = None


class JobLogsResponse(BaseModel):
    """Response for job logs endpoint."""

    job_id: str
    logs: str
    lines: int


class JobProgressResponse(BaseModel):
    """Response for job progress endpoint."""

    job_id: str
    step: str = "N/A"
    loss: str = "N/A"


class JobActionResponse(BaseModel):
    """Response for job action (stop, delete)."""

    job_id: str
    success: bool
    message: str


class JobStatusUpdate(BaseModel):
    """Status update for a job."""

    job_id: str
    old_status: str
    new_status: str
    instance_status: str
    reason: str


class JobStatusCheckResponse(BaseModel):
    """Response for bulk status check."""

    updates: list[JobStatusUpdate]
    checked_count: int


# --- Job Creation Models ---


class DatasetConfig(BaseModel):
    """Dataset configuration for training."""

    id: str = Field(..., description="Dataset ID")
    source: str = Field("r2", description="Dataset source: r2, hub, local")
    hf_repo_id: Optional[str] = Field(None, description="HuggingFace repo ID (for hub source)")


class PolicyConfig(BaseModel):
    """Policy configuration for training."""

    type: str = Field("act", description="Policy type: act, pi0, groot, smolvla, etc.")
    pretrained_path: Optional[str] = Field(None, description="Pretrained model path")
    compile_model: Optional[bool] = Field(None, description="Enable torch.compile")
    gradient_checkpointing: Optional[bool] = Field(None, description="Enable gradient checkpointing")
    dtype: Optional[str] = Field(None, description="Model dtype: float32, float16, bfloat16")


class TrainingParams(BaseModel):
    """Training parameters."""

    steps: Optional[int] = Field(None, description="Number of training steps")
    batch_size: Optional[int] = Field(None, description="Batch size")
    save_freq: Optional[int] = Field(None, description="Checkpoint save frequency")


class CloudConfig(BaseModel):
    """Cloud instance configuration."""

    gpu_model: str = Field("H100", description="GPU model: H100, A100, L40S")
    gpus_per_instance: int = Field(1, ge=1, le=8, description="Number of GPUs")
    storage_size: Optional[int] = Field(None, description="Storage size in GB")
    location: str = Field("auto", description="Location: auto, FIN-01, ICE-01, etc.")
    is_spot: bool = Field(True, description="Use spot instance")


class JobCreateRequest(BaseModel):
    """Request to create a new training job."""

    name: str = Field(..., description="Job name/ID")
    dataset: DatasetConfig
    policy: PolicyConfig
    training: TrainingParams = Field(default_factory=TrainingParams)
    cloud: CloudConfig = Field(default_factory=CloudConfig)
    checkpoint_repo_id: Optional[str] = Field(None, description="HF repo for checkpoint upload")
    wandb_enable: bool = Field(True, description="Enable Weights & Biases logging")
    background: bool = Field(True, description="Run in background mode")
    sync_dataset: bool = Field(False, description="Sync dataset to R2 before training")


class JobCreateResponse(BaseModel):
    """Response for job creation."""

    job_id: str
    instance_id: str
    status: str
    message: str
    ip: Optional[str] = None


class InstanceStatusResponse(BaseModel):
    """Response for instance status check."""

    job_id: str
    instance_id: str
    instance_status: Optional[str] = Field(None, description="Verda instance status")
    job_status: str = Field(..., description="Local job status")
    ip: Optional[str] = None
    remote_process_status: Optional[str] = Field(None, description="SSH process status")
    gpu_model: Optional[str] = None
    gpus_per_instance: Optional[int] = None
    created_at: Optional[str] = None
    message: str = ""
