"""Platform detection models."""

from typing import Optional

from pydantic import BaseModel, Field


class PlatformInfo(BaseModel):
    """Platform information response."""

    # Basic info
    os_type: str = Field(..., description="OS type: linux, darwin, windows")
    arch: str = Field(..., description="Architecture: x86_64, aarch64")

    # Jetson/Tegra
    is_jetson: bool = Field(False, description="Running on NVIDIA Jetson")
    jetson_model: Optional[str] = Field(None, description="Jetson model: Orin, Xavier, etc.")

    # CUDA
    has_cuda: bool = Field(False, description="CUDA is available")
    cuda_version: Optional[str] = Field(None, description="CUDA version")
    gpu_name: Optional[str] = Field(None, description="GPU name")
    gpu_count: int = Field(0, description="Number of GPUs")

    # Apple Silicon
    has_mps: bool = Field(False, description="Apple MPS is available")

    # Compute settings
    compute_device: str = Field("cpu", description="Recommended compute device: cuda, mps, cpu")
    pytorch_build_required: bool = Field(False, description="PyTorch source build required")
    torch_compile_available: bool = Field(True, description="torch.compile is available")


class PlatformResponse(BaseModel):
    """Response for platform endpoint."""

    platform: PlatformInfo
    cached: bool = Field(False, description="Result was from cache")
