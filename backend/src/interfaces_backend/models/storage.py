"""Storage data models for datasets and models management."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --- Enums ---


class DataSource(str, Enum):
    """Data source type."""

    R2 = "r2"
    HUGGINGFACE = "huggingface"


class DataStatus(str, Enum):
    """Data status."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class DatasetType(str, Enum):
    """Dataset type."""

    RECORDED = "recorded"
    EVAL = "eval"
    HUGGINGFACE = "huggingface"


class ModelType(str, Enum):
    """Model type."""

    TRAINED = "trained"
    HUGGINGFACE = "huggingface"


# --- Sync Info ---


class SyncInfo(BaseModel):
    """Sync information for a data item."""

    hash: Optional[str] = Field(None, description="Content hash (sha256:xxxx)")
    size_bytes: int = Field(0, description="Total size in bytes")
    last_synced_at: Optional[str] = Field(None, description="Last sync timestamp")


class PartialSyncInfo(BaseModel):
    """Partial sync information for datasets."""

    mode: str = Field("full", description="Sync mode: full or partial")
    synced_episodes: List[int] = Field(default_factory=list, description="Synced episode indices")
    total_episodes: int = Field(0, description="Total episode count")
    synced_size_bytes: int = Field(0, description="Synced data size")
    total_size_bytes: int = Field(0, description="Total data size")


# --- Type-specific Info ---


class RecordingInfo(BaseModel):
    """Recording metadata for recorded datasets."""

    robot_type: str = Field("so101", description="Robot type")
    cameras: List[str] = Field(default_factory=list, description="Camera IDs used")
    fps: int = Field(30, description="Recording FPS")
    episode_count: int = Field(0, description="Number of episodes")
    total_frames: int = Field(0, description="Total frame count")
    duration_seconds: float = Field(0.0, description="Total duration")


class EvalInfo(BaseModel):
    """Evaluation metadata for eval datasets."""

    model_id: str = Field(..., description="Model used for evaluation")
    policy_type: str = Field(..., description="Policy type")
    success_rate: Optional[float] = Field(None, description="Success rate 0-1")
    episodes_evaluated: int = Field(0, description="Episodes evaluated")


class HuggingFaceInfo(BaseModel):
    """HuggingFace Hub metadata."""

    repo_id: str = Field(..., description="HuggingFace repo ID")
    commit_hash: Optional[str] = Field(None, description="Commit hash")
    downloaded_at: Optional[str] = Field(None, description="Download timestamp")


class TrainingInfo(BaseModel):
    """Training metadata for trained models."""

    dataset_id: str = Field(..., description="Training dataset ID")
    base_model: Optional[str] = Field(None, description="Base/pretrained model ID")
    steps: int = Field(0, description="Training steps")
    final_loss: Optional[float] = Field(None, description="Final training loss")
    gpu_model: Optional[str] = Field(None, description="GPU model used")
    job_id: Optional[str] = Field(None, description="Training job ID")


class ModelConfig(BaseModel):
    """Model configuration."""

    input_features: Dict[str, Any] = Field(default_factory=dict)
    output_features: Dict[str, Any] = Field(default_factory=dict)


# --- Core Metadata ---


class DatasetMetadata(BaseModel):
    """Dataset metadata (.meta.json)."""

    schema_version: int = Field(1, description="Schema version")
    id: str = Field(..., description="Dataset ID")
    name: str = Field(..., description="Human readable name")
    source: DataSource = Field(..., description="Data source")
    status: DataStatus = Field(DataStatus.ACTIVE, description="Status")

    # Ownership and timestamps
    created_by: str = Field("user", description="Creator username")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    archived_at: Optional[str] = Field(None, description="Archive timestamp")

    # Sync info
    sync: SyncInfo = Field(default_factory=SyncInfo, description="Sync information")
    partial_sync: Optional[PartialSyncInfo] = Field(None, description="Partial sync info")

    # Dataset type and info
    dataset_type: DatasetType = Field(..., description="Dataset type")
    project_id: Optional[str] = Field(None, description="Associated project ID")

    # Type-specific metadata
    recording: Optional[RecordingInfo] = Field(None, description="Recording info")
    eval: Optional[EvalInfo] = Field(None, description="Eval info")
    huggingface: Optional[HuggingFaceInfo] = Field(None, description="HuggingFace info")

    # Optional
    tags: List[str] = Field(default_factory=list, description="Tags")
    description: Optional[str] = Field(None, description="Description")


class ModelMetadata(BaseModel):
    """Model metadata (.meta.json)."""

    schema_version: int = Field(1, description="Schema version")
    id: str = Field(..., description="Model ID")
    name: str = Field(..., description="Human readable name")
    source: DataSource = Field(..., description="Data source")
    status: DataStatus = Field(DataStatus.ACTIVE, description="Status")

    # Ownership and timestamps
    created_by: str = Field("user", description="Creator username")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    archived_at: Optional[str] = Field(None, description="Archive timestamp")

    # Sync info
    sync: SyncInfo = Field(default_factory=SyncInfo, description="Sync information")

    # Model type and info
    model_type: ModelType = Field(..., description="Model type")
    policy_type: str = Field(..., description="Policy type (act, pi0, etc.)")

    # Type-specific metadata
    training: Optional[TrainingInfo] = Field(None, description="Training info")
    huggingface: Optional[HuggingFaceInfo] = Field(None, description="HuggingFace info")
    config: ModelConfig = Field(default_factory=ModelConfig, description="Model config")

    # Optional
    tags: List[str] = Field(default_factory=list, description="Tags")
    description: Optional[str] = Field(None, description="Description")


# --- Manifest ---


class ManifestEntry(BaseModel):
    """Entry in the manifest."""

    path: str = Field(..., description="Relative path from ~/.percus")
    source: DataSource = Field(..., description="Data source")
    type: str = Field(..., description="Type (recorded/eval/trained/huggingface)")
    hash: Optional[str] = Field(None, description="Content hash")
    size_bytes: int = Field(0, description="Size in bytes")
    status: DataStatus = Field(DataStatus.ACTIVE, description="Status")


class ProjectEntry(BaseModel):
    """Project entry in manifest."""

    path: str = Field(..., description="Relative path")
    datasets: List[str] = Field(default_factory=list, description="Dataset IDs")
    models: List[str] = Field(default_factory=list, description="Model IDs")


class Manifest(BaseModel):
    """Global manifest (manifest.json)."""

    schema_version: int = Field(1, description="Schema version")
    last_updated: str = Field(..., description="Last update timestamp")
    datasets: Dict[str, ManifestEntry] = Field(default_factory=dict)
    models: Dict[str, ManifestEntry] = Field(default_factory=dict)
    projects: Dict[str, ProjectEntry] = Field(default_factory=dict)


# --- API Request/Response Models ---


class DatasetListResponse(BaseModel):
    """Response for dataset list endpoint."""

    datasets: List[DatasetMetadata]
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

    datasets_count: int = 0
    datasets_size_bytes: int = 0
    models_count: int = 0
    models_size_bytes: int = 0
    archive_count: int = 0
    archive_size_bytes: int = 0
    total_size_bytes: int = 0


class ArchiveListResponse(BaseModel):
    """Response for archived items list."""

    datasets: List[DatasetMetadata] = Field(default_factory=list)
    models: List[ModelMetadata] = Field(default_factory=list)
    total: int = 0
