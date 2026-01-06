"""Inference API router."""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from interfaces_backend.models.inference import (
    InferenceModelInfo,
    InferenceModelsResponse,
    InferenceDeviceCompatibility,
    InferenceDeviceCompatibilityResponse,
    InferenceRunRequest,
    InferenceRunResponse,
)
from percus_ai.inference import PolicyExecutor, detect_device as percus_detect_device
from percus_ai.storage import (
    get_data_dir,
    get_models_dir,
    get_project_root,
    get_user_config_path,
    ManifestManager,
    R2SyncService,
)

logger = logging.getLogger(__name__)

# Global instances for R2 sync
_manifest_manager: Optional[ManifestManager] = None
_sync_service: Optional[R2SyncService] = None


def _get_manifest() -> ManifestManager:
    """Get or create manifest manager."""
    global _manifest_manager
    if _manifest_manager is None:
        _manifest_manager = ManifestManager()
    return _manifest_manager


def _get_sync_service() -> R2SyncService:
    """Get or create R2 sync service."""
    global _sync_service
    if _sync_service is None:
        bucket = os.getenv("R2_BUCKET", "percus-data")
        version = os.getenv("R2_VERSION", "v2")
        _sync_service = R2SyncService(_get_manifest(), bucket, version=version)
    return _sync_service


def _load_user_config() -> dict:
    """Load user configuration for auto_download_models setting."""
    path = get_user_config_path()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        sync = raw.get("sync", {})
        return {
            "auto_download_models": sync.get("auto_download_models", raw.get("auto_download_models", True)),
        }
    return {"auto_download_models": True}

router = APIRouter(prefix="/api/inference", tags=["inference"])

# Models directory (integrated with storage system)
MODELS_DIR = get_models_dir()

# Repository root
_REPO_ROOT = get_project_root()

# Environment scripts (now in features/percus_ai/environment/)
RUN_IN_ENV_SCRIPT = _REPO_ROOT / "features" / "percus_ai" / "environment" / "run_in_env.sh"
POLICY_MAP_FILE = _REPO_ROOT / "envs" / "policy_map.yaml"


def _get_policy_type(model_path: Path) -> Optional[str]:
    """Get policy type from model's config.json."""
    config_path = model_path / "config.json"
    if not config_path.exists():
        # Search subdirectories (e.g. HuggingFace format)
        for p in model_path.glob("**/config.json"):
            config_path = p
            break

    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
                return config.get("type")
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _get_env_for_policy(policy_type: str) -> str:
    """Get environment name for policy type from policy_map.yaml."""
    if not POLICY_MAP_FILE.exists():
        return "act"  # Default fallback

    try:
        with open(POLICY_MAP_FILE) as f:
            policy_map = yaml.safe_load(f)

        environments = policy_map.get("environments", {})
        for env_config in environments.values():
            policies = env_config.get("policies", [])
            if policy_type in policies:
                # Return short name (without .venv- prefix)
                venv = env_config["venv"]
                return venv.replace(".venv-", "")

        # Return default environment
        return policy_map.get("default_environment", "act")
    except Exception:
        return "act"


def _detect_device() -> str:
    """Detect best available compute device."""
    try:
        return percus_detect_device()
    except Exception:
        # Fallback detection (via subprocess to avoid numpy conflicts)
        from interfaces_backend.utils.torch_info import get_torch_info
        torch_info = get_torch_info()
        if torch_info.get("cuda_available"):
            return "cuda"
        elif torch_info.get("mps_available"):
            return "mps"
        return "cpu"


def _list_models() -> list[dict]:
    """List available models for inference from storage directories."""
    import json

    if not MODELS_DIR.exists():
        return []

    models = []

    # Scan subdirectories: r2/, hub/, and direct models
    subdirs_to_scan = []

    # Add r2 models
    r2_dir = MODELS_DIR / "r2"
    if r2_dir.exists():
        subdirs_to_scan.extend(r2_dir.iterdir())

    # Add hub models
    hub_dir = MODELS_DIR / "hub"
    if hub_dir.exists():
        subdirs_to_scan.extend(hub_dir.iterdir())

    # Add direct models (for backward compatibility)
    for item in MODELS_DIR.iterdir():
        if item.is_dir() and item.name not in ("r2", "hub"):
            subdirs_to_scan.append(item)

    for model_dir in subdirs_to_scan:
        if not model_dir.is_dir():
            continue

        config_file = model_dir / "config.json"
        if not config_file.exists():
            continue

        try:
            with open(config_file) as f:
                config = json.load(f)

            # Determine source from path
            source = "local"
            if "r2" in model_dir.parts:
                source = "r2"
            elif "hub" in model_dir.parts:
                source = "hub"

            models.append({
                "model_id": model_dir.name,
                "name": model_dir.name,
                "policy_type": config.get("type", "unknown"),
                "local_path": str(model_dir),
                "source": source,
                "size_mb": sum(
                    f.stat().st_size for f in model_dir.rglob("*") if f.is_file()
                ) / (1024 * 1024),
            })
        except Exception:
            continue

    return models


