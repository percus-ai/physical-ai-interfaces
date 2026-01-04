"""Analytics API router."""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter

from interfaces_backend.models.analytics import (
    OverviewStats,
    OverviewResponse,
    ProjectStats,
    ProjectsStatsResponse,
    TrainingStats,
    TrainingStatsResponse,
    StorageCategory,
    StorageStatsResponse,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Standard directories
DATASETS_DIR = Path.cwd() / "datasets"
MODELS_DIR = Path.cwd() / "models"
TRAINING_CONFIGS_DIR = Path.cwd() / "training_configs"


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


def _count_episodes(project_dir: Path) -> int:
    """Count episodes in a project directory."""
    count = 0
    for item in project_dir.iterdir():
        if item.is_dir() and item.name.startswith("episode_"):
            count += 1
    return count


def _count_models(project_dir: Path) -> int:
    """Count models in a project directory."""
    count = 0
    if project_dir.exists():
        for item in project_dir.iterdir():
            if item.is_dir():
                # Check for model files
                if (item / "config.json").exists() or list(item.glob("*.safetensors")):
                    count += 1
    return count


def _get_project_stats() -> list[dict]:
    """Collect statistics for all projects."""
    projects = []

    if not DATASETS_DIR.exists():
        return projects

    for project_dir in DATASETS_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        # Count episodes
        episode_count = _count_episodes(project_dir)
        if episode_count == 0:
            continue

        # Get storage size
        storage_bytes = _get_dir_size(project_dir)
        storage_mb = storage_bytes / (1024 * 1024)

        # Count models for this project
        model_dir = MODELS_DIR / project_dir.name
        model_count = _count_models(model_dir) if model_dir.exists() else 0

        # Get last activity
        try:
            last_activity = datetime.fromtimestamp(
                project_dir.stat().st_mtime
            ).isoformat()
        except Exception:
            last_activity = None

        # Count total frames (from parquet files)
        total_frames = 0
        for episode_dir in project_dir.iterdir():
            if episode_dir.is_dir():
                parquet_files = list(episode_dir.glob("*.parquet"))
                if parquet_files:
                    try:
                        import pyarrow.parquet as pq
                        for pf in parquet_files:
                            table = pq.read_table(pf)
                            total_frames += len(table)
                    except ImportError:
                        pass
                    except Exception:
                        pass

        projects.append({
            "project_id": project_dir.name,
            "name": project_dir.name,
            "episode_count": episode_count,
            "model_count": model_count,
            "total_frames": total_frames,
            "total_duration_hours": 0.0,  # Would need metadata
            "storage_mb": storage_mb,
            "last_activity": last_activity,
        })

    return projects


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
    project_stats = _get_project_stats()
    training_stats = _get_training_stats()

    total_episodes = sum(p["episode_count"] for p in project_stats)
    total_models = sum(p["model_count"] for p in project_stats)
    total_storage_mb = sum(p["storage_mb"] for p in project_stats)

    # Add models directory storage
    if MODELS_DIR.exists():
        total_storage_mb += _get_dir_size(MODELS_DIR) / (1024 * 1024)

    return OverviewResponse(
        stats=OverviewStats(
            total_projects=len(project_stats),
            total_episodes=total_episodes,
            total_models=total_models,
            total_training_jobs=training_stats["total_jobs"],
            active_training_jobs=training_stats["active_jobs"],
            total_storage_gb=total_storage_mb / 1024,
        ),
        updated_at=datetime.now().isoformat(),
    )


@router.get("/projects", response_model=ProjectsStatsResponse)
async def get_projects_stats():
    """Get per-project statistics."""
    project_stats = _get_project_stats()

    projects = [
        ProjectStats(
            project_id=p["project_id"],
            name=p["name"],
            episode_count=p["episode_count"],
            model_count=p["model_count"],
            total_frames=p["total_frames"],
            total_duration_hours=p["total_duration_hours"],
            storage_mb=p["storage_mb"],
            last_activity=p["last_activity"],
        )
        for p in project_stats
    ]

    return ProjectsStatsResponse(projects=projects, total=len(projects))


@router.get("/projects/{project_name}", response_model=ProjectStats)
async def get_project_stats(project_name: str):
    """Get statistics for a specific project."""
    project_stats = _get_project_stats()

    for p in project_stats:
        if p["project_id"] == project_name:
            return ProjectStats(
                project_id=p["project_id"],
                name=p["name"],
                episode_count=p["episode_count"],
                model_count=p["model_count"],
                total_frames=p["total_frames"],
                total_duration_hours=p["total_duration_hours"],
                storage_mb=p["storage_mb"],
                last_activity=p["last_activity"],
            )

    # Return empty stats for non-existent project
    return ProjectStats(
        project_id=project_name,
        name=project_name,
        episode_count=0,
        model_count=0,
        total_frames=0,
        total_duration_hours=0.0,
        storage_mb=0.0,
        last_activity=None,
    )


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

    # Training configs
    configs_size = _get_dir_size(TRAINING_CONFIGS_DIR) / (1024 * 1024)
    configs_files = sum(1 for _ in TRAINING_CONFIGS_DIR.rglob("*") if _.is_file()) if TRAINING_CONFIGS_DIR.exists() else 0
    categories.append({
        "category": "training_configs",
        "size_mb": configs_size,
        "file_count": configs_files,
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
        import shutil
        total, used, free = shutil.disk_usage(Path.cwd())
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
