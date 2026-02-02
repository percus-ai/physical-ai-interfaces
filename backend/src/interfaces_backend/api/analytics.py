"""Analytics API router."""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from interfaces_backend.models.analytics import (
    OverviewStats,
    OverviewResponse,
    ProfileStats,
    ProfileStatsResponse,
    TrainingStats,
    TrainingStatsResponse,
    StorageCategory,
    StorageStatsResponse,
)
from percus_ai.db import get_supabase_async_client
from percus_ai.storage import get_datasets_dir, get_models_dir

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Local storage directories
DATASETS_DIR = get_datasets_dir()
MODELS_DIR = get_models_dir()


def _get_dir_size(path: Path) -> float:
    """Get directory size in bytes."""
    if not path.exists():
        return 0

    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except Exception:
                pass
    return total


async def _get_profile_stats() -> list[dict]:
    """Collect statistics for profile instances from DB."""
    client = await get_supabase_async_client()
    profile_rows = (
        await client.table("profile_instances").select("id,name,updated_at").execute()
    ).data or []
    dataset_rows = (
        await client.table("datasets")
        .select("profile_instance_id,episode_count,size_bytes,updated_at,status")
        .execute()
    ).data or []
    model_rows = (
        await client.table("models")
        .select("profile_instance_id,size_bytes,updated_at,status")
        .execute()
    ).data or []

    stats: dict[str, dict] = {}
    for row in profile_rows:
        profile_id = row.get("id")
        if not profile_id:
            continue
        stats[profile_id] = {
            "profile_instance_id": profile_id,
            "name": row.get("name") or "",
            "dataset_count": 0,
            "model_count": 0,
            "episode_count": 0,
            "storage_bytes": 0,
            "last_activity": row.get("updated_at"),
        }

    for row in dataset_rows:
        if row.get("status") and row.get("status") != "active":
            continue
        profile_id = row.get("profile_instance_id")
        if not profile_id:
            continue
        entry = stats.setdefault(
            profile_id,
            {
                "profile_instance_id": profile_id,
                "name": "",
                "dataset_count": 0,
                "model_count": 0,
                "episode_count": 0,
                "storage_bytes": 0,
                "last_activity": None,
            },
        )
        entry["dataset_count"] += 1
        entry["episode_count"] += row.get("episode_count") or 0
        entry["storage_bytes"] += row.get("size_bytes") or 0
        updated_at = row.get("updated_at")
        if updated_at and (entry["last_activity"] is None or updated_at > entry["last_activity"]):
            entry["last_activity"] = updated_at

    for row in model_rows:
        if row.get("status") and row.get("status") != "active":
            continue
        profile_id = row.get("profile_instance_id")
        if not profile_id:
            continue
        entry = stats.setdefault(
            profile_id,
            {
                "profile_instance_id": profile_id,
                "name": "",
                "dataset_count": 0,
                "model_count": 0,
                "episode_count": 0,
                "storage_bytes": 0,
                "last_activity": None,
            },
        )
        entry["model_count"] += 1
        entry["storage_bytes"] += row.get("size_bytes") or 0
        updated_at = row.get("updated_at")
        if updated_at and (entry["last_activity"] is None or updated_at > entry["last_activity"]):
            entry["last_activity"] = updated_at

    return list(stats.values())


def _get_training_stats() -> dict:
    """Collect training job statistics."""
    # This would integrate with training.py job storage
    # For now, return placeholder stats
    return {
        "total_jobs": 0,
        "completed_jobs": 0,
        "failed_jobs": 0,
        "active_jobs": 0,
        "average_duration_hours": 0.0,
        "success_rate": 0.0,
        "total_gpu_hours": 0.0,
        "jobs_by_status": {},
        "jobs_by_month": {},
    }


