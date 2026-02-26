"""Runtime helpers for controlling VLAbor docker scripts."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from collections.abc import Generator
from pathlib import Path
from typing import Sequence

from percus_ai.storage.paths import get_project_root

_DEFAULT_SCRIPT_TIMEOUT_S = int(os.environ.get("VLABOR_SCRIPT_TIMEOUT_S", "120"))
_VLABOR_LOCK = threading.Lock()


class VlaborCommandError(RuntimeError):
    """Raised when a VLAbor control script fails."""


def _failed_result(cmd: list[str], message: str, exit_code: int = 1) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=cmd, returncode=exit_code, stdout="", stderr=message)


def _vlabor_script_path(script_name: str) -> Path:
    return get_project_root() / "docker" / "vlabor" / script_name


def _run_vlabor_script(
    script_name: str,
    args: Sequence[str] | None = None,
    *,
    strict: bool = True,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    script_path = _vlabor_script_path(script_name)
    cmd = [str(script_path), *(list(args) if args else [])]

    if not script_path.exists():
        message = f"VLAbor script not found: {script_path}"
        if strict:
            raise VlaborCommandError(message)
        return _failed_result(cmd, message)

    if not os.access(script_path, os.X_OK):
        message = f"VLAbor script is not executable: {script_path}"
        if strict:
            raise VlaborCommandError(message)
        return _failed_result(cmd, message)

    try:
        with _VLABOR_LOCK:
            result = subprocess.run(
                cmd,
                cwd=get_project_root(),
                capture_output=True,
                text=True,
                timeout=timeout or _DEFAULT_SCRIPT_TIMEOUT_S,
            )
    except subprocess.TimeoutExpired as exc:
        message = f"VLAbor script timeout ({script_name}): {exc}"
        if strict:
            raise VlaborCommandError(message) from exc
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else message
        return subprocess.CompletedProcess(args=cmd, returncode=124, stdout=stdout, stderr=stderr)

    if result.returncode != 0 and strict:
        detail = (result.stderr or result.stdout).strip() or f"exit code={result.returncode}"
        raise VlaborCommandError(f"VLAbor script failed ({script_name}): {detail}")

    return result


def start_vlabor(
    *,
    profile: str | None = None,
    domain_id: int | None = None,
    dev_mode: bool = False,
    strict: bool = True,
) -> subprocess.CompletedProcess[str]:
    args: list[str] = []
    if profile:
        profile_name = profile.strip()
        if profile_name:
            args.append(profile_name)
    if domain_id is not None:
        args.extend(["--domain-id", str(domain_id)])
    if dev_mode:
        args.append("--dev")
    return _run_vlabor_script("up", args, strict=strict)


def stop_vlabor(*, strict: bool = True) -> subprocess.CompletedProcess[str]:
    return _run_vlabor_script("down", strict=strict)


def restart_vlabor(
    *,
    profile: str | None = None,
    domain_id: int | None = None,
    dev_mode: bool = False,
    strict: bool = True,
) -> subprocess.CompletedProcess[str]:
    args: list[str] = []
    if profile:
        profile_name = profile.strip()
        if profile_name:
            args.append(profile_name)
    if domain_id is not None:
        args.extend(["--domain-id", str(domain_id)])
    if dev_mode:
        args.append("--dev")
    return _run_vlabor_script("restart", args, strict=strict, timeout=300)


def stream_vlabor_script(
    script_name: str,
    args: Sequence[str] | None = None,
    *,
    timeout: int | None = None,
) -> Generator[dict[str, str], None, None]:
    """Run a VLAbor script and yield output lines as they arrive.

    Yields dicts like:
      {"type": "log", "stream": "stdout", "line": "..."}
      {"type": "complete", "exit_code": 0}
      {"type": "error", "message": "..."}
    """
    script_path = _vlabor_script_path(script_name)
    cmd = [str(script_path), *(list(args) if args else [])]

    if not script_path.exists():
        yield {"type": "error", "message": f"VLAbor script not found: {script_path}"}
        return

    if not os.access(script_path, os.X_OK):
        yield {"type": "error", "message": f"VLAbor script is not executable: {script_path}"}
        return

    effective_timeout = timeout or _DEFAULT_SCRIPT_TIMEOUT_S

    with _VLABOR_LOCK:
        proc = subprocess.Popen(
            cmd,
            cwd=get_project_root(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                # Docker outputs progress bars using \r to overwrite the same line.
                # Keep only the final segment after the last \r.
                line = raw_line.rstrip("\n")
                if "\r" in line:
                    line = line.rsplit("\r", 1)[-1]
                line = line.strip()
                if line:
                    yield {"type": "log", "line": line}
            proc.wait(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            yield {"type": "error", "message": f"Timeout after {effective_timeout}s"}
            return

    exit_code = proc.returncode
    yield {"type": "complete", "exit_code": str(exit_code)}


def start_vlabor_on_backend_startup(
    profile: str | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Start VLAbor container on backend startup with the given profile."""
    active_logger = logger or logging.getLogger(__name__)
    if shutil.which("docker") is None:
        active_logger.warning("docker command not found; skip VLAbor startup")
        return

    result = start_vlabor(profile=profile, strict=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit code={result.returncode}"
        active_logger.warning("VLAbor startup failed: %s", detail)
    else:
        active_logger.info("VLAbor started with profile=%s", profile or "(default)")