@router.get("/models", response_model=InferenceModelsResponse)
async def list_inference_models():
    """List models available for inference."""
    models_data = _list_models()

    models = []
    for m in models_data:
        models.append(
            InferenceModelInfo(
                model_id=m.get("model_id", m.get("name", "")),
                name=m.get("name", ""),
                policy_type=m.get("policy_type", "unknown"),
                local_path=m.get("local_path"),
                size_mb=m.get("size_mb", 0.0),
                is_loaded=False,  # No longer tracking loaded state
            )
        )

    return InferenceModelsResponse(models=models, total=len(models))


@router.get("/device-compatibility", response_model=InferenceDeviceCompatibilityResponse)
async def get_device_compatibility():
    """Check device compatibility for inference."""
    devices = []

    # Check CUDA
    cuda_available = False
    cuda_memory_total = None
    cuda_memory_free = None

    # Get CUDA/MPS info via subprocess to avoid numpy conflicts
    from interfaces_backend.utils.torch_info import get_torch_info
    torch_info = get_torch_info()

    if torch_info.get("cuda_available"):
        cuda_available = True
        cuda_memory_total = torch_info.get("cuda_memory_total")
        cuda_memory_free = torch_info.get("cuda_memory_free")

    devices.append(
        InferenceDeviceCompatibility(
            device="cuda",
            available=cuda_available,
            memory_total_mb=cuda_memory_total,
            memory_free_mb=cuda_memory_free,
        )
    )

    # Check MPS (Apple Silicon)
    mps_available = torch_info.get("mps_available", False)

    devices.append(
        InferenceDeviceCompatibility(
            device="mps",
            available=mps_available,
            memory_total_mb=None,
            memory_free_mb=None,
        )
    )

    # CPU is always available
    devices.append(
        InferenceDeviceCompatibility(
            device="cpu",
            available=True,
            memory_total_mb=None,
            memory_free_mb=None,
        )
    )

    # Determine recommended device
    if cuda_available:
        recommended = "cuda"
    elif mps_available:
        recommended = "mps"
    else:
        recommended = "cpu"

    return InferenceDeviceCompatibilityResponse(
        devices=devices,
        recommended=recommended,
    )


def _find_model_path(model_id: str, auto_download: bool = True) -> Optional[Path]:
    """Find model path in storage directories.

    If model is not found locally and auto_download is enabled,
    attempts to download from R2.
    """
    # Check R2 models
    r2_path = MODELS_DIR / "r2" / model_id
    if r2_path.exists():
        return r2_path

    # Check Hub models
    hub_path = MODELS_DIR / "hub" / model_id
    if hub_path.exists():
        return hub_path

    # Check direct models directory
    direct_path = MODELS_DIR / model_id
    if direct_path.exists():
        return direct_path

    # Model not found locally - try R2 fallback download if enabled
    if auto_download:
        user_config = _load_user_config()
        if user_config.get("auto_download_models", True):
            try:
                logger.info(f"Model {model_id} not found locally, checking R2...")
                sync_service = _get_sync_service()
                remote_models = sync_service.list_remote_models()

                if model_id in remote_models:
                    logger.info(f"Downloading model {model_id} from R2...")
                    sync_service.download_model(model_id)
                    # After download, model should be in r2 directory
                    if r2_path.exists():
                        logger.info(f"Successfully downloaded model {model_id} from R2")
                        return r2_path
            except Exception as e:
                logger.warning(f"R2 fallback download failed for {model_id}: {e}")

    return None


