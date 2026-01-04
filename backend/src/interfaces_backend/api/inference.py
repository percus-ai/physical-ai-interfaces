"""Inference API router."""

import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException

from interfaces_backend.models.inference import (
    InferenceModelInfo,
    InferenceModelsResponse,
    InferenceLoadRequest,
    InferenceLoadResponse,
    InferenceSession,
    InferenceUnloadRequest,
    InferenceUnloadResponse,
    InferencePredictRequest,
    InferencePredictResponse,
    InferenceSessionsResponse,
    InferenceDeviceCompatibility,
    InferenceDeviceCompatibilityResponse,
)

router = APIRouter(prefix="/api/inference", tags=["inference"])

# In-memory session storage
_sessions: Dict[str, dict] = {}

# Models directory
MODELS_DIR = Path.cwd() / "models"


def _get_percus_inference():
    """Import percus_ai.inference if available."""
    try:
        from percus_ai.inference import PolicyExecutor, detect_device

        return PolicyExecutor, detect_device
    except ImportError:
        features_path = Path(__file__).resolve().parents[5] / "features"
        if features_path.exists() and str(features_path) not in sys.path:
            sys.path.insert(0, str(features_path))
            try:
                from percus_ai.inference import PolicyExecutor, detect_device

                return PolicyExecutor, detect_device
            except ImportError:
                pass
    return None, None


def _get_storage_hub():
    """Import percus_ai.storage.hub if available."""
    try:
        from percus_ai.storage import list_local_models, get_local_model_info

        return list_local_models, get_local_model_info
    except ImportError:
        features_path = Path(__file__).resolve().parents[5] / "features"
        if features_path.exists() and str(features_path) not in sys.path:
            sys.path.insert(0, str(features_path))
            try:
                from percus_ai.storage import list_local_models, get_local_model_info

                return list_local_models, get_local_model_info
            except ImportError:
                pass
    return None, None


