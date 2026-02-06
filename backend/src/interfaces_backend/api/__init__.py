"""API routers."""

from interfaces_backend.api.analytics import router as analytics_router
from interfaces_backend.api.auth import router as auth_router
from interfaces_backend.api.build import router as build_router
from interfaces_backend.api.calibration import router as calibration_router
from interfaces_backend.api.config import router as config_router
from interfaces_backend.api.experiments import router as experiments_router
from interfaces_backend.api.hardware import router as hardware_router
from interfaces_backend.api.inference import router as inference_router
from interfaces_backend.api.operate import router as operate_router
from interfaces_backend.api.platform import router as platform_router
from interfaces_backend.api.profiles import router as profiles_router
from interfaces_backend.api.recording import router as recording_router
from interfaces_backend.api.storage import router as storage_router
from interfaces_backend.api.stream import router as stream_router
from interfaces_backend.api.system import router as system_router
from interfaces_backend.api.teleop import router as teleop_router
from interfaces_backend.api.training import router as training_router
from interfaces_backend.api.user import router as user_router

__all__ = [
    "analytics_router",
    "auth_router",
    "build_router",
    "calibration_router",
    "config_router",
    "experiments_router",
    "hardware_router",
    "inference_router",
    "operate_router",
    "platform_router",
    "profiles_router",
    "recording_router",
    "storage_router",
    "stream_router",
    "system_router",
    "teleop_router",
    "training_router",
    "user_router",
]
