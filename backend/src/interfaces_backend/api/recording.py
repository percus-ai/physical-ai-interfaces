"""Recording API router with LeRobot integration."""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from interfaces_backend.models.recording import (
    CameraConfig,
    RecordingStartRequest,
    RecordingStartResponse,
    RecordingSession,
    RecordingStopRequest,
    RecordingStopResponse,
    RecordingSessionsResponse,
    RecordingInfo,
    RecordingListResponse,
    RecordingValidateResponse,
    RecordingExportRequest,
    RecordingExportResponse,
)

router = APIRouter(prefix="/api/recording", tags=["recording"])

# In-memory session storage
_sessions: Dict[str, dict] = {}

# Recordings storage directory
RECORDINGS_DIR = Path.cwd() / "datasets"


def _build_camera_entry(cam: CameraConfig) -> Dict[str, Any]:
    """Build camera configuration entry for LeRobot YAML.

    Based on Archive's 1_record_data.py build_camera_entry function.
    """
    cam_type = cam.camera_type.lower()
    entry: Dict[str, Any] = {"type": cam_type}

    if cam_type == "opencv":
        entry.update({
            "index_or_path": cam.index_or_path,
            "fps": cam.fps,
            "width": cam.width,
            "height": cam.height,
            "warmup_s": cam.warmup_s,
        })
        if cam.color_mode:
            entry["color_mode"] = cam.color_mode
        if cam.rotation is not None:
            entry["rotation"] = cam.rotation

    elif cam_type == "intelrealsense":
        entry.update({
            "serial_number_or_name": cam.index_or_path,
            "fps": cam.fps,
            "width": cam.width,
            "height": cam.height,
            "warmup_s": cam.warmup_s,
        })
        if cam.color_mode:
            entry["color_mode"] = cam.color_mode
        if cam.rotation is not None:
            entry["rotation"] = cam.rotation

    else:
        # Fallback for unknown types
        entry.update({
            "index_or_path": cam.index_or_path,
            "fps": cam.fps,
            "width": cam.width,
            "height": cam.height,
            "warmup_s": cam.warmup_s,
        })

    return entry


