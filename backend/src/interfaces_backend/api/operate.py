"""Operate status API."""

from __future__ import annotations

import json
import os
import socket
import subprocess
from typing import Optional

from fastapi import APIRouter

from interfaces_backend.models.operate import OperateServiceStatus, OperateStatusResponse
from interfaces_backend.utils.torch_info import get_torch_info
from percus_ai.storage.paths import get_project_root

router = APIRouter(prefix="/api/operate", tags=["operate"])

_ZMQ_ENDPOINT = os.environ.get(
    "INFERENCE_BRIDGE_ZMQ_ENDPOINT",
    os.environ.get("RUNNER_BRIDGE_ZMQ_ENDPOINT", "tcp://127.0.0.1:5556"),
)


def _check_tcp(host: str, port: int, timeout: float = 0.6) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "ok"
    except Exception as exc:  # noqa: BLE001 - surfaced to UI
        return False, str(exc)


def _parse_tcp_endpoint(endpoint: str) -> Optional[tuple[str, int]]:
    if not endpoint:
        return None
    raw = endpoint
    if raw.startswith("tcp://"):
        raw = raw[len("tcp://") :]
    raw = raw.split("/")[0]
    if ":" not in raw:
        return None
    host, port_str = raw.rsplit(":", 1)
    host = host.strip() or "127.0.0.1"
    if host in ("0.0.0.0", "*"):
        host = "127.0.0.1"
    try:
        port = int(port_str)
    except ValueError:
        return None
    return host, port


def _get_compose_status(service: str) -> OperateServiceStatus:
    repo_root = get_project_root()
    compose_file = repo_root / "docker-compose.ros2.yml"
    if not compose_file.exists():
        return OperateServiceStatus(name=service, status="unknown", message="docker-compose.ros2.yml not found")

    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "ps", "--format", "json", service],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return OperateServiceStatus(name=service, status="unknown", message=result.stderr.strip() or "compose error")

    try:
        data = json.loads(result.stdout)
    except Exception:
        return OperateServiceStatus(name=service, status="unknown", message="compose parse failed")

    entry = None
    if isinstance(data, list):
        entry = data[0] if data else None
    elif isinstance(data, dict):
        entry = data

    if not entry:
        return OperateServiceStatus(name=service, status="stopped", message="service not running")

    state_raw = (entry.get("State") or "").lower()
    if "running" in state_raw:
        status = "running"
    elif "restarting" in state_raw:
        status = "degraded"
    elif "exited" in state_raw or "stopped" in state_raw:
        status = "stopped"
    else:
        status = "unknown"

    return OperateServiceStatus(
        name=service,
        status=status,
        message=entry.get("Status") or entry.get("State") or "",
        details={
            "state": entry.get("State"),
            "running_for": entry.get("RunningFor"),
            "container_id": entry.get("ID"),
        },
    )


def _build_network_status() -> OperateServiceStatus:
    zenoh_ok, zenoh_msg = _check_tcp("127.0.0.1", 7447)
    rosbridge_ok, rosbridge_msg = _check_tcp("127.0.0.1", 9090)

    zmq_host_port = _parse_tcp_endpoint(_ZMQ_ENDPOINT)
    if zmq_host_port:
        zmq_ok, zmq_msg = _check_tcp(zmq_host_port[0], zmq_host_port[1])
    else:
        zmq_ok = False
        zmq_msg = "invalid endpoint"

    details = {
        "zenoh": {"status": "running" if zenoh_ok else "stopped", "message": zenoh_msg},
        "rosbridge": {"status": "running" if rosbridge_ok else "stopped", "message": rosbridge_msg},
        "zmq": {"status": "running" if zmq_ok else "stopped", "message": zmq_msg, "endpoint": _ZMQ_ENDPOINT},
    }

    if zenoh_ok and rosbridge_ok and zmq_ok:
        status = "running"
        message = "all links reachable"
    elif zenoh_ok or rosbridge_ok or zmq_ok:
        status = "degraded"
        message = "partial connectivity"
    else:
        status = "stopped"
        message = "no connectivity"

    return OperateServiceStatus(name="network", status=status, message=message, details=details)


def _build_driver_status() -> OperateServiceStatus:
    info = get_torch_info()

    torch_version = info.get("torch_version")
    cuda_available = bool(info.get("cuda_available"))
    cuda_version = info.get("cuda_version")
    gpu_name = info.get("gpu_name")
    error = info.get("error")

    if not torch_version:
        status = "stopped"
        message = "PyTorch not installed"
    elif cuda_available:
        status = "running"
        message = f"CUDA {cuda_version or 'available'}"
    else:
        status = "degraded"
        message = "CUDA unavailable (CPU only)"

    if error:
        status = "error"
        message = error

    return OperateServiceStatus(
        name="driver",
        status=status,
        message=message,
        details={
            "torch_version": torch_version,
            "cuda_available": cuda_available,
            "cuda_version": cuda_version,
            "gpu_name": gpu_name,
        },
    )


@router.get("/status", response_model=OperateStatusResponse)
async def get_operate_status():
    backend = OperateServiceStatus(name="backend", status="running", message="ok")
    vlabor = _get_compose_status("vlabor")
    lerobot = _get_compose_status("lerobot-ros2")
    network = _build_network_status()
    driver = _build_driver_status()

    return OperateStatusResponse(
        backend=backend,
        vlabor=vlabor,
        lerobot=lerobot,
        network=network,
        driver=driver,
    )
