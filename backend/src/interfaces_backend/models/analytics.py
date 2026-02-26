"""Analytics API models."""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class OverviewStats(BaseModel):
    """Overview statistics."""

    total_profiles: int = Field(0, description="Total number of VLAbor profiles")
    total_datasets: int = Field(0, description="Total number of datasets")
    total_episodes: int = Field(0, description="Total number of recorded episodes")
    total_models: int = Field(0, description="Total number of trained models")
    total_training_jobs: int = Field(0, description="Total training jobs")
    active_training_jobs: int = Field(0, description="Currently active jobs")
    total_storage_gb: float = Field(0.0, description="Total storage used in GB")


class OverviewResponse(BaseModel):
    """Response for overview endpoint."""

    stats: OverviewStats
    updated_at: str = Field(..., description="Last update timestamp")


class ProfileStats(BaseModel):
    """Statistics for a single VLAbor profile."""

    profile_name: str = Field(..., description="VLAbor profile name")
    dataset_count: int = Field(0, description="Number of datasets")
    model_count: int = Field(0, description="Number of models")
    episode_count: int = Field(0, description="Number of episodes")
    storage_mb: float = Field(0.0, description="Storage used in MB")
    last_activity: Optional[str] = Field(None, description="Last activity timestamp")


class ProfileStatsResponse(BaseModel):
    """Response for profile statistics endpoint."""

    profiles: List[ProfileStats]
    total: int


class TrainingStats(BaseModel):
    """Training job statistics."""

    total_jobs: int = Field(0, description="Total training jobs")
    completed_jobs: int = Field(0, description="Completed jobs")
    failed_jobs: int = Field(0, description="Failed jobs")
    active_jobs: int = Field(0, description="Currently running jobs")
    average_duration_hours: float = Field(0.0, description="Average job duration")
    success_rate: float = Field(0.0, description="Success rate (0-1)")
    total_gpu_hours: float = Field(0.0, description="Total GPU hours used")


class TrainingStatsResponse(BaseModel):
    """Response for training statistics endpoint."""

    stats: TrainingStats
    jobs_by_status: Dict[str, int] = Field(default_factory=dict, description="Jobs by status")
    jobs_by_month: Dict[str, int] = Field(default_factory=dict, description="Jobs by month")


class StorageCategory(BaseModel):
    """Storage usage by category."""

    category: str = Field(..., description="Category name")
    size_mb: float = Field(0.0, description="Size in MB")
    file_count: int = Field(0, description="Number of files")
    percentage: float = Field(0.0, description="Percentage of total")


class StorageStatsResponse(BaseModel):
    """Response for storage statistics endpoint."""

    total_size_gb: float = Field(0.0, description="Total storage in GB")
    available_gb: float = Field(0.0, description="Available storage in GB")
    used_percentage: float = Field(0.0, description="Usage percentage")
    categories: List[StorageCategory]
