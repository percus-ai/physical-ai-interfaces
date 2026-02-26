"""System API router."""

import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query
import psutil

from interfaces_backend.utils.torch_info import get_torch_info
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
from percus_ai.storage import get_datasets_dir, get_features_path, get_storage_root

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
        datasets_dir = get_datasets_dir()
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

    # Check PyTorch/CUDA (via subprocess to avoid numpy conflicts)
    torch_info = get_torch_info()
    if torch_info.get("torch_version"):
        cuda_status = "running" if torch_info.get("cuda_available") else "stopped"
        cuda_msg = f"CUDA {torch_info.get('cuda_version')}" if torch_info.get("cuda_available") else "CPU only"
        services.append(ServiceStatus(
            name="pytorch",
            status=cuda_status if torch_info.get("cuda_available") else "running",
            message=cuda_msg,
        ))
    else:
        services.append(ServiceStatus(
            name="pytorch",
            status="stopped",
            message="Not installed",
        ))
        overall_status = "degraded"

    # Check LeRobot
    import lerobot
    services.append(ServiceStatus(
        name="lerobot",
        status="running",
        message=f"Version {getattr(lerobot, '__version__', 'unknown')}",
    ))

    # Check percus_ai
    features_path = get_features_path()
    if features_path.exists() and str(features_path) not in sys.path:
        sys.path.insert(0, str(features_path))
    import percus_ai
    services.append(ServiceStatus(
        name="percus_ai",
        status="running",
        message="Available",
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

    # CPU
    cpu_percent = psutil.cpu_percent(interval=0.1)
    cpu_count = psutil.cpu_count() or 1

    # Memory
    mem = psutil.virtual_memory()
    memory_total_gb = mem.total / (1024 ** 3)
    memory_used_gb = mem.used / (1024 ** 3)
    memory_percent = mem.percent

    # Disk
    disk = psutil.disk_usage(str(get_storage_root()))
    disk_total_gb = disk.total / (1024 ** 3)
    disk_used_gb = disk.used / (1024 ** 3)
    disk_percent = disk.percent

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

    features_path = get_features_path()
    if features_path.exists() and str(features_path) not in sys.path:
        sys.path.insert(0, str(features_path))
    import percus_ai
    percus_ai_version = getattr(percus_ai, "__version__", "installed")

    import lerobot
    lerobot_version = getattr(lerobot, "__version__", "installed")

    # Get PyTorch version via subprocess
    torch_info = get_torch_info()
    pytorch_version = torch_info.get("torch_version")

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
    """Get GPU information using nvidia-smi (no torch import needed)."""
    gpus = []
    cuda_version = None
    driver_version = None
    available = False

    # Get CUDA version from torch info (via subprocess)
    from interfaces_backend.utils.torch_info import get_torch_info
    torch_info = get_torch_info()
    if torch_info.get("cuda_available"):
        available = True
        cuda_version = torch_info.get("cuda_version")

    # Get GPU info via nvidia-smi
    try:
        # Get driver version
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            driver_version = result.stdout.strip().split("\n")[0]
            available = True

        # Get detailed GPU info
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 7:
                    try:
                        def parse_float(val: str) -> float | None:
                            if val == "[N/A]" or val == "N/A":
                                return None
                            return float(val)

                        gpus.append(GpuInfo(
                            device_id=int(parts[0]),
                            name=parts[1],
                            memory_total_mb=parse_float(parts[2]),
                            memory_used_mb=parse_float(parts[3]),
                            memory_free_mb=parse_float(parts[4]),
                            utilization_percent=parse_float(parts[5]) or 0.0,
                            temperature_c=parse_float(parts[6]),
                        ))
                    except (ValueError, IndexError):
                        pass
    except Exception:
        pass

    return GpuResponse(
        available=available,
        cuda_version=cuda_version,
        driver_version=driver_version,
        gpus=gpus,
    )
