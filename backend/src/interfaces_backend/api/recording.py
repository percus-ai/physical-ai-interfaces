"""Recording API router with LeRobot integration.

Simplified version that directly executes lerobot-record using project configuration.
"""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from interfaces_backend.utils.paths import get_datasets_dir, get_projects_dir, get_data_dir

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
    # Try multiple locations
    candidates = [
        get_data_dir() / "user_devices.json",
        Path.cwd() / "user_devices.json",
        Path.cwd() / "data" / "user_devices.json",
    ]

    for path in candidates:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

    raise FileNotFoundError("user_devices.json not found")


def _load_user_config() -> dict:
    """Load user configuration."""
    candidates = [
        get_data_dir() / "user_config.yaml",
        Path.cwd() / "user_config.yaml",
        Path.cwd() / "data" / "user_config.yaml",
    ]

    for path in candidates:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)

    # Return defaults
    return {
        "username": "user",
        "default_fps": 30,
        "environment_name": "lerobot",
    }


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
            data_dir = episode_dir / "data"
            if data_dir.exists():
                parquet_files.extend(list(data_dir.glob("*.parquet")))

            if not parquet_files and not meta_file.exists():
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
                if parquet_files:
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
    config_file = None

    try:
        # Receive recording request
        data = await websocket.receive_json()

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
            project_config = _load_project_config(project_name)
        except FileNotFoundError as e:
            await websocket.send_json({
                "type": "error",
                "error": str(e)
            })
            await websocket.close()
            return

        try:
            device_config = _load_device_config()
        except FileNotFoundError as e:
            await websocket.send_json({
                "type": "error",
                "error": str(e)
            })
            await websocket.close()
            return

        user_config = _load_user_config()
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

        # Send start notification
        await websocket.send_json({
            "type": "start",
            "project_name": project_name,
            "output_path": str(output_path),
            "num_episodes": num_episodes,
        })

        # Run subprocess with output streaming
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(recordings_dir.parent),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

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

        # Send completion notification
        await websocket.send_json({
            "type": "complete",
            "success": return_code == 0,
            "return_code": return_code,
            "output_path": str(output_path),
            "message": "Recording completed" if return_code == 0 else f"Recording failed (exit code: {return_code})",
        })

    except WebSocketDisconnect:
        # Client disconnected, terminate process if running
        if _active_recording_process and _active_recording_process.returncode is None:
            _active_recording_process.terminate()
        _active_recording_process = None
    except Exception as e:
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
