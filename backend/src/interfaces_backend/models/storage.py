"""Storage API request/response models (DB-backed)."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# --- API Request/Response Models ---


class DatasetInfo(BaseModel):
    """Dataset information for API responses."""

    id: str = Field(..., description="Dataset ID")
    name: str = Field(..., description="Dataset name")
    profile_name: Optional[str] = Field(None, description="VLAbor profile name")
    profile_snapshot: Optional[dict] = Field(None, description="Profile snapshot")
    source: str = Field("r2", description="Data source")
    status: str = Field("active", description="Data status")
    dataset_type: str = Field("recorded", description="Dataset type")
    episode_count: int = Field(0, description="Number of episodes")
    size_bytes: int = Field(0, description="Size in bytes")
    is_local: bool = Field(False, description="Dataset is downloaded locally")
    created_at: Optional[str] = Field(None, description="Creation time")
    updated_at: Optional[str] = Field(None, description="Last update time")


class DatasetListResponse(BaseModel):
    """Response for dataset list endpoint."""

    datasets: List[DatasetInfo]
    total: int


class DatasetMergeRequest(BaseModel):
    """Request to merge multiple datasets into one."""

    dataset_name: str = Field(..., description="Merged dataset name")
    source_dataset_ids: List[str] = Field(..., description="Source dataset IDs (>=2)")


class DatasetMergeResponse(BaseModel):
    """Response for dataset merge."""

    success: bool
    dataset_id: str
    message: str
    size_bytes: int = 0
    episode_count: int = 0


class ModelInfo(BaseModel):
    """Model information for API responses."""

    id: str = Field(..., description="Model ID")
    name: str = Field(..., description="Model name")
    dataset_id: Optional[str] = Field(None, description="Dataset ID")
    profile_name: Optional[str] = Field(None, description="VLAbor profile name")
    profile_snapshot: Optional[dict] = Field(None, description="Profile snapshot")
    policy_type: Optional[str] = Field(None, description="Policy type")
    training_steps: Optional[int] = Field(None, description="Training steps")
    batch_size: Optional[int] = Field(None, description="Batch size")
    size_bytes: int = Field(0, description="Size in bytes")
    is_local: bool = Field(False, description="Model is downloaded locally")
    source: str = Field("r2", description="Data source")
    status: str = Field("active", description="Data status")
    created_at: Optional[str] = Field(None, description="Creation time")
    updated_at: Optional[str] = Field(None, description="Last update time")


class ModelListResponse(BaseModel):
    """Response for model list endpoint."""

    models: List[ModelInfo]
    total: int


ModelSyncJobState = Literal["queued", "running", "completed", "failed", "cancelled"]


class ModelSyncJobDetail(BaseModel):
    files_done: int = 0
    total_files: int = 0
    transferred_bytes: int = 0
    total_bytes: int = 0
    current_file: Optional[str] = None


class ModelSyncJobStatus(BaseModel):
    job_id: str
    model_id: str
    state: ModelSyncJobState
    progress_percent: float = 0.0
    message: Optional[str] = None
    error: Optional[str] = None
    detail: ModelSyncJobDetail = Field(default_factory=ModelSyncJobDetail)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ModelSyncJobAcceptedResponse(BaseModel):
    job_id: str
    model_id: str
    state: ModelSyncJobState = "queued"
    message: str = "accepted"


class ModelSyncJobListResponse(BaseModel):
    jobs: List[ModelSyncJobStatus] = Field(default_factory=list)


class ModelSyncJobCancelResponse(BaseModel):
    job_id: str
    accepted: bool
    state: ModelSyncJobState
    message: str


class ArchiveResponse(BaseModel):
    """Response for archive/restore operations."""

    id: str
    success: bool
    message: str
    status: str


class DatasetReuploadResponse(BaseModel):
    """Response for dataset re-upload operation."""

    id: str
    success: bool
    message: str


class DatasetPlaybackCameraInfo(BaseModel):
    """Camera stream info for dataset playback."""

    key: str = Field(..., description="Feature key, e.g. observation.images.cam_top")
    label: str = Field(..., description="Camera label")
    width: Optional[int] = Field(None, description="Video width")
    height: Optional[int] = Field(None, description="Video height")
    fps: Optional[int] = Field(None, description="Video FPS")
    codec: Optional[str] = Field(None, description="Video codec")
    pix_fmt: Optional[str] = Field(None, description="Pixel format")


class DatasetPlaybackResponse(BaseModel):
    """Playback metadata for a local dataset."""

    dataset_id: str = Field(..., description="Dataset ID")
    is_local: bool = Field(..., description="Whether dataset exists locally")
    total_episodes: int = Field(0, description="Total episode count")
    fps: int = Field(0, description="Dataset FPS")
    use_videos: bool = Field(False, description="Whether dataset stores videos")
    cameras: List[DatasetPlaybackCameraInfo] = Field(default_factory=list)


class StorageUsageResponse(BaseModel):
    """Response for storage usage endpoint."""

    datasets_count: int = 0
    datasets_size_bytes: int = 0
    models_count: int = 0
    models_size_bytes: int = 0
    archive_count: int = 0
    archive_size_bytes: int = 0
    total_size_bytes: int = 0


class ArchiveListResponse(BaseModel):
    """Response for archived items list."""

    datasets: List[DatasetInfo] = Field(default_factory=list)
    models: List[ModelInfo] = Field(default_factory=list)
    total: int = 0


class ArchiveBulkRequest(BaseModel):
    """Request for bulk archive operations."""

    dataset_ids: List[str] = Field(default_factory=list)
    model_ids: List[str] = Field(default_factory=list)


class ArchiveBulkResponse(BaseModel):
    """Response for bulk archive operations."""

    success: bool
    restored: List[str] = Field(default_factory=list)
    deleted: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class HuggingFaceDatasetImportRequest(BaseModel):
    """Request to import a dataset from HuggingFace."""

    repo_id: str = Field(..., description="HuggingFace repo ID")
    dataset_id: Optional[str] = Field(None, description="Dataset ID to store (UUID)")
    dataset_name: Optional[str] = Field(None, description="Dataset display name")
    profile_name: Optional[str] = Field(None, description="VLAbor profile name")
    name: Optional[str] = Field(None, description="Dataset display name")
    force: bool = Field(False, description="Overwrite local data if exists")


class HuggingFaceModelImportRequest(BaseModel):
    """Request to import a model from HuggingFace."""

    repo_id: str = Field(..., description="HuggingFace repo ID")
    model_id: Optional[str] = Field(None, description="Model ID to store (UUID)")
    model_name: Optional[str] = Field(None, description="Model display name")
    dataset_id: Optional[str] = Field(None, description="Associated dataset ID")
    profile_name: Optional[str] = Field(None, description="VLAbor profile name")
    force: bool = Field(False, description="Overwrite local data if exists")


class HuggingFaceExportRequest(BaseModel):
    """Request to export a dataset or model to HuggingFace."""

    repo_id: str = Field(..., description="HuggingFace repo ID")
    private: bool = Field(False, description="Create private repository")
    commit_message: Optional[str] = Field(None, description="Commit message")


class HuggingFaceTransferResponse(BaseModel):
    """Response for HuggingFace import/export."""

    success: bool
    message: str
    item_id: str
    repo_url: Optional[str] = None
