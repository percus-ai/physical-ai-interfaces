"""Configuration models."""

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """Application configuration."""

    data_dir: str = Field("data/", description="Data directory path")
    robot_type: str = Field("so101", description="Default robot type")
    hf_token_set: bool = Field(False, description="HuggingFace token is configured")
    wandb_token_set: bool = Field(False, description="W&B token is configured")


class ConfigResponse(BaseModel):
    """Response for config endpoint."""

    config: AppConfig
