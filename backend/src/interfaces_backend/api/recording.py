"""Recording API router with LeRobot integration.

Simplified version that directly executes lerobot-record using project configuration.
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from percus_ai.db import get_supabase_client
from percus_ai.storage import (
    get_datasets_dir,
    get_projects_dir,
    get_user_devices_path,
    get_user_config_path,
)
from percus_ai.storage.r2_db_sync import R2DBSyncService

logger = logging.getLogger(__name__)

# Thread pool for R2 sync operations
_upload_executor = ThreadPoolExecutor(max_workers=2)

# Global instance for R2 sync
_sync_service: Optional[R2DBSyncService] = None


def _get_sync_service() -> R2DBSyncService:
    """Get or create DB-backed R2 sync service."""
    global _sync_service
    if _sync_service is None:
        _sync_service = R2DBSyncService()
    return _sync_service

router = APIRouter(prefix="/api/recording", tags=["recording"])


# --- Request/Response Models ---


class RecordRequest(BaseModel):
    """Simple recording request."""
    project_name: str
    num_episodes: int = 1
    username: Optional[str] = None


class RecordResponse(BaseModel):
    """Recording response."""
    success: bool
    message: str
    project_name: str
    output_path: Optional[str] = None
    return_code: int = 0


class RecordingInfo(BaseModel):
    """Recording information."""
    recording_id: str
    project_id: str
    episode_name: str
    created_at: str
    frames: int = 0
    size_mb: float = 0.0
    cameras: List[str] = []
    path: str


class RecordingListResponse(BaseModel):
    """List of recordings."""
    recordings: List[RecordingInfo]
    total: int


class RecordingValidateResponse(BaseModel):
    """Validation response."""
    recording_id: str
    is_valid: bool
    errors: List[str] = []
    warnings: List[str] = []


# --- Helper Functions ---


def _load_project_config(project_name: str) -> dict:
    """Load project configuration from YAML file."""
    projects_dir = get_projects_dir()
    yaml_path = projects_dir / f"{project_name}.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"Project not found: {project_name}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_device_config() -> dict:
    """Load device configuration from user_devices.json."""
    path = get_user_devices_path()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    raise FileNotFoundError(f"user_devices.json not found at {path}")


def _load_user_config() -> dict:
    """Load user configuration."""
    path = get_user_config_path()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        # Handle both flat and structured config formats
        user = raw.get("user", {})
        sync = raw.get("sync", {})
        recording = raw.get("recording", {})
        environment = raw.get("environment", {})

        return {
            "username": user.get("username", raw.get("username", "user")),
            "default_fps": recording.get("default_fps", raw.get("default_fps", 30)),
            "environment_name": environment.get("environment_name", raw.get("environment_name", "lerobot")),
            "auto_upload_after_recording": sync.get("auto_upload_after_recording", raw.get("auto_upload_after_recording", True)),
        }

    # Return defaults
    return {
        "username": "user",
        "default_fps": 30,
        "environment_name": "lerobot",
        "auto_upload_after_recording": True,
    }


def _upsert_dataset_record(
    dataset_id: str,
    project_id: str,
    name: str,
    episode_count: int,
    task_detail: str,
) -> None:
    client = get_supabase_client()
    payload = {
        "id": dataset_id,
        "project_id": project_id,
        "name": name,
        "episode_count": episode_count,
        "dataset_type": "recorded",
        "source": "r2",
        "status": "active",
        "task_detail": task_detail,
    }
    client.table("datasets").upsert(payload, on_conflict="id").execute()


def _build_camera_entry(
    cam_name: str,
    cam_settings: dict,
    cam_config: dict,
    default_fps: int
) -> Dict[str, Any]:
    """Build camera configuration entry for LeRobot YAML.

    Based on Archive's 1_record_data.py build_camera_entry function.
    """
    cam_type = (cam_config.get("type", "opencv") or "opencv").lower()
    cam_id = cam_config.get("id", 0)
    width = cam_settings.get("width", 640)
    height = cam_settings.get("height", 480)
    fps_val = cam_settings.get("fps", default_fps)
    warmup = cam_settings.get("warmup_time_s", cam_settings.get("warmup_s", 5))

    entry: Dict[str, Any] = {"type": cam_type}

    if cam_type == "opencv":
        entry.update({
            "index_or_path": int(cam_id) if str(cam_id).isdigit() else cam_id,
            "fps": fps_val,
            "width": width,
            "height": height,
            "warmup_s": warmup,
        })
        if "color_mode" in cam_settings:
            entry["color_mode"] = cam_settings["color_mode"]
        if "rotation" in cam_settings:
            entry["rotation"] = cam_settings["rotation"]
        if "fourcc" in cam_settings:
            entry["fourcc"] = cam_settings["fourcc"]

    elif cam_type == "intelrealsense":
        entry.update({
            "serial_number_or_name": cam_id,
            "fps": fps_val,
            "width": width,
            "height": height,
            "warmup_s": warmup,
        })
        if "color_mode" in cam_settings:
            entry["color_mode"] = cam_settings["color_mode"]
        if "rotation" in cam_settings:
            entry["rotation"] = cam_settings["rotation"]
        if "use_depth" in cam_settings:
            entry["use_depth"] = cam_settings["use_depth"]

    else:
        # Fallback
        entry.update({
            "index_or_path": cam_id,
            "fps": fps_val,
            "width": width,
            "height": height,
            "warmup_s": warmup,
        })

    return entry


def _resolve_port(device_config: dict, arm_type: str) -> Optional[str]:
    """Resolve serial port for leader/follower arm."""
    # Try different naming conventions
    candidates = [
        f"{arm_type}_right",
        f"{arm_type}_left",
        f"{arm_type}_arm",
        arm_type,
    ]

    for key in candidates:
        arm = device_config.get(key)
        if arm and arm.get("port"):
            return arm["port"]

    return None


def _resolve_id(device_config: dict, arm_type: str, default_id: str) -> str:
    """Resolve calibration ID for leader/follower arm."""
    candidates = [
        f"{arm_type}_right",
        f"{arm_type}_left",
        f"{arm_type}_arm",
        arm_type,
    ]

    for key in candidates:
        arm = device_config.get(key)
        if arm and arm.get("calibration_id"):
            return arm["calibration_id"]

    return default_id


def _list_recordings(project_id: Optional[str] = None) -> List[dict]:
    """List stored recordings."""
    recordings = []
    recordings_dir = get_datasets_dir()

    if not recordings_dir.exists():
        return recordings

    search_dirs = []
    if project_id:
        project_dir = recordings_dir / project_id
        if project_dir.exists():
            search_dirs = [project_dir]
    else:
        search_dirs = [d for d in recordings_dir.iterdir() if d.is_dir()]

    for project_dir in search_dirs:
        for episode_dir in project_dir.iterdir():
            if not episode_dir.is_dir():
                continue

            # Check for recording data
            parquet_files = list(episode_dir.glob("*.parquet"))
            meta_file = episode_dir / "meta.json"
            meta_info = episode_dir / "meta" / "info.json"
            data_dir = episode_dir / "data"
            if data_dir.exists():
                parquet_files.extend(list(data_dir.glob("*.parquet")))

            if not parquet_files and not meta_file.exists() and not meta_info.exists():
                continue

            try:
                size_bytes = sum(
                    f.stat().st_size for f in episode_dir.rglob("*") if f.is_file()
                )
                size_mb = size_bytes / (1024 * 1024)

                created_at = datetime.fromtimestamp(
                    episode_dir.stat().st_mtime
                ).isoformat()

                # Count frames
                frames = 0
                if meta_info.exists():
                    try:
                        with open(meta_info, "r", encoding="utf-8") as f:
                            info = json.load(f)
                        frames = int(info.get("total_frames") or 0)
                    except Exception:
                        frames = 0

                if frames == 0 and parquet_files:
                    try:
                        import pyarrow.parquet as pq
                        for pf in parquet_files:
                            table = pq.read_table(pf)
                            frames += len(table)
                    except Exception:
                        pass

                # Detect cameras
                cameras = []
                videos_dir = episode_dir / "videos"
                if videos_dir.exists():
                    for vid_file in videos_dir.glob("*.mp4"):
                        cameras.append(vid_file.stem)

                recordings.append({
                    "recording_id": f"{project_dir.name}/{episode_dir.name}",
                    "project_id": project_dir.name,
                    "episode_name": episode_dir.name,
                    "created_at": created_at,
                    "frames": frames,
                    "size_mb": size_mb,
                    "cameras": cameras,
                    "path": str(episode_dir),
                })
            except Exception:
                continue

    return recordings


# --- API Endpoints ---


@router.post("/record", response_model=RecordResponse)
async def record(request: RecordRequest):
    """Start recording directly using project configuration.

    This is the simplified recording endpoint that:
    1. Loads project config from YAML
    2. Loads device config from user_devices.json
    3. Builds lerobot-record YAML config
    4. Executes lerobot-record synchronously
    """
    project_name = request.project_name
    num_episodes = request.num_episodes

    # Load configurations
    try:
        project_config = _load_project_config(project_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        device_config = _load_device_config()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    user_config = _load_user_config()
    username = request.username or user_config.get("username", "user")
    fps = user_config.get("default_fps", 30)

    # Extract project settings
    project = project_config.get("project", {})
    recording = project_config.get("recording", {})
    cameras_settings = project_config.get("cameras", {})

    project_id = project.get("name", project_name)
    description = project.get("description", f"Recording for {project_name}")
    episode_time_s = recording.get("episode_time_s", 60)
    reset_time_s = recording.get("reset_time_s", 10)

    # Resolve ports and IDs
    follower_port = _resolve_port(device_config, "follower")
    leader_port = _resolve_port(device_config, "leader")

    if not follower_port or not leader_port:
        raise HTTPException(
            status_code=400,
            detail="Leader or follower port not configured in user_devices.json"
        )

    follower_id = _resolve_id(device_config, "follower", "so101_follower")
    leader_id = _resolve_id(device_config, "leader", "so101_leader")

    # Build cameras config
    cameras_dict = {}
    for cam_name, cam_settings in cameras_settings.items():
        cam_config = device_config.get("cameras", {}).get(cam_name, {})
        if cam_config:
            cameras_dict[cam_name] = _build_camera_entry(
                cam_name, cam_settings or {}, cam_config, fps
            )

    # Generate output path
    # Use dynamic path resolution
    recordings_dir = get_datasets_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_name = f"{timestamp}_{username}"
    output_path = recordings_dir / project_id / session_name
    # Don't create the directory - lerobot-record creates it internally
    # Only ensure parent (project) directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    repo_id = f"{username}/{project_id}"

    # Build LeRobot YAML config
    lerobot_config = {
        "robot": {
            "type": "so101_follower",
            "port": follower_port,
            "id": follower_id,
            "cameras": cameras_dict,
        },
        "teleop": {
            "type": "so101_leader",
            "port": leader_port,
            "id": leader_id,
        },
        "dataset": {
            "repo_id": repo_id,
            "root": str(output_path),
            "single_task": description,
            "episode_time_s": episode_time_s,
            "reset_time_s": reset_time_s,
            "num_episodes": num_episodes,
            "private": True,
            "push_to_hub": False,
        },
        "display_data": True,
    }

    # Write config to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(lerobot_config, f)
        config_file = f.name

    try:
        # Build command
        cmd = ["lerobot-record", f"--config={config_file}"]

        # Check if we should use conda
        conda_env = user_config.get("environment_name", "lerobot")
        use_conda = os.environ.get("USE_CONDA", "false").lower() == "true"

        if use_conda:
            cmd = [
                "conda", "run", "-n", conda_env,
                "--no-capture-output", "--live-stream",
                "lerobot-record", f"--config={config_file}"
            ]

        # Clear PYTHONPATH
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)

        # Execute lerobot-record
        result = subprocess.run(
            cmd,
            cwd=str(recordings_dir.parent),
            env=env,
            capture_output=False,  # Allow real-time output
        )

        success = result.returncode == 0
        message = "Recording completed" if success else f"Recording failed (exit code: {result.returncode})"

        dataset_id = None
        if success:
            dataset_id = f"{project_id}/{session_name}"
            _upsert_dataset_record(
                dataset_id=dataset_id,
                project_id=project_id,
                name=session_name,
                episode_count=int(num_episodes),
                task_detail=description,
            )

        # Auto-upload to R2 if enabled and recording succeeded
        if success and user_config.get("auto_upload_after_recording", True):
            try:
                sync_service = _get_sync_service()
                ok, error = sync_service.upload_dataset_with_progress(dataset_id, None)
                if ok:
                    message = "Recording completed and uploaded to R2"
                    logger.info(f"Auto-uploaded dataset {dataset_id} to R2")
                else:
                    message = f"Recording completed but upload failed: {error}"
                    logger.error(f"Auto-upload failed for {dataset_id}: {error}")
            except Exception as e:
                logger.error(f"Auto-upload failed for {project_id}/{session_name}: {e}")
                message = f"Recording completed but upload failed: {e}"

        return RecordResponse(
            success=success,
            message=message,
            project_name=project_name,
            output_path=str(output_path),
            return_code=result.returncode,
        )

    finally:
        # Cleanup
        subprocess.run(["pkill", "-f", "lerobot-record"], capture_output=True)
        if os.path.exists(config_file):
            os.remove(config_file)


# Store active recording process for cancellation
_active_recording_process: Optional[asyncio.subprocess.Process] = None


@router.websocket("/ws/record")
async def websocket_record(websocket: WebSocket):
    """WebSocket endpoint for recording with real-time output streaming.

    Client sends:
        {
            "project_name": "...",
            "num_episodes": 1,
            "username": "user"  # optional
        }

    Server sends:
        {"type": "start", "project_name": "...", "output_path": "..."}
        {"type": "output", "line": "..."}  # stdout lines
        {"type": "error_output", "line": "..."}  # stderr lines
        {"type": "complete", "success": true, "return_code": 0, "output_path": "..."}
        {"type": "error", "error": "..."}

    Client can send to stop:
        {"action": "stop"}
    """
    global _active_recording_process

    await websocket.accept()
    logger.info("WebSocket /ws/record accepted")
    config_file = None

    try:
        # Receive recording request
        logger.info("Waiting for recording request...")
        data = await websocket.receive_json()
        logger.info(f"Received recording request: {data}")

        # Handle stop action
        if data.get("action") == "stop":
            if _active_recording_process:
                _active_recording_process.terminate()
                await websocket.send_json({
                    "type": "stopped",
                    "message": "Recording stopped by user"
                })
            await websocket.close()
            return

        project_name = data.get("project_name")
        num_episodes = data.get("num_episodes", 1)
        username = data.get("username")

        if not project_name:
            await websocket.send_json({
                "type": "error",
                "error": "project_name is required"
            })
            await websocket.close()
            return

        # Load configurations
        try:
            logger.info(f"Loading project config for: {project_name}")
            project_config = _load_project_config(project_name)
            logger.info(f"Loaded project config: {project_config.get('project', {}).get('name', 'N/A')}")
        except FileNotFoundError as e:
            logger.error(f"Project config not found: {e}")
            await websocket.send_json({
                "type": "error",
                "error": str(e)
            })
            await websocket.close()
            return

        try:
            logger.info("Loading device config...")
            device_config = _load_device_config()
            logger.info(f"Loaded device config: {list(device_config.keys())}")
        except FileNotFoundError as e:
            logger.error(f"Device config not found: {e}")
            await websocket.send_json({
                "type": "error",
                "error": str(e)
            })
            await websocket.close()
            return

        user_config = _load_user_config()
        logger.info(f"Loaded user config: username={user_config.get('username', 'N/A')}")
        username = username or user_config.get("username", "user")
        fps = user_config.get("default_fps", 30)

        # Extract project settings
        project = project_config.get("project", {})
        recording = project_config.get("recording", {})
        cameras_settings = project_config.get("cameras", {})

        project_id = project.get("name", project_name)
        description = project.get("description", f"Recording for {project_name}")
        episode_time_s = recording.get("episode_time_s", 60)
        reset_time_s = recording.get("reset_time_s", 10)

        # Resolve ports and IDs
        follower_port = _resolve_port(device_config, "follower")
        leader_port = _resolve_port(device_config, "leader")

        if not follower_port or not leader_port:
            await websocket.send_json({
                "type": "error",
                "error": "Leader or follower port not configured in user_devices.json"
            })
            await websocket.close()
            return

        follower_id = _resolve_id(device_config, "follower", "so101_follower")
        leader_id = _resolve_id(device_config, "leader", "so101_leader")

        # Build cameras config
        cameras_dict = {}
        for cam_name, cam_settings in cameras_settings.items():
            cam_config = device_config.get("cameras", {}).get(cam_name, {})
            if cam_config:
                cameras_dict[cam_name] = _build_camera_entry(
                    cam_name, cam_settings or {}, cam_config, fps
                )

        # Generate output path
        recordings_dir = get_datasets_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_name = f"{timestamp}_{username}"
        output_path = recordings_dir / project_id / session_name
        # Don't create the directory - lerobot-record creates it internally
        # Only ensure parent (project) directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        repo_id = f"{username}/{project_id}"

        # Build LeRobot YAML config
        lerobot_config = {
            "robot": {
                "type": "so101_follower",
                "port": follower_port,
                "id": follower_id,
                "cameras": cameras_dict,
            },
            "teleop": {
                "type": "so101_leader",
                "port": leader_port,
                "id": leader_id,
            },
            "dataset": {
                "repo_id": repo_id,
                "root": str(output_path),
                "single_task": description,
                "episode_time_s": episode_time_s,
                "reset_time_s": reset_time_s,
                "num_episodes": num_episodes,
                "private": True,
                "push_to_hub": False,
            },
            "display_data": True,
        }

        # Write config to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(lerobot_config, f)
            config_file = f.name

        # Build command
        cmd = ["lerobot-record", f"--config={config_file}"]

        # Check if we should use conda
        conda_env = user_config.get("environment_name", "lerobot")
        use_conda = os.environ.get("USE_CONDA", "false").lower() == "true"

        if use_conda:
            cmd = [
                "conda", "run", "-n", conda_env,
                "--no-capture-output", "--live-stream",
                "lerobot-record", f"--config={config_file}"
            ]

        # Clear PYTHONPATH
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)

        logger.info(f"Starting recording: cmd={cmd}")
        logger.info(f"Output path: {output_path}")

        # Send start notification
        await websocket.send_json({
            "type": "start",
            "project_name": project_name,
            "output_path": str(output_path),
            "num_episodes": num_episodes,
        })
        logger.info("Sent start notification to WebSocket")

        # Run subprocess with output streaming
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(recordings_dir.parent),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info(f"Subprocess started with PID: {process.pid}")

        _active_recording_process = process

        async def read_stream(stream, output_type):
            """Read from stream and send to websocket."""
            while True:
                line = await stream.readline()
                if not line:
                    break
                try:
                    text = line.decode("utf-8", errors="replace").rstrip()
                    if text:
                        await websocket.send_json({
                            "type": output_type,
                            "line": text,
                        })
                        # Log subprocess output to file
                        if output_type == "error_output":
                            logger.error(f"[subprocess] {text}")
                        else:
                            logger.debug(f"[subprocess] {text}")
                except Exception:
                    pass

        # Also listen for stop commands while streaming
        async def listen_for_stop():
            """Listen for stop command from client."""
            try:
                while process.returncode is None:
                    try:
                        msg = await asyncio.wait_for(
                            websocket.receive_json(),
                            timeout=1.0
                        )
                        if msg.get("action") == "stop":
                            if process.returncode is None:
                                process.terminate()
                            break
                    except asyncio.TimeoutError:
                        continue  # Check if process ended, then continue waiting
            except WebSocketDisconnect:
                if process.returncode is None:
                    process.terminate()
            except Exception:
                pass

        # Create tasks for concurrent execution
        stdout_task = asyncio.create_task(read_stream(process.stdout, "output"))
        stderr_task = asyncio.create_task(read_stream(process.stderr, "error_output"))
        stop_task = asyncio.create_task(listen_for_stop())

        # Wait for streams to complete (process finished)
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

        # Cancel stop listener since process is done
        stop_task.cancel()
        try:
            await stop_task
        except asyncio.CancelledError:
            pass

        # Get return code
        return_code = await process.wait()

        _active_recording_process = None

        success = return_code == 0
        message = "Recording completed" if success else f"Recording failed (exit code: {return_code})"
        logger.info(f"Recording finished with return_code={return_code}, success={success}")

        dataset_id = None
        if success:
            dataset_id = f"{project_id}/{session_name}"
            _upsert_dataset_record(
                dataset_id=dataset_id,
                project_id=project_id,
                name=session_name,
                episode_count=int(num_episodes),
                task_detail=description,
            )

        # Auto-upload to R2 if enabled and recording succeeded
        upload_status = None
        auto_upload_enabled = user_config.get("auto_upload_after_recording", True)
        logger.info(f"Auto-upload check: success={success}, auto_upload_enabled={auto_upload_enabled}")

        if success and auto_upload_enabled:
            try:
                logger.info("Starting auto-upload to R2...")
                sync_service = _get_sync_service()
                logger.info(f"Uploading dataset: {dataset_id}")

                # Queue for progress updates from thread
                progress_queue: asyncio.Queue = asyncio.Queue()
                main_loop = asyncio.get_running_loop()

                def progress_callback(progress: dict):
                    """Callback to put progress in queue (called from thread)."""
                    asyncio.run_coroutine_threadsafe(
                        progress_queue.put(progress),
                        main_loop
                    )

                async def run_upload():
                    """Run upload in thread pool."""
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(
                        _upload_executor,
                        lambda: sync_service.upload_dataset_with_progress(
                            dataset_id, progress_callback
                        )
                    )

                # Start upload task
                upload_task = asyncio.create_task(run_upload())

                # Forward progress updates to WebSocket
                while True:
                    try:
                        progress = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                        # Forward progress to client with upload prefix
                        # Create a copy without "type" to avoid overwriting the prefixed type
                        progress_data = {k: v for k, v in progress.items() if k != "type"}
                        await websocket.send_json({
                            "type": f"upload_{progress.get('type', 'progress')}",
                            **progress_data,
                        })

                        if progress.get("type") in ("complete", "error"):
                            break
                    except asyncio.TimeoutError:
                        if upload_task.done():
                            # Drain remaining queue items
                            while not progress_queue.empty():
                                progress = await progress_queue.get()
                                progress_data = {k: v for k, v in progress.items() if k != "type"}
                                await websocket.send_json({
                                    "type": f"upload_{progress.get('type', 'progress')}",
                                    **progress_data,
                                })
                            break

                # Get result
                try:
                    upload_success, upload_error = await upload_task
                    if upload_success:
                        message = "Recording completed and uploaded to R2"
                        upload_status = "success"
                        logger.info(f"Auto-uploaded dataset {dataset_id} to R2")
                    else:
                        message = f"Recording completed but upload failed: {upload_error}"
                        upload_status = "failed"
                        logger.error(f"Auto-upload failed for {dataset_id}: {upload_error}")
                except Exception as e:
                    logger.error(f"Auto-upload task failed for {dataset_id}: {e}")
                    message = f"Recording completed but upload failed: {e}"
                    upload_status = "failed"

            except Exception as e:
                logger.error(f"Auto-upload failed for {project_id}/{session_name}: {e}")
                message = f"Recording completed but upload failed: {e}"
                upload_status = "failed"

        # Send completion notification
        logger.info(f"Sending complete notification: success={success}, message={message}")
        await websocket.send_json({
            "type": "complete",
            "success": success,
            "return_code": return_code,
            "output_path": str(output_path),
            "message": message,
            "upload_status": upload_status,
        })
        logger.info("Complete notification sent")

    except WebSocketDisconnect:
        # Client disconnected, terminate process if running
        logger.info("WebSocket disconnected by client")
        if _active_recording_process and _active_recording_process.returncode is None:
            _active_recording_process.terminate()
        _active_recording_process = None
    except Exception as e:
        logger.exception(f"WebSocket handler error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "error": str(e),
            })
        except Exception:
            pass
    finally:
        _active_recording_process = None
        # Cleanup
        subprocess.run(["pkill", "-f", "lerobot-record"], capture_output=True)
        if config_file and os.path.exists(config_file):
            os.remove(config_file)
        try:
            # Small delay to ensure final message is transmitted before closing
            await asyncio.sleep(0.2)
            await websocket.close()
        except Exception:
            pass


@router.get("/recordings", response_model=RecordingListResponse)
async def list_recordings(project_id: Optional[str] = None):
    """List stored recordings."""
    recordings_data = _list_recordings(project_id)

    recordings = [
        RecordingInfo(
            recording_id=r["recording_id"],
            project_id=r["project_id"],
            episode_name=r["episode_name"],
            created_at=r["created_at"],
            frames=r["frames"],
            size_mb=r["size_mb"],
            cameras=r["cameras"],
            path=r["path"],
        )
        for r in recordings_data
    ]

    return RecordingListResponse(recordings=recordings, total=len(recordings))


@router.get("/recordings/{recording_id:path}/validate", response_model=RecordingValidateResponse)
async def validate_recording(recording_id: str):
    """Validate recording data."""
    parts = recording_id.split("/")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid recording ID format")

    project_id, episode_name = parts
    recordings_dir = get_datasets_dir()
    recording_path = recordings_dir / project_id / episode_name

    if not recording_path.exists():
        raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")

    errors = []
    warnings = []

    # Check for parquet files
    parquet_files = list(recording_path.glob("*.parquet"))
    data_dir = recording_path / "data"
    if data_dir.exists():
        parquet_files.extend(list(data_dir.glob("*.parquet")))

    if not parquet_files:
        errors.append("No parquet files found")

    # Check for metadata
    meta_file = recording_path / "meta" / "info.json"
    if not meta_file.exists():
        meta_file = recording_path / "meta.json"
    if not meta_file.exists():
        warnings.append("Missing metadata file")

    is_valid = len(errors) == 0

    return RecordingValidateResponse(
        recording_id=recording_id,
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
    )


@router.get("/recordings/{recording_id:path}", response_model=RecordingInfo)
async def get_recording(recording_id: str):
    """Get recording details."""
    parts = recording_id.split("/")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid recording ID format")

    project_id, episode_name = parts
    recordings_dir = get_datasets_dir()
    recording_path = recordings_dir / project_id / episode_name

    if not recording_path.exists():
        raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")

    recordings = _list_recordings(project_id)
    for r in recordings:
        if r["episode_name"] == episode_name:
            return RecordingInfo(
                recording_id=r["recording_id"],
                project_id=r["project_id"],
                episode_name=r["episode_name"],
                created_at=r["created_at"],
                frames=r["frames"],
                size_mb=r["size_mb"],
                cameras=r["cameras"],
                path=r["path"],
            )

    raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")


@router.delete("/recordings/{recording_id:path}")
async def delete_recording(recording_id: str):
    """Delete a stored recording."""
    parts = recording_id.split("/")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid recording ID format")

    project_id, episode_name = parts
    recordings_dir = get_datasets_dir()
    recording_path = recordings_dir / project_id / episode_name

    if not recording_path.exists():
        raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")

    try:
        shutil.rmtree(recording_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete recording: {e}")

    return {"recording_id": recording_id, "message": "Recording deleted"}
