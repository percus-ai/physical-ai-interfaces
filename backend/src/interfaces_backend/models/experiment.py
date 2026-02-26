"""Experiment management API request/response models."""

from typing import List, Optional

from pydantic import BaseModel, Field


class ExperimentCreateRequest(BaseModel):
    """Create experiment request."""

    model_id: str = Field(..., description="Model ID")
    profile_instance_id: Optional[str] = Field(None, description="Profile instance ID")
    name: str = Field(..., description="Experiment name")
    purpose: Optional[str] = Field(None, description="Experiment purpose")
    evaluation_count: int = Field(..., description="Number of evaluations")
    metric: str = Field("binary", description="Metric type")
    metric_options: Optional[List[str]] = Field(
        None, description="Candidate values for evaluations",
    )
    result_image_files: Optional[List[str]] = Field(
        None, description="R2 keys for result images",
    )
    notes: Optional[str] = Field(None, description="Notes")


class ExperimentUpdateRequest(BaseModel):
    """Update experiment request."""

    name: Optional[str] = Field(None, description="Experiment name")
    purpose: Optional[str] = Field(None, description="Experiment purpose")
    evaluation_count: Optional[int] = Field(None, description="Number of evaluations")
    metric: Optional[str] = Field(None, description="Metric type")
    metric_options: Optional[List[str]] = Field(
        None, description="Candidate values for evaluations",
    )
    result_image_files: Optional[List[str]] = Field(
        None, description="R2 keys for result images",
    )
    notes: Optional[str] = Field(None, description="Notes")


class ExperimentModel(BaseModel):
    """Experiment response."""

    id: str = Field(..., description="Experiment ID")
    model_id: str = Field(..., description="Model ID")
    profile_instance_id: Optional[str] = Field(None, description="Profile instance ID")
    name: str = Field(..., description="Experiment name")
    purpose: Optional[str] = Field(None, description="Experiment purpose")
    evaluation_count: int = Field(..., description="Number of evaluations")
    metric: str = Field(..., description="Metric type")
    metric_options: Optional[List[str]] = Field(
        None, description="Candidate values for evaluations",
    )
    result_image_files: Optional[List[str]] = Field(
        None, description="R2 keys for result images",
    )
    notes: Optional[str] = Field(None, description="Notes")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")


class ExperimentListResponse(BaseModel):
    """Experiment list response."""

    experiments: List[ExperimentModel]
    total: int


class ExperimentEvaluationInput(BaseModel):
    """Experiment evaluation input (index assigned by server)."""

    value: Optional[str] = Field(None, description="Evaluation value")
    image_files: Optional[List[str]] = Field(
        None, description="R2 keys for evaluation images",
    )
    notes: Optional[str] = Field(None, description="Notes")


class ExperimentEvaluationReplaceRequest(BaseModel):
    """Replace evaluations request."""

    items: List[ExperimentEvaluationInput]


class ExperimentEvaluationModel(BaseModel):
    """Experiment evaluation response."""

    id: str = Field(..., description="Evaluation ID")
    experiment_id: str = Field(..., description="Experiment ID")
    trial_index: int = Field(..., description="Trial index (1-based)")
    value: str = Field(..., description="Evaluation value")
    image_files: Optional[List[str]] = Field(
        None, description="R2 keys for evaluation images",
    )
    notes: Optional[str] = Field(None, description="Notes")
    created_at: Optional[str] = Field(None, description="Creation timestamp")


class ExperimentEvaluationListResponse(BaseModel):
    """Experiment evaluations list response."""

    evaluations: List[ExperimentEvaluationModel]
    total: int


class ExperimentEvaluationSummary(BaseModel):
    """Evaluation summary response."""

    total: int = Field(0, description="Total evaluations")
    counts: dict = Field(default_factory=dict, description="Value counts")
    rates: dict = Field(default_factory=dict, description="Value rates (%)")


class ExperimentMediaUrlRequest(BaseModel):
    """Request signed URLs for stored image keys."""

    keys: List[str] = Field(default_factory=list, description="R2 object keys")


class ExperimentMediaUrlResponse(BaseModel):
    """Signed URLs for stored image keys."""

    urls: dict[str, str] = Field(default_factory=dict, description="Key to signed URL")


class ExperimentAnalysisInput(BaseModel):
    """Experiment analysis input (index assigned by server)."""

    name: Optional[str] = Field(None, description="Analysis name")
    purpose: Optional[str] = Field(None, description="Analysis purpose")
    notes: Optional[str] = Field(None, description="Analysis notes")
    image_files: Optional[List[str]] = Field(
        None, description="R2 keys for analysis images",
    )


class ExperimentAnalysisReplaceRequest(BaseModel):
    """Replace analyses request."""

    items: List[ExperimentAnalysisInput]


class ExperimentAnalysisUpdateRequest(BaseModel):
    """Update analysis block request."""

    name: Optional[str] = Field(None, description="Analysis name")
    purpose: Optional[str] = Field(None, description="Analysis purpose")
    notes: Optional[str] = Field(None, description="Analysis notes")
    image_files: Optional[List[str]] = Field(
        None, description="R2 keys for analysis images",
    )


class ExperimentAnalysisModel(BaseModel):
    """Experiment analysis response."""

    id: str = Field(..., description="Analysis ID")
    experiment_id: str = Field(..., description="Experiment ID")
    block_index: int = Field(..., description="Block index (1-based)")
    name: Optional[str] = Field(None, description="Analysis name")
    purpose: Optional[str] = Field(None, description="Analysis purpose")
    notes: Optional[str] = Field(None, description="Analysis notes")
    image_files: Optional[List[str]] = Field(
        None, description="R2 keys for analysis images",
    )
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")


class ExperimentAnalysisListResponse(BaseModel):
    """Experiment analyses list response."""

    analyses: List[ExperimentAnalysisModel]
    total: int
