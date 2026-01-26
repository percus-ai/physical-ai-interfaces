"""Training job models."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(str, Enum):
    """Training job status."""

    STARTING = "starting"
    DEPLOYING = "deploying"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    TERMINATED = "terminated"


class CleanupStatus(str, Enum):
    """Cleanup status for failed/terminated jobs."""

    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class TrainingMode(str, Enum):
    """Training mode."""

    TRAIN = "train"
    RESUME_HUB = "resume_hub"
    RESUME_LOCAL = "resume_local"


class JobInfo(BaseModel):
    """Training job information."""

    job_id: str
    job_name: str
    instance_id: str
    ip: Optional[str] = None
    status: JobStatus
    dataset_id: Optional[str] = None
    policy_type: Optional[str] = None
    failure_reason: Optional[str] = None
    termination_reason: Optional[str] = None
    cleanup_status: Optional[CleanupStatus] = None
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
    started_at: Optional[datetime] = None

    # GPU info
    gpu_model: Optional[str] = None
    gpus_per_instance: Optional[int] = None

    # Completion info
    exit_code: Optional[int] = None
    completed_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(use_enum_values=True)


class JobListResponse(BaseModel):
    """Response for job list endpoint."""

    jobs: list[JobInfo]
    total: int


class JobDetailResponse(BaseModel):
    """Response for job detail endpoint."""

    job: JobInfo
    remote_status: Optional[str] = None
    progress: Optional[dict] = None
    latest_train_metrics: Optional[dict] = None
    latest_val_metrics: Optional[dict] = None
    summary: Optional[dict] = None
    early_stopping: Optional[dict] = None
    training_config: Optional[dict] = None


class JobLogsResponse(BaseModel):
    """Response for job logs endpoint."""

    job_id: str
    logs: str
    lines: int
    source: Optional[str] = None


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
    use_amp: Optional[bool] = Field(None, description="Enable AMP (mixed precision)")


class TrainingParams(BaseModel):
    """Training parameters."""

    steps: Optional[int] = Field(None, description="Number of training steps")
    batch_size: Optional[int] = Field(None, description="Batch size")
    save_freq: Optional[int] = Field(None, ge=50, description="Checkpoint save frequency")
    log_freq: Optional[int] = Field(None, ge=1, description="Logging frequency (steps)")
    num_workers: Optional[int] = Field(None, ge=0, description="Dataloader workers")
    save_checkpoint: Optional[bool] = Field(None, description="Save checkpoints during training")


class ValidationConfig(BaseModel):
    """Validation parameters."""

    enable: bool = Field(True, description="Enable validation during training")
    eval_freq: Optional[int] = Field(None, ge=1, description="Validation frequency (steps)")
    max_batches: Optional[int] = Field(None, ge=1, description="Max validation batches")
    batch_size: Optional[int] = Field(None, ge=1, description="Validation batch size")


class EarlyStoppingConfig(BaseModel):
    """Early stopping parameters."""

    enable: bool = Field(True, description="Enable early stopping")
    patience: int = Field(5, ge=1, description="Patience (number of worsening evals)")
    min_delta: float = Field(0.0, description="Minimum change to qualify as improvement")
    mode: str = Field("min", description="Mode: min or max")


class CloudConfig(BaseModel):
    """Cloud instance configuration."""

    gpu_model: str = Field("H100", description="GPU model: H100, A100, L40S")
    gpus_per_instance: int = Field(1, ge=1, le=8, description="Number of GPUs")
    storage_size: Optional[int] = Field(None, description="Storage size in GB")
    location: str = Field("auto", description="Location: auto, FIN-01, ICE-01, etc.")
    is_spot: bool = Field(True, description="Use spot instance")


class JobCreateRequest(BaseModel):
    """Request to create a new training job."""
    job_name: Optional[str] = Field(None, description="Job display name")
    dataset: Optional[DatasetConfig] = Field(None, description="Dataset config")
    policy: Optional[PolicyConfig] = Field(None, description="Policy config")
    training: TrainingParams = Field(default_factory=TrainingParams)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    early_stopping: EarlyStoppingConfig = Field(default_factory=EarlyStoppingConfig)
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


# --- Checkpoint Models (for continue training) ---


class CheckpointDatasetInfo(BaseModel):
    """Dataset information embedded in checkpoint for compatibility checking."""

    camera_names: list[str] = Field(default_factory=list, description="Camera names used in training")
    action_dim: int = Field(0, description="Action dimension")
    state_dim: int = Field(0, description="State dimension")


class CheckpointInfo(BaseModel):
    """Checkpoint information for listing."""

    job_name: str = Field(..., description="Training job name")
    policy_type: str = Field(..., description="Policy type (act, pi0, smolvla, etc.)")
    step: int = Field(..., description="Latest/selected step number")
    dataset_id: str = Field(..., description="Training dataset ID")
    dataset_info: CheckpointDatasetInfo = Field(
        default_factory=CheckpointDatasetInfo,
        description="Dataset compatibility info"
    )
    created_at: str = Field(..., description="Job creation timestamp")
    size_mb: float = Field(0.0, description="Total checkpoint size in MB")
    pretrained_path: Optional[str] = Field(None, description="Base pretrained model path")
    author: Optional[str] = Field(None, description="Author user id")


class CheckpointListResponse(BaseModel):
    """Response for checkpoint list endpoint."""

    checkpoints: list[CheckpointInfo]
    total: int


class CheckpointDetailResponse(BaseModel):
    """Response for checkpoint detail endpoint."""

    job_name: str
    policy_type: str
    dataset_id: str
    dataset_info: CheckpointDatasetInfo = Field(default_factory=CheckpointDatasetInfo)
    pretrained_path: Optional[str] = None
    available_steps: list[int] = Field(default_factory=list, description="All available step numbers")
    latest_step: int = Field(0, description="Latest step number")
    created_at: str = ""
    size_mb: float = 0.0
    author: Optional[str] = None


class CheckpointDownloadRequest(BaseModel):
    """Request to download a checkpoint."""

    step: Optional[int] = Field(None, description="Specific step to download (None for latest)")
    target_path: Optional[str] = Field(None, description="Custom target path (optional)")


class CheckpointDownloadResponse(BaseModel):
    """Response for checkpoint download."""

    success: bool
    job_name: str
    step: int
    target_path: str
    message: str


# --- Verda Storage Models ---


class VerdaStorageItem(BaseModel):
    """Verda storage volume summary."""

    id: str
    name: Optional[str] = None
    size_gb: int = 0
    status: str = "unknown"
    state: str = "active"  # active or deleted
    is_os_volume: bool = False
    volume_type: Optional[str] = None
    location: Optional[str] = None
    instance_id: Optional[str] = None
    created_at: Optional[str] = None
    deleted_at: Optional[str] = None


class VerdaStorageListResponse(BaseModel):
    """Response for Verda storage list."""

    items: list[VerdaStorageItem]
    total: int


class VerdaStorageActionRequest(BaseModel):
    """Request for Verda storage actions."""

    volume_ids: list[str]


class VerdaStorageActionFailure(BaseModel):
    """Failure detail for Verda storage actions."""

    id: str
    reason: str


class VerdaStorageActionResult(BaseModel):
    """Result for Verda storage actions."""

    success_ids: list[str] = Field(default_factory=list)
    failed: list[VerdaStorageActionFailure] = Field(default_factory=list)
    skipped: list[VerdaStorageActionFailure] = Field(default_factory=list)


class JobReviveResponse(BaseModel):
    """Response for reviving a terminated instance with restored storage."""

    job_id: str
    old_instance_id: str
    volume_id: str
    instance_id: str
    instance_type: str
    ip: str
    ssh_user: str = "root"
    ssh_private_key: str
    location: str
    message: str


class DatasetCompatibilityCheckRequest(BaseModel):
    """Request for dataset compatibility check."""

    checkpoint_job_name: str = Field(..., description="Source checkpoint job name")
    dataset_id: str = Field(..., description="Target dataset ID to check")


class DatasetCompatibilityCheckResponse(BaseModel):
    """Result of dataset compatibility check for continue training."""

    is_compatible: bool = Field(..., description="Whether datasets are compatible")
    errors: list[str] = Field(default_factory=list, description="Critical errors (blocking)")
    warnings: list[str] = Field(default_factory=list, description="Warnings (non-blocking)")
    checkpoint_info: CheckpointDatasetInfo = Field(default_factory=CheckpointDatasetInfo)
    dataset_info: CheckpointDatasetInfo = Field(default_factory=CheckpointDatasetInfo)


# --- Continue Training Models ---


class ContinueCheckpointConfig(BaseModel):
    """Checkpoint reference for continue training."""

    job_name: str = Field(..., description="Source checkpoint job name")
    step: Optional[int] = Field(None, description="Specific step (None for latest)")


class ContinueDatasetConfig(BaseModel):
    """Dataset config for continue training."""

    id: str = Field(..., description="Dataset ID")
    use_original: bool = Field(True, description="Use original training dataset")


class ContinueTrainingParams(BaseModel):
    """Training params for continue training."""

    additional_steps: int = Field(..., description="Additional steps to train")
    batch_size: Optional[int] = Field(None, description="Batch size")
    save_freq: Optional[int] = Field(None, description="Checkpoint save frequency")
    log_freq: Optional[int] = Field(None, ge=1, description="Logging frequency (steps)")
    num_workers: Optional[int] = Field(None, ge=0, description="Dataloader workers")
    save_checkpoint: Optional[bool] = Field(None, description="Save checkpoints during training")


class JobCreateContinueRequest(BaseModel):
    """Request to create a continue training job."""

    type: str = Field("continue", description="Job type: must be 'continue'")
    checkpoint: ContinueCheckpointConfig = Field(..., description="Source checkpoint")
    dataset: ContinueDatasetConfig = Field(..., description="Dataset config")
    training: ContinueTrainingParams = Field(..., description="Training params")
    policy: Optional[PolicyConfig] = Field(None, description="Policy overrides")
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    early_stopping: EarlyStoppingConfig = Field(default_factory=EarlyStoppingConfig)
    cloud: CloudConfig = Field(default_factory=CloudConfig)
    wandb_enable: bool = Field(True, description="Enable W&B logging")
    author: Optional[str] = Field(None, description="Author user id")


# =============================================================================
# GPU Availability
# =============================================================================


class GpuAvailabilityInfo(BaseModel):
    """GPU availability information for a specific configuration."""

    gpu_model: str = Field(..., description="GPU model name (e.g., 'H100', 'A100')")
    gpu_count: int = Field(..., description="Number of GPUs")
    instance_type: str = Field(..., description="Verda instance type")
    spot_available: bool = Field(..., description="Spot instance available")
    ondemand_available: bool = Field(..., description="On-demand instance available")
    spot_locations: list[str] = Field(default_factory=list, description="Locations with spot availability")
    ondemand_locations: list[str] = Field(default_factory=list, description="Locations with on-demand availability")
    spot_price_per_hour: Optional[float] = Field(None, description="Spot price per hour")


class GpuAvailabilityResponse(BaseModel):
    """Response for GPU availability check."""

    available: list[GpuAvailabilityInfo] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=datetime.now)
