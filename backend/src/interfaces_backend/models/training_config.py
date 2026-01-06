"""Training configuration models."""

from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field


class DatasetConfigModel(BaseModel):
    """Dataset configuration."""

    id: str = Field(..., description="Dataset ID")
    source: str = Field("r2", description="Dataset source: r2, hub, local")
    hf_repo_id: Optional[str] = Field(None, description="HuggingFace repo ID")


class PolicyConfigModel(BaseModel):
    """Policy configuration."""

    type: str = Field("act", description="Policy type: act, pi0, groot, smolvla")
    pretrained_path: Optional[str] = Field(None, description="Pretrained model path")
    compile_model: Optional[bool] = Field(None, description="Enable torch.compile")
    gradient_checkpointing: Optional[bool] = Field(None, description="Enable gradient checkpointing")
    dtype: Optional[str] = Field(None, description="Model dtype: float32, float16, bfloat16")


class TrainingParamsModel(BaseModel):
    """Training parameters."""

    steps: Optional[int] = Field(None, description="Number of training steps")
    batch_size: Optional[int] = Field(None, description="Batch size")
    save_freq: Optional[int] = Field(None, description="Checkpoint save frequency")


class OutputConfigModel(BaseModel):
    """Output configuration."""

    output_dir: Optional[str] = Field(None, description="Output directory")
    checkpoint_repo_id: Optional[str] = Field(None, description="HF repo for checkpoint upload")
    upload_every_save: bool = Field(False, description="Upload checkpoint on every save")


class WandbConfigModel(BaseModel):
    """Weights & Biases configuration."""

    enable: bool = Field(True, description="Enable W&B logging")


class CloudConfigModel(BaseModel):
    """Cloud instance configuration."""

    gpu_model: str = Field("H100", description="GPU model")
    gpus_per_instance: int = Field(1, ge=1, le=8, description="Number of GPUs")
    storage_size: Optional[int] = Field(None, description="Storage size in GB")
    location: str = Field("auto", description="Cloud location")
    is_spot: bool = Field(True, description="Use spot instance")


class TrainingConfigModel(BaseModel):
    """Complete training configuration."""

    name: str = Field(..., description="Configuration name")
    dataset: DatasetConfigModel
    policy: PolicyConfigModel
    training: TrainingParamsModel = Field(default_factory=TrainingParamsModel)
    output: OutputConfigModel = Field(default_factory=OutputConfigModel)
    wandb: WandbConfigModel = Field(default_factory=WandbConfigModel)
    cloud: CloudConfigModel = Field(default_factory=CloudConfigModel)


class TrainingConfigInfo(BaseModel):
    """Training config info for listing."""

    config_id: str = Field(..., description="Config ID (filename without extension)")
    name: str = Field(..., description="Config name")
    policy_type: str = Field(..., description="Policy type")
    dataset_id: str = Field(..., description="Dataset ID")
    gpu_model: str = Field(..., description="GPU model")
    file_path: str = Field(..., description="Path to config file")
    modified_at: Optional[str] = Field(None, description="Last modified time")


class TrainingConfigListResponse(BaseModel):
    """Response for config list endpoint."""

    configs: List[TrainingConfigInfo]
    total: int


class TrainingConfigDetailResponse(BaseModel):
    """Response for config detail endpoint."""

    config_id: str
    config: TrainingConfigModel
    file_path: str


class TrainingConfigCreateRequest(BaseModel):
    """Request to create training config."""

    config: TrainingConfigModel


class TrainingConfigCreateResponse(BaseModel):
    """Response for config creation."""

    config_id: str
    file_path: str
    message: str


class TrainingConfigValidationResult(BaseModel):
    """Validation result for training config."""

    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class TrainingConfigDryRunResult(BaseModel):
    """Dry run result for training config."""

    config_id: str
    would_create_instance: Dict[str, Any]
    estimated_cost_per_hour: Optional[float] = None
    files_to_deploy: List[str]
    remote_command: str


# --- R2 Sync Response Models ---


class ConfigSyncStatusResponse(BaseModel):
    """Response for config sync status check."""

    config_name: str = Field(..., description="Config name")
    status: str = Field(..., description="Sync status: synced, local_only, remote_only, modified, conflict")
    local_hash: Optional[str] = Field(None, description="Local file hash")
    remote_hash: Optional[str] = Field(None, description="Remote file hash")


class ConfigSyncResponse(BaseModel):
    """Response for config sync operations (upload/download)."""

    success: bool = Field(..., description="Operation success")
    message: str = Field(..., description="Result message")
    config_name: str = Field(..., description="Config name")


class RemoteConfigListResponse(BaseModel):
    """Response for remote config listing."""

    configs: List[str] = Field(default_factory=list, description="List of remote config names")
