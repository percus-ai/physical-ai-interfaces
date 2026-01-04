"""System API models."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ServiceStatus(BaseModel):
    """Status of a system service."""

    name: str = Field(..., description="Service name")
    status: str = Field(..., description="Status: running, stopped, error")
    message: Optional[str] = Field(None, description="Status message")


class HealthResponse(BaseModel):
    """Response for health check endpoint."""

    status: str = Field(..., description="Overall status: healthy, degraded, unhealthy")
    services: List[ServiceStatus]
    uptime_seconds: float = Field(0.0, description="Server uptime in seconds")


class ResourceUsage(BaseModel):
    """Resource usage information."""

    cpu_percent: float = Field(0.0, description="CPU usage percentage")
    cpu_count: int = Field(1, description="Number of CPU cores")
    memory_total_gb: float = Field(0.0, description="Total memory in GB")
    memory_used_gb: float = Field(0.0, description="Used memory in GB")
    memory_percent: float = Field(0.0, description="Memory usage percentage")
    disk_total_gb: float = Field(0.0, description="Total disk space in GB")
    disk_used_gb: float = Field(0.0, description="Used disk space in GB")
    disk_percent: float = Field(0.0, description="Disk usage percentage")


class ResourcesResponse(BaseModel):
    """Response for resources endpoint."""

    resources: ResourceUsage
    timestamp: str = Field(..., description="Measurement timestamp")


class LogEntry(BaseModel):
    """Log entry."""

    timestamp: str = Field(..., description="Log timestamp")
    level: str = Field(..., description="Log level: debug, info, warning, error")
    message: str = Field(..., description="Log message")
    source: Optional[str] = Field(None, description="Log source/module")


class LogsResponse(BaseModel):
    """Response for logs endpoint."""

    logs: List[LogEntry]
    total: int = Field(0, description="Total log entries")
    has_more: bool = Field(False, description="More logs available")


class SystemInfo(BaseModel):
    """System information."""

    # Platform
    platform: str = Field(..., description="Platform: linux, darwin, windows")
    platform_version: str = Field("", description="Platform version")
    architecture: str = Field("", description="CPU architecture")
    hostname: str = Field("", description="Hostname")

    # Python
    python_version: str = Field(..., description="Python version")
    python_executable: str = Field("", description="Python executable path")

    # Paths
    working_directory: str = Field("", description="Current working directory")
    home_directory: str = Field("", description="Home directory")
    config_directory: str = Field("", description="Config directory")

    # Versions
    app_version: str = Field("0.1.0", description="Application version")
    percus_ai_version: Optional[str] = Field(None, description="percus_ai version")
    lerobot_version: Optional[str] = Field(None, description="LeRobot version")
    pytorch_version: Optional[str] = Field(None, description="PyTorch version")


class SystemInfoResponse(BaseModel):
    """Response for system info endpoint."""

    info: SystemInfo


class GpuInfo(BaseModel):
    """GPU information."""

    device_id: int = Field(..., description="GPU device ID")
    name: str = Field(..., description="GPU name")
    memory_total_mb: float = Field(0.0, description="Total memory in MB")
    memory_used_mb: float = Field(0.0, description="Used memory in MB")
    memory_free_mb: float = Field(0.0, description="Free memory in MB")
    utilization_percent: float = Field(0.0, description="GPU utilization percentage")
    temperature_c: Optional[float] = Field(None, description="Temperature in Celsius")


class GpuResponse(BaseModel):
    """Response for GPU endpoint."""

    available: bool = Field(..., description="GPU is available")
    cuda_version: Optional[str] = Field(None, description="CUDA version")
    driver_version: Optional[str] = Field(None, description="Driver version")
    gpus: List[GpuInfo]
