"""Storage API request/response models (DB-backed)."""

from typing import List, Optional

from pydantic import BaseModel, Field


# --- API Request/Response Models ---


class DatasetInfo(BaseModel):
    """Dataset information for API responses."""

    id: str = Field(..., description="Dataset ID")
    name: str = Field(..., description="Dataset name")
    project_id: str = Field(..., description="Project ID")
    environment_id: Optional[str] = Field(None, description="Environment ID")
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


class ModelInfo(BaseModel):
    """Model information for API responses."""

    id: str = Field(..., description="Model ID")
    name: str = Field(..., description="Model name")
    project_id: str = Field(..., description="Project ID")
    dataset_id: Optional[str] = Field(None, description="Dataset ID")
    policy_type: Optional[str] = Field(None, description="Policy type")
    training_steps: Optional[int] = Field(None, description="Training steps")
    batch_size: Optional[int] = Field(None, description="Batch size")
    size_bytes: int = Field(0, description="Size in bytes")
    source: str = Field("r2", description="Data source")
    status: str = Field("active", description="Data status")
    created_at: Optional[str] = Field(None, description="Creation time")
    updated_at: Optional[str] = Field(None, description="Last update time")


class ModelListResponse(BaseModel):
    """Response for model list endpoint."""

    models: List[ModelInfo]
    total: int


class ArchiveResponse(BaseModel):
    """Response for archive/restore operations."""

    id: str
    success: bool
    message: str
    status: str


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
    project_id: str = Field(..., description="Project ID")
    dataset_id: str = Field(..., description="Dataset ID to store")
    name: Optional[str] = Field(None, description="Dataset display name")
    force: bool = Field(False, description="Overwrite local data if exists")


class HuggingFaceModelImportRequest(BaseModel):
    """Request to import a model from HuggingFace."""

    repo_id: str = Field(..., description="HuggingFace repo ID")
    project_id: str = Field(..., description="Project ID")
    model_id: str = Field(..., description="Model ID to store")
    dataset_id: Optional[str] = Field(None, description="Associated dataset ID")
    name: Optional[str] = Field(None, description="Model display name")
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