def _generate_session_name(username: str) -> str:
    """Generate session name with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{username}"


def _generate_episode_name(project_id: str) -> str:
    """Generate episode name based on existing episodes."""
    project_dir = RECORDINGS_DIR / project_id
    if not project_dir.exists():
        return "episode_001"

    existing = []
    for item in project_dir.iterdir():
        if item.is_dir() and item.name.startswith("episode_"):
            try:
                num = int(item.name.split("_")[1])
                existing.append(num)
            except (IndexError, ValueError):
                pass

    next_num = max(existing) + 1 if existing else 1
    return f"episode_{next_num:03d}"


def _run_lerobot_recording(session_id: str, config_file: str, session_data: dict) -> None:
    """Run lerobot-record in a background thread.

    Based on Archive's 1_record_data.py _record_episode function.
    """
    try:
        session_data["status"] = "recording"
        session_data["is_recording"] = True
        session_data["recording_started_at"] = datetime.now().isoformat()

        # Build command
        # Try to find the best way to run lerobot-record
        cmd = ["lerobot-record", f"--config={config_file}"]

        # Check if we should use conda
        conda_env = os.environ.get("LEROBOT_CONDA_ENV", "lerobot")
        use_conda = os.environ.get("USE_CONDA", "false").lower() == "true"

        if use_conda:
            cmd = [
                "conda", "run", "-n", conda_env,
                "--no-capture-output", "--live-stream",
                "lerobot-record", f"--config={config_file}"
            ]

        # Clear PYTHONPATH to avoid conflicts
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)

        # Run the recording process
        result = subprocess.run(
            cmd,
            cwd=str(RECORDINGS_DIR.parent),
            env=env,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            session_data["status"] = "completed"
            session_data["is_recording"] = False
        else:
            session_data["status"] = "failed"
            session_data["is_recording"] = False
            session_data["error_message"] = result.stderr or f"Exit code: {result.returncode}"

    except Exception as e:
        session_data["status"] = "failed"
        session_data["is_recording"] = False
        session_data["error_message"] = str(e)

    finally:
        # Cleanup config file
        try:
            if os.path.exists(config_file):
                os.remove(config_file)
        except Exception:
            pass

        # Update end time
        session_data["recording_ended_at"] = datetime.now().isoformat()

        # Calculate duration
        if session_data.get("recording_started_at"):
            try:
                start = datetime.fromisoformat(session_data["recording_started_at"])
                end = datetime.fromisoformat(session_data["recording_ended_at"])
                session_data["duration_seconds"] = (end - start).total_seconds()
            except Exception:
                pass


def _list_recordings(project_id: Optional[str] = None) -> list[dict]:
    """List stored recordings."""
    recordings = []

    if not RECORDINGS_DIR.exists():
        return recordings

    search_dirs = []
    if project_id:
        project_dir = RECORDINGS_DIR / project_id
        if project_dir.exists():
            search_dirs = [project_dir]
    else:
        search_dirs = [d for d in RECORDINGS_DIR.iterdir() if d.is_dir()]

    for project_dir in search_dirs:
        for episode_dir in project_dir.iterdir():
            if not episode_dir.is_dir():
                continue

            # Check for recording data (parquet files or meta.json)
            parquet_files = list(episode_dir.glob("*.parquet"))
            meta_file = episode_dir / "meta.json"

            if not parquet_files and not meta_file.exists():
                # Check subdirectories for LeRobot v2 format
                data_dir = episode_dir / "data"
                if data_dir.exists():
                    parquet_files = list(data_dir.glob("*.parquet"))

            if not parquet_files and not meta_file.exists():
                continue

            try:
                # Calculate size
                size_bytes = sum(
                    f.stat().st_size for f in episode_dir.rglob("*") if f.is_file()
                )
                size_mb = size_bytes / (1024 * 1024)

                # Get creation time
                created_at = datetime.fromtimestamp(
                    episode_dir.stat().st_mtime
                ).isoformat()

                # Count frames from parquet if available
                frames = 0
                if parquet_files:
                    try:
                        import pyarrow.parquet as pq
                        for pf in parquet_files:
                            table = pq.read_table(pf)
                            frames += len(table)
                    except ImportError:
                        pass
                    except Exception:
                        pass

                # Detect cameras from directory structure
                cameras = []
                videos_dir = episode_dir / "videos"
                if videos_dir.exists():
                    for vid_file in videos_dir.glob("*.mp4"):
                        cameras.append(vid_file.stem)
                else:
                    for cam_dir in episode_dir.iterdir():
                        if cam_dir.is_dir() and cam_dir.name.startswith(("cam", "camera", "observation")):
                            cameras.append(cam_dir.name)

                recordings.append({
                    "recording_id": f"{project_dir.name}/{episode_dir.name}",
                    "project_id": project_dir.name,
                    "episode_name": episode_dir.name,
                    "created_at": created_at,
                    "duration_seconds": 0.0,
                    "frames": frames,
                    "size_mb": size_mb,
                    "cameras": cameras,
                    "path": str(episode_dir),
                    "is_valid": True,
                })
            except Exception:
                continue

    return recordings


@router.post("/start", response_model=RecordingStartResponse)
async def start_recording(request: RecordingStartRequest):
    """Start a recording session.

    Creates a recording session configured for LeRobot data collection.
    Call /{session_id}/run to begin actual recording.
    """
    session_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # Generate session/episode name
    session_name = _generate_session_name(request.username)
    episode_name = request.episode_name or session_name

    # Create output directory
    output_path = RECORDINGS_DIR / request.project_id / episode_name

    try:
        output_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create output directory: {e}")

    # Build cameras dict for LeRobot config
    cameras_dict = {}
    camera_ids = []
    for cam in request.cameras:
        cameras_dict[cam.camera_id] = _build_camera_entry(cam)
        camera_ids.append(cam.camera_id)

    # Build LeRobot YAML config
    repo_id = f"{request.username}/{request.project_id}"

    lerobot_config = {
        "robot": {
            "type": f"{request.robot_type}_follower",
            "port": request.follower_port,
            "id": request.follower_id,
            "cameras": cameras_dict,
        },
        "teleop": {
            "type": f"{request.robot_type}_leader",
            "port": request.leader_port,
            "id": request.leader_id,
        },
        "dataset": {
            "repo_id": repo_id,
            "root": str(output_path),
            "single_task": request.task_description or f"Recording for {request.project_id}",
            "episode_time_s": request.episode_time_s,
            "reset_time_s": request.reset_time_s,
            "num_episodes": request.num_episodes,
            "private": True,
            "push_to_hub": False,
        },
        "display_data": True,
    }

    session_data = {
        "session_id": session_id,
        "project_id": request.project_id,
        "episode_name": episode_name,
        "status": "pending",
        "is_recording": False,
        "started_at": now,
        "frames_recorded": 0,
        "duration_seconds": 0.0,
        "cameras": camera_ids,
        "output_path": str(output_path),
        "leader_port": request.leader_port,
        "follower_port": request.follower_port,
        "leader_id": request.leader_id,
        "follower_id": request.follower_id,
        "fps": request.fps,
        "num_episodes": request.num_episodes,
        "current_episode": 0,
        "lerobot_config": lerobot_config,
        "config_file": None,
        "thread": None,
        "process": None,
        "error_message": None,
    }
    _sessions[session_id] = session_data

    return RecordingStartResponse(
        session=RecordingSession(
            session_id=session_id,
            project_id=request.project_id,
            episode_name=episode_name,
            status="pending",
            is_recording=False,
            started_at=now,
            frames_recorded=0,
            duration_seconds=0.0,
            cameras=camera_ids,
            output_path=str(output_path),
            num_episodes=request.num_episodes,
            current_episode=0,
            error_message=None,
        ),
        message="Recording session created. Call /{session_id}/run to start recording.",
    )


@router.post("/{session_id}/run")
async def run_recording(session_id: str):
    """Start running a recording session.

    This starts lerobot-record in a background thread.
    """
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    session = _sessions[session_id]

    if session.get("is_recording"):
        return {"session_id": session_id, "status": "already_recording", "message": "Already recording"}

    if session.get("status") == "completed":
        return {"session_id": session_id, "status": "completed", "message": "Recording already completed"}

    # Write LeRobot config to temp file
    try:
        import yaml

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(session["lerobot_config"], f)
            config_file = f.name

        session["config_file"] = config_file

    except ImportError:
        # Fallback to JSON if PyYAML not available
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(session["lerobot_config"], f)
            config_file = f.name
        session["config_file"] = config_file

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create config file: {e}")

    # Start recording in background thread
    thread = threading.Thread(
        target=_run_lerobot_recording,
        args=(session_id, config_file, session),
        daemon=True,
    )
    thread.start()
    session["thread"] = thread

    return {
        "session_id": session_id,
        "status": "recording",
        "message": "Recording started with lerobot-record",
        "config": session["lerobot_config"],
    }


@router.post("/stop", response_model=RecordingStopResponse)
async def stop_recording(request: RecordingStopRequest):
    """Stop a recording session."""
    session_id = request.session_id

    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    session = _sessions[session_id]

    # Try to stop lerobot-record process
    if session.get("is_recording"):
        try:
            # Kill lerobot-record processes
            subprocess.run(["pkill", "-f", "lerobot-record"], capture_output=True)
        except Exception:
            pass

    session["status"] = "stopped"
    session["is_recording"] = False

    # Calculate duration
    started_at = session.get("started_at", "")
    duration = session.get("duration_seconds", 0.0)
    if not duration and started_at:
        try:
            start = datetime.fromisoformat(started_at)
            duration = (datetime.now() - start).total_seconds()
        except Exception:
            pass

    frames = session.get("frames_recorded", 0)
    output_path = session.get("output_path")

    # Calculate output size
    size_mb = 0.0
    if output_path and Path(output_path).exists():
        try:
            size_bytes = sum(
                f.stat().st_size
                for f in Path(output_path).rglob("*")
                if f.is_file()
            )
            size_mb = size_bytes / (1024 * 1024)
        except Exception:
            pass

    # Cleanup config file
    config_file = session.get("config_file")
    if config_file and os.path.exists(config_file):
        try:
            os.remove(config_file)
        except Exception:
            pass

    # Remove session
    del _sessions[session_id]

    return RecordingStopResponse(
        session_id=session_id,
        success=True,
        message="Recording stopped",
        total_frames=frames,
        duration_seconds=duration,
        output_path=output_path,
        size_mb=size_mb,
    )


@router.get("/status/{session_id}", response_model=RecordingSession)
async def get_recording_status(session_id: str):
    """Get status of a recording session."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    s = _sessions[session_id]

    # Calculate current duration if recording
    duration = s.get("duration_seconds", 0.0)
    if s.get("is_recording") and s.get("recording_started_at"):
        try:
            start = datetime.fromisoformat(s["recording_started_at"])
            duration = (datetime.now() - start).total_seconds()
        except Exception:
            pass

    return RecordingSession(
        session_id=s["session_id"],
        project_id=s.get("project_id", ""),
        episode_name=s.get("episode_name", ""),
        status=s.get("status", "pending"),
        is_recording=s.get("is_recording", False),
        started_at=s.get("started_at", ""),
        frames_recorded=s.get("frames_recorded", 0),
        duration_seconds=duration,
        cameras=s.get("cameras", []),
        output_path=s.get("output_path"),
        num_episodes=s.get("num_episodes", 1),
        current_episode=s.get("current_episode", 0),
        error_message=s.get("error_message"),
    )


