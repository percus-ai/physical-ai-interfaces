"""Platform detection API."""

from fastapi import APIRouter, Query

from interfaces_backend.models.platform import PlatformInfo, PlatformResponse
from percus_ai.environment import Platform

router = APIRouter(prefix="/api/platform", tags=["platform"])


@router.get("", response_model=PlatformResponse)
async def get_platform(
    refresh: bool = Query(False, description="Force refresh (ignore cache)"),
):
    """Get platform information.

    Detects OS, architecture, GPU, CUDA, and other platform details.
    Results are cached for faster subsequent calls.
    """
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
