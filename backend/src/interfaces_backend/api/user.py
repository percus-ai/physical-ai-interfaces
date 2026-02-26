"""User API router."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
import cv2
import lerobot
from serial.tools import list_ports
import yaml

from interfaces_backend.models.user import (
    UserConfigModel,
    UserConfigUpdateRequest,
    CameraDeviceConfig,
    ArmDeviceConfig,
    DeviceConfigModel,
    DeviceConfigUpdateRequest,
    EnvironmentCheckResult,
    EnvironmentValidationResponse,
)
from percus_ai.db import get_supabase_session
from percus_ai.storage import get_user_config_path, get_user_devices_path

router = APIRouter(prefix="/api/user", tags=["user"])

# Config file paths
USER_CONFIG_PATH = get_user_config_path()
DEVICES_CONFIG_PATH = get_user_devices_path()


def _load_user_config() -> dict:
    """Load user configuration from file."""
    if not USER_CONFIG_PATH.exists():
        return {
            "email": "",
            "preferred_tool": "uv",
            "gpu_available": False,
            "cuda_version": None,
            "auto_upload_after_recording": True,
            "auto_download_models": True,
            "sync_on_startup": False,
            "default_fps": 30,
            "preview_window": True,
            "save_raw_video": True,
            "devices_file": "user_devices.json",
        }

    try:
        with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        user = data.get("user", {})
        environment = data.get("environment", {})
        sync = data.get("sync", {})
        recording = data.get("recording", {})

        return {
            "email": user.get("email", ""),
            "preferred_tool": environment.get("preferred_tool", "uv"),
            "gpu_available": environment.get("gpu_available", False),
            "cuda_version": environment.get("cuda_version"),
            "auto_upload_after_recording": sync.get("auto_upload_after_recording", True),
            "auto_download_models": sync.get("auto_download_models", True),
            "sync_on_startup": sync.get("sync_on_startup", False),
            "default_fps": recording.get("default_fps", 30),
            "preview_window": recording.get("preview_window", True),
            "save_raw_video": recording.get("save_raw_video", True),
            "devices_file": data.get("devices_file", "user_devices.json"),
        }
    except Exception:
        return {
            "email": "",
            "preferred_tool": "uv",
            "gpu_available": False,
            "cuda_version": None,
            "auto_upload_after_recording": True,
            "auto_download_models": True,
            "sync_on_startup": False,
            "default_fps": 30,
            "preview_window": True,
            "save_raw_video": True,
            "devices_file": "user_devices.json",
        }


def _save_user_config(config: dict) -> None:
    """Save user configuration to file."""
    # Create directory if needed
    USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Convert to YAML structure
    data = {
        "user": {
            "email": config.get("email", ""),
        },
        "environment": {
            "preferred_tool": config.get("preferred_tool", "uv"),
            "gpu_available": config.get("gpu_available", False),
            "cuda_version": config.get("cuda_version"),
        },
        "sync": {
            "auto_upload_after_recording": config.get("auto_upload_after_recording", True),
            "auto_download_models": config.get("auto_download_models", True),
            "sync_on_startup": config.get("sync_on_startup", False),
        },
        "recording": {
            "default_fps": config.get("default_fps", 30),
            "preview_window": config.get("preview_window", True),
            "save_raw_video": config.get("save_raw_video", True),
        },
        "devices_file": config.get("devices_file", "user_devices.json"),
    }

    with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

def _load_device_config() -> dict:
    """Load device configuration from file."""
    if not DEVICES_CONFIG_PATH.exists():
        return {
            "cameras": {},
            "leader_right": None,
            "follower_right": None,
            "leader_left": None,
            "follower_left": None,
            "schema_version": 1,
            "updated_at": "",
        }

    try:
        with open(DEVICES_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Parse cameras
        cameras = {}
        for name, cam_data in data.get("cameras", {}).items():
            cameras[name] = {
                "id": cam_data.get("id", 0),
                "type": cam_data.get("type", "opencv"),
                "width": cam_data.get("width", 640),
                "height": cam_data.get("height", 480),
                "fps": cam_data.get("fps", 30),
            }

        # Parse arms (new format)
        def parse_arm(arm_data: Optional[dict]) -> Optional[dict]:
            if not arm_data:
                return None
            return {
                "port": arm_data.get("port", ""),
                "type": arm_data.get("type", "so101"),
                "calibration_id": arm_data.get("calibration_id"),
            }

        # Legacy format fallback
        leader_right = parse_arm(data.get("leader_right")) or parse_arm(data.get("leader_arm"))
        follower_right = parse_arm(data.get("follower_right")) or parse_arm(data.get("follower_arm"))
        leader_left = parse_arm(data.get("leader_left"))
        follower_left = parse_arm(data.get("follower_left"))

        return {
            "cameras": cameras,
            "leader_right": leader_right,
            "follower_right": follower_right,
            "leader_left": leader_left,
            "follower_left": follower_left,
            "schema_version": data.get("schema_version", 1),
            "updated_at": data.get("updated_at", ""),
        }
    except Exception:
        return {
            "cameras": {},
            "leader_right": None,
            "follower_right": None,
            "leader_left": None,
            "follower_left": None,
            "schema_version": 1,
            "updated_at": "",
        }


def _save_device_config(config: dict) -> None:
    """Save device configuration to file."""
    # Convert to JSON-serializable format
    data = {
        "cameras": {},
        "schema_version": config.get("schema_version", 1),
        "updated_at": datetime.now().isoformat(),
    }

    # Serialize cameras
    for name, cam in config.get("cameras", {}).items():
        if isinstance(cam, dict):
            data["cameras"][name] = cam
        else:
            data["cameras"][name] = {
                "id": cam.id,
                "type": cam.type,
                "width": cam.width,
                "height": cam.height,
                "fps": cam.fps,
            }

    # Serialize arms
    def serialize_arm(arm: Optional[dict]) -> Optional[dict]:
        if not arm:
            return None
        if isinstance(arm, dict):
            return arm
        return {
            "port": arm.port,
            "type": arm.type,
            "calibration_id": arm.calibration_id,
        }

    if config.get("leader_right"):
        data["leader_right"] = serialize_arm(config["leader_right"])
    if config.get("follower_right"):
        data["follower_right"] = serialize_arm(config["follower_right"])
    if config.get("leader_left"):
        data["leader_left"] = serialize_arm(config["leader_left"])
    if config.get("follower_left"):
        data["follower_left"] = serialize_arm(config["follower_left"])

    with open(DEVICES_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@router.get("/config", response_model=UserConfigModel)
async def get_user_config():
    """Get user configuration."""
    config = _load_user_config()
    session = get_supabase_session() or {}

    return UserConfigModel(
        user_id=session.get("user_id"),
        email=config.get("email", ""),
        preferred_tool=config.get("preferred_tool", "uv"),
        gpu_available=config.get("gpu_available", False),
        cuda_version=config.get("cuda_version"),
        auto_upload_after_recording=config.get("auto_upload_after_recording", True),
        auto_download_models=config.get("auto_download_models", True),
        sync_on_startup=config.get("sync_on_startup", False),
        default_fps=config.get("default_fps", 30),
        preview_window=config.get("preview_window", True),
        save_raw_video=config.get("save_raw_video", True),
        devices_file=config.get("devices_file", "user_devices.json"),
    )


@router.put("/config", response_model=UserConfigModel)
async def update_user_config(request: UserConfigUpdateRequest):
    """Update user configuration."""
    config = _load_user_config()

    # Update only provided fields
    if request.email is not None:
        config["email"] = request.email
    if request.preferred_tool is not None:
        config["preferred_tool"] = request.preferred_tool
    if request.gpu_available is not None:
        config["gpu_available"] = request.gpu_available
    if request.cuda_version is not None:
        config["cuda_version"] = request.cuda_version
    if request.auto_upload_after_recording is not None:
        config["auto_upload_after_recording"] = request.auto_upload_after_recording
    if request.auto_download_models is not None:
        config["auto_download_models"] = request.auto_download_models
    if request.sync_on_startup is not None:
        config["sync_on_startup"] = request.sync_on_startup
    if request.default_fps is not None:
        config["default_fps"] = request.default_fps
    if request.preview_window is not None:
        config["preview_window"] = request.preview_window
    if request.save_raw_video is not None:
        config["save_raw_video"] = request.save_raw_video

    _save_user_config(config)

    session = get_supabase_session() or {}
    return UserConfigModel(
        user_id=session.get("user_id"),
        email=config.get("email", ""),
        preferred_tool=config.get("preferred_tool", "uv"),
        gpu_available=config.get("gpu_available", False),
        cuda_version=config.get("cuda_version"),
        auto_upload_after_recording=config.get("auto_upload_after_recording", True),
        auto_download_models=config.get("auto_download_models", True),
        sync_on_startup=config.get("sync_on_startup", False),
        default_fps=config.get("default_fps", 30),
        preview_window=config.get("preview_window", True),
        save_raw_video=config.get("save_raw_video", True),
        devices_file=config.get("devices_file", "user_devices.json"),
    )


@router.get("/devices", response_model=DeviceConfigModel)
async def get_device_config():
    """Get device configuration."""
    config = _load_device_config()

    cameras = {}
    for name, cam in config.get("cameras", {}).items():
        cameras[name] = CameraDeviceConfig(
            id=cam.get("id", 0),
            type=cam.get("type", "opencv"),
            friendly_name=cam.get("friendly_name"),
            width=cam.get("width", 640),
            height=cam.get("height", 480),
            fps=cam.get("fps", 30),
        )

    def to_arm_config(arm: Optional[dict]) -> Optional[ArmDeviceConfig]:
        if not arm:
            return None
        return ArmDeviceConfig(
            port=arm.get("port", ""),
            type=arm.get("type", "so101"),
            calibration_id=arm.get("calibration_id"),
        )

    return DeviceConfigModel(
        cameras=cameras,
        leader_right=to_arm_config(config.get("leader_right")),
        follower_right=to_arm_config(config.get("follower_right")),
        leader_left=to_arm_config(config.get("leader_left")),
        follower_left=to_arm_config(config.get("follower_left")),
        schema_version=config.get("schema_version", 1),
        updated_at=config.get("updated_at", ""),
    )


@router.put("/devices", response_model=DeviceConfigModel)
async def update_device_config(request: DeviceConfigUpdateRequest):
    """Update device configuration."""
    config = _load_device_config()

    # Update cameras if provided
    if request.cameras is not None:
        config["cameras"] = {}
        for name, cam in request.cameras.items():
            config["cameras"][name] = {
                "id": cam.id,
                "type": cam.type,
                "width": cam.width,
                "height": cam.height,
                "fps": cam.fps,
            }

    # Update arms if provided
    def update_arm(current: Optional[dict], new: Optional[ArmDeviceConfig]) -> Optional[dict]:
        if new is None:
            return current
        return {
            "port": new.port,
            "type": new.type,
            "calibration_id": new.calibration_id,
        }

    if request.leader_right is not None:
        config["leader_right"] = update_arm(config.get("leader_right"), request.leader_right)
    if request.follower_right is not None:
        config["follower_right"] = update_arm(config.get("follower_right"), request.follower_right)
    if request.leader_left is not None:
        config["leader_left"] = update_arm(config.get("leader_left"), request.leader_left)
    if request.follower_left is not None:
        config["follower_left"] = update_arm(config.get("follower_left"), request.follower_left)

    _save_device_config(config)

    # Return updated config
    cameras = {}
    for name, cam in config.get("cameras", {}).items():
        cameras[name] = CameraDeviceConfig(
            id=cam.get("id", 0),
            type=cam.get("type", "opencv"),
            friendly_name=cam.get("friendly_name"),
            width=cam.get("width", 640),
            height=cam.get("height", 480),
            fps=cam.get("fps", 30),
        )

    def to_arm_config(arm: Optional[dict]) -> Optional[ArmDeviceConfig]:
        if not arm:
            return None
        return ArmDeviceConfig(
            port=arm.get("port", ""),
            type=arm.get("type", "so101"),
            calibration_id=arm.get("calibration_id"),
        )

    return DeviceConfigModel(
        cameras=cameras,
        leader_right=to_arm_config(config.get("leader_right")),
        follower_right=to_arm_config(config.get("follower_right")),
        leader_left=to_arm_config(config.get("leader_left")),
        follower_left=to_arm_config(config.get("follower_left")),
        schema_version=config.get("schema_version", 1),
        updated_at=config.get("updated_at", ""),
    )


@router.post("/validate-environment", response_model=EnvironmentValidationResponse)
async def validate_environment():
    """Validate environment setup."""
    checks = []
    errors = []
    warnings = []

    # Check Python version
    import sys
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    python_ok = sys.version_info >= (3, 10)
    checks.append(EnvironmentCheckResult(
        name="Python version",
        passed=python_ok,
        message=f"Python {python_version}" + (" (OK)" if python_ok else " (requires 3.10+)"),
        details={"version": python_version},
    ))
    if not python_ok:
        errors.append("Python 3.10 or higher is required")

    # Check PyTorch (via subprocess to avoid numpy conflicts)
    from interfaces_backend.utils.torch_info import get_torch_info
    torch_info = get_torch_info()
    if torch_info.get("torch_version"):
        torch_version = torch_info["torch_version"]
        cuda_available = torch_info.get("cuda_available", False)
        cuda_version = torch_info.get("cuda_version")
        checks.append(EnvironmentCheckResult(
            name="PyTorch",
            passed=True,
            message=f"PyTorch {torch_version}" + (f" (CUDA: {cuda_version})" if cuda_available else " (CPU only)"),
            details={"version": torch_version, "cuda_available": cuda_available},
        ))
        if not cuda_available:
            warnings.append("CUDA not available - GPU acceleration disabled")
    else:
        checks.append(EnvironmentCheckResult(
            name="PyTorch",
            passed=False,
            message="PyTorch not installed",
        ))
        errors.append("PyTorch is required")

    # Check LeRobot
    checks.append(EnvironmentCheckResult(
        name="LeRobot",
        passed=True,
        message="LeRobot installed",
        details={"version": getattr(lerobot, "__version__", "unknown")},
    ))

    # Check OpenCV
    checks.append(EnvironmentCheckResult(
        name="OpenCV",
        passed=True,
        message=f"OpenCV {cv2.__version__}",
        details={"version": cv2.__version__},
    ))

    # Check device config
    device_config = _load_device_config()
    has_cameras = len(device_config.get("cameras", {})) > 0
    has_arms = any([
        device_config.get("leader_right"),
        device_config.get("follower_right"),
        device_config.get("leader_left"),
        device_config.get("follower_left"),
    ])

    checks.append(EnvironmentCheckResult(
        name="Device configuration",
        passed=has_cameras or has_arms,
        message=f"Cameras: {len(device_config.get('cameras', {}))}, Arms configured: {has_arms}",
        details={
            "cameras": list(device_config.get("cameras", {}).keys()),
            "has_arms": has_arms,
        },
    ))
    if not (has_cameras or has_arms):
        warnings.append("No devices configured - run device setup")

    # Check serial ports
    ports = list(list_ports.comports())
    checks.append(EnvironmentCheckResult(
        name="Serial ports",
        passed=True,
        message=f"{len(ports)} port(s) available",
        details={"ports": [p.device for p in ports]},
    ))

    is_valid = len(errors) == 0

    return EnvironmentValidationResponse(
        is_valid=is_valid,
        checks=checks,
        errors=errors,
        warnings=warnings,
    )
