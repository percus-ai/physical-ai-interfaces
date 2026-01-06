"""Configuration API."""

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter

from interfaces_backend.models.config import (
    AppConfig,
    ConfigResponse,
    EnvironmentInfo,
    EnvironmentsResponse,
)
from percus_ai.environment import EnvironmentManager, Platform

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


@router.get("/environments", response_model=EnvironmentsResponse)
async def get_environments():
    """Get available training environments and policies.

    Returns environment configurations and which policies they support.
    """
    environments = {}
    available_policies = []

    try:
        manager = EnvironmentManager()
        policy_map = manager.get_policy_map()

        # Check platform compatibility
        platform = None
        try:
            platform = Platform.detect()
        except Exception:
            pass

        env_configs = policy_map.get("environments", {})
        for env_name, env_config in env_configs.items():
            policies = env_config.get("policies", [])
            gpu_required = env_config.get("gpu_required", False)

            # Check compatibility
            compatible = True
            if platform and gpu_required and not platform.has_cuda:
                compatible = False

            environments[env_name] = EnvironmentInfo(
                name=env_name,
                venv=env_config.get("venv", env_name),
                policies=policies,
                description=env_config.get("description", ""),
                gpu_required=gpu_required,
                compatible=compatible,
            )
            available_policies.extend(policies)

    except Exception:
        pass

    # Remove duplicates from policies
    available_policies = list(set(available_policies))

    return EnvironmentsResponse(
        environments=environments,
        available_policies=sorted(available_policies),
    )
