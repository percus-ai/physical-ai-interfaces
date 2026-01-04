"""Platform detection API."""

import sys
from pathlib import Path

from fastapi import APIRouter, Query

from interfaces_backend.models.platform import PlatformInfo, PlatformResponse

router = APIRouter(prefix="/api/platform", tags=["platform"])


def _get_platform_module():
    """Import percus_ai.environment.Platform if available."""
    try:
        from percus_ai.environment import Platform

        return Platform
    except ImportError:
        # Try adding features path
        features_path = Path(__file__).resolve().parents[5] / "features"
        if features_path.exists() and str(features_path) not in sys.path:
            sys.path.insert(0, str(features_path))
            try:
                from percus_ai.environment import Platform

                return Platform
            except ImportError:
                pass
    return None


@router.get("", response_model=PlatformResponse)
async def get_platform(
    refresh: bool = Query(False, description="Force refresh (ignore cache)"),
):
    """Get platform information.

    Detects OS, architecture, GPU, CUDA, and other platform details.
    Results are cached for faster subsequent calls.
    """
    Platform = _get_platform_module()

    if Platform is None:
        # Fallback: return minimal info without percus_ai
        import platform as py_platform

        return PlatformResponse(
            platform=PlatformInfo(
                os_type=py_platform.system().lower(),
                arch=py_platform.machine(),
            ),
            cached=False,
        )

    # Use percus_ai Platform detection
    platform = Platform.detect(use_cache=not refresh)
    platform_dict = platform.to_dict()

    return PlatformResponse(
        platform=PlatformInfo(
            os_type=platform_dict.get("os_type", "unknown"),
            arch=platform_dict.get("arch", "unknown"),
            is_jetson=platform_dict.get("is_jetson", False),
            jetson_model=platform_dict.get("jetson_model"),
            has_cuda=platform_dict.get("has_cuda", False),
            cuda_version=platform_dict.get("cuda_version"),
            gpu_name=platform_dict.get("gpu_name"),
            gpu_count=platform_dict.get("gpu_count", 0),
            has_mps=platform_dict.get("has_mps", False),
            compute_device=platform_dict.get("compute_device", "cpu"),
            pytorch_build_required=platform_dict.get("pytorch_build_required", False),
            torch_compile_available=platform_dict.get("torch_compile_available", True),
        ),
        cached=not refresh,
    )


@router.post("/refresh", response_model=PlatformResponse)
async def refresh_platform():
    """Force refresh platform detection.

    Same as GET /api/platform?refresh=true
    """
    return await get_platform(refresh=True)