@router.get("/sessions", response_model=RecordingSessionsResponse)
async def list_recording_sessions():
    """List active recording sessions."""
    sessions = []
    for s in _sessions.values():
        duration = s.get("duration_seconds", 0.0)
        if s.get("is_recording") and s.get("recording_started_at"):
            try:
                start = datetime.fromisoformat(s["recording_started_at"])
                duration = (datetime.now() - start).total_seconds()
            except Exception:
                pass

        sessions.append(
            RecordingSession(
                session_id=s["session_id"],
                project_id=s.get("project_id", ""),
                episode_name=s.get("episode_name", ""),
                status=s.get("status", "pending"),
                is_recording=s.get("is_recording", False),
                started_at=s.get("started_at", ""),
                frames_recorded=s.get("frames_recorded", 0),
                duration_seconds=duration,
                cameras=s.get("cameras", []),
                output_path=s.get("output_path"),
                num_episodes=s.get("num_episodes", 1),
                current_episode=s.get("current_episode", 0),
                error_message=s.get("error_message"),
            )
        )

    return RecordingSessionsResponse(sessions=sessions, total=len(sessions))


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
            duration_seconds=r["duration_seconds"],
            frames=r["frames"],
            size_mb=r["size_mb"],
            cameras=r["cameras"],
            path=r["path"],
            is_valid=r["is_valid"],
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
    recording_path = RECORDINGS_DIR / project_id / episode_name

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
                duration_seconds=r["duration_seconds"],
                frames=r["frames"],
                size_mb=r["size_mb"],
                cameras=r["cameras"],
                path=r["path"],
                is_valid=r["is_valid"],
            )

    raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")


