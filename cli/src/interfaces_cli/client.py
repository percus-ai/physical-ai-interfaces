"""HTTP client for Backend API.

Auto-generated based on OpenAPI schema from /openapi.json
"""

import json
import os
import socket
import sys
from typing import Any, Callable, Dict, List, Optional

import httpx
import websocket

from interfaces_cli.auth_session import clear_session, load_session, save_session


def get_backend_url() -> str:
    """Get backend URL from environment or default."""
    return os.environ.get("PHI_BACKEND_URL", "http://localhost:8000")


class PhiClient:
    """HTTP client for Phi Backend API."""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 30.0):
        """Initialize client.

        Args:
            base_url: Backend URL (defaults to PHI_BACKEND_URL env or localhost:8000)
            timeout: Request timeout in seconds
        """
        self.base_url = base_url or get_backend_url()
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)
        self._session: Optional[Dict[str, Any]] = load_session()
        self._apply_session()

    def _apply_session(self) -> None:
        token = None
        if self._session:
            token = self._session.get("access_token")
        if token:
            self._client.headers["Authorization"] = f"Bearer {token}"
        else:
            self._client.headers.pop("Authorization", None)

    def _update_session(self, session: Optional[Dict[str, Any]]) -> None:
        self._session = session
        if session:
            save_session(session)
        else:
            clear_session()
        self._apply_session()

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # =========================================================================
    # Health
    # =========================================================================

    def health(self) -> Dict[str, Any]:
        """GET /health - Check backend health."""
        response = self._client.get("/health")
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # Auth
    # =========================================================================

    def auth_status(self) -> Dict[str, Any]:
        """GET /api/auth/status - Get auth status."""
        response = self._client.get("/api/auth/status")
        response.raise_for_status()
        return response.json()

    def auth_login(self, email: str, password: str) -> Dict[str, Any]:
        """POST /api/auth/login - Login."""
        response = self._client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
            headers={"X-Client": "cli"},
        )
        response.raise_for_status()
        data = response.json()
        access_token = data.get("access_token")
        if access_token:
            session = {
                "access_token": access_token,
                "refresh_token": data.get("refresh_token"),
                "expires_at": data.get("expires_at"),
                "session_expires_at": data.get("session_expires_at"),
                "user_id": data.get("user_id"),
            }
            self._update_session(session)
        return data

    def auth_logout(self) -> Dict[str, Any]:
        """POST /api/auth/logout - Logout."""
        response = self._client.post("/api/auth/logout")
        response.raise_for_status()
        data = response.json()
        self._update_session(None)
        return data

    # =========================================================================
    # Analytics
    # =========================================================================

    def get_analytics_overview(self) -> Dict[str, Any]:
        """GET /api/analytics/overview - Get overall statistics."""
        response = self._client.get("/api/analytics/overview")
        response.raise_for_status()
        return response.json()

    def get_analytics_profiles(self) -> Dict[str, Any]:
        """GET /api/analytics/profiles - Get per-profile statistics."""
        response = self._client.get("/api/analytics/profiles")
        response.raise_for_status()
        return response.json()

    def get_analytics_training(self) -> Dict[str, Any]:
        """GET /api/analytics/training - Get training job statistics."""
        response = self._client.get("/api/analytics/training")
        response.raise_for_status()
        return response.json()

    def get_analytics_storage(self) -> Dict[str, Any]:
        """GET /api/analytics/storage - Get storage usage breakdown."""
        response = self._client.get("/api/analytics/storage")
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # Config
    # =========================================================================

    def get_config(self) -> Dict[str, Any]:
        """GET /api/config - Get current configuration."""
        response = self._client.get("/api/config")
        response.raise_for_status()
        return response.json()


    # =========================================================================
    # Hardware (Devices)
    # =========================================================================

    def get_hardware_status(self) -> Dict[str, Any]:
        """GET /api/hardware - Get hardware status."""
        response = self._client.get("/api/hardware")
        response.raise_for_status()
        return response.json()

    def list_cameras(self) -> Dict[str, Any]:
        """GET /api/hardware/cameras - List detected cameras."""
        response = self._client.get("/api/hardware/cameras")
        response.raise_for_status()
        return response.json()

    def list_serial_ports(self) -> Dict[str, Any]:
        """GET /api/hardware/serial-ports - List detected serial ports."""
        response = self._client.get("/api/hardware/serial-ports")
        response.raise_for_status()
        return response.json()

    def list_devices(self) -> Dict[str, Any]:
        """Get combined device count (cameras + serial ports)."""
        status = self.get_hardware_status()
        total = status.get("cameras_detected", 0) + status.get("ports_detected", 0)
        return {"total": total, "status": status}

    def scan_devices(self) -> Dict[str, Any]:
        """Scan for all devices."""
        cameras = self.list_cameras()
        ports = self.list_serial_ports()
        return {
            "cameras": cameras.get("cameras", []),
            "serial_ports": ports.get("ports", []),
            "total": len(cameras.get("cameras", [])) + len(ports.get("ports", [])),
        }

    # =========================================================================
    # Inference
    # =========================================================================

    def list_inference_models(self) -> Dict[str, Any]:
        """GET /api/inference/models - List available inference models."""
        response = self._client.get("/api/inference/models")
        response.raise_for_status()
        return response.json()

    def get_device_compatibility(self) -> Dict[str, Any]:
        """GET /api/inference/device-compatibility - Get device compatibility."""
        response = self._client.get("/api/inference/device-compatibility")
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # Platform
    # =========================================================================

    def get_platform(self) -> Dict[str, Any]:
        """GET /api/platform - Get platform info."""
        response = self._client.get("/api/platform")
        response.raise_for_status()
        return response.json()

    def refresh_platform(self) -> Dict[str, Any]:
        """POST /api/platform/refresh - Refresh platform detection."""
        response = self._client.post("/api/platform/refresh")
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # Profiles
    # =========================================================================

    def list_profiles(self) -> Dict[str, Any]:
        """GET /api/profiles - List VLAbor profiles."""
        response = self._client.get("/api/profiles")
        response.raise_for_status()
        return response.json()

    def get_active_profile(self) -> Dict[str, Any]:
        """GET /api/profiles/active - Get active VLAbor profile."""
        response = self._client.get("/api/profiles/active")
        response.raise_for_status()
        return response.json()

    def set_active_profile(self, profile_name: str) -> Dict[str, Any]:
        """PUT /api/profiles/active - Switch active VLAbor profile."""
        response = self._client.put("/api/profiles/active", json={"profile_name": profile_name})
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # Recording
    # =========================================================================

    def create_recording_session(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/recording/session/create - Create recording session."""
        response = self._client.post("/api/recording/session/create", json=data)
        response.raise_for_status()
        return response.json()

    def start_recording_session(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/recording/session/start - Start recorder by dataset_id."""
        response = self._client.post("/api/recording/session/start", json=data)
        response.raise_for_status()
        return response.json()

    def stop_recording_session(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/recording/session/stop - Stop recorder."""
        response = self._client.post("/api/recording/session/stop", json=data)
        response.raise_for_status()
        return response.json()

    def pause_recording_session(self) -> Dict[str, Any]:
        """POST /api/recording/session/pause - Pause recorder."""
        response = self._client.post("/api/recording/session/pause")
        response.raise_for_status()
        return response.json()

    def resume_recording_session(self) -> Dict[str, Any]:
        """POST /api/recording/session/resume - Resume recorder."""
        response = self._client.post("/api/recording/session/resume")
        response.raise_for_status()
        return response.json()

    def cancel_recording_session(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """POST /api/recording/session/cancel - Cancel recorder."""
        response = self._client.post("/api/recording/session/cancel", json=data or {})
        response.raise_for_status()
        return response.json()

    def get_recording_status(self, session_id: str) -> Dict[str, Any]:
        """GET /api/recording/sessions/{session_id}/status - Recorder status."""
        response = self._client.get(f"/api/recording/sessions/{session_id}/status")
        response.raise_for_status()
        return response.json()

    def list_recordings(self) -> Dict[str, Any]:
        """GET /api/recording/recordings - List recordings."""
        response = self._client.get("/api/recording/recordings")
        response.raise_for_status()
        return response.json()

    def get_recording(self, recording_id: str) -> Dict[str, Any]:
        """GET /api/recording/recordings/{recording_id} - Get recording."""
        response = self._client.get(f"/api/recording/recordings/{recording_id}")
        response.raise_for_status()
        return response.json()

    def delete_recording(self, recording_id: str) -> Dict[str, Any]:
        """DELETE /api/recording/recordings/{recording_id} - Delete recording."""
        response = self._client.delete(f"/api/recording/recordings/{recording_id}")
        response.raise_for_status()
        return response.json()

    def validate_recording(self, recording_id: str) -> Dict[str, Any]:
        """GET /api/recording/recordings/{recording_id}/validate - Validate."""
        response = self._client.get(f"/api/recording/recordings/{recording_id}/validate")
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # Storage
    # =========================================================================

    def list_datasets(self, profile_name: Optional[str] = None) -> Dict[str, Any]:
        """GET /api/storage/datasets - List datasets."""
        params = {}
        if profile_name:
            params["profile_name"] = profile_name
        response = self._client.get("/api/storage/datasets", params=params)
        response.raise_for_status()
        return response.json()

    def get_dataset(self, dataset_id: str) -> Dict[str, Any]:
        """GET /api/storage/datasets/{dataset_id} - Get dataset."""
        response = self._client.get(f"/api/storage/datasets/{dataset_id}")
        response.raise_for_status()
        return response.json()

    def delete_dataset(self, dataset_id: str) -> Dict[str, Any]:
        """DELETE /api/storage/datasets/{dataset_id} - Delete (archive)."""
        response = self._client.delete(f"/api/storage/datasets/{dataset_id}")
        response.raise_for_status()
        return response.json()

    def restore_dataset(self, dataset_id: str) -> Dict[str, Any]:
        """POST /api/storage/datasets/{dataset_id}/restore - Restore."""
        response = self._client.post(f"/api/storage/datasets/{dataset_id}/restore")
        response.raise_for_status()
        return response.json()

    def merge_datasets(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/storage/datasets/merge - Merge datasets."""
        response = self._client.post("/api/storage/datasets/merge", json=payload)
        response.raise_for_status()
        return response.json()

    def merge_datasets_ws(
        self,
        payload: Dict[str, Any],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Merge datasets with real-time progress via WebSocket."""
        import websocket

        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/storage/ws/merge"

        result: Dict[str, Any] = {"type": "error", "error": "Unknown error"}

        try:
            ws = websocket.create_connection(ws_url, timeout=None, enable_multithread=True)
            ws.send(json.dumps(payload))

            while True:
                message = ws.recv()
                data = json.loads(message)

                if data.get("type") == "heartbeat":
                    continue

                if progress_callback:
                    progress_callback(data)

                if data.get("type") in ("complete", "error"):
                    result = data
                    break

            ws.close()
        except Exception as e:
            if progress_callback:
                progress_callback({"type": "error", "error": str(e)})
            result = {"type": "error", "error": str(e)}

        return result

    def import_hf_dataset_ws(
        self,
        payload: Dict[str, Any],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Import dataset from HF with real-time progress via WebSocket."""
        import websocket

        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/storage/ws/huggingface/datasets/import"

        result: Dict[str, Any] = {"type": "error", "error": "Unknown error"}

        try:
            ws = websocket.create_connection(ws_url, timeout=None, enable_multithread=True)
            ws.send(json.dumps(payload))

            while True:
                message = ws.recv()
                data = json.loads(message)

                if data.get("type") == "heartbeat":
                    continue

                if progress_callback:
                    progress_callback(data)

                if data.get("type") in ("complete", "error"):
                    result = data
                    break

            ws.close()
        except Exception as e:
            if progress_callback:
                progress_callback({"type": "error", "error": str(e)})
            result = {"type": "error", "error": str(e)}

        return result

    def import_hf_model_ws(
        self,
        payload: Dict[str, Any],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Import model from HF with real-time progress via WebSocket."""
        import websocket

        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/storage/ws/huggingface/models/import"

        result: Dict[str, Any] = {"type": "error", "error": "Unknown error"}

        try:
            ws = websocket.create_connection(ws_url, timeout=None, enable_multithread=True)
            ws.send(json.dumps(payload))

            while True:
                message = ws.recv()
                data = json.loads(message)

                if data.get("type") == "heartbeat":
                    continue

                if progress_callback:
                    progress_callback(data)

                if data.get("type") in ("complete", "error"):
                    result = data
                    break

            ws.close()
        except Exception as e:
            if progress_callback:
                progress_callback({"type": "error", "error": str(e)})
            result = {"type": "error", "error": str(e)}

        return result

    def export_hf_dataset_ws(
        self,
        dataset_id: str,
        payload: Dict[str, Any],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Export dataset to HF with real-time progress via WebSocket."""
        import websocket

        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/storage/ws/huggingface/datasets/{dataset_id}/export"

        result: Dict[str, Any] = {"type": "error", "error": "Unknown error"}

        try:
            ws = websocket.create_connection(ws_url, timeout=None, enable_multithread=True)
            ws.send(json.dumps(payload))

            while True:
                message = ws.recv()
                data = json.loads(message)

                if data.get("type") == "heartbeat":
                    continue

                if progress_callback:
                    progress_callback(data)

                if data.get("type") in ("complete", "error"):
                    result = data
                    break

            ws.close()
        except Exception as e:
            if progress_callback:
                progress_callback({"type": "error", "error": str(e)})
            result = {"type": "error", "error": str(e)}

        return result

    def export_hf_model_ws(
        self,
        model_id: str,
        payload: Dict[str, Any],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Export model to HF with real-time progress via WebSocket."""
        import websocket

        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/storage/ws/huggingface/models/{model_id}/export"

        result: Dict[str, Any] = {"type": "error", "error": "Unknown error"}

        try:
            ws = websocket.create_connection(ws_url, timeout=None, enable_multithread=True)
            ws.send(json.dumps(payload))

            while True:
                message = ws.recv()
                data = json.loads(message)

                if data.get("type") == "heartbeat":
                    continue

                if progress_callback:
                    progress_callback(data)

                if data.get("type") in ("complete", "error"):
                    result = data
                    break

            ws.close()
        except Exception as e:
            if progress_callback:
                progress_callback({"type": "error", "error": str(e)})
            result = {"type": "error", "error": str(e)}

        return result

    def list_models(self) -> Dict[str, Any]:
        """GET /api/storage/models - List models."""
        response = self._client.get("/api/storage/models")
        response.raise_for_status()
        return response.json()

    def get_model(self, model_id: str) -> Dict[str, Any]:
        """GET /api/storage/models/{model_id} - Get model."""
        response = self._client.get(f"/api/storage/models/{model_id}")
        response.raise_for_status()
        return response.json()

    def delete_model(self, model_id: str) -> Dict[str, Any]:
        """DELETE /api/storage/models/{model_id} - Delete (archive)."""
        response = self._client.delete(f"/api/storage/models/{model_id}")
        response.raise_for_status()
        return response.json()

    def restore_model(self, model_id: str) -> Dict[str, Any]:
        """POST /api/storage/models/{model_id}/restore - Restore."""
        response = self._client.post(f"/api/storage/models/{model_id}/restore")
        response.raise_for_status()
        return response.json()

    def import_hf_dataset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/storage/huggingface/datasets/import - Import dataset from HF."""
        response = self._client.post(
            "/api/storage/huggingface/datasets/import",
            json=payload,
            timeout=None,
        )
        response.raise_for_status()
        return response.json()

    def import_hf_model(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/storage/huggingface/models/import - Import model from HF."""
        response = self._client.post(
            "/api/storage/huggingface/models/import",
            json=payload,
            timeout=None,
        )
        response.raise_for_status()
        return response.json()

    def export_hf_dataset(self, dataset_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/storage/huggingface/datasets/{dataset_id}/export - Export dataset to HF."""
        response = self._client.post(
            f"/api/storage/huggingface/datasets/{dataset_id}/export",
            json=payload,
            timeout=None,
        )
        response.raise_for_status()
        return response.json()

    def export_hf_model(self, model_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/storage/huggingface/models/{model_id}/export - Export model to HF."""
        response = self._client.post(
            f"/api/storage/huggingface/models/{model_id}/export",
            json=payload,
            timeout=None,
        )
        response.raise_for_status()
        return response.json()

    def get_storage_usage(self) -> Dict[str, Any]:
        """GET /api/storage/usage - Get storage usage."""
        response = self._client.get("/api/storage/usage")
        response.raise_for_status()
        return response.json()

    def list_archive(self) -> Dict[str, Any]:
        """GET /api/storage/archive - List archived items."""
        response = self._client.get("/api/storage/archive")
        response.raise_for_status()
        return response.json()

    def restore_archives(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/storage/archive/restore - Bulk restore archived items."""
        response = self._client.post("/api/storage/archive/restore", json=payload)
        response.raise_for_status()
        return response.json()

    def delete_archives(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/storage/archive/delete - Bulk delete archived items."""
        response = self._client.post("/api/storage/archive/delete", json=payload)
        response.raise_for_status()
        return response.json()

    def delete_archived_dataset(self, dataset_id: str) -> Dict[str, Any]:
        """DELETE /api/storage/archive/datasets/{dataset_id} - Delete archived dataset."""
        response = self._client.delete(f"/api/storage/archive/datasets/{dataset_id}")
        response.raise_for_status()
        return response.json()

    def delete_archived_model(self, model_id: str) -> Dict[str, Any]:
        """DELETE /api/storage/archive/models/{model_id} - Delete archived model."""
        response = self._client.delete(f"/api/storage/archive/models/{model_id}")
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # System
    # =========================================================================

    def get_system_info(self) -> Dict[str, Any]:
        """GET /api/system/info - Get system info."""
        response = self._client.get("/api/system/info")
        response.raise_for_status()
        return response.json()

    def get_system_health(self) -> Dict[str, Any]:
        """GET /api/system/health - Get detailed system health."""
        response = self._client.get("/api/system/health")
        response.raise_for_status()
        return response.json()

    def get_system_gpu(self) -> Dict[str, Any]:
        """GET /api/system/gpu - Get GPU info."""
        response = self._client.get("/api/system/gpu")
        response.raise_for_status()
        return response.json()

    def get_system_resources(self) -> Dict[str, Any]:
        """GET /api/system/resources - Get resource usage."""
        response = self._client.get("/api/system/resources")
        response.raise_for_status()
        return response.json()

    def get_system_logs(self, limit: int = 100) -> Dict[str, Any]:
        """GET /api/system/logs - Get system logs."""
        response = self._client.get("/api/system/logs", params={"limit": limit})
        response.raise_for_status()
        return response.json()

    def clear_system_logs(self) -> Dict[str, Any]:
        """POST /api/system/logs/clear - Clear logs."""
        response = self._client.post("/api/system/logs/clear")
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # Teleop
    # =========================================================================

    def list_teleop_sessions(self) -> Dict[str, Any]:
        """GET /api/teleop/local/sessions - List local teleop sessions."""
        response = self._client.get("/api/teleop/local/sessions")
        response.raise_for_status()
        return response.json()

    def get_teleop_status(self, session_id: str) -> Dict[str, Any]:
        """GET /api/teleop/local/status/{session_id} - Get teleop status."""
        response = self._client.get(f"/api/teleop/local/status/{session_id}")
        response.raise_for_status()
        return response.json()

    def start_teleop(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/teleop/local/start - Start local teleop session."""
        response = self._client.post("/api/teleop/local/start", json=data)
        response.raise_for_status()
        return response.json()

    def stop_teleop(self, session_id: str) -> Dict[str, Any]:
        """POST /api/teleop/local/stop - Stop local teleop session."""
        response = self._client.post("/api/teleop/local/stop", json={"session_id": session_id})
        response.raise_for_status()
        return response.json()

    def run_teleop(self, session_id: str) -> Dict[str, Any]:
        """POST /api/teleop/local/{session_id}/run - Run teleop."""
        response = self._client.post(f"/api/teleop/local/{session_id}/run")
        response.raise_for_status()
        return response.json()

    # Remote teleop
    def list_remote_teleop_sessions(self) -> Dict[str, Any]:
        """GET /api/teleop/remote/sessions - List remote sessions."""
        response = self._client.get("/api/teleop/remote/sessions")
        response.raise_for_status()
        return response.json()

    def start_teleop_leader(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/teleop/remote/leader/start - Start leader."""
        response = self._client.post("/api/teleop/remote/leader/start", json=data)
        response.raise_for_status()
        return response.json()

    def stop_teleop_leader(self, session_id: str) -> Dict[str, Any]:
        """POST /api/teleop/remote/leader/{session_id}/stop - Stop leader."""
        response = self._client.post(f"/api/teleop/remote/leader/{session_id}/stop")
        response.raise_for_status()
        return response.json()

    def start_teleop_follower(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/teleop/remote/follower/start - Start follower."""
        response = self._client.post("/api/teleop/remote/follower/start", json=data)
        response.raise_for_status()
        return response.json()

    def stop_teleop_follower(self, session_id: str) -> Dict[str, Any]:
        """POST /api/teleop/remote/follower/{session_id}/stop - Stop follower."""
        response = self._client.post(f"/api/teleop/remote/follower/{session_id}/stop")
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # Training
    # =========================================================================

    def get_gpu_availability(self, scan: str = "all") -> Dict[str, Any]:
        """GET /api/training/gpu-availability - Check GPU availability.

        Returns availability info for all GPU model/count combinations.
        """
        params = {"scan": scan} if scan else None
        response = self._client.get("/api/training/gpu-availability", params=params)
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # Verda Storage
    # =========================================================================

    def list_verda_storage(self) -> Dict[str, Any]:
        """GET /api/training/verda/storage - List Verda storage volumes."""
        response = self._client.get("/api/training/verda/storage")
        response.raise_for_status()
        return response.json()

    def delete_verda_storage(self, volume_ids: List[str]) -> Dict[str, Any]:
        """POST /api/training/verda/storage/delete - Logical delete volumes."""
        response = self._client.post(
            "/api/training/verda/storage/delete",
            json={"volume_ids": volume_ids},
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()

    def restore_verda_storage(self, volume_ids: List[str]) -> Dict[str, Any]:
        """POST /api/training/verda/storage/restore - Restore volumes from trash."""
        response = self._client.post(
            "/api/training/verda/storage/restore",
            json={"volume_ids": volume_ids},
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()

    def purge_verda_storage(self, volume_ids: List[str]) -> Dict[str, Any]:
        """POST /api/training/verda/storage/purge - Permanently delete volumes."""
        response = self._client.post(
            "/api/training/verda/storage/purge",
            json={"volume_ids": volume_ids},
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()

    def get_gpu_availability_ws(
        self,
        scan: str = "all",
        on_checking: Optional[Callable[[str], None]] = None,
        on_result: Optional[Callable[[str, int, bool, bool], None]] = None,
        on_complete: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Stream GPU availability check via WebSocket.

        Results are streamed in real-time as each GPU check completes.

        Args:
            on_checking: Callback when starting to check a GPU (gpu_model)
            on_result: Callback with result (gpu_model, gpu_count, spot_available, ondemand_available)
            on_complete: Callback when all checks are done
            on_error: Callback on error

        Returns:
            Dict with all results: {"available": [...], "cached": bool}
        """
        import socket
        import websocket

        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/training/ws/gpu-availability"
        if scan:
            ws_url = f"{ws_url}?scan={scan}"

        results: Dict[str, Any] = {"available": [], "cached": False}

        try:
            ws = websocket.create_connection(ws_url, timeout=60)
            sock = ws.sock
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

            while True:
                message = ws.recv()
                msg_data = json.loads(message)
                msg_type = msg_data.get("type", "")

                if msg_type == "cached":
                    results["cached"] = True
                elif msg_type == "checking":
                    if on_checking:
                        on_checking(msg_data.get("gpu_model", ""))
                elif msg_type == "result":
                    gpu_model = msg_data.get("gpu_model", "")
                    gpu_count = msg_data.get("gpu_count", 1)
                    spot_available = msg_data.get("spot_available", False)
                    ondemand_available = msg_data.get("ondemand_available", False)

                    results["available"].append({
                        "gpu_model": gpu_model,
                        "gpu_count": gpu_count,
                        "spot_available": spot_available,
                        "ondemand_available": ondemand_available,
                    })

                    if on_result:
                        on_result(gpu_model, gpu_count, spot_available, ondemand_available)
                elif msg_type == "complete":
                    if on_complete:
                        on_complete()
                    break
                elif msg_type == "error":
                    if on_error:
                        on_error(msg_data.get("error", "Unknown error"))
                    break

            ws.close()
        except Exception as e:
            if on_error:
                on_error(str(e))

        return results

    def list_training_jobs(self) -> Dict[str, Any]:
        """GET /api/training/jobs - List training jobs."""
        response = self._client.get("/api/training/jobs")
        response.raise_for_status()
        return response.json()

    def get_training_job(self, job_id: str) -> Dict[str, Any]:
        """GET /api/training/jobs/{job_id} - Get job."""
        response = self._client.get(f"/api/training/jobs/{job_id}")
        response.raise_for_status()
        return response.json()

    def create_training_job(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/training/jobs - Create and start job."""
        response = self._client.post("/api/training/jobs", json=data)
        if response.status_code >= 400:
            # Try to get detailed error message from response body
            try:
                error_data = response.json()
                detail = error_data.get("detail", str(error_data))
            except Exception:
                detail = response.text or response.reason_phrase
            raise Exception(f"[{response.status_code}] {detail}")
        return response.json()

    def stop_training_job(self, job_id: str) -> Dict[str, Any]:
        """POST /api/training/jobs/{job_id}/stop - Stop job."""
        response = self._client.post(f"/api/training/jobs/{job_id}/stop")
        response.raise_for_status()
        return response.json()

    def delete_training_job(self, job_id: str) -> Dict[str, Any]:
        """DELETE /api/training/jobs/{job_id} - Delete job."""
        response = self._client.delete(f"/api/training/jobs/{job_id}")
        response.raise_for_status()
        return response.json()

    def revive_training_job(self, job_id: str) -> Dict[str, Any]:
        """POST /api/training/jobs/{job_id}/revive - Revive job instance."""
        response = self._client.post(f"/api/training/jobs/{job_id}/revive")
        response.raise_for_status()
        return response.json()

    def revive_training_job_ws(
        self,
        job_id: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Revive job instance via WebSocket with progress updates."""
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/training/ws/jobs/{job_id}/revive"
        result: Dict[str, Any] = {"type": "error", "error": "Unknown error"}

        try:
            ws = websocket.create_connection(ws_url, timeout=None, enable_multithread=True)
            while True:
                message = ws.recv()
                msg_data = json.loads(message)
                if progress_callback:
                    progress_callback(msg_data)
                if msg_data.get("type") in ("complete", "error"):
                    result = msg_data
                    break
            ws.close()
        except Exception as e:
            if progress_callback:
                progress_callback({"type": "error", "error": str(e)})
            result = {"type": "error", "error": str(e)}

        return result

    def get_training_job_logs(self, job_id: str, log_type: str = "training") -> Dict[str, Any]:
        """GET /api/training/jobs/{job_id}/logs - Get logs."""
        response = self._client.get(
            f"/api/training/jobs/{job_id}/logs",
            params={"log_type": log_type},
        )
        response.raise_for_status()
        return response.json()

    def download_training_job_logs(self, job_id: str, log_type: str = "training") -> str:
        """GET /api/training/jobs/{job_id}/logs/download - Download full logs."""
        response = self._client.get(
            f"/api/training/jobs/{job_id}/logs/download",
            params={"log_type": log_type},
            timeout=120.0,
        )
        response.raise_for_status()
        return response.text

    def get_training_job_log_status(self, job_id: str, log_type: str = "training") -> Dict[str, Any]:
        """GET /api/training/jobs/{job_id}/logs/status - Check log presence on R2."""
        response = self._client.get(
            f"/api/training/jobs/{job_id}/logs/status",
            params={"log_type": log_type},
        )
        response.raise_for_status()
        return response.json()

    def stream_training_job_logs_ws(
        self,
        job_id: str,
        log_type: str = "training",
        on_log: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str, str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Stream job logs in real-time via WebSocket.

        Connects to WebSocket endpoint and receives log lines as they arrive.
        SSH connection is maintained on server side.

        Args:
            job_id: Training job ID
            on_log: Callback for each log line
            on_status: Callback for status changes (status, message)
            on_error: Callback for errors
        """
        import socket
        import websocket

        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/training/ws/jobs/{job_id}/logs?log_type={log_type}"

        try:
            ws = websocket.create_connection(
                ws_url,
                timeout=None,
                skip_utf8_validation=True,
                enable_multithread=True,
            )
            # Set socket keepalive
            sock = ws.sock
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 30)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
            except (AttributeError, OSError):
                pass

            while True:
                message = ws.recv()
                msg_data = json.loads(message)
                msg_type = msg_data.get("type", "")

                if msg_type == "heartbeat":
                    continue
                elif msg_type == "log":
                    if on_log:
                        on_log(msg_data.get("line", ""))
                elif msg_type == "connected":
                    if on_status:
                        on_status("connected", msg_data.get("message", ""))
                elif msg_type == "status":
                    if on_status:
                        on_status(msg_data.get("status", ""), msg_data.get("message", ""))
                    # End stream on terminal status
                    if msg_data.get("status") not in ("connected",):
                        break
                elif msg_type == "error":
                    if on_error:
                        on_error(msg_data.get("error", "Unknown error"))
                    break

            ws.close()
        except Exception as e:
            if on_error:
                on_error(str(e))

    def create_job_session_ws(self, job_id: str) -> "JobSessionWebSocket":
        """Create a unified WebSocket session for job details and log streaming.

        This maintains a single SSH connection for the entire session,
        providing immediate local job info followed by SSH-dependent data.

        Returns:
            JobSessionWebSocket instance for managing the session
        """
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/training/ws/jobs/{job_id}/session"
        return JobSessionWebSocket(ws_url, job_id)

    # =========================================================================
    # Verda Storage (WebSocket)
    # =========================================================================

    def verda_storage_action_ws(
        self,
        action: str,
        volume_ids: List[str],
        on_message: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Run Verda storage action via WebSocket with progress."""
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/training/ws/verda/storage"
        result: Dict[str, Any] = {}

        try:
            ws = websocket.create_connection(ws_url, timeout=None)
            ws.send(json.dumps({"action": action, "volume_ids": volume_ids}))

            while True:
                message = ws.recv()
                data = json.loads(message)
                if on_message:
                    on_message(data)

                if data.get("type") == "error":
                    error_msg = data.get("error", "Unknown error")
                    if on_error:
                        on_error(error_msg)
                    result = {"error": error_msg}
                    break

                if data.get("type") == "complete":
                    result = data.get("result", {})
                    break

            ws.close()
        except websocket.WebSocketConnectionClosedException:
            error_msg = "WebSocket connection closed"
            if on_error:
                on_error(error_msg)
            result = {"error": error_msg}
        except Exception as e:
            error_msg = str(e)
            if on_error:
                on_error(error_msg)
            result = {"error": error_msg}

        return result

    def get_training_job_progress(self, job_id: str) -> Dict[str, Any]:
        """GET /api/training/jobs/{job_id}/progress - Get progress."""
        response = self._client.get(f"/api/training/jobs/{job_id}/progress")
        response.raise_for_status()
        return response.json()

    def get_training_job_metrics(self, job_id: str, limit: int = 1000) -> Dict[str, Any]:
        """GET /api/training/jobs/{job_id}/metrics - Get metric series."""
        response = self._client.get(
            f"/api/training/jobs/{job_id}/metrics",
            params={"limit": limit},
        )
        response.raise_for_status()
        return response.json()

    def get_training_instance_status(self, job_id: str) -> Dict[str, Any]:
        """GET /api/training/jobs/{job_id}/instance-status - Instance status."""
        response = self._client.get(f"/api/training/jobs/{job_id}/instance-status")
        response.raise_for_status()
        return response.json()

    def check_training_jobs_status(self) -> Dict[str, Any]:
        """POST /api/training/jobs/check-status - Check all jobs."""
        response = self._client.post("/api/training/jobs/check-status")
        response.raise_for_status()
        return response.json()

    def create_continue_training_job(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/training/jobs/continue - Create continue training job."""
        response = self._client.post("/api/training/jobs/continue", json=data)
        if response.status_code >= 400:
            try:
                error_data = response.json()
                detail = error_data.get("detail", str(error_data))
            except Exception:
                detail = response.text or response.reason_phrase
            raise Exception(f"[{response.status_code}] {detail}")
        return response.json()

    def create_training_job_ws(
        self,
        data: Dict[str, Any],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Create training job with real-time progress via WebSocket.

        This method uses WebSocket to stream progress updates during job creation,
        including instance provisioning, IP assignment, SSH connection, and deployment.

        Args:
            data: Job creation request dict:
                {
                    "job_name": "job_name",
                    "dataset": {"id": "...", "source": "r2"},
                    "policy": {"type": "act", "pretrained_path": null},
                    "training": {"steps": 100000, "batch_size": 32},
                    "cloud": {"gpu_model": "H100", "gpus_per_instance": 1, "is_spot": true},
                    "checkpoint_repo_id": null,
                    "wandb_enable": true
                }
            progress_callback: Called with progress updates. Receives dict with:
                - type: "start", "validating", "validated", "selecting_instance",
                        "instance_selected", "finding_location", "location_found",
                        "creating_instance", "instance_created", "waiting_ip",
                        "ip_assigned", "waiting_running", "instance_running",
                        "connecting_ssh", "ssh_ready", "deploying",
                        "starting_training", "complete", "error", "heartbeat"
                - Additional fields depending on type (message, elapsed, timeout, etc.)

        Returns:
            Final result dict with job_id, instance_id, ip, status on success,
            or error on failure.
        """
        import socket
        import websocket

        # Convert http URL to ws URL
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/training/ws/create-job"

        result: Dict[str, Any] = {"type": "error", "error": "Unknown error"}

        try:
            headers = []
            token = self._session.get("access_token") if self._session else None
            if token:
                headers.append(f"Authorization: Bearer {token}")

            # Create WebSocket with keepalive settings for long-running operations
            ws = websocket.create_connection(
                ws_url,
                timeout=None,  # No recv timeout (job creation can take 20+ minutes)
                skip_utf8_validation=True,
                enable_multithread=True,
                header=headers or None,
            )
            # Set socket keepalive to detect dead connections
            sock = ws.sock
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            # Linux-specific keepalive settings
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 30)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
            except (AttributeError, OSError):
                pass  # Not available on all platforms

            # Send job creation request
            ws.send(json.dumps(data))

            # Receive progress updates until done
            while True:
                message = ws.recv()
                msg_data = json.loads(message)

                # Skip heartbeat messages (keepalive from server)
                if msg_data.get("type") == "heartbeat":
                    continue

                if progress_callback:
                    progress_callback(msg_data)

                if msg_data.get("type") in ("complete", "error"):
                    result = msg_data
                    break

            ws.close()
        except Exception as e:
            if progress_callback:
                progress_callback({"type": "error", "error": str(e)})
            result = {"type": "error", "error": str(e)}

        return result

    # =========================================================================
    # Training Checkpoints
    # =========================================================================

    def list_training_checkpoints(self, policy_type: Optional[str] = None) -> Dict[str, Any]:
        """GET /api/training/checkpoints - List checkpoints."""
        params = {}
        if policy_type:
            params["policy_type"] = policy_type
        response = self._client.get("/api/training/checkpoints", params=params)
        response.raise_for_status()
        return response.json()

    def get_training_checkpoint(self, job_name: str) -> Dict[str, Any]:
        """GET /api/training/checkpoints/{job_name} - Get checkpoint details."""
        response = self._client.get(f"/api/training/checkpoints/{job_name}")
        response.raise_for_status()
        return response.json()

    def download_training_checkpoint(
        self, job_name: str, step: Optional[int] = None, target_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """POST /api/training/checkpoints/{job_name}/download - Download checkpoint."""
        data: Dict[str, Any] = {}
        if step is not None:
            data["step"] = step
        if target_path is not None:
            data["target_path"] = target_path
        response = self._client.post(f"/api/training/checkpoints/{job_name}/download", json=data)
        response.raise_for_status()
        return response.json()

    def check_dataset_compatibility(
        self, checkpoint_job_name: str, dataset_id: str
    ) -> Dict[str, Any]:
        """POST /api/training/checkpoints/compatibility-check - Check dataset compatibility."""
        data = {
            "checkpoint_job_name": checkpoint_job_name,
            "dataset_id": dataset_id,
        }
        response = self._client.post("/api/training/checkpoints/compatibility-check", json=data)
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # Calibration
    # =========================================================================

    def list_calibrations(self) -> Dict[str, Any]:
        """GET /api/calibration - List calibrations."""
        response = self._client.get("/api/calibration")
        response.raise_for_status()
        return response.json()

    def list_calibrations_by_arm_type(self, arm_type: Optional[str] = None) -> Dict[str, Any]:
        """GET /api/calibration/arms - List calibrations by arm type."""
        params = {"arm_type": arm_type} if arm_type else {}
        response = self._client.get("/api/calibration/arms", params=params)
        response.raise_for_status()
        return response.json()

    def list_calibration_sessions(self) -> Dict[str, Any]:
        """GET /api/calibration/sessions - List sessions."""
        response = self._client.get("/api/calibration/sessions")
        response.raise_for_status()
        return response.json()

    def get_calibration_session(self, session_id: str) -> Dict[str, Any]:
        """GET /api/calibration/arms/{session_id}/status - Get session status."""
        response = self._client.get(f"/api/calibration/arms/{session_id}/status")
        response.raise_for_status()
        return response.json()

    def get_calibration(self, arm_id: str, arm_type: str = "so101") -> Dict[str, Any]:
        """GET /api/calibration/arms/{arm_id} - Get calibration."""
        response = self._client.get(f"/api/calibration/arms/{arm_id}", params={"arm_type": arm_type})
        response.raise_for_status()
        return response.json()

    def start_calibration(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/calibration/arms/start - Start calibration.

        Required fields in data:
        - arm_type: str (e.g., "so101", "so100")
        - port: str (e.g., "/dev/ttyUSB0")
        - arm_id: Optional[str] (auto-generated if not provided)
        """
        response = self._client.post("/api/calibration/arms/start", json=data)
        response.raise_for_status()
        return response.json()

    def record_calibration_position(self, session_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/calibration/arms/{session_id}/record-position.

        Required fields in data:
        - motor_name: str (e.g., "shoulder_pan")
        - position_type: str ("min", "max", or "home")
        """
        response = self._client.post(
            f"/api/calibration/arms/{session_id}/record-position",
            json=data
        )
        response.raise_for_status()
        return response.json()

    def complete_calibration(self, session_id: str, save: bool = True) -> Dict[str, Any]:
        """POST /api/calibration/arms/{session_id}/complete - Complete."""
        response = self._client.post(
            f"/api/calibration/arms/{session_id}/complete",
            json={"save": save}
        )
        response.raise_for_status()
        return response.json()

    def update_calibration(self, arm_id: str, data: Dict[str, Any], arm_type: str = "so101") -> Dict[str, Any]:
        """PUT /api/calibration/arms/{arm_id} - Update calibration."""
        response = self._client.put(
            f"/api/calibration/arms/{arm_id}",
            json=data,
            params={"arm_type": arm_type}
        )
        response.raise_for_status()
        return response.json()

    def delete_calibration(self, arm_id: str, arm_type: str = "so101") -> Dict[str, Any]:
        """DELETE /api/calibration/arms/{arm_id} - Delete."""
        response = self._client.delete(f"/api/calibration/arms/{arm_id}", params={"arm_type": arm_type})
        response.raise_for_status()
        return response.json()

    def export_calibration(self, arm_id: str, arm_type: str = "so101") -> Dict[str, Any]:
        """GET /api/calibration/export/{arm_id} - Export."""
        response = self._client.get(f"/api/calibration/export/{arm_id}", params={"arm_type": arm_type})
        response.raise_for_status()
        return response.json()

    def import_calibration(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/calibration/import - Import calibration.

        Required: data must contain 'calibration' key with CalibrationDataModel.
        """
        response = self._client.post("/api/calibration/import", json=data)
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # User
    # =========================================================================

    def get_user_config(self) -> Dict[str, Any]:
        """GET /api/user/config - Get user config."""
        response = self._client.get("/api/user/config")
        response.raise_for_status()
        return response.json()

    def update_user_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """PUT /api/user/config - Update user config."""
        response = self._client.put("/api/user/config", json=data)
        response.raise_for_status()
        return response.json()

    def get_user_devices(self) -> Dict[str, Any]:
        """GET /api/user/devices - Get user devices config."""
        response = self._client.get("/api/user/devices")
        response.raise_for_status()
        return response.json()

    def update_user_devices(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """PUT /api/user/devices - Update user devices."""
        response = self._client.put("/api/user/devices", json=data)
        response.raise_for_status()
        return response.json()

    def validate_environment(self) -> Dict[str, Any]:
        """POST /api/user/validate-environment - Validate environment."""
        response = self._client.post("/api/user/validate-environment")
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # Build
    # =========================================================================

    def get_bundled_torch_status(self) -> Dict[str, Any]:
        """GET /api/build/bundled-torch/status - Get bundled-torch status."""
        response = self._client.get("/api/build/bundled-torch/status")
        response.raise_for_status()
        return response.json()

    def build_bundled_torch_ws(
        self,
        pytorch_version: Optional[str] = None,
        torchvision_version: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Build bundled-torch with real-time progress via WebSocket.

        Args:
            pytorch_version: PyTorch version (git tag/branch, e.g., "v2.1.0")
            torchvision_version: torchvision version (git tag/branch, e.g., "v0.16.0")
            progress_callback: Called with progress updates

        Returns:
            Final result with type='complete' or type='error'
        """
        import websocket

        # Convert http URL to ws URL
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/build/ws/bundled-torch"

        result: Dict[str, Any] = {"type": "error", "error": "Unknown error"}

        try:
            # Create WebSocket with keepalive settings for long-running builds
            ws = websocket.create_connection(
                ws_url,
                timeout=None,  # No recv timeout
                skip_utf8_validation=True,
                enable_multithread=True,
            )
            # Set socket keepalive to detect dead connections
            import socket
            sock = ws.sock
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            # Linux-specific keepalive settings
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 30)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
            except (AttributeError, OSError):
                pass  # Not available on all platforms

            # Send build request
            ws.send(json.dumps({
                "action": "build",
                "pytorch_version": pytorch_version,
                "torchvision_version": torchvision_version,
            }))

            # Receive progress updates until done
            while True:
                message = ws.recv()
                data = json.loads(message)

                # Skip heartbeat messages (keepalive from server)
                if data.get("type") == "heartbeat":
                    continue

                if progress_callback:
                    progress_callback(data)

                if data.get("type") in ("complete", "error"):
                    result = data
                    break

            ws.close()
        except Exception as e:
            if progress_callback:
                progress_callback({"type": "error", "error": str(e)})
            result = {"type": "error", "error": str(e)}

        return result

    def clean_bundled_torch_ws(
        self,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Clean bundled-torch with progress via WebSocket.

        Args:
            progress_callback: Called with progress updates

        Returns:
            Final result with type='complete' or type='error'
        """
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/build/ws/bundled-torch"

        result: Dict[str, Any] = {"type": "error", "error": "Unknown error"}

        try:
            ws = websocket.create_connection(ws_url, timeout=60)

            # Send clean request
            ws.send(json.dumps({"action": "clean"}))

            # Receive progress until done
            while True:
                message = ws.recv()
                data = json.loads(message)

                if progress_callback:
                    progress_callback(data)

                if data.get("type") in ("complete", "error"):
                    result = data
                    break

            ws.close()
        except Exception as e:
            if progress_callback:
                progress_callback({"type": "error", "error": str(e)})
            result = {"type": "error", "error": str(e)}

        return result


class JobSessionWebSocket:
    """Unified WebSocket session for job details and log streaming.

    Maintains a single SSH connection on the server side for the entire session.

    Usage:
        session = api.create_job_session_ws(job_id)
        session.connect()

        # Receive messages
        while True:
            msg = session.receive()
            if msg["type"] == "job_info":
                # Local job info (immediate)
                ...
            elif msg["type"] == "ssh_connected":
                # SSH connected, remote info follows
                ...
            elif msg["type"] == "progress":
                # Training progress
                ...
            elif msg["type"] == "log":
                # Log line (when streaming)
                ...

        # Start/stop log streaming
        session.start_logs()
        session.stop_logs()

        # Refresh status/progress
        session.refresh()

        session.close()
    """

    def __init__(self, ws_url: str, job_id: str):
        self.ws_url = ws_url
        self.job_id = job_id
        self._ws = None
        self._connected = False

    def connect(self) -> bool:
        """Connect to WebSocket server."""
        try:
            self._ws = websocket.create_connection(
                self.ws_url,
                timeout=None,
                skip_utf8_validation=True,
                enable_multithread=True,
            )
            # Set socket keepalive
            sock = self._ws.sock
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 30)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
            except (AttributeError, OSError):
                pass
            self._connected = True
            return True
        except Exception:
            return False

    def receive(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Receive a message from the server.

        Args:
            timeout: Timeout in seconds (None for blocking)

        Returns:
            Message dict or None if timeout/error
        """
        if not self._ws:
            return None

        try:
            if timeout is not None:
                self._ws.settimeout(timeout)
            message = self._ws.recv()
            return json.loads(message)
        except Exception:
            return None

    def send_action(self, action: str) -> bool:
        """Send an action to the server."""
        if not self._ws:
            return False
        try:
            self._ws.send(json.dumps({"action": action}))
            return True
        except Exception:
            return False

    def start_logs(self) -> bool:
        """Request log streaming to start."""
        return self.send_action("start_logs")

    def stop_logs(self) -> bool:
        """Request log streaming to stop."""
        return self.send_action("stop_logs")

    def refresh(self) -> bool:
        """Request status/progress refresh."""
        return self.send_action("refresh")

    def close(self) -> None:
        """Close the WebSocket connection."""
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
            self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._connected and self._ws is not None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
