"""API routers."""

from interfaces_backend.api.analytics import router as analytics_router
from interfaces_backend.api.build import router as build_router
from interfaces_backend.api.calibration import router as calibration_router
from interfaces_backend.api.config import router as config_router
from interfaces_backend.api.hardware import router as hardware_router
from interfaces_backend.api.inference import router as inference_router
from interfaces_backend.api.platform import router as platform_router
from interfaces_backend.api.project import router as project_router
from interfaces_backend.api.recording import router as recording_router
from interfaces_backend.api.storage import router as storage_router
from interfaces_backend.api.system import router as system_router
from interfaces_backend.api.teleop import router as teleop_router
from interfaces_backend.api.training import router as training_router
from interfaces_backend.api.user import router as user_router

__all__ = [
    "analytics_router",
    "build_router",
    "calibration_router",
    "config_router",
    "hardware_router",
    "inference_router",
    "platform_router",
    "project_router",
    "recording_router",
    "storage_router",
    "system_router",
    "teleop_router",
    "training_router",
    "user_router",
]
