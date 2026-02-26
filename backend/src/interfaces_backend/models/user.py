"""User API models."""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class UserConfigModel(BaseModel):
    """User configuration."""

    user_id: Optional[str] = Field(None, description="Supabase user id")
    email: str = Field("", description="Email address")
    preferred_tool: str = Field("uv", description="Preferred Python tool (uv/pip)")
    gpu_available: bool = Field(False, description="GPU is available")
    cuda_version: Optional[str] = Field(None, description="CUDA version if available")
    auto_upload_after_recording: bool = Field(True, description="Auto upload after recording")
    auto_download_models: bool = Field(True, description="Auto download models")
    sync_on_startup: bool = Field(False, description="Sync on startup")
    default_fps: int = Field(30, description="Default FPS for recording")
    preview_window: bool = Field(True, description="Show preview window")
    save_raw_video: bool = Field(True, description="Save raw video")
    devices_file: str = Field("user_devices.json", description="Devices config file")


class UserConfigUpdateRequest(BaseModel):
    """Request to update user configuration."""

    email: Optional[str] = Field(None, description="Email address")
    preferred_tool: Optional[str] = Field(None, description="Preferred Python tool")
    gpu_available: Optional[bool] = Field(None, description="GPU availability")
    cuda_version: Optional[str] = Field(None, description="CUDA version")
    auto_upload_after_recording: Optional[bool] = Field(None, description="Auto upload")
    auto_download_models: Optional[bool] = Field(None, description="Auto download")
    sync_on_startup: Optional[bool] = Field(None, description="Sync on startup")
    default_fps: Optional[int] = Field(None, description="Default FPS")
    preview_window: Optional[bool] = Field(None, description="Preview window")
    save_raw_video: Optional[bool] = Field(None, description="Save raw video")


class CameraDeviceConfig(BaseModel):
    """Camera device configuration."""

    id: Union[int, str] = Field(..., description="Camera ID (index or device path)")
    type: str = Field("opencv", description="Camera type: opencv, realsense, usb")
    friendly_name: Optional[str] = Field(None, description="Human-readable camera name")
    width: int = Field(640, description="Frame width")
    height: int = Field(480, description="Frame height")
    fps: int = Field(30, description="Frames per second")


class ArmDeviceConfig(BaseModel):
    """Arm device configuration."""

    port: str = Field(..., description="Serial port")
    type: str = Field("so101", description="Arm type: so101, so100")
    calibration_id: Optional[str] = Field(None, description="Calibration ID")


class DeviceConfigModel(BaseModel):
    """Device configuration."""

    cameras: Dict[str, CameraDeviceConfig] = Field(
        default_factory=dict, description="Camera configurations"
    )
    leader_right: Optional[ArmDeviceConfig] = Field(None, description="Right leader arm")
    follower_right: Optional[ArmDeviceConfig] = Field(None, description="Right follower arm")
    leader_left: Optional[ArmDeviceConfig] = Field(None, description="Left leader arm")
    follower_left: Optional[ArmDeviceConfig] = Field(None, description="Left follower arm")
    schema_version: int = Field(1, description="Config schema version")
    updated_at: str = Field("", description="Last update timestamp")


class DeviceConfigUpdateRequest(BaseModel):
    """Request to update device configuration."""

    cameras: Optional[Dict[str, CameraDeviceConfig]] = Field(None, description="Cameras")
    leader_right: Optional[ArmDeviceConfig] = Field(None, description="Right leader")
    follower_right: Optional[ArmDeviceConfig] = Field(None, description="Right follower")
    leader_left: Optional[ArmDeviceConfig] = Field(None, description="Left leader")
    follower_left: Optional[ArmDeviceConfig] = Field(None, description="Left follower")


class EnvironmentCheckResult(BaseModel):
    """Result of environment validation."""

    name: str = Field(..., description="Check name")
    passed: bool = Field(..., description="Check passed")
    message: str = Field(..., description="Result message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional details")


class EnvironmentValidationResponse(BaseModel):
    """Response for environment validation endpoint."""

    is_valid: bool = Field(..., description="All checks passed")
    checks: List[EnvironmentCheckResult]
    errors: List[str] = Field(default_factory=list, description="Error messages")
    warnings: List[str] = Field(default_factory=list, description="Warning messages")
