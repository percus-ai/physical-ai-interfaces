"""Inference API models."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class InferenceModelInfo(BaseModel):
    """Model information for inference."""

    model_id: str = Field(..., description="Model ID")
    name: str = Field(..., description="Model name")
    policy_type: str = Field(..., description="Policy type")
    local_path: Optional[str] = Field(None, description="Local path")
    size_mb: float = Field(0.0, description="Model size in MB")
    is_loaded: bool = Field(False, description="Model is loaded in memory")
    is_local: bool = Field(True, description="Model is downloaded locally")
    source: str = Field("local", description="Model source: r2, hub, local")


class InferenceModelsResponse(BaseModel):
    """Response for models list endpoint."""

    models: List[InferenceModelInfo]
    total: int


class InferenceLoadRequest(BaseModel):
    """Request to load a model for inference."""

    model_id: str = Field(..., description="Model ID to load")
    device: str = Field("auto", description="Device: cuda, mps, cpu, auto")


class InferenceSession(BaseModel):
    """Inference session information."""

    session_id: str = Field(..., description="Session ID")
    model_id: str = Field(..., description="Loaded model ID")
    policy_type: str = Field(..., description="Policy type")
    device: str = Field(..., description="Device being used")
    memory_mb: float = Field(0.0, description="Memory usage in MB")
    created_at: str = Field(..., description="Session creation time")


class InferenceLoadResponse(BaseModel):
    """Response for model load endpoint."""

    session: InferenceSession
    message: str


class InferenceUnloadRequest(BaseModel):
    """Request to unload a model."""

    session_id: str = Field(..., description="Session ID to unload")


class InferenceUnloadResponse(BaseModel):
    """Response for model unload endpoint."""

    session_id: str
    success: bool
    message: str


class InferencePredictRequest(BaseModel):
    """Request for inference prediction."""

    session_id: str = Field(..., description="Session ID")
    observation: Dict[str, Any] = Field(..., description="Observation data")


class InferencePredictResponse(BaseModel):
    """Response for inference prediction."""

    session_id: str
    action: Dict[str, Any] = Field(..., description="Predicted action")
    inference_time_ms: float = Field(0.0, description="Inference time in ms")


class InferenceSessionsResponse(BaseModel):
    """Response for sessions list endpoint."""

    sessions: List[InferenceSession]
    total: int


class InferenceDeviceCompatibility(BaseModel):
    """Device compatibility information."""

    device: str = Field(..., description="Device name")
    available: bool = Field(..., description="Device is available")
    memory_total_mb: Optional[float] = Field(None, description="Total memory in MB")
    memory_free_mb: Optional[float] = Field(None, description="Free memory in MB")


class InferenceDeviceCompatibilityResponse(BaseModel):
    """Response for device compatibility endpoint."""

    devices: List[InferenceDeviceCompatibility]
    recommended: str = Field("cpu", description="Recommended device")


class InferenceRunRequest(BaseModel):
    """Request to run inference on robot."""

    model_id: str = Field(..., description="Model ID to run")
    project: str = Field(..., description="Project name")
    episodes: int = Field(1, description="Number of episodes to run")
    robot_type: str = Field("so101", description="Robot type (so101/so100/koch)")
    device: Optional[str] = Field(None, description="Device: cuda, mps, cpu (auto if None)")


class InferenceRunResponse(BaseModel):
    """Response for run inference endpoint."""

    success: bool
    model_id: str
    project: str
    message: str
    return_code: int = Field(0, description="Process return code")
    output: Optional[str] = Field(None, description="Process output (if captured)")
