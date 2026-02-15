"""Bridge to the lerobot_session_recorder HTTP API (port 8082).

Consolidates recorder communication previously duplicated in
recording.py and inference.py.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

from fastapi import HTTPException

from interfaces_backend.services.lerobot_runtime import (
    LerobotCommandError,
    get_lerobot_service_state,
    start_lerobot,
    stop_lerobot,
)
from interfaces_backend.services.vlabor_profiles import extract_camera_specs
from percus_ai.observability import ArmId, CommOverheadReporter, PointId, resolve_ids

logger = logging.getLogger(__name__)

_RECORDER_URL = os.environ.get("LEROBOT_RECORDER_URL", "http://127.0.0.1:8082")
_COMM_REPORTER = CommOverheadReporter("backend")


class RecorderBridge:
    """HTTP client for the lerobot_session_recorder service."""

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url or _RECORDER_URL

    # -- public API -----------------------------------------------------------

    def start(self, payload: dict) -> dict:
        return self._call("/api/session/start", payload)

    def stop(self, *, save_current: bool = True) -> dict:
        return self._call("/api/session/stop", {"save_current": save_current})

    def pause(self) -> dict:
        return self._call("/api/session/pause", {})

    def resume(self) -> dict:
        return self._call("/api/session/resume", {})

    def status(self) -> dict:
        return self._call("/api/session/status")

    def redo_episode(self) -> dict:
        return self._call("/api/episode/redo", {})

    def cancel_episode(self) -> dict:
        return self._call("/api/episode/cancel", {})

    # -- infrastructure -------------------------------------------------------

    def ensure_running(self) -> None:
        """Make sure the recorder is reachable, starting Docker if needed."""
        try:
            self._call("/api/session/status")
            return
        except HTTPException as exc:
            if exc.status_code != 503:
                raise

        try:
            start_lerobot(strict=True)
        except LerobotCommandError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        service_state = get_lerobot_service_state("lerobot-ros2")
        if service_state:
            state_raw = (service_state.get("State") or "").lower()
            if "running" not in state_raw:
                detail = service_state.get("Status") or service_state.get("State") or "unknown"
                raise HTTPException(status_code=503, detail=f"lerobot-ros2 not running: {detail}")

        deadline = time.time() + 60
        last_error: HTTPException | None = None
        while time.time() < deadline:
            try:
                self._call("/api/session/status")
                return
            except HTTPException as exc:
                last_error = exc
                if exc.status_code != 503:
                    raise
            time.sleep(1)

        detail = "Recorder unreachable after start"
        if last_error and last_error.detail:
            detail = f"{detail}: {last_error.detail}"
        raise HTTPException(status_code=503, detail=detail)

    def start_docker(self) -> None:
        """Start the lerobot Docker stack."""
        try:
            start_lerobot(strict=True)
        except LerobotCommandError as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to start lerobot stack: {exc}"
            ) from exc

    def stop_docker(self) -> None:
        """Stop the lerobot Docker stack (best-effort)."""
        result = stop_lerobot(strict=False)
        if result.returncode != 0:
            logger.warning("lerobot stack stop failed: %s", result.stderr.strip())

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def build_cameras(profile_snapshot: dict) -> list[dict]:
        """Build the camera list for the recorder from a profile snapshot."""
        cameras: list[dict] = []
        for spec in extract_camera_specs(profile_snapshot):
            if not bool(spec.get("enabled", True)):
                continue
            name = str(spec.get("name") or "").strip()
            topic = str(spec.get("topic") or "").strip()
            if name and topic:
                cameras.append({"name": name, "topic": topic})
        return cameras

    # -- internal HTTP --------------------------------------------------------

    def _call(self, path: str, payload: dict | None = None) -> dict:
        url = f"{self._base_url}{path}"
        data = None
        headers: dict[str, str] = {}
        method = "GET"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
            method = "POST"

        session_hint = None
        if isinstance(payload, dict):
            session_hint = (
                str(payload.get("dataset_id") or payload.get("session_id") or "").strip()
                or None
            )
        session_id, trace_id = resolve_ids(session_hint, None)
        timer = _COMM_REPORTER.timed(
            point_id=PointId.CP_02,
            session_id=session_id,
            trace_id=trace_id,
            arm=ArmId.NONE,
            payload_bytes=len(data) if data is not None else 0,
            tags={"method": method, "path": path},
        )

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body_bytes = resp.read()
                timer.success(
                    extra_tags={"status_code": resp.status, "response_bytes": len(body_bytes)}
                )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8") if exc.fp else str(exc)
            timer.error(detail, extra_tags={"status_code": exc.code})
            raise HTTPException(status_code=exc.code, detail=detail) from exc
        except urllib.error.URLError as exc:
            timer.error(str(exc), extra_tags={"status_code": 503})
            raise HTTPException(status_code=503, detail=f"Recorder unreachable: {exc}") from exc

        body = body_bytes.decode("utf-8")
        try:
            return json.loads(body) if body else {}
        except json.JSONDecodeError:
            return {"raw": body}


# -- singleton ----------------------------------------------------------------

_bridge: RecorderBridge | None = None


def get_recorder_bridge() -> RecorderBridge:
    global _bridge
    if _bridge is None:
        _bridge = RecorderBridge()
    return _bridge
