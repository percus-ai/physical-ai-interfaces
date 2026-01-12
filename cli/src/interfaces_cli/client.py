"""HTTP client for Backend API.

Auto-generated based on OpenAPI schema from /openapi.json
"""

import json
import os
from typing import Any, Callable, Dict, List, Optional

import httpx


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
    # Analytics
    # =========================================================================

    def get_analytics_overview(self) -> Dict[str, Any]:
        """GET /api/analytics/overview - Get overall statistics."""
        response = self._client.get("/api/analytics/overview")
        response.raise_for_status()
        return response.json()

    def get_analytics_projects(self) -> Dict[str, Any]:
        """GET /api/analytics/projects - Get per-project statistics."""
        response = self._client.get("/api/analytics/projects")
        response.raise_for_status()
        return response.json()

    def get_analytics_project(self, project_name: str) -> Dict[str, Any]:
        """GET /api/analytics/projects/{project_name} - Get project stats."""
        response = self._client.get(f"/api/analytics/projects/{project_name}")
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

    def get_config_environments(self) -> Dict[str, Any]:
        """GET /api/config/environments - Get available environments."""
        response = self._client.get("/api/config/environments")
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

    def list_inference_sessions(self) -> Dict[str, Any]:
        """GET /api/inference/sessions - List inference sessions."""
        response = self._client.get("/api/inference/sessions")
        response.raise_for_status()
        return response.json()

    def get_inference_session(self, session_id: str) -> Dict[str, Any]:
        """GET /api/inference/sessions/{session_id} - Get session details."""
        response = self._client.get(f"/api/inference/sessions/{session_id}")
        response.raise_for_status()
        return response.json()

    def get_device_compatibility(self) -> Dict[str, Any]:
        """GET /api/inference/device-compatibility - Get device compatibility."""
        response = self._client.get("/api/inference/device-compatibility")
        response.raise_for_status()
        return response.json()

    def load_inference_model(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/inference/load - Load model for inference."""
        response = self._client.post("/api/inference/load", json=data)
        response.raise_for_status()
        return response.json()

    def unload_inference_model(self, session_id: str) -> Dict[str, Any]:
        """POST /api/inference/unload - Unload current model."""
        response = self._client.post("/api/inference/unload", json={"session_id": session_id})
        response.raise_for_status()
        return response.json()

    def predict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/inference/predict - Run prediction."""
        response = self._client.post("/api/inference/predict", json=data)
        response.raise_for_status()
        return response.json()

    def reset_inference_session(self, session_id: str) -> Dict[str, Any]:
        """POST /api/inference/sessions/{session_id}/reset - Reset session."""
        response = self._client.post(f"/api/inference/sessions/{session_id}/reset")
        response.raise_for_status()
        return response.json()

    def run_inference(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/inference/run - Run inference on robot."""
        response = self._client.post("/api/inference/run", json=data, timeout=600.0)
        response.raise_for_status()
        return response.json()

    def run_inference_with_progress(
        self,
        data: Dict[str, Any],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Run inference via WebSocket with real-time output streaming.

        Args:
            data: Dict with model_id, project, episodes, robot_type, device
            progress_callback: Called with each message from WebSocket

        Returns:
            Final result with type='complete' or type='error'
        """
        import websocket

        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/inference/ws/run"

        result: Dict[str, Any] = {"type": "error", "error": "Unknown error"}

        try:
            ws = websocket.create_connection(ws_url, timeout=None)  # No timeout for long-running inference

            # Send inference request
            ws.send(json.dumps(data))

            # Receive messages until done
            while True:
                message = ws.recv()
                msg_data = json.loads(message)

                if progress_callback:
                    progress_callback(msg_data)

                if msg_data.get("type") in ("complete", "error"):
                    result = msg_data
                    break

            ws.close()
        except ImportError:
            if progress_callback:
                progress_callback({
                    "type": "error",
                    "error": "websocket-client not installed"
                })
            result = {"type": "error", "error": "websocket-client not installed"}
        except Exception as e:
            if progress_callback:
                progress_callback({"type": "error", "error": str(e)})
            result = {"type": "error", "error": str(e)}

        return result

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
    # Projects
    # =========================================================================

    def list_projects(self) -> Dict[str, Any]:
        """GET /api/projects - List all projects."""
        response = self._client.get("/api/projects")
        response.raise_for_status()
        return response.json()

    def get_project(self, project_name: str) -> Dict[str, Any]:
        """GET /api/projects/{project_name} - Get project details."""
        response = self._client.get(f"/api/projects/{project_name}")
        response.raise_for_status()
        return response.json()

    def create_project(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/projects - Create a new project."""
        response = self._client.post("/api/projects", json=data)
        response.raise_for_status()
        return response.json()

    def delete_project(self, project_name: str, delete_data: bool = False) -> Dict[str, Any]:
        """DELETE /api/projects/{project_name} - Delete a project."""
        response = self._client.delete(
            f"/api/projects/{project_name}",
            params={"delete_data": delete_data}
        )
        response.raise_for_status()
        return response.json()

    def get_project_stats(self, project_name: str) -> Dict[str, Any]:
        """GET /api/projects/{project_name}/stats - Get project stats."""
        response = self._client.get(f"/api/projects/{project_name}/stats")
        response.raise_for_status()
        return response.json()

    def validate_project(self, project_name: str) -> Dict[str, Any]:
        """GET /api/projects/{project_name}/validate - Validate project."""
        response = self._client.get(f"/api/projects/{project_name}/validate")
        response.raise_for_status()
        return response.json()

    def validate_project_devices(self, project_name: str) -> Dict[str, Any]:
        """GET /api/projects/{project_name}/validate-devices - Validate devices."""
        response = self._client.get(f"/api/projects/{project_name}/validate-devices")
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # Recording
    # =========================================================================

    def record(self, project_name: str, num_episodes: int = 1, username: str = None) -> Dict[str, Any]:
        """POST /api/recording/record - Start recording directly.

        Args:
            project_name: Name of the project (must exist in data/projects/)
            num_episodes: Number of episodes to record
            username: Optional username override
        """
        data = {
            "project_name": project_name,
            "num_episodes": num_episodes,
        }
        if username:
            data["username"] = username
        response = self._client.post("/api/recording/record", json=data, timeout=3600)
        response.raise_for_status()
        return response.json()

    def record_ws(
        self,
        project_name: str,
        num_episodes: int = 1,
        username: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Start recording via WebSocket with real-time output streaming.

        Args:
            project_name: Name of the project
            num_episodes: Number of episodes to record
            username: Optional username override
            progress_callback: Callback for progress updates. Receives dict with:
                - type: "start", "output", "error_output", "complete", "error"
                - Additional fields depending on type

        Returns:
            Final result with type='complete' or type='error'
        """
        import websocket

        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/recording/ws/record"

        result: Dict[str, Any] = {"type": "error", "error": "Unknown error"}
        last_received_msg: Dict[str, Any] = {}

        try:
            ws = websocket.create_connection(ws_url, timeout=None)

            # Send recording request
            request_data = {
                "project_name": project_name,
                "num_episodes": num_episodes,
            }
            if username:
                request_data["username"] = username
            ws.send(json.dumps(request_data))

            # Receive messages until done
            import sys
            while True:
                try:
                    message = ws.recv()
                    if not message:
                        continue
                    msg_data = json.loads(message)
                    last_received_msg = msg_data

                    # Debug: log all received messages
                    msg_type = msg_data.get("type", "unknown")
                    if msg_type in ("complete", "error", "stopped", "start"):
                        print(f"[DEBUG] Received {msg_type} message: {msg_data}", file=sys.stderr)

                    if progress_callback:
                        progress_callback(msg_data)

                    if msg_data.get("type") in ("complete", "error", "stopped"):
                        result = msg_data
                        break
                except websocket.WebSocketConnectionClosedException:
                    # Connection closed by server
                    print(f"[DEBUG] WebSocket connection closed. last_received_msg: {last_received_msg}", file=sys.stderr)
                    if last_received_msg.get("type") in ("complete", "error", "stopped"):
                        result = last_received_msg
                    else:
                        result = {
                            "type": "error",
                            "error": "Connection closed unexpectedly",
                            "last_message": last_received_msg,
                        }
                    break
            try:
                ws.close()
            except Exception:
                pass
        except ImportError:
            if progress_callback:
                progress_callback({
                    "type": "error",
                    "error": "websocket-client not installed"
                })
            result = {"type": "error", "error": "websocket-client not installed"}
        except websocket.WebSocketConnectionClosedException:
            # Connection closed during setup or early
            result = {
                "type": "error",
                "error": "Connection closed by server",
                "last_message": last_received_msg,
            }
            if progress_callback:
                progress_callback(result)
        except Exception as e:
            if progress_callback:
                progress_callback({"type": "error", "error": str(e)})
            result = {"type": "error", "error": str(e)}

        # Debug: print the actual result being returned
        import sys
        print(f"\n[DEBUG] record_ws returning: {result}", file=sys.stderr)
        return result

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

    def list_datasets(self) -> Dict[str, Any]:
        """GET /api/storage/datasets - List datasets."""
        response = self._client.get("/api/storage/datasets")
        response.raise_for_status()
        return response.json()

    def list_dataset_projects(self) -> Dict[str, Any]:
        """GET /api/storage/dataset-projects - List dataset projects from R2.

        Returns top-level directories under datasets/ in R2.
        Each project contains multiple recording sessions.

        Returns:
            Dict with "projects" list and "total" count
        """
        response = self._client.get("/api/storage/dataset-projects")
        response.raise_for_status()
        return response.json()

    def list_project_sessions(
        self,
        project_id: str,
        exclude_eval: bool = True,
        sort: str = "date_desc",
    ) -> Dict[str, Any]:
        """GET /api/storage/dataset-projects/{project_id}/sessions - List sessions in a project.

        Args:
            project_id: Project ID (e.g., '0001_black_cube_to_tray')
            exclude_eval: If True, exclude evaluation sessions (eval_* prefix)
            sort: Sort order by date - 'date_asc' (oldest first) or 'date_desc' (newest first)

        Returns:
            Dict with "project_id", "sessions" list, and "total" count
        """
        response = self._client.get(
            f"/api/storage/dataset-projects/{project_id}/sessions",
            params={"exclude_eval": exclude_eval, "sort": sort},
        )
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

    def get_dataset_sync_status(self, dataset_id: str) -> Dict[str, Any]:
        """GET /api/storage/datasets/{dataset_id}/sync - Get sync status."""
        response = self._client.get(f"/api/storage/datasets/{dataset_id}/sync")
        response.raise_for_status()
        return response.json()

    def upload_dataset(self, dataset_id: str) -> Dict[str, Any]:
        """POST /api/storage/datasets/{dataset_id}/upload - Upload to R2."""
        response = self._client.post(f"/api/storage/datasets/{dataset_id}/upload")
        response.raise_for_status()
        return response.json()

    def download_dataset(self, dataset_id: str) -> Dict[str, Any]:
        """POST /api/storage/datasets/{dataset_id}/download - Download from R2."""
        response = self._client.post(f"/api/storage/datasets/{dataset_id}/download")
        response.raise_for_status()
        return response.json()

    def publish_dataset(self, dataset_id: str, repo_id: str, private: bool = False, commit_message: Optional[str] = None) -> Dict[str, Any]:
        """POST /api/storage/datasets/{dataset_id}/publish - Publish to Hub."""
        data = {"repo_id": repo_id, "private": private}
        if commit_message:
            data["commit_message"] = commit_message
        response = self._client.post(f"/api/storage/datasets/{dataset_id}/publish", json=data)
        response.raise_for_status()
        return response.json()

    def restore_dataset(self, dataset_id: str) -> Dict[str, Any]:
        """POST /api/storage/datasets/{dataset_id}/restore - Restore."""
        response = self._client.post(f"/api/storage/datasets/{dataset_id}/restore")
        response.raise_for_status()
        return response.json()

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

    def get_model_sync_status(self, model_id: str) -> Dict[str, Any]:
        """GET /api/storage/models/{model_id}/sync - Get sync status."""
        response = self._client.get(f"/api/storage/models/{model_id}/sync")
        response.raise_for_status()
        return response.json()

    def upload_model(self, model_id: str) -> Dict[str, Any]:
        """POST /api/storage/models/{model_id}/upload - Upload to R2."""
        response = self._client.post(f"/api/storage/models/{model_id}/upload")
        response.raise_for_status()
        return response.json()

    def download_model(self, model_id: str) -> Dict[str, Any]:
        """POST /api/storage/models/{model_id}/download - Download from R2."""
        response = self._client.post(f"/api/storage/models/{model_id}/download")
        response.raise_for_status()
        return response.json()

    def publish_model(self, model_id: str, repo_id: str, private: bool = False, commit_message: Optional[str] = None) -> Dict[str, Any]:
        """POST /api/storage/models/{model_id}/publish - Publish to Hub."""
        data = {"repo_id": repo_id, "private": private}
        if commit_message:
            data["commit_message"] = commit_message
        response = self._client.post(f"/api/storage/models/{model_id}/publish", json=data)
        response.raise_for_status()
        return response.json()

    def restore_model(self, model_id: str) -> Dict[str, Any]:
        """POST /api/storage/models/{model_id}/restore - Restore."""
        response = self._client.post(f"/api/storage/models/{model_id}/restore")
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

    # Storage Projects

    def list_storage_projects(self) -> Dict[str, Any]:
        """GET /api/storage/projects - List projects."""
        response = self._client.get("/api/storage/projects")
        response.raise_for_status()
        return response.json()

    def get_storage_project(self, project_id: str) -> Dict[str, Any]:
        """GET /api/storage/projects/{project_id} - Get project details."""
        response = self._client.get(f"/api/storage/projects/{project_id}")
        response.raise_for_status()
        return response.json()

    def upload_storage_project(self, project_id: str) -> Dict[str, Any]:
        """POST /api/storage/projects/{project_id}/upload - Upload project to R2."""
        response = self._client.post(f"/api/storage/projects/{project_id}/upload")
        response.raise_for_status()
        return response.json()

    def download_storage_project(self, project_id: str) -> Dict[str, Any]:
        """POST /api/storage/projects/{project_id}/download - Download project from R2."""
        response = self._client.post(f"/api/storage/projects/{project_id}/download")
        response.raise_for_status()
        return response.json()

    def list_remote_projects(self) -> Dict[str, Any]:
        """GET /api/storage/projects/remote/list - List projects on R2."""
        response = self._client.get("/api/storage/projects/remote/list")
        response.raise_for_status()
        return response.json()

    def sync_storage_projects(self) -> Dict[str, Any]:
        """POST /api/storage/projects/sync - Sync projects from R2."""
        response = self._client.post("/api/storage/projects/sync")
        response.raise_for_status()
        return response.json()

    def search_datasets(self, query: str, limit: int = 20) -> Dict[str, Any]:
        """GET /api/storage/search/datasets - Search datasets."""
        response = self._client.get("/api/storage/search/datasets", params={"query": query, "limit": limit})
        response.raise_for_status()
        return response.json()

    def search_models(self, query: str, limit: int = 20) -> Dict[str, Any]:
        """GET /api/storage/search/models - Search models."""
        response = self._client.get("/api/storage/search/models", params={"query": query, "limit": limit})
        response.raise_for_status()
        return response.json()

    def import_dataset(self, repo_id: str, force: bool = False) -> Dict[str, Any]:
        """POST /api/storage/import/dataset - Import dataset from Hub."""
        response = self._client.post("/api/storage/import/dataset", params={"repo_id": repo_id, "force": force})
        response.raise_for_status()
        return response.json()

    def import_model(self, repo_id: str, force: bool = False) -> Dict[str, Any]:
        """POST /api/storage/import/model - Import model from Hub."""
        response = self._client.post("/api/storage/import/model", params={"repo_id": repo_id, "force": force})
        response.raise_for_status()
        return response.json()

    def push_manifest(self) -> Dict[str, Any]:
        """POST /api/storage/sync/manifest/push - Push manifest to R2."""
        response = self._client.post("/api/storage/sync/manifest/push")
        response.raise_for_status()
        return response.json()

    def pull_manifest(self) -> Dict[str, Any]:
        """POST /api/storage/sync/manifest/pull - Pull manifest from R2."""
        response = self._client.post("/api/storage/sync/manifest/pull")
        response.raise_for_status()
        return response.json()

    def regenerate_manifest(self) -> Dict[str, Any]:
        """POST /api/storage/sync/manifest/regenerate - Regenerate manifest from R2 and local."""
        response = self._client.post("/api/storage/sync/manifest/regenerate", timeout=120.0)
        response.raise_for_status()
        return response.json()

    def list_legacy_models(self) -> Dict[str, Any]:
        """GET /api/storage/migration/legacy/models - List legacy models."""
        response = self._client.get("/api/storage/migration/legacy/models")
        response.raise_for_status()
        return response.json()

    def list_legacy_datasets(self) -> Dict[str, Any]:
        """GET /api/storage/migration/legacy/datasets - List legacy datasets."""
        response = self._client.get("/api/storage/migration/legacy/datasets")
        response.raise_for_status()
        return response.json()

    def migrate_models(self, item_ids: List[str], delete_legacy: bool = False) -> Dict[str, Any]:
        """POST /api/storage/migration/models - Migrate models to new version."""
        response = self._client.post(
            "/api/storage/migration/models",
            json={"item_ids": item_ids, "delete_legacy": delete_legacy},
        )
        response.raise_for_status()
        return response.json()

    def migrate_datasets(self, item_ids: List[str], delete_legacy: bool = False) -> Dict[str, Any]:
        """POST /api/storage/migration/datasets - Migrate datasets to new version."""
        response = self._client.post(
            "/api/storage/migration/datasets",
            json={"item_ids": item_ids, "delete_legacy": delete_legacy},
        )
        response.raise_for_status()
        return response.json()

    def migrate_single_model(self, item_id: str, delete_legacy: bool = False, timeout: float = 600.0) -> Dict[str, Any]:
        """Migrate a single model with extended timeout for large files."""
        with httpx.Client(base_url=self.base_url, timeout=timeout) as client:
            response = client.post(
                "/api/storage/migration/models",
                json={"item_ids": [item_id], "delete_legacy": delete_legacy},
            )
            response.raise_for_status()
            return response.json()

    def migrate_single_dataset(self, item_id: str, delete_legacy: bool = False, timeout: float = 600.0) -> Dict[str, Any]:
        """Migrate a single dataset with extended timeout for large files."""
        with httpx.Client(base_url=self.base_url, timeout=timeout) as client:
            response = client.post(
                "/api/storage/migration/datasets",
                json={"item_ids": [item_id], "delete_legacy": delete_legacy},
            )
            response.raise_for_status()
            return response.json()

    def migrate_with_progress(
        self,
        entry_type: str,
        item_ids: List[str],
        delete_legacy: bool = False,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Migrate items with real-time progress via WebSocket.

        Args:
            entry_type: 'models' or 'datasets'
            item_ids: List of item IDs to migrate
            delete_legacy: Delete legacy items after migration
            progress_callback: Called with progress updates

        Returns:
            Final result with success_count, failed_count, results
        """
        import websocket

        # Convert http URL to ws URL
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/storage/ws/migration"

        result = {"success_count": 0, "failed_count": 0, "results": {}}

        try:
            ws = websocket.create_connection(ws_url)

            # Send migration request
            ws.send(json.dumps({
                "action": "migrate",
                "entry_type": entry_type,
                "item_ids": item_ids,
                "delete_legacy": delete_legacy,
            }))

            # Receive progress updates until done
            while True:
                message = ws.recv()
                data = json.loads(message)

                if progress_callback:
                    progress_callback(data)

                if data.get("type") == "done":
                    result = data
                    break
                elif data.get("type") == "error" and "item_id" not in data:
                    # Global error
                    raise Exception(data.get("error", "Unknown error"))

            ws.close()
        except ImportError:
            # websocket-client not installed, fall back to HTTP
            if progress_callback:
                progress_callback({"type": "fallback", "message": "WebSocket not available, using HTTP"})
            for item_id in item_ids:
                if progress_callback:
                    progress_callback({"type": "start", "item_id": item_id})
                try:
                    if entry_type == "models":
                        res = self.migrate_single_model(item_id, delete_legacy)
                    else:
                        res = self.migrate_single_dataset(item_id, delete_legacy)
                    item_result = res.get("results", {}).get(item_id, {})
                    result["results"][item_id] = item_result
                    if item_result.get("success"):
                        result["success_count"] += 1
                    else:
                        result["failed_count"] += 1
                    if progress_callback:
                        progress_callback({"type": "complete", "item_id": item_id})
                except Exception as e:
                    result["results"][item_id] = {"success": False, "error": str(e)}
                    result["failed_count"] += 1
                    if progress_callback:
                        progress_callback({"type": "error", "item_id": item_id, "error": str(e)})
        except Exception as e:
            raise Exception(f"Migration failed: {e}")

        return result

    def sync_with_progress(
        self,
        action: str,
        entry_type: str,
        item_ids: List[str],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Sync items (download/upload) with real-time progress via WebSocket.

        Args:
            action: 'download' or 'upload'
            entry_type: 'models' or 'datasets'
            item_ids: List of item IDs to sync
            progress_callback: Called with progress updates

        Returns:
            Final result with success_count, failed_count, results
        """
        import websocket

        # Convert http URL to ws URL
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/storage/ws/sync"

        result = {"success_count": 0, "failed_count": 0, "results": {}}

        try:
            ws = websocket.create_connection(ws_url)

            # Send sync request
            ws.send(json.dumps({
                "action": action,
                "entry_type": entry_type,
                "item_ids": item_ids,
            }))

            # Receive progress updates until done
            while True:
                message = ws.recv()
                data = json.loads(message)

                if progress_callback:
                    progress_callback(data)

                if data.get("type") == "done":
                    result = data
                    break
                elif data.get("type") == "error" and "item_id" not in data:
                    # Global error
                    raise Exception(data.get("error", "Unknown error"))

            ws.close()
        except ImportError:
            # websocket-client not installed, fall back to HTTP
            if progress_callback:
                progress_callback({"type": "fallback", "message": "WebSocket not available, using HTTP"})
            for item_id in item_ids:
                if progress_callback:
                    progress_callback({"type": "start", "item_id": item_id})
                try:
                    if action == "download":
                        if entry_type == "models":
                            self.download_model(item_id)
                        else:
                            self.download_dataset(item_id)
                    else:  # upload
                        if entry_type == "models":
                            self.upload_model(item_id)
                        else:
                            self.upload_dataset(item_id)
                    result["results"][item_id] = {"success": True, "error": ""}
                    result["success_count"] += 1
                    if progress_callback:
                        progress_callback({"type": "complete", "item_id": item_id})
                except Exception as e:
                    result["results"][item_id] = {"success": False, "error": str(e)}
                    result["failed_count"] += 1
                    if progress_callback:
                        progress_callback({"type": "error", "item_id": item_id, "error": str(e)})
        except Exception as e:
            raise Exception(f"Sync failed: {e}")

        return result

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

    def list_training_configs(self) -> Dict[str, Any]:
        """GET /api/training/configs - List training configs."""
        response = self._client.get("/api/training/configs")
        response.raise_for_status()
        return response.json()

    def get_training_config(self, config_id: str) -> Dict[str, Any]:
        """GET /api/training/configs/{config_id} - Get config."""
        response = self._client.get(f"/api/training/configs/{config_id}")
        response.raise_for_status()
        return response.json()

    def create_training_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/training/configs - Create config."""
        response = self._client.post("/api/training/configs", json=data)
        response.raise_for_status()
        return response.json()

    def update_training_config(self, config_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """PUT /api/training/configs/{config_id} - Update config."""
        response = self._client.put(f"/api/training/configs/{config_id}", json=data)
        response.raise_for_status()
        return response.json()

    def delete_training_config(self, config_id: str) -> Dict[str, Any]:
        """DELETE /api/training/configs/{config_id} - Delete config."""
        response = self._client.delete(f"/api/training/configs/{config_id}")
        response.raise_for_status()
        return response.json()

    def validate_training_config(self, config_id: str) -> Dict[str, Any]:
        """GET /api/training/configs/{config_id}/validate - Validate."""
        response = self._client.get(f"/api/training/configs/{config_id}/validate")
        response.raise_for_status()
        return response.json()

    def dry_run_training(self, config_id: str) -> Dict[str, Any]:
        """POST /api/training/configs/{config_id}/dry-run - Dry run."""
        response = self._client.post(f"/api/training/configs/{config_id}/dry-run")
        response.raise_for_status()
        return response.json()

    def get_gpu_availability(self) -> Dict[str, Any]:
        """GET /api/training/gpu-availability - Check GPU availability.

        Returns availability info for all GPU model/count combinations.
        """
        response = self._client.get("/api/training/gpu-availability")
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
        except ImportError:
            if on_error:
                on_error("websocket-client not installed")
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

    def get_training_job_logs(self, job_id: str) -> Dict[str, Any]:
        """GET /api/training/jobs/{job_id}/logs - Get logs."""
        response = self._client.get(f"/api/training/jobs/{job_id}/logs")
        response.raise_for_status()
        return response.json()

    def stream_training_job_logs_ws(
        self,
        job_id: str,
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
        ws_url = f"{ws_url}/api/training/ws/jobs/{job_id}/logs"

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
        except ImportError:
            if on_error:
                on_error("websocket-client not installed")
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
        try:
            import websocket
        except ImportError:
            error_msg = "websocket-client not installed. Run: pip install websocket-client"
            if on_error:
                on_error(error_msg)
            return {"error": error_msg}

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
                    "name": "job_name",
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
                        "ip_assigned", "connecting_ssh", "ssh_ready", "deploying",
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
            # Create WebSocket with keepalive settings for long-running operations
            ws = websocket.create_connection(
                ws_url,
                timeout=None,  # No recv timeout (job creation can take 20+ minutes)
                skip_utf8_validation=True,
                enable_multithread=True,
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
        except ImportError:
            # websocket-client not installed
            error_msg = "websocket-client not installed. Run: pip install websocket-client"
            if progress_callback:
                progress_callback({"type": "error", "error": error_msg})
            result = {"type": "error", "error": error_msg}
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
        except ImportError:
            # websocket-client not installed
            if progress_callback:
                progress_callback({
                    "type": "error",
                    "error": "websocket-client not installed. Run: pip install websocket-client"
                })
            result = {"type": "error", "error": "websocket-client not installed"}
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
        import websocket

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
        except ImportError:
            if progress_callback:
                progress_callback({
                    "type": "error",
                    "error": "websocket-client not installed"
                })
            result = {"type": "error", "error": "websocket-client not installed"}
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
        import socket
        import websocket

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