@router.post("/run", response_model=InferenceRunResponse)
async def run_inference(request: InferenceRunRequest):
    """Run inference on robot with the specified model.

    Uses run_in_env.sh to execute percus_ai.inference.cli in the appropriate
    policy environment (e.g., .venv-pi0 for pi05 models) with bundled-torch
    PYTHONPATH injection.
    """
    model_id = request.model_id
    project = request.project
    episodes = request.episodes
    robot_type = request.robot_type
    device = request.device

    # Find model path
    model_path = _find_model_path(model_id)
    if not model_path:
        raise HTTPException(
            status_code=404,
            detail=f"Model not found: {model_id}. Check if it's downloaded in {MODELS_DIR}",
        )

    # Detect policy type and get appropriate environment
    policy_type = _get_policy_type(model_path)
    if not policy_type:
        policy_type = "act"  # Default fallback
    env_name = _get_env_for_policy(policy_type)

    # Check if run_in_env.sh exists
    if not RUN_IN_ENV_SCRIPT.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Environment script not found: {RUN_IN_ENV_SCRIPT}",
        )

    # Build command using run_in_env.sh
    # Format: run_in_env.sh <env_name> python -m percus_ai.inference.executor [args...]
    cmd = [
        str(RUN_IN_ENV_SCRIPT),
        env_name,
        "python", "-m", "percus_ai.inference.executor",
        "--project", project,
        "--policy-path", str(model_path),
        "--episodes", str(episodes),
        "--robot-type", robot_type,
    ]

    if device:
        cmd.extend(["--device", device])

    # Execute (run_in_env.sh handles PYTHONPATH for features and bundled-torch)
    try:
        result = subprocess.run(
            cmd,
            cwd=_REPO_ROOT,
            capture_output=False,  # Let output flow to terminal
            text=True,
        )

        return InferenceRunResponse(
            success=result.returncode == 0,
            model_id=model_id,
            project=project,
            message=f"Inference completed (env: {env_name}, policy: {policy_type})" if result.returncode == 0 else f"Inference failed (env: {env_name})",
            return_code=result.returncode,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to run inference: {str(e)}",
        )


@router.websocket("/ws/run")
async def websocket_run_inference(websocket: WebSocket):
    """WebSocket endpoint for running inference with real-time output streaming.

    Client sends:
        {
            "model_id": "...",
            "project": "...",
            "episodes": 1,
            "robot_type": "so101",
            "device": "cuda" | "mps" | "cpu" | null
        }

    Server sends:
        {"type": "start", "model_id": "...", "env": "...", "policy": "..."}
        {"type": "output", "line": "..."}  # stdout lines
        {"type": "error_output", "line": "..."}  # stderr lines
        {"type": "complete", "success": true, "return_code": 0}
        {"type": "error", "error": "..."}
    """
    import asyncio

    await websocket.accept()

    try:
        # Receive run request
        data = await websocket.receive_json()

        model_id = data.get("model_id")
        project = data.get("project")
        episodes = data.get("episodes", 1)
        robot_type = data.get("robot_type", "so101")
        device = data.get("device")

        if not model_id or not project:
            await websocket.send_json({
                "type": "error",
                "error": "model_id and project are required"
            })
            await websocket.close()
            return

        # Find model path
        model_path = _find_model_path(model_id)
        if not model_path:
            await websocket.send_json({
                "type": "error",
                "error": f"Model not found: {model_id}"
            })
            await websocket.close()
            return

        # Detect policy type and get appropriate environment
        policy_type = _get_policy_type(model_path)
        if not policy_type:
            policy_type = "act"
        env_name = _get_env_for_policy(policy_type)

        # Check if run_in_env.sh exists
        if not RUN_IN_ENV_SCRIPT.exists():
            await websocket.send_json({
                "type": "error",
                "error": f"Environment script not found: {RUN_IN_ENV_SCRIPT}"
            })
            await websocket.close()
            return

        # Build command
        cmd = [
            str(RUN_IN_ENV_SCRIPT),
            env_name,
            "python", "-m", "percus_ai.inference.executor",
            "--project", project,
            "--policy-path", str(model_path),
            "--episodes", str(episodes),
            "--robot-type", robot_type,
        ]

        if device:
            cmd.extend(["--device", device])

        # Send start notification
        await websocket.send_json({
            "type": "start",
            "model_id": model_id,
            "project": project,
            "env": env_name,
            "policy": policy_type,
        })

        # Run subprocess with output streaming
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=_REPO_ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

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

        # Read stdout and stderr concurrently
        await asyncio.gather(
            read_stream(process.stdout, "output"),
            read_stream(process.stderr, "error_output"),
        )

        # Wait for process to complete
        return_code = await process.wait()

        # Send completion notification
        await websocket.send_json({
            "type": "complete",
            "success": return_code == 0,
            "return_code": return_code,
            "message": f"Inference completed (env: {env_name}, policy: {policy_type})" if return_code == 0 else f"Inference failed (env: {env_name})",
        })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({
                "type": "error",
                "error": str(e),
            })
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
