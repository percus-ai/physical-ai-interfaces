"""Docker compose path and command helpers."""

from __future__ import annotations

import os
import platform
from pathlib import Path

from percus_ai.storage.paths import get_project_root

_DEFAULT_VLABOR_IMAGE_REPO = "ghcr.io/takatronix/vlabor-local"


def get_lerobot_compose_file() -> Path:
    return get_project_root() / "docker-compose.ros2.yml"


def get_vlabor_compose_file() -> Path:
    return get_project_root() / "docker" / "vlabor" / "compose.yml"


def _detect_vlabor_arch_tag() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "linux-amd64"
    if machine in ("aarch64", "arm64"):
        return "linux-arm64"
    return "latest"


def _parse_env_keys(lines: list[str]) -> set[str]:
    keys: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def get_vlabor_env_file() -> Path:
    """Return compose env file for vlabor.

    When docker/vlabor/.env is absent (or does not define VLABOR_IMAGE),
    generate a resolved env file that picks architecture-specific GHCR image:
    - x86_64/amd64 -> ghcr.io/takatronix/vlabor-local:linux-amd64
    - arm64/aarch64 -> ghcr.io/takatronix/vlabor-local:linux-arm64
    """
    vlabor_dir = get_project_root() / "docker" / "vlabor"
    base_env = vlabor_dir / ".env"
    resolved_env = vlabor_dir / ".env.resolved"

    lines: list[str] = []
    if base_env.exists():
        lines = base_env.read_text(encoding="utf-8").splitlines()

    keys = _parse_env_keys(lines)
    if "VLABOR_IMAGE" not in keys and "VLABOR_IMAGE" not in os.environ:
        tag = _detect_vlabor_arch_tag()
        lines.append(f"VLABOR_IMAGE={_DEFAULT_VLABOR_IMAGE_REPO}:{tag}")

    if lines:
        resolved_env.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return resolved_env

    return base_env


def build_compose_command(compose_file: Path, env_file: Path | None = None) -> list[str]:
    cmd = ["docker", "compose", "-f", str(compose_file)]
    if env_file and env_file.exists():
        cmd.extend(["--env-file", str(env_file)])
    return cmd
