"""Project management data models."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CameraConfigModel(BaseModel):
    """Camera configuration for a project."""

    width: int = Field(640, description="Camera width")
    height: int = Field(480, description="Camera height")
    warmup_time_s: int = Field(5, description="Camera warmup time in seconds")
    depth: bool = Field(False, description="Enable depth capture")
    rgb: bool = Field(True, description="Enable RGB capture")


class ProjectCreateRequest(BaseModel):
    """Request to create a new project."""

    display_name: str = Field(..., description="Human-readable project name")
    description: str = Field("", description="Project description")
    cameras: Optional[Dict[str, CameraConfigModel]] = Field(
        None, description="Camera configurations"
    )
    episode_time_s: int = Field(20, description="Episode duration in seconds")
    reset_time_s: int = Field(10, description="Reset time between episodes")
    robot_type: str = Field("so101", description="Robot type (so101, so100, koch)")


class ProjectModel(BaseModel):
    """Project information."""

    name: str = Field(..., description="Project ID/name")
    display_name: str = Field(..., description="Human-readable name")
    description: str = Field("", description="Project description")
    version: str = Field("1.0", description="Project version")
    created_at: str = Field(..., description="Creation date")
    robot_type: str = Field("so101", description="Robot type")
    episode_time_s: int = Field(20, description="Episode duration")
    reset_time_s: int = Field(10, description="Reset time")
    cameras: Dict[str, Any] = Field(default_factory=dict, description="Camera configs")
    arms: Dict[str, str] = Field(default_factory=dict, description="Arm configs")


class ProjectListResponse(BaseModel):
    """Response for project list endpoint."""

    projects: List[str] = Field(..., description="List of project names")
    total: int = Field(..., description="Total count")


class ProjectStatsModel(BaseModel):
    """Project statistics."""

    project_name: str = Field(..., description="Project name")
    episode_count: int = Field(0, description="Number of episodes")
    model_count: int = Field(0, description="Number of models")
    dataset_size_bytes: int = Field(0, description="Dataset size in bytes")
    models_size_bytes: int = Field(0, description="Models size in bytes")
    user_stats: Dict[str, int] = Field(
        default_factory=dict, description="Episodes per user"
    )
    episodes: List[str] = Field(default_factory=list, description="Episode names")
    models: List[str] = Field(default_factory=list, description="Model names")


class ProjectValidateResponse(BaseModel):
    """Response for project validation."""

    project_name: str = Field(..., description="Project name")
    is_valid: bool = Field(..., description="Whether dataset is valid")
    issues: List[str] = Field(default_factory=list, description="Validation issues")


class ProjectDeviceValidation(BaseModel):
    """Response for device validation against project."""

    project_name: str = Field(..., description="Project name")
    all_devices_present: bool = Field(..., description="All required devices present")
    missing_devices: List[str] = Field(
        default_factory=list, description="Missing devices"
    )
