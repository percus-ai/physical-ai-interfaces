"""Runtime helpers for controlling the lerobot-ros2 Docker stack.

Manages the lifecycle of containers defined in docker-compose.ros2.yml:
lerobot-ros2, rosbridge, zenoh-router, otel-collector.
"""

from __future__ import annotations

import json
import logging
import subprocess

from interfaces_backend.utils.docker_compose import build_compose_command, get_lerobot_compose_file

logger = logging.getLogger(__name__)

_LEROBOT_SERVICES = ["lerobot-ros2", "rosbridge", "zenoh-router", "otel-collector"]


class LerobotCommandError(RuntimeError):
    """Raised when a lerobot stack command fails."""


def start_lerobot(*, strict: bool = True) -> subprocess.CompletedProcess[str]:
    """Start the lerobot-ros2 Docker stack (``docker compose up -d``)."""
    compose_file = get_lerobot_compose_file()
    if not compose_file.exists():
        message = f"Compose file not found: {compose_file}"
        if strict:
            raise LerobotCommandError(message)
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=message)
    compose_cmd = build_compose_command(compose_file)
    result = subprocess.run(
        [*compose_cmd, "up", "-d", *_LEROBOT_SERVICES],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and strict:
        raise LerobotCommandError(f"lerobot stack start failed: {result.stderr.strip()}")
    return result


def stop_lerobot(*, strict: bool = True) -> subprocess.CompletedProcess[str]:
    """Stop the lerobot-ros2 Docker stack (``docker compose down``)."""
    compose_file = get_lerobot_compose_file()
    if not compose_file.exists():
        if strict:
            raise LerobotCommandError(f"Compose file not found: {compose_file}")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    compose_cmd = build_compose_command(compose_file)
    result = subprocess.run(
        [*compose_cmd, "down"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and strict:
        raise LerobotCommandError(f"lerobot stack stop failed: {result.stderr.strip()}")
    return result


def get_lerobot_service_state(service: str) -> dict:
    """Return docker compose service state as a dict (empty on failure)."""
    compose_file = get_lerobot_compose_file()
    if not compose_file.exists():
        return {}
    compose_cmd = build_compose_command(compose_file)
    result = subprocess.run(
        [*compose_cmd, "ps", "--format", "json", service],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout:
        return {}
    try:
        data = json.loads(result.stdout)
    except Exception:
        return {}
    if isinstance(data, list):
        return data[0] if data else {}
    if isinstance(data, dict):
        return data
    return {}


def stop_lerobot_on_backend_startup(logger: logging.Logger | None = None) -> None:
    """Best-effort shutdown of stale lerobot containers on backend startup."""
    active_logger = logger or logging.getLogger(__name__)
    result = stop_lerobot(strict=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit code={result.returncode}"
        active_logger.warning("lerobot startup cleanup failed: %s", detail)