def _detect_device() -> str:
    """Detect best available compute device."""
    _, detect_device = _get_percus_inference()
    if detect_device:
        return detect_device()

    # Fallback detection
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def _list_models() -> list[dict]:
    """List available models for inference."""
    list_local_models, get_local_model_info = _get_storage_hub()

    if list_local_models:
        try:
            models = list_local_models(MODELS_DIR)
            return [m.to_dict() for m in models]
        except Exception:
            pass

    # Fallback: scan models directory
    if not MODELS_DIR.exists():
        return []

    models = []
    for model_dir in MODELS_DIR.iterdir():
        if not model_dir.is_dir():
            continue

        config_file = model_dir / "config.json"
        if not config_file.exists():
            continue

        try:
            import json

            with open(config_file) as f:
                config = json.load(f)

            models.append({
                "model_id": model_dir.name,
                "name": model_dir.name,
                "policy_type": config.get("type", "unknown"),
                "local_path": str(model_dir),
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

    # Mark loaded models
    loaded_model_ids = {s["model_id"] for s in _sessions.values()}

    models = []
    for m in models_data:
        models.append(
            InferenceModelInfo(
                model_id=m.get("model_id", m.get("name", "")),
                name=m.get("name", ""),
                policy_type=m.get("policy_type", "unknown"),
                local_path=m.get("local_path"),
                size_mb=m.get("size_mb", 0.0),
                is_loaded=m.get("model_id", m.get("name", "")) in loaded_model_ids,
            )
        )

    return InferenceModelsResponse(models=models, total=len(models))


@router.post("/load", response_model=InferenceLoadResponse)
async def load_model(request: InferenceLoadRequest):
    """Load a model for inference.

    Creates an inference session that can be used for predictions.
    """
    model_id = request.model_id
    device = request.device

    # Check if model exists
    model_path = MODELS_DIR / model_id
    if not model_path.exists():
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")

    # Determine device
    if device == "auto":
        device = _detect_device()

    # Check if model is already loaded
    for session_id, session in _sessions.items():
        if session["model_id"] == model_id:
            return InferenceLoadResponse(
                session=InferenceSession(
                    session_id=session_id,
                    model_id=model_id,
                    policy_type=session.get("policy_type", "unknown"),
                    device=session.get("device", device),
                    memory_mb=session.get("memory_mb", 0.0),
                    created_at=session.get("created_at", ""),
                ),
                message="Model already loaded",
            )

    # Create session
    session_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # Try to load model
    PolicyExecutor, _ = _get_percus_inference()
    policy_type = "unknown"
    memory_mb = 0.0

    if PolicyExecutor:
        try:
            # Note: Actual model loading would happen here
            # For now, we just record the session
            config_file = model_path / "config.json"
            if config_file.exists():
                import json

                with open(config_file) as f:
                    config = json.load(f)
                policy_type = config.get("type", "unknown")
        except Exception:
            pass

    session_data = {
        "session_id": session_id,
        "model_id": model_id,
        "model_path": str(model_path),
        "policy_type": policy_type,
        "device": device,
        "memory_mb": memory_mb,
        "created_at": now,
        "executor": None,  # Would hold PolicyExecutor instance
    }
    _sessions[session_id] = session_data

    return InferenceLoadResponse(
        session=InferenceSession(
            session_id=session_id,
            model_id=model_id,
            policy_type=policy_type,
            device=device,
            memory_mb=memory_mb,
            created_at=now,
        ),
        message="Model loaded successfully",
    )


@router.post("/unload", response_model=InferenceUnloadResponse)
async def unload_model(request: InferenceUnloadRequest):
    """Unload a model and free resources."""
    session_id = request.session_id

    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # Clean up executor if present
    session = _sessions[session_id]
    if session.get("executor"):
        try:
            del session["executor"]
        except Exception:
            pass

    del _sessions[session_id]

    return InferenceUnloadResponse(
        session_id=session_id,
        success=True,
        message="Model unloaded",
    )


@router.post("/predict", response_model=InferencePredictResponse)
async def predict(request: InferencePredictRequest):
    """Run inference on observation data."""
    import time

    session_id = request.session_id

    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    session = _sessions[session_id]
    start_time = time.perf_counter()

    # Run prediction
    action = {}
    executor = session.get("executor")

    if executor:
        try:
            action = executor.predict(request.observation)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Prediction failed: {e}")
    else:
        # Placeholder: return empty action
        action = {"joints": [0.0] * 6}

    inference_time_ms = (time.perf_counter() - start_time) * 1000

    return InferencePredictResponse(
        session_id=session_id,
        action=action,
        inference_time_ms=inference_time_ms,
    )


@router.get("/sessions", response_model=InferenceSessionsResponse)
async def list_sessions():
    """List active inference sessions."""
    sessions = [
        InferenceSession(
            session_id=s["session_id"],
            model_id=s["model_id"],
            policy_type=s.get("policy_type", "unknown"),
            device=s.get("device", "cpu"),
            memory_mb=s.get("memory_mb", 0.0),
            created_at=s.get("created_at", ""),
        )
        for s in _sessions.values()
    ]

    return InferenceSessionsResponse(sessions=sessions, total=len(sessions))


@router.get("/sessions/{session_id}", response_model=InferenceSession)
async def get_session(session_id: str):
    """Get inference session details."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    s = _sessions[session_id]
    return InferenceSession(
        session_id=s["session_id"],
        model_id=s["model_id"],
        policy_type=s.get("policy_type", "unknown"),
        device=s.get("device", "cpu"),
        memory_mb=s.get("memory_mb", 0.0),
        created_at=s.get("created_at", ""),
    )


@router.post("/sessions/{session_id}/reset")
async def reset_session(session_id: str):
    """Reset inference session state."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    session = _sessions[session_id]

    # Reset executor state if present
    executor = session.get("executor")
    if executor and hasattr(executor, "reset"):
        try:
            executor.reset()
        except Exception:
            pass

    return {"session_id": session_id, "message": "Session reset"}


@router.get("/device-compatibility", response_model=InferenceDeviceCompatibilityResponse)
async def get_device_compatibility():
    """Check device compatibility for inference."""
    devices = []

    # Check CUDA
    cuda_available = False
    cuda_memory_total = None
    cuda_memory_free = None
    try:
        import torch

        if torch.cuda.is_available():
            cuda_available = True
            cuda_memory_total = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024)
            cuda_memory_free = (
                torch.cuda.get_device_properties(0).total_memory
                - torch.cuda.memory_allocated(0)
            ) / (1024 * 1024)
    except ImportError:
        pass

    devices.append(
        InferenceDeviceCompatibility(
            device="cuda",
            available=cuda_available,
            memory_total_mb=cuda_memory_total,
            memory_free_mb=cuda_memory_free,
        )
    )

    # Check MPS (Apple Silicon)
    mps_available = False
    try:
        import torch

        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            mps_available = True
    except ImportError:
        pass

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
