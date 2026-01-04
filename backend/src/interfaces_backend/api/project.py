"""Project management API router."""

import logging
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from interfaces_backend.models.project import (
    ProjectCreateRequest,
    ProjectDeviceValidation,
    ProjectListResponse,
    ProjectModel,
    ProjectStatsModel,
    ProjectValidateResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["projects"])

# Project directories
PROJECTS_DIR = Path.cwd() / "projects"
DATASETS_DIR = Path.cwd() / "datasets"
MODELS_DIR = Path.cwd() / "models"


def _get_project_manager():
    """Import ProjectManager from percus_ai if available."""
    try:
        from percus_ai.core.project import ProjectManager
        return ProjectManager()
    except ImportError:
        features_path = Path(__file__).resolve().parents[5] / "features"
        if features_path.exists() and str(features_path) not in sys.path:
            sys.path.insert(0, str(features_path))
            try:
                from percus_ai.core.project import ProjectManager
                return ProjectManager()
            except ImportError:
                pass
    return None


def _get_config_loader():
    """Import ConfigLoader from percus_ai if available."""
    try:
        from percus_ai.core.project import ConfigLoader
        return ConfigLoader()
    except ImportError:
        features_path = Path(__file__).resolve().parents[5] / "features"
        if features_path.exists() and str(features_path) not in sys.path:
            sys.path.insert(0, str(features_path))
            try:
                from percus_ai.core.project import ConfigLoader
                return ConfigLoader()
            except ImportError:
                pass
    return None


# --- Project Endpoints ---


@router.get("", response_model=ProjectListResponse)
async def list_projects():
    """List all available projects."""
    manager = _get_project_manager()
    if manager:
        projects = manager.list_projects()
    else:
        # Fallback: list YAML files in projects directory
        if PROJECTS_DIR.exists():
            projects = sorted([f.stem for f in PROJECTS_DIR.glob("*.yaml")])
        else:
            projects = []

    return ProjectListResponse(projects=projects, total=len(projects))


@router.get("/{project_name}", response_model=ProjectModel)
async def get_project(project_name: str):
    """Get project details."""
    manager = _get_project_manager()
    if not manager:
        raise HTTPException(
            status_code=503,
            detail="ProjectManager not available"
        )

    try:
        project = manager.get_project(project_name)
        return ProjectModel(
            name=project.name,
            display_name=project.display_name,
            description=project.description,
            version=project.version,
            created_at=project.created_at,
            robot_type=project.robot_type,
            episode_time_s=project.episode_time_s,
            reset_time_s=project.reset_time_s,
            cameras=project.cameras,
            arms=project.arms,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_name}"
        )


@router.post("", response_model=ProjectModel)
async def create_project(request: ProjectCreateRequest):
    """Create a new project."""
    manager = _get_project_manager()
    if not manager:
        raise HTTPException(
            status_code=503,
            detail="ProjectManager not available"
        )

    try:
        # Convert camera models to dicts if provided
        cameras = None
        if request.cameras:
            cameras = {
                name: cam.model_dump()
                for name, cam in request.cameras.items()
            }

        project = manager.create_project(
            display_name=request.display_name,
            description=request.description,
            cameras=cameras,
            episode_time_s=request.episode_time_s,
            reset_time_s=request.reset_time_s,
            robot_type=request.robot_type,
        )

        return ProjectModel(
            name=project.name,
            display_name=project.display_name,
            description=project.description,
            version=project.version,
            created_at=project.created_at,
            robot_type=project.robot_type,
            episode_time_s=project.episode_time_s,
            reset_time_s=project.reset_time_s,
            cameras=project.cameras,
            arms=project.arms,
        )
    except FileExistsError:
        raise HTTPException(
            status_code=409,
            detail=f"Project already exists: {request.display_name}"
        )
    except Exception as e:
        logger.error(f"Failed to create project: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create project: {str(e)}"
        )


@router.get("/{project_name}/stats", response_model=ProjectStatsModel)
async def get_project_stats(project_name: str):
    """Get project statistics."""
    manager = _get_project_manager()
    if not manager:
        raise HTTPException(
            status_code=503,
            detail="ProjectManager not available"
        )

    try:
        stats = manager.get_project_stats(project_name)

        return ProjectStatsModel(
            project_name=project_name,
            episode_count=stats["episode_count"],
            model_count=stats["model_count"],
            dataset_size_bytes=stats["dataset_size"],
            models_size_bytes=stats["models_size"],
            user_stats=stats["user_stats"],
            episodes=[ep.name for ep in stats["episodes"]],
            models=stats["models"],
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_name}"
        )


@router.get("/{project_name}/validate", response_model=ProjectValidateResponse)
async def validate_project(project_name: str):
    """Validate project dataset."""
    manager = _get_project_manager()
    if not manager:
        raise HTTPException(
            status_code=503,
            detail="ProjectManager not available"
        )

    try:
        is_valid, issues = manager.validate_dataset(project_name)

        return ProjectValidateResponse(
            project_name=project_name,
            is_valid=is_valid,
            issues=issues,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_name}"
        )


@router.get("/{project_name}/validate-devices", response_model=ProjectDeviceValidation)
async def validate_project_devices(project_name: str, devices_file: Optional[str] = None):
    """Validate that required devices are configured for a project."""
    loader = _get_config_loader()
    if not loader:
        raise HTTPException(
            status_code=503,
            detail="ConfigLoader not available"
        )

    try:
        project = loader.load_project(project_name)
        devices = loader.load_device_config(devices_file)
        all_present, missing = loader.validate_project_devices(project, devices)

        return ProjectDeviceValidation(
            project_name=project_name,
            all_devices_present=all_present,
            missing_devices=missing,
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )


@router.delete("/{project_name}")
async def delete_project(project_name: str, delete_data: bool = False):
    """Delete a project.

    Args:
        project_name: Project to delete
        delete_data: If True, also delete associated datasets and models
    """
    project_yaml = PROJECTS_DIR / f"{project_name}.yaml"

    if not project_yaml.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_name}"
        )

    import shutil

    # Delete project YAML
    project_yaml.unlink()

    deleted_items = ["project config"]

    if delete_data:
        # Delete dataset directory
        dataset_dir = DATASETS_DIR / project_name
        if dataset_dir.exists():
            shutil.rmtree(dataset_dir)
            deleted_items.append("datasets")

        # Delete models directory
        models_dir = MODELS_DIR / project_name
        if models_dir.exists():
            shutil.rmtree(models_dir)
            deleted_items.append("models")

    return {
        "success": True,
        "message": f"Deleted: {', '.join(deleted_items)}",
        "project_name": project_name,
    }
