"""Hardware detection models."""

from typing import List, Optional

from pydantic import BaseModel, Field


class CameraInfo(BaseModel):
    """Camera information."""

    id: int = Field(..., description="OpenCV camera ID")
    name: str = Field("", description="Camera name/description")
    width: int = Field(0, description="Frame width")
    height: int = Field(0, description="Frame height")
    fps: float = Field(0.0, description="Frames per second")
    backend: str = Field("", description="OpenCV backend name")
    is_working: bool = Field(False, description="Can read frames")


class SerialPortInfo(BaseModel):
    """Serial port information."""

    port: str = Field(..., description="Port path (e.g., /dev/ttyUSB0)")
    description: Optional[str] = Field(None, description="Device description")
    manufacturer: Optional[str] = Field(None, description="Manufacturer")
    product: Optional[str] = Field(None, description="Product name")
    serial_number: Optional[str] = Field(None, description="Serial number")
    vid: Optional[str] = Field(None, description="Vendor ID (hex)")
    pid: Optional[str] = Field(None, description="Product ID (hex)")


class CamerasResponse(BaseModel):
    """Response for cameras endpoint."""

    cameras: List[CameraInfo]
    scan_count: int = Field(0, description="Number of IDs scanned")


class SerialPortsResponse(BaseModel):
    """Response for serial ports endpoint."""

    ports: List[SerialPortInfo]


class HardwareStatusResponse(BaseModel):
    """Response for hardware status endpoint."""

    opencv_available: bool = Field(False, description="OpenCV is installed")
    pyserial_available: bool = Field(False, description="pyserial is installed")
    cameras_detected: int = Field(0, description="Number of cameras detected")
    ports_detected: int = Field(0, description="Number of serial ports detected")
