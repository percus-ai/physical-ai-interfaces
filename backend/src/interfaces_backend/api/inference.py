"""Inference API router."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from interfaces_backend.clients.gpu_host import GpuHostClient
from interfaces_backend.clients.runner_bridge import RunnerBridgeClient
from interfaces_backend.models.inference import (
    InferenceDeviceCompatibility,
    InferenceDeviceCompatibilityResponse,
    InferenceModelInfo,
    InferenceModelsResponse,
    InferenceRunnerStartRequest,
    InferenceRunnerStartResponse,
    InferenceRunnerStatusResponse,
    InferenceRunnerStopRequest,
    InferenceRunnerStopResponse,
)
from interfaces_backend.utils.torch_info import get_torch_info
from percus_ai.db import get_supabase_client
from percus_ai.gpu_host.models import StartRequest, StopRequest
from percus_ai.inference.camera_maps import get_camera_maps_for_model, get_policy_type_from_config
from percus_ai.storage.paths import get_models_dir, get_project_root
from percus_ai.storage.r2_db_sync import R2DBSyncService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inference", tags=["inference"])

MODELS_DIR = get_models_dir()

_RUNNER_ZMQ_ENDPOINT = os.environ.get("RUNNER_BRIDGE_ZMQ_ENDPOINT", "tcp://127.0.0.1:5556")
_RUNNER_COMPOSE_SERVICE = os.environ.get("RUNNER_BRIDGE_SERVICE", "lerobot-ros2")
_RUNNER_AUTO_START = os.environ.get("RUNNER_BRIDGE_AUTO_START", "1") != "0"
_GPU_WORKER_DEVICE = os.environ.get("GPU_WORKER_DEVICE", "cuda:0")

_DEFAULT_ARM_NAMESPACES = ["left_arm", "right_arm"]
_DEFAULT_JOINT_NAMES = ["joint1", "joint2", "joint3", "joint4", "joint5", "joint6"]


def _list_models() -> list[dict]:
    models: list[dict] = []
    client = get_supabase_client()
    rows = client.table("models").select("*").eq("status", "active").execute().data or []

    for row in rows:
        model_id = row.get("id")
        if not model_id:
            continue
        model_path = MODELS_DIR / model_id
        size_bytes = row.get("size_bytes") or 0
        models.append({
            "model_id": model_id,
            "name": row.get("name") or model_id,
            "policy_type": row.get("policy_type") or "unknown",
            "local_path": str(model_path) if model_path.exists() else None,
            "source": row.get("source") or "r2",
            "size_mb": size_bytes / (1024 * 1024),
            "is_local": model_path.exists(),
        })

    return models


def _ensure_runner_service() -> None:
    if not _RUNNER_AUTO_START:
        return
    repo_root = get_project_root()
    compose_file = repo_root / "docker-compose.ros2.yml"
    if not compose_file.exists():
        raise HTTPException(status_code=500, detail="docker-compose.ros2.yml not found")
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "up", "-d", _RUNNER_COMPOSE_SERVICE],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"runner bridge start failed: {result.stderr.strip()}")


def _resolve_model_path(model_id: str) -> Path:
    model_path = MODELS_DIR / model_id
    if model_path.exists():
        if not _resolve_model_config_path(model_path):
            raise HTTPException(status_code=404, detail=f"Model config.json not found: {model_path}")
        return model_path

    client = get_supabase_client()
    rows = (
        client.table("models")
        .select("*")
        .eq("id", model_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        rows = (
            client.table("models")
            .select("*")
            .eq("name", model_id)
            .limit(1)
            .execute()
            .data
            or []
        )

    row = rows[0] if rows else {}
    resolved_id = row.get("id") or model_id
    model_path = MODELS_DIR / str(resolved_id)
    if model_path.exists():
        if not _resolve_model_config_path(model_path):
            raise HTTPException(status_code=404, detail=f"Model config.json not found: {model_path}")
        return model_path

    sync_service = R2DBSyncService()
    sync_result = sync_service.ensure_model_local(str(resolved_id), auto_download=True)
    if sync_result.success and model_path.exists():
        if not _resolve_model_config_path(model_path):
            raise HTTPException(status_code=404, detail=f"Model config.json not found: {model_path}")
        return model_path

    name = row.get("name")
    if name:
        candidate = MODELS_DIR / str(name)
        if candidate.exists():
            if not _resolve_model_config_path(candidate):
                raise HTTPException(status_code=404, detail=f"Model config.json not found: {candidate}")
            return candidate

    if not sync_result.success:
        raise HTTPException(status_code=502, detail=f"Model download failed: {sync_result.message}")
    raise HTTPException(status_code=404, detail=f"Model not found locally: {model_id}")


def _resolve_model_policy_type(model_path: Path, model_id: str, override: str | None) -> str:
    if override:
        return override
    policy_type = get_policy_type_from_config(str(model_path))
    if policy_type:
        return policy_type
    client = get_supabase_client()
    rows = (
        client.table("models")
        .select("*")
        .eq("id", model_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if rows and rows[0].get("policy_type"):
        return rows[0]["policy_type"]
    return "unknown"


def _load_model_config(model_path: Path) -> dict:
    if model_path.is_file() and model_path.name == "config.json":
        config_path = model_path
    else:
        config_path = model_path / "config.json"
        if not config_path.exists():
            config_path = model_path / "pretrained_model" / "config.json"
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _resolve_model_config_path(model_path: Path) -> Optional[Path]:
    if model_path.is_file() and model_path.name == "config.json":
        return model_path
    if model_path.is_dir():
        root_config = model_path / "config.json"
        if root_config.exists():
            return root_config
        nested_config = model_path / "pretrained_model" / "config.json"
        if nested_config.exists():
            return nested_config
    return None


def _extract_camera_shapes(config: dict) -> dict[str, list[int]]:
    shapes: dict[str, list[int]] = {}
    input_features = config.get("input_features") or {}
    for key, value in input_features.items():
        if not key.startswith("observation.images."):
            continue
        name = key.replace("observation.images.", "")
        shape = None
        if isinstance(value, dict):
            shape = value.get("shape")
            if shape is None:
                cfg = value.get("config")
                if isinstance(cfg, dict):
                    shape = cfg.get("shape")
        elif isinstance(value, (list, tuple)) and len(value) == 3:
            shape = value
        if shape is not None:
            shapes[name] = [int(x) for x in shape]
    return shapes


@router.get("/models", response_model=InferenceModelsResponse)
async def list_inference_models():
    """List models available for inference."""
    models_data = _list_models()
    models = [
        InferenceModelInfo(
            model_id=m.get("model_id", m.get("name", "")),
            name=m.get("name", ""),
            policy_type=m.get("policy_type", "unknown"),
            local_path=m.get("local_path"),
            size_mb=m.get("size_mb", 0.0),
            is_loaded=False,
            is_local=m.get("is_local", True),
            source=m.get("source", "local"),
        )
        for m in models_data
    ]
    return InferenceModelsResponse(models=models, total=len(models))


@router.get("/device-compatibility", response_model=InferenceDeviceCompatibilityResponse)
async def get_device_compatibility():
    """Check device compatibility for inference."""
    torch_info = get_torch_info()

    cuda_available = torch_info.get("cuda_available", False)
    mps_available = torch_info.get("mps_available", False)

    devices = [
        InferenceDeviceCompatibility(
            device="cuda",
            available=cuda_available,
            memory_total_mb=torch_info.get("cuda_memory_total"),
            memory_free_mb=torch_info.get("cuda_memory_free"),
        ),
        InferenceDeviceCompatibility(
            device="mps",
            available=mps_available,
            memory_total_mb=None,
            memory_free_mb=None,
        ),
        InferenceDeviceCompatibility(
            device="cpu",
            available=True,
            memory_total_mb=None,
            memory_free_mb=None,
        ),
    ]

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


@router.post("/runner/start", response_model=InferenceRunnerStartResponse)
async def start_inference_runner(request: InferenceRunnerStartRequest):
    _ensure_runner_service()

    model_path = _resolve_model_path(request.model_id)
    policy_type = _resolve_model_policy_type(model_path, request.model_id, request.policy_type)
    config = _load_model_config(model_path)
    camera_shapes = request.camera_shapes or _extract_camera_shapes(config)
    _, rename_map = get_camera_maps_for_model(str(model_path))
    if request.rename_map:
        rename_map = request.rename_map

    arm_namespaces = request.arm_namespaces or _DEFAULT_ARM_NAMESPACES
    joint_names = request.joint_names or _DEFAULT_JOINT_NAMES
    full_joint_names = [f"{ns}_{joint}" for ns in arm_namespaces for joint in joint_names]

    session_id = request.session_id or uuid4().hex[:8]
    zmq_endpoint = request.zmq_endpoint or _RUNNER_ZMQ_ENDPOINT

    runner_client = RunnerBridgeClient()
    try:
        runner_client.start({
            "session_id": session_id,
            "task": request.task,
            "zmq_endpoint": zmq_endpoint,
        })
    except Exception as exc:
        logger.exception("Runner bridge start failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    gpu_client = GpuHostClient()
    try:
        gpu_resp = gpu_client.start(StartRequest(
            session_id=session_id,
            policy_type=policy_type,
            model_path=str(model_path),
            device=request.device or _GPU_WORKER_DEVICE,
            actions_per_chunk=request.actions_per_chunk,
            joint_names=full_joint_names,
            camera_shapes=camera_shapes,
            rename_map=rename_map,
            zmq_endpoint=zmq_endpoint,
        ))
    except Exception as exc:
        logger.exception("GPU host start failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        runner_status = runner_client.status()
    except Exception:
        runner_status = {}

    return InferenceRunnerStartResponse(
        success=True,
        session_id=session_id,
        zmq_endpoint=zmq_endpoint,
        runner_status=runner_status,
        gpu_host_status=gpu_resp.model_dump(),
    )


@router.post("/runner/stop", response_model=InferenceRunnerStopResponse)
async def stop_inference_runner(request: InferenceRunnerStopRequest):
    runner_client = RunnerBridgeClient()
    session_id = request.session_id
    runner_status = {}
    try:
        runner_status = runner_client.status()
    except Exception:
        runner_status = {}

    if not session_id:
        session_id = runner_status.get("session_id") if isinstance(runner_status, dict) else None

    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    try:
        runner_client.stop()
    except Exception as exc:
        logger.exception("Runner bridge stop failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    gpu_status = {}
    try:
        gpu_client = GpuHostClient()
        gpu_resp = gpu_client.stop(StopRequest(session_id=session_id))
        gpu_status = gpu_resp.model_dump()
    except Exception as exc:
        logger.exception("GPU host stop failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return InferenceRunnerStopResponse(
        success=True,
        session_id=session_id,
        runner_status=runner_status if isinstance(runner_status, dict) else {},
        gpu_host_status=gpu_status,
    )


@router.get("/runner/status", response_model=InferenceRunnerStatusResponse)
async def get_inference_runner_status():
    runner_client = RunnerBridgeClient()
    gpu_client = GpuHostClient()

    try:
        runner_status = runner_client.status()
    except Exception as exc:
        logger.exception("Runner bridge status failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        gpu_status = gpu_client.status().model_dump()
    except Exception as exc:
        logger.exception("GPU host status failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return InferenceRunnerStatusResponse(
        runner_status=runner_status,
        gpu_host_status=gpu_status,
    )
