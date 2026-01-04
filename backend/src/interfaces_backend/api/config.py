"""Configuration API."""

import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter

from interfaces_backend.models.config import (
    AppConfig,
    ConfigResponse,
    EnvironmentInfo,
    EnvironmentsResponse,
)

router = APIRouter(prefix="/api/config", tags=["config"])


def _get_environment_manager():
    """Import percus_ai.environment.EnvironmentManager if available."""
    try:
        from percus_ai.environment import EnvironmentManager

        return EnvironmentManager
    except ImportError:
        features_path = Path(__file__).resolve().parents[5] / "features"
        if features_path.exists() and str(features_path) not in sys.path:
            sys.path.insert(0, str(features_path))
            try:
                from percus_ai.environment import EnvironmentManager

                return EnvironmentManager
            except ImportError:
                pass
    return None


def _get_platform_module():
    """Import percus_ai.environment.Platform if available."""
    try:
        from percus_ai.environment import Platform

        return Platform
    except ImportError:
        pass
    return None


@router.get("", response_model=ConfigResponse)
async def get_config():
    """Get application configuration."""
    return ConfigResponse(
        config=AppConfig(
            data_dir=os.environ.get("PHI_DATA_DIR", "data/"),
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
    EnvironmentManager = _get_environment_manager()
    Platform = _get_platform_module()

    environments = {}
    available_policies = []

    if EnvironmentManager is not None:
        # Get policy map from manager
        try:
            manager = EnvironmentManager()
            policy_map = manager.get_policy_map()

            # Check platform compatibility
            platform = None
            if Platform is not None:
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
