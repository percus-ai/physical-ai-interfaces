"""Analytics API models."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class OverviewStats(BaseModel):
    """Overview statistics."""

    total_projects: int = Field(0, description="Total number of projects")
    total_episodes: int = Field(0, description="Total number of recorded episodes")
    total_models: int = Field(0, description="Total number of trained models")
    total_training_jobs: int = Field(0, description="Total training jobs")
    active_training_jobs: int = Field(0, description="Currently active jobs")
    total_storage_gb: float = Field(0.0, description="Total storage used in GB")


class OverviewResponse(BaseModel):
    """Response for overview endpoint."""

    stats: OverviewStats
    updated_at: str = Field(..., description="Last update timestamp")


class ProjectStats(BaseModel):
    """Statistics for a single project."""

    project_id: str = Field(..., description="Project identifier")
    name: str = Field("", description="Project name")
    episode_count: int = Field(0, description="Number of episodes")
    model_count: int = Field(0, description="Number of models")
    total_frames: int = Field(0, description="Total frames recorded")
    total_duration_hours: float = Field(0.0, description="Total duration in hours")
    storage_mb: float = Field(0.0, description="Storage used in MB")
    last_activity: Optional[str] = Field(None, description="Last activity timestamp")


class ProjectsStatsResponse(BaseModel):
    """Response for projects statistics endpoint."""

    projects: List[ProjectStats]
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