@router.get("/overview", response_model=OverviewResponse)
async def get_overview():
    """Get overall statistics."""
    client = await get_supabase_async_client()
    profiles = (await client.table("profile_instances").select("id").execute()).data or []
    datasets = (
        await client.table("datasets").select("episode_count,size_bytes,status").execute()
    ).data or []
    models = (await client.table("models").select("size_bytes,status").execute()).data or []
    jobs = (await client.table("training_jobs").select("status").execute()).data or []

    total_episodes = sum(d.get("episode_count") or 0 for d in datasets if d.get("status") == "active")
    total_models = sum(1 for m in models if m.get("status") == "active")
    total_datasets = sum(1 for d in datasets if d.get("status") == "active")
    total_storage_mb = (
        sum(d.get("size_bytes") or 0 for d in datasets)
        + sum(m.get("size_bytes") or 0 for m in models)
    ) / (1024 * 1024)

    training_stats = _get_training_stats()
    active_jobs = sum(1 for job in jobs if job.get("status") in ("running", "starting", "deploying"))
    total_jobs = len(jobs)

    return OverviewResponse(
        stats=OverviewStats(
            total_profiles=len(profiles),
            total_datasets=total_datasets,
            total_episodes=total_episodes,
            total_models=total_models,
            total_training_jobs=total_jobs,
            active_training_jobs=active_jobs,
            total_storage_gb=total_storage_mb / 1024,
        ),
        updated_at=datetime.now().isoformat(),
    )


@router.get("/profiles", response_model=ProfileStatsResponse)
async def get_profile_stats():
    """Get per-profile statistics."""
    profile_stats = await _get_profile_stats()
    profiles = [
        ProfileStats(
            profile_instance_id=p["profile_instance_id"],
            name=p.get("name") or "",
            dataset_count=p.get("dataset_count", 0),
            model_count=p.get("model_count", 0),
            episode_count=p.get("episode_count", 0),
            storage_mb=(p.get("storage_bytes") or 0) / (1024 * 1024),
            last_activity=p.get("last_activity"),
        )
        for p in profile_stats
    ]
    return ProfileStatsResponse(profiles=profiles, total=len(profiles))


@router.get("/training", response_model=TrainingStatsResponse)
async def get_training_stats():
    """Get training job statistics."""
    stats = _get_training_stats()

    return TrainingStatsResponse(
        stats=TrainingStats(
            total_jobs=stats["total_jobs"],
            completed_jobs=stats["completed_jobs"],
            failed_jobs=stats["failed_jobs"],
            active_jobs=stats["active_jobs"],
            average_duration_hours=stats["average_duration_hours"],
            success_rate=stats["success_rate"],
            total_gpu_hours=stats["total_gpu_hours"],
        ),
        jobs_by_status=stats["jobs_by_status"],
        jobs_by_month=stats["jobs_by_month"],
    )


@router.get("/storage", response_model=StorageStatsResponse)
async def get_storage_stats():
    """Get storage usage breakdown."""
    categories = []

    # Datasets
    datasets_size = _get_dir_size(DATASETS_DIR) / (1024 * 1024)
    datasets_files = sum(1 for _ in DATASETS_DIR.rglob("*") if _.is_file()) if DATASETS_DIR.exists() else 0
    categories.append({
        "category": "datasets",
        "size_mb": datasets_size,
        "file_count": datasets_files,
    })

    # Models
    models_size = _get_dir_size(MODELS_DIR) / (1024 * 1024)
    models_files = sum(1 for _ in MODELS_DIR.rglob("*") if _.is_file()) if MODELS_DIR.exists() else 0
    categories.append({
        "category": "models",
        "size_mb": models_size,
        "file_count": models_files,
    })

    # Calibrations
    calibration_dir = Path.home() / ".cache" / "percus_ai" / "calibration"
    calib_size = _get_dir_size(calibration_dir) / (1024 * 1024)
    calib_files = sum(1 for _ in calibration_dir.rglob("*") if _.is_file()) if calibration_dir.exists() else 0
    categories.append({
        "category": "calibrations",
        "size_mb": calib_size,
        "file_count": calib_files,
    })

    # Calculate totals
    total_size_mb = sum(c["size_mb"] for c in categories)
    total_size_gb = total_size_mb / 1024

    # Get available disk space
    try:
        total, used, free = shutil.disk_usage(get_storage_root())
        available_gb = free / (1024 * 1024 * 1024)
        used_percentage = (used / total) * 100 if total > 0 else 0
    except Exception:
        available_gb = 0.0
        used_percentage = 0.0

    # Calculate percentages
    storage_categories = []
    for c in categories:
        percentage = (c["size_mb"] / total_size_mb * 100) if total_size_mb > 0 else 0
        storage_categories.append(StorageCategory(
            category=c["category"],
            size_mb=c["size_mb"],
            file_count=c["file_count"],
            percentage=percentage,
        ))

    return StorageStatsResponse(
        total_size_gb=total_size_gb,
        available_gb=available_gb,
        used_percentage=used_percentage,
        categories=storage_categories,
    )
