"""Storage API request/response models.

Core data models are in percus_ai.storage.
This module only contains API-specific request/response models.
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from percus_ai.storage import (
    DataSource,
    DataStatus,
    DatasetMetadata,
    ModelMetadata,
)


# --- API Request/Response Models ---


class DatasetInfo(BaseModel):
    """Dataset information for API responses with local status."""

    id: str = Field(..., description="Dataset ID")
    short_id: Optional[str] = Field(None, description="6-char alphanumeric short ID for job naming")
    name: str = Field(..., description="Dataset name")
    source: DataSource = Field(..., description="Data source: r2, hub, local")
    status: DataStatus = Field(..., description="Data status")
    dataset_type: str = Field("recorded", description="Dataset type")
    episode_count: int = Field(0, description="Number of episodes")
    size_bytes: int = Field(0, description="Size in bytes")
    is_local: bool = Field(True, description="Dataset is downloaded locally")
    created_at: Optional[str] = Field(None, description="Creation time")
    updated_at: Optional[str] = Field(None, description="Last update time")


class DatasetListResponse(BaseModel):
    """Response for dataset list endpoint."""

    datasets: List[DatasetInfo]
    total: int


class ModelListResponse(BaseModel):
    """Response for model list endpoint."""

    models: List[ModelMetadata]
    total: int


class SyncRequest(BaseModel):
    """Request for sync operations."""

    mode: str = Field("full", description="Sync mode: full or partial")
    episodes: Optional[List[int]] = Field(None, description="Episode indices for partial sync")
    include_videos: bool = Field(True, description="Include video files")


class SyncStatusResponse(BaseModel):
    """Response for sync status check."""

    id: str
    source: DataSource
    local_hash: Optional[str] = None
    remote_hash: Optional[str] = None
    is_synced: bool = False
    local_size_bytes: int = 0
    remote_size_bytes: int = 0


class UploadResponse(BaseModel):
    """Response for upload operations."""

    id: str
    success: bool
    message: str
    size_bytes: int = 0
    hash: Optional[str] = None


class DownloadResponse(BaseModel):
    """Response for download operations."""

    id: str
    success: bool
    message: str
    size_bytes: int = 0
    hash: Optional[str] = None


class PublishRequest(BaseModel):
    """Request to publish to HuggingFace."""

    repo_id: str = Field(..., description="Target HuggingFace repo ID")
    private: bool = Field(False, description="Make repo private")
    commit_message: Optional[str] = Field(None, description="Commit message")


class PublishResponse(BaseModel):
    """Response for publish operations."""

    id: str
    success: bool
    message: str
    repo_url: Optional[str] = None


class ArchiveResponse(BaseModel):
    """Response for archive/restore operations."""

    id: str
    success: bool
    message: str
    status: DataStatus


class StorageUsageResponse(BaseModel):
    """Response for storage usage endpoint."""

    # Local storage (downloaded to disk)
    datasets_count: int = 0
    datasets_size_bytes: int = 0
    models_count: int = 0
    models_size_bytes: int = 0
    archive_count: int = 0
    archive_size_bytes: int = 0
    total_size_bytes: int = 0
    # Remote storage (on R2, not downloaded)
    remote_datasets_count: int = 0
    remote_datasets_size_bytes: int = 0
    remote_models_count: int = 0
    remote_models_size_bytes: int = 0
    remote_total_size_bytes: int = 0


class ArchiveListResponse(BaseModel):
    """Response for archived items list."""

    datasets: List[DatasetMetadata] = Field(default_factory=list)
    models: List[ModelMetadata] = Field(default_factory=list)
    total: int = 0
