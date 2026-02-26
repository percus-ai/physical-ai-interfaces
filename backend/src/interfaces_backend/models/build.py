"""Build data models for bundled-torch building."""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# --- Enums ---


class BuildStatus(str, Enum):
    """Build status."""

    PENDING = "pending"
    CLONING = "cloning"
    BUILDING = "building"
    COMPLETED = "completed"
    FAILED = "failed"


class BuildStep(str, Enum):
    """Build step identifiers."""

    CLONE_PYTORCH = "clone_pytorch"
    CLONE_TORCHVISION = "clone_torchvision"
    BUILD_PYTORCH = "build_pytorch"
    BUILD_TORCHVISION = "build_torchvision"


# --- Request/Response Models ---


class BundledTorchStatusResponse(BaseModel):
    """Response for bundled-torch status check."""

    exists: bool = Field(..., description="Whether bundled-torch exists")
    pytorch_version: Optional[str] = Field(None, description="PyTorch version")
    torchvision_version: Optional[str] = Field(None, description="torchvision version")
    numpy_version: Optional[str] = Field(None, description="numpy version used for build")
    pytorch_path: Optional[str] = Field(None, description="PyTorch source path")
    torchvision_path: Optional[str] = Field(None, description="torchvision source path")
    is_valid: bool = Field(False, description="Whether build is valid (has .so files)")
    is_jetson: bool = Field(False, description="Whether running on Jetson")


# --- WebSocket Message Models ---


class BuildProgressMessage(BaseModel):
    """WebSocket progress message."""

    type: str = Field(..., description="Message type: start|progress|step_complete|log|complete|error")
    step: Optional[str] = Field(None, description="Current build step")
    percent: Optional[int] = Field(None, description="Progress percentage (0-100)")
    message: Optional[str] = Field(None, description="Human-readable message")
    line: Optional[str] = Field(None, description="Log line (for type=log)")
    output_path: Optional[str] = Field(None, description="Output path (for type=complete)")
    error: Optional[str] = Field(None, description="Error message (for type=error)")
