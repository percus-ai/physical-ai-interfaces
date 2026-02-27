"""Experiment management API router (DB-backed)."""

import logging
import os
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from interfaces_backend.models.experiment import (
    ExperimentAnalysisListResponse,
    ExperimentAnalysisModel,
    ExperimentAnalysisReplaceRequest,
    ExperimentAnalysisUpdateRequest,
    ExperimentCreateRequest,
    ExperimentEvaluationListResponse,
    ExperimentEvaluationModel,
    ExperimentEvaluationReplaceRequest,
    ExperimentEvaluationSummary,
    ExperimentListResponse,
    ExperimentMediaUrlRequest,
    ExperimentMediaUrlResponse,
    ExperimentModel,
    ExperimentUpdateRequest,
)
from percus_ai.db import get_current_user_id, get_supabase_async_client
from percus_ai.storage.s3 import S3Manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/experiments", tags=["experiments"])

DEFAULT_METRIC_OPTIONS = ["成功", "失敗", "部分成功"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_user_id() -> str:
    try:
        return get_current_user_id()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Login required") from exc


def _row_to_experiment(row: dict) -> ExperimentModel:
    return ExperimentModel(
        id=row.get("id"),
        model_id=row.get("model_id"),
        profile_instance_id=row.get("profile_instance_id"),
        name=row.get("name"),
        purpose=row.get("purpose"),
        evaluation_count=row.get("evaluation_count") or 0,
        metric=row.get("metric") or "binary",
        metric_options=row.get("metric_options"),
        result_image_files=row.get("result_image_files"),
        notes=row.get("notes"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _row_to_evaluation(row: dict) -> ExperimentEvaluationModel:
    return ExperimentEvaluationModel(
        id=row.get("id"),
        experiment_id=row.get("experiment_id"),
        trial_index=row.get("trial_index") or 0,
        value=row.get("value") or "",
        image_files=row.get("image_files"),
        notes=row.get("notes"),
        created_at=row.get("created_at"),
    )


def _row_to_analysis(row: dict) -> ExperimentAnalysisModel:
    return ExperimentAnalysisModel(
        id=row.get("id"),
        experiment_id=row.get("experiment_id"),
        block_index=row.get("block_index") or 0,
        name=row.get("name"),
        purpose=row.get("purpose"),
        notes=row.get("notes"),
        image_files=row.get("image_files"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _get_r2_bucket() -> str:
    bucket = os.environ.get("R2_BUCKET") or os.environ.get("S3_BUCKET")
    if not bucket:
        raise HTTPException(status_code=500, detail="R2_BUCKET is not configured")
    return bucket


def _get_r2_version_prefix() -> str:
    version = os.environ.get("R2_VERSION", "v2").strip("/")
    return f"{version}/" if version else ""


@router.post("", response_model=ExperimentModel)
async def create_experiment(request: ExperimentCreateRequest):
    """Create a new experiment."""
    user_id = _require_user_id()
    client = await get_supabase_async_client()
    metric_options = (
        request.metric_options
        if request.metric_options is not None
        else DEFAULT_METRIC_OPTIONS
    )
    record = {
        "id": str(uuid4()),
        "model_id": request.model_id,
        "profile_instance_id": request.profile_instance_id,
        "name": request.name,
        "purpose": request.purpose,
        "evaluation_count": request.evaluation_count,
        "metric": request.metric,
        "metric_options": metric_options,
        "result_image_files": request.result_image_files,
        "notes": request.notes,
        "owner_user_id": user_id,
        "updated_at": _now_iso(),
    }
    response = await client.table("experiments").insert(record).execute()
    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=500, detail="Failed to create experiment")
    return _row_to_experiment(rows[0])


@router.get("", response_model=ExperimentListResponse)
async def list_experiments(
    model_id: Optional[str] = Query(None, description="Filter by model"),
    profile_instance_id: Optional[str] = Query(None, description="Filter by profile instance"),
    limit: int = Query(100, description="Max rows"),
    offset: int = Query(0, description="Offset"),
):
    """List experiments."""
    client = await get_supabase_async_client()
    query = client.table("experiments").select("*")
    if model_id:
        query = query.eq("model_id", model_id)
    if profile_instance_id:
        query = query.eq("profile_instance_id", profile_instance_id)
    if limit > 0:
        query = query.range(offset, offset + limit - 1)
    rows = (await query.execute()).data or []
    experiments = [_row_to_experiment(row) for row in rows]
    return ExperimentListResponse(experiments=experiments, total=len(experiments))


@router.get("/{experiment_id}", response_model=ExperimentModel)
async def get_experiment(experiment_id: str):
    """Get experiment details."""
    client = await get_supabase_async_client()
    rows = (
        await client.table("experiments")
        .select("*")
        .eq("id", experiment_id)
        .execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return _row_to_experiment(rows[0])


@router.patch("/{experiment_id}", response_model=ExperimentModel)
async def update_experiment(experiment_id: str, request: ExperimentUpdateRequest):
    """Update experiment details."""
    _require_user_id()
    client = await get_supabase_async_client()
    update_data = request.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    update_data["updated_at"] = _now_iso()
    response = (
        await client.table("experiments")
        .update(update_data)
        .eq("id", experiment_id)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return _row_to_experiment(rows[0])


@router.delete("/{experiment_id}")
async def delete_experiment(experiment_id: str):
    """Delete experiment (cascade deletes evaluations and analyses)."""
    _require_user_id()
    client = await get_supabase_async_client()
    existing = (
        await client.table("experiments").select("id").eq("id", experiment_id).execute()
    ).data or []
    if not existing:
        raise HTTPException(status_code=404, detail="Experiment not found")
    await client.table("experiments").delete().eq("id", experiment_id).execute()
    return {"deleted": True}


@router.get("/{experiment_id}/evaluations", response_model=ExperimentEvaluationListResponse)
async def list_experiment_evaluations(experiment_id: str):
    """List evaluations for an experiment."""
    client = await get_supabase_async_client()
    rows = (
        await client.table("experiment_evaluations")
        .select("*")
        .eq("experiment_id", experiment_id)
        .order("trial_index")
        .execute()
    ).data or []
    evaluations = [_row_to_evaluation(row) for row in rows]
    return ExperimentEvaluationListResponse(evaluations=evaluations, total=len(evaluations))


@router.put("/{experiment_id}/evaluations")
async def replace_experiment_evaluations(
    experiment_id: str, request: ExperimentEvaluationReplaceRequest
):
    """Replace all evaluations for an experiment (indices assigned by server)."""
    user_id = _require_user_id()
    client = await get_supabase_async_client()
    existing = (
        await client.table("experiments").select("id").eq("id", experiment_id).execute()
    ).data or []
    if not existing:
        raise HTTPException(status_code=404, detail="Experiment not found")
    await client.table("experiment_evaluations").delete().eq("experiment_id", experiment_id).execute()

    items = request.items or []
    if items:
        records = []
        for idx, item in enumerate(items, start=1):
            records.append(
                {
                    "id": str(uuid4()),
                    "experiment_id": experiment_id,
                    "trial_index": idx,
                    "value": item.value or "",
                    "image_files": item.image_files,
                    "notes": item.notes,
                    "owner_user_id": user_id,
                }
            )
        await client.table("experiment_evaluations").insert(records).execute()
    return {"updated": True, "count": len(items)}


@router.get("/{experiment_id}/evaluation_summary", response_model=ExperimentEvaluationSummary)
async def experiment_evaluation_summary(experiment_id: str):
    """Get evaluation summary for an experiment."""
    client = await get_supabase_async_client()
    rows = (
        await client.table("experiment_evaluations")
        .select("value")
        .eq("experiment_id", experiment_id)
        .execute()
    ).data or []
    total = len(rows)
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get("value") or ""
        counts[value] = counts.get(value, 0) + 1
    rates = {key: (count / total * 100.0) for key, count in counts.items()} if total else {}
    return ExperimentEvaluationSummary(total=total, counts=counts, rates=rates)


@router.post("/media-urls", response_model=ExperimentMediaUrlResponse)
async def get_experiment_media_urls(request: ExperimentMediaUrlRequest):
    """Generate signed URLs for experiment-related images."""
    _require_user_id()
    keys = [key for key in (request.keys or []) if key]
    if not keys:
        return ExperimentMediaUrlResponse(urls={})
    bucket = _get_r2_bucket()
    s3 = S3Manager()
    urls: dict[str, str] = {}
    for key in keys:
        try:
            urls[key] = s3.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=3600,
            )
        except Exception as exc:
            logger.warning("Failed to sign key %s: %s", key, exc)
    return ExperimentMediaUrlResponse(urls=urls)


@router.get("/{experiment_id}/analyses", response_model=ExperimentAnalysisListResponse)
async def list_experiment_analyses(experiment_id: str):
    """List analyses for an experiment."""
    client = await get_supabase_async_client()
    rows = (
        await client.table("experiment_analyses")
        .select("*")
        .eq("experiment_id", experiment_id)
        .order("block_index")
        .execute()
    ).data or []
    analyses = [_row_to_analysis(row) for row in rows]
    return ExperimentAnalysisListResponse(analyses=analyses, total=len(analyses))


@router.put("/{experiment_id}/analyses")
async def replace_experiment_analyses(
    experiment_id: str, request: ExperimentAnalysisReplaceRequest
):
    """Replace all analyses for an experiment (indices assigned by server)."""
    user_id = _require_user_id()
    client = await get_supabase_async_client()
    existing = (
        await client.table("experiments").select("id").eq("id", experiment_id).execute()
    ).data or []
    if not existing:
        raise HTTPException(status_code=404, detail="Experiment not found")
    await client.table("experiment_analyses").delete().eq("experiment_id", experiment_id).execute()

    items = request.items or []
    if items:
        records = []
        now_iso = _now_iso()
        for idx, item in enumerate(items, start=1):
            records.append(
                {
                    "id": str(uuid4()),
                    "experiment_id": experiment_id,
                    "block_index": idx,
                    "name": item.name,
                    "purpose": item.purpose,
                    "notes": item.notes,
                    "image_files": item.image_files,
                    "owner_user_id": user_id,
                    "updated_at": now_iso,
                }
            )
        await client.table("experiment_analyses").insert(records).execute()
    return {"updated": True, "count": len(items)}


@router.patch("/{experiment_id}/analyses/{block_index}", response_model=ExperimentAnalysisModel)
async def update_experiment_analysis(
    experiment_id: str,
    block_index: int,
    request: ExperimentAnalysisUpdateRequest,
):
    """Update analysis block."""
    _require_user_id()
    client = await get_supabase_async_client()
    update_data = request.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    update_data["updated_at"] = _now_iso()
    response = (
        await client.table("experiment_analyses")
        .update(update_data)
        .eq("experiment_id", experiment_id)
        .eq("block_index", block_index)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Analysis block not found")
    return _row_to_analysis(rows[0])


@router.delete("/{experiment_id}/analyses/{block_index}")
async def delete_experiment_analysis(experiment_id: str, block_index: int):
    """Delete analysis block."""
    _require_user_id()
    client = await get_supabase_async_client()
    response = (
        await client.table("experiment_analyses")
        .delete()
        .eq("experiment_id", experiment_id)
        .eq("block_index", block_index)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Analysis block not found")
    return {"deleted": True}


@router.post("/{experiment_id}/uploads")
async def upload_experiment_images(
    experiment_id: str,
    scope: str = Query("experiment", description="experiment, evaluation, or analysis"),
    trial_index: Optional[int] = Query(None, description="Trial index for evaluation scope"),
    block_index: Optional[int] = Query(None, description="Block index for analysis scope"),
    files: list[UploadFile] = File(...),
):
    """Upload images to R2 and return keys."""
    _require_user_id()
    client = await get_supabase_async_client()
    existing = (
        await client.table("experiments").select("id").eq("id", experiment_id).execute()
    ).data or []
    if not existing:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if scope not in {"experiment", "evaluation", "analysis"}:
        raise HTTPException(status_code=400, detail="Invalid scope")
    if scope == "evaluation" and not trial_index:
        raise HTTPException(status_code=400, detail="trial_index is required for evaluation scope")
    if scope == "analysis" and not block_index:
        raise HTTPException(status_code=400, detail="block_index is required for analysis scope")

    bucket = _get_r2_bucket()
    prefix = _get_r2_version_prefix()
    if scope == "experiment":
        base_key = f"{prefix}experiments/{experiment_id}/images"
    elif scope == "evaluation":
        base_key = f"{prefix}experiments/{experiment_id}/evaluations/{trial_index}"
    else:
        base_key = f"{prefix}experiments/{experiment_id}/analyses/{block_index}"

    s3 = S3Manager()
    uploaded: list[str] = []
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    for idx, upfile in enumerate(files, start=1):
        filename = upfile.filename or f"image_{idx}"
        safe_name = filename.replace("/", "_")
        key = f"{base_key}/{timestamp}_{idx}_{safe_name}"
        try:
            s3.client.upload_fileobj(upfile.file, bucket, key)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc
        uploaded.append(key)
    return {"keys": uploaded}