@router.delete("/recordings/{recording_id:path}")
async def delete_recording(recording_id: str):
    """Delete a stored recording."""
    parts = recording_id.split("/")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid recording ID format")

    project_id, episode_name = parts
    recording_path = RECORDINGS_DIR / project_id / episode_name

    if not recording_path.exists():
        raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")

    try:
        shutil.rmtree(recording_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete recording: {e}")

    return {"recording_id": recording_id, "message": "Recording deleted"}


@router.get("/recordings/{recording_id:path}/validate", response_model=RecordingValidateResponse)
async def validate_recording(recording_id: str):
    """Validate recording data quality."""
    parts = recording_id.split("/")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid recording ID format")

    project_id, episode_name = parts
    recording_path = RECORDINGS_DIR / project_id / episode_name

    if not recording_path.exists():
        raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")

    errors = []
    warnings = []
    stats = {}

    # Check for parquet files (LeRobot v2 format)
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

    # Analyze parquet files if available
    if parquet_files:
        try:
            import pyarrow.parquet as pq

            total_rows = 0
            for pf in parquet_files:
                table = pq.read_table(pf)
                total_rows += len(table)
                stats[pf.name] = {
                    "rows": len(table),
                    "columns": table.column_names,
                }

            stats["total_frames"] = total_rows

            if total_rows == 0:
                errors.append("Recording has no data frames")
            elif total_rows < 10:
                warnings.append(f"Recording has very few frames ({total_rows})")

        except ImportError:
            warnings.append("pyarrow not installed - cannot validate parquet files")
        except Exception as e:
            errors.append(f"Error reading parquet files: {e}")

    # Check for video files
    videos_dir = recording_path / "videos"
    if videos_dir.exists():
        video_files = list(videos_dir.glob("*.mp4"))
    else:
        video_files = list(recording_path.glob("*.mp4")) + list(recording_path.glob("*.avi"))
    stats["video_files"] = len(video_files)

    is_valid = len(errors) == 0

    return RecordingValidateResponse(
        recording_id=recording_id,
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        stats=stats,
    )


@router.post("/recordings/{recording_id:path}/export", response_model=RecordingExportResponse)
async def export_recording(recording_id: str, request: RecordingExportRequest):
    """Export recording to specified format."""
    parts = recording_id.split("/")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid recording ID format")

    project_id, episode_name = parts
    recording_path = RECORDINGS_DIR / project_id / episode_name

    if not recording_path.exists():
        raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")

    # Recording is already in LeRobot format
    size_mb = 0.0
    try:
        size_bytes = sum(
            f.stat().st_size for f in recording_path.rglob("*") if f.is_file()
        )
        size_mb = size_bytes / (1024 * 1024)
    except Exception:
        pass

    return RecordingExportResponse(
        recording_id=recording_id,
        success=True,
        message=f"Recording is in LeRobot format at {recording_path}",
        export_path=str(recording_path),
        size_mb=size_mb,
    )
