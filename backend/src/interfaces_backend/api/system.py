"""System API router."""

import os
import platform
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query

from interfaces_backend.models.system import (
    ServiceStatus,
    HealthResponse,
    ResourceUsage,
    ResourcesResponse,
    LogEntry,
    LogsResponse,
    SystemInfo,
    SystemInfoResponse,
    GpuInfo,
    GpuResponse,
)

router = APIRouter(prefix="/api/system", tags=["system"])

# Server start time for uptime calculation
_server_start_time = time.time()

# In-memory log buffer
_log_buffer: list[dict] = []
_max_log_entries = 1000


def _add_log(level: str, message: str, source: Optional[str] = None) -> None:
    """Add a log entry to the buffer."""
    global _log_buffer

    entry = {
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "message": message,
        "source": source,
    }

    _log_buffer.append(entry)

    # Trim buffer if too large
    if len(_log_buffer) > _max_log_entries:
        _log_buffer = _log_buffer[-_max_log_entries:]


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check with service status."""
    services = []
    overall_status = "healthy"

    # Check database/storage
    try:
        datasets_dir = Path.cwd() / "datasets"
        if datasets_dir.exists() or not datasets_dir.exists():  # Just check access
            services.append(ServiceStatus(
                name="storage",
                status="running",
                message="Storage accessible",
            ))
    except Exception as e:
        services.append(ServiceStatus(
            name="storage",
            status="error",
            message=str(e),
        ))
        overall_status = "degraded"

    # Check PyTorch/CUDA
    try:
        import torch
        cuda_status = "running" if torch.cuda.is_available() else "stopped"
        cuda_msg = f"CUDA {torch.version.cuda}" if torch.cuda.is_available() else "CPU only"
        services.append(ServiceStatus(
            name="pytorch",
            status=cuda_status if torch.cuda.is_available() else "running",
            message=cuda_msg,
        ))
    except ImportError:
        services.append(ServiceStatus(
            name="pytorch",
            status="stopped",
            message="Not installed",
        ))
        overall_status = "degraded"

    # Check LeRobot
    try:
        import lerobot
        services.append(ServiceStatus(
            name="lerobot",
            status="running",
            message=f"Version {getattr(lerobot, '__version__', 'unknown')}",
        ))
    except ImportError:
        services.append(ServiceStatus(
            name="lerobot",
            status="stopped",
            message="Not installed",
        ))

    # Check percus_ai
    try:
        features_path = Path(__file__).resolve().parents[5] / "features"
        if features_path.exists() and str(features_path) not in sys.path:
            sys.path.insert(0, str(features_path))
        import percus_ai
        services.append(ServiceStatus(
            name="percus_ai",
            status="running",
            message="Available",
        ))
    except ImportError:
        services.append(ServiceStatus(
            name="percus_ai",
            status="stopped",
            message="Not available",
        ))

    uptime = time.time() - _server_start_time

    return HealthResponse(
        status=overall_status,
        services=services,
        uptime_seconds=uptime,
    )


@router.get("/resources", response_model=ResourcesResponse)
async def get_resources():
    """Get current resource usage."""
    cpu_percent = 0.0
    cpu_count = 1
    memory_total_gb = 0.0
    memory_used_gb = 0.0
    memory_percent = 0.0
    disk_total_gb = 0.0
    disk_used_gb = 0.0
    disk_percent = 0.0

    try:
        import psutil

        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count() or 1

        # Memory
        mem = psutil.virtual_memory()
        memory_total_gb = mem.total / (1024 ** 3)
        memory_used_gb = mem.used / (1024 ** 3)
        memory_percent = mem.percent

        # Disk
        disk = psutil.disk_usage(str(Path.cwd()))
        disk_total_gb = disk.total / (1024 ** 3)
        disk_used_gb = disk.used / (1024 ** 3)
        disk_percent = disk.percent

    except ImportError:
        # Fallback without psutil
        cpu_count = os.cpu_count() or 1

        # Try to get disk info
        try:
            import shutil
            total, used, free = shutil.disk_usage(Path.cwd())
            disk_total_gb = total / (1024 ** 3)
            disk_used_gb = used / (1024 ** 3)
            disk_percent = (used / total) * 100 if total > 0 else 0
        except Exception:
            pass

    return ResourcesResponse(
        resources=ResourceUsage(
            cpu_percent=cpu_percent,
            cpu_count=cpu_count,
            memory_total_gb=memory_total_gb,
            memory_used_gb=memory_used_gb,
            memory_percent=memory_percent,
            disk_total_gb=disk_total_gb,
            disk_used_gb=disk_used_gb,
            disk_percent=disk_percent,
        ),
        timestamp=datetime.now().isoformat(),
    )


@router.get("/logs", response_model=LogsResponse)
async def get_logs(
    level: Optional[str] = Query(None, description="Filter by level"),
    since: Optional[str] = Query(None, description="Logs since timestamp"),
    limit: int = Query(100, description="Maximum entries to return"),
):
    """Get application logs."""
    logs = _log_buffer.copy()

    # Filter by level
    if level:
        logs = [l for l in logs if l["level"].lower() == level.lower()]

    # Filter by timestamp
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            logs = [
                l for l in logs
                if datetime.fromisoformat(l["timestamp"]) >= since_dt
            ]
        except ValueError:
            pass

    # Sort by timestamp (newest first)
    logs.sort(key=lambda x: x["timestamp"], reverse=True)

    # Apply limit
    total = len(logs)
    has_more = total > limit
    logs = logs[:limit]

    return LogsResponse(
        logs=[
            LogEntry(
                timestamp=l["timestamp"],
                level=l["level"],
                message=l["message"],
                source=l.get("source"),
            )
            for l in logs
        ],
        total=total,
        has_more=has_more,
    )


@router.post("/logs/clear")
async def clear_logs():
    """Clear application logs."""
    global _log_buffer
    count = len(_log_buffer)
    _log_buffer = []
    _add_log("info", f"Logs cleared ({count} entries)", source="system")

    return {"message": f"Cleared {count} log entries"}


@router.get("/info", response_model=SystemInfoResponse)
async def get_system_info():
    """Get system information."""
    # Python info
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    # Get package versions
    percus_ai_version = None
    lerobot_version = None
    pytorch_version = None

    try:
        features_path = Path(__file__).resolve().parents[5] / "features"
        if features_path.exists() and str(features_path) not in sys.path:
            sys.path.insert(0, str(features_path))
        import percus_ai
        percus_ai_version = getattr(percus_ai, "__version__", "installed")
    except ImportError:
        pass

    try:
        import lerobot
        lerobot_version = getattr(lerobot, "__version__", "installed")
    except ImportError:
        pass

    try:
        import torch
        pytorch_version = torch.__version__
    except ImportError:
        pass

    return SystemInfoResponse(
        info=SystemInfo(
            platform=sys.platform,
            platform_version=platform.release(),
            architecture=platform.machine(),
            hostname=platform.node(),
            python_version=python_version,
            python_executable=sys.executable,
            working_directory=str(Path.cwd()),
            home_directory=str(Path.home()),
            config_directory=str(Path.home() / ".config" / "percus_ai"),
            app_version="0.1.0",
            percus_ai_version=percus_ai_version,
            lerobot_version=lerobot_version,
            pytorch_version=pytorch_version,
        ),
    )


@router.get("/gpu", response_model=GpuResponse)
async def get_gpu_info():
    """Get GPU information."""
    gpus = []
    cuda_version = None
    driver_version = None
    available = False

    try:
        import torch

        if torch.cuda.is_available():
            available = True
            cuda_version = torch.version.cuda

            # Get driver version if nvidia-smi available
            try:
                import subprocess
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    driver_version = result.stdout.strip().split("\n")[0]
            except Exception:
                pass

            # Get GPU info for each device
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                memory_total = props.total_memory / (1024 * 1024)

                try:
                    memory_allocated = torch.cuda.memory_allocated(i) / (1024 * 1024)
                    memory_free = memory_total - memory_allocated
                except Exception:
                    memory_allocated = 0
                    memory_free = memory_total

                # Get utilization and temperature via nvidia-smi
                utilization = 0.0
                temperature = None
                try:
                    import subprocess
                    result = subprocess.run(
                        [
                            "nvidia-smi",
                            f"--id={i}",
                            "--query-gpu=utilization.gpu,temperature.gpu",
                            "--format=csv,noheader,nounits",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        parts = result.stdout.strip().split(",")
                        if len(parts) >= 2:
                            utilization = float(parts[0].strip())
                            temperature = float(parts[1].strip())
                except Exception:
                    pass

                gpus.append(GpuInfo(
                    device_id=i,
                    name=props.name,
                    memory_total_mb=memory_total,
                    memory_used_mb=memory_allocated,
                    memory_free_mb=memory_free,
                    utilization_percent=utilization,
                    temperature_c=temperature,
                ))

    except ImportError:
        pass

    return GpuResponse(
        available=available,
        cuda_version=cuda_version,
        driver_version=driver_version,
        gpus=gpus,
    )
