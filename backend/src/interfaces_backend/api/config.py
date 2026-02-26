"""Configuration API."""

import os

from fastapi import APIRouter

from interfaces_backend.models.config import AppConfig, ConfigResponse

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=ConfigResponse)
async def get_config():
    """Get application configuration."""
    from percus_ai.storage import get_data_dir

    return ConfigResponse(
        config=AppConfig(
            data_dir=str(get_data_dir()),
            robot_type=os.environ.get("PHI_ROBOT_TYPE", "so101"),
            hf_token_set=bool(os.environ.get("HF_TOKEN")),
            wandb_token_set=bool(os.environ.get("WANDB_API_KEY")),
        )
    )

