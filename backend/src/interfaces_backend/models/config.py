"""Configuration models."""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """Application configuration."""

    data_dir: str = Field("data/", description="Data directory path")
    robot_type: str = Field("so101", description="Default robot type")
    hf_token_set: bool = Field(False, description="HuggingFace token is configured")
    wandb_token_set: bool = Field(False, description="W&B token is configured")


class EnvironmentInfo(BaseModel):
    """Training environment information."""

    name: str = Field(..., description="Environment name")
    venv: str = Field(..., description="Virtual environment name")
    policies: List[str] = Field(default_factory=list, description="Supported policies")
    description: str = Field("", description="Environment description")
    gpu_required: bool = Field(False, description="GPU is required")
    compatible: bool = Field(True, description="Compatible with current platform")


class ConfigResponse(BaseModel):
    """Response for config endpoint."""

    config: AppConfig


class EnvironmentsResponse(BaseModel):
    """Response for environments endpoint."""

    environments: Dict[str, EnvironmentInfo]
    available_policies: List[str] = Field(default_factory=list, description="All available policy types")
