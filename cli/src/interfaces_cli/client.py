"""HTTP client for Backend API.

Auto-generated based on OpenAPI schema from /openapi.json
"""

import os
from typing import Any, Dict, Optional

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

    def list_recording_sessions(self) -> Dict[str, Any]:
        """GET /api/recording/sessions - List recording sessions."""
        response = self._client.get("/api/recording/sessions")
        response.raise_for_status()
        return response.json()

    def get_recording_status(self, session_id: str) -> Dict[str, Any]:
        """GET /api/recording/status/{session_id} - Get recording status."""
        response = self._client.get(f"/api/recording/status/{session_id}")
        response.raise_for_status()
        return response.json()

    def start_recording(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/recording/start - Start recording session."""
        response = self._client.post("/api/recording/start", json=data)
        response.raise_for_status()
        return response.json()

    def stop_recording(self, session_id: str) -> Dict[str, Any]:
        """POST /api/recording/stop - Stop recording session."""
        response = self._client.post("/api/recording/stop", json={"session_id": session_id})
        response.raise_for_status()
        return response.json()

    def run_recording(self, session_id: str) -> Dict[str, Any]:
        """POST /api/recording/{session_id}/run - Run recording."""
        response = self._client.post(f"/api/recording/{session_id}/run")
        response.raise_for_status()
        return response.json()

    def delete_recording(self, recording_id: str) -> Dict[str, Any]:
        """DELETE /api/recording/recordings/{recording_id} - Delete recording."""
        response = self._client.delete(f"/api/recording/recordings/{recording_id}")
        response.raise_for_status()
        return response.json()

    def export_recording(self, recording_id: str) -> Dict[str, Any]:
        """POST /api/recording/recordings/{recording_id}/export - Export."""
        response = self._client.post(f"/api/recording/recordings/{recording_id}/export")
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
        response.raise_for_status()
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
