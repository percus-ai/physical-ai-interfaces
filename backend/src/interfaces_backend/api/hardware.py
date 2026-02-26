"""Hardware detection API."""

import platform as py_platform
from pathlib import Path
from typing import List

import cv2
from serial.tools import list_ports

from fastapi import APIRouter, Query

from interfaces_backend.models.hardware import (
    CameraInfo,
    CamerasResponse,
    HardwareStatusResponse,
    SerialPortInfo,
    SerialPortsResponse,
)

router = APIRouter(prefix="/api/hardware", tags=["hardware"])


def _detect_cameras(max_cameras: int = 10) -> List[CameraInfo]:
    """Detect cameras using OpenCV."""
    cameras = []

    for camera_id in range(max_cameras):
        try:
            cap = cv2.VideoCapture(camera_id)

            if cap.isOpened():
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                backend_name = cap.getBackendName()

                # Try to read a frame
                ret, _ = cap.read()
                is_working = ret

                cameras.append(
                    CameraInfo(
                        id=camera_id,
                        name=f"Camera {camera_id}",
                        width=width,
                        height=height,
                        fps=fps,
                        backend=backend_name,
                        is_working=is_working,
                    )
                )

                cap.release()
            else:
                cap.release()
                # Stop scanning if we hit a non-existent camera (after ID 0)
                if camera_id > 0:
                    break
        except Exception:
            break

    return cameras


def _detect_serial_ports() -> List[SerialPortInfo]:
    """Detect serial ports using pyserial."""
    ports = []
    system = py_platform.system()

    for port in list_ports.comports():
        if not port.device:
            continue

        device_path = port.device

        # On macOS, prefer /dev/tty.* over /dev/cu.* for bidirectional communication
        if system == "Darwin" and device_path.startswith("/dev/cu."):
            tty_path = device_path.replace("/dev/cu.", "/dev/tty.")
            if Path(tty_path).exists():
                device_path = tty_path

        ports.append(
            SerialPortInfo(
                port=device_path,
                description=getattr(port, "description", None),
                manufacturer=getattr(port, "manufacturer", None),
                product=getattr(port, "product", None),
                serial_number=getattr(port, "serial_number", None),
                vid=f"{port.vid:04x}" if getattr(port, "vid", None) else None,
                pid=f"{port.pid:04x}" if getattr(port, "pid", None) else None,
            )
        )

    return ports


@router.get("", response_model=HardwareStatusResponse)
async def get_hardware_status():
    """Get overall hardware status.

    Returns availability of detection libraries and counts of detected devices.
    """
    opencv_available = True
    pyserial_available = True

    # Count devices
    cameras_count = 0
    ports_count = 0

    if opencv_available:
        cameras = _detect_cameras(max_cameras=5)
        cameras_count = len(cameras)

    if pyserial_available:
        ports = _detect_serial_ports()
        ports_count = len(ports)

    return HardwareStatusResponse(
        opencv_available=opencv_available,
        pyserial_available=pyserial_available,
        cameras_detected=cameras_count,
        ports_detected=ports_count,
    )


@router.get("/cameras", response_model=CamerasResponse)
async def get_cameras(
    max_scan: int = Query(10, ge=1, le=20, description="Maximum camera IDs to scan"),
):
    """Detect connected cameras.

    Scans OpenCV camera IDs to find available cameras.
    """
    cameras = _detect_cameras(max_cameras=max_scan)
    return CamerasResponse(
        cameras=cameras,
        scan_count=max_scan,
    )


@router.get("/serial-ports", response_model=SerialPortsResponse)
async def get_serial_ports():
    """Detect connected serial ports.

    Lists available serial ports for robot arm connections.
    """
    ports = _detect_serial_ports()
    return SerialPortsResponse(ports=ports)
