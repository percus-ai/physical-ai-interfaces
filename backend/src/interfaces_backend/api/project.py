"""Project management API router."""

import logging
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
from percus_ai.core.project import ProjectManager, ConfigLoader
from percus_ai.storage import (
    get_projects_dir,
    get_datasets_dir,
    get_models_dir,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["projects"])


# --- Project Endpoints ---


@router.get("/debug-paths")
async def debug_paths():
    """Debug endpoint to check path resolution."""
    import os
    projects_dir = get_projects_dir()
    manager = ProjectManager()
    manager_info = None
    try:
        manager_info = {
            "type": str(type(manager)),
            "projects_dir": str(getattr(manager, 'projects_dir', 'N/A')),
            "list_projects": manager.list_projects() if hasattr(manager, 'list_projects') else "N/A",
        }
    except Exception as e:
        manager_info = {"error": str(e)}
    return {
        "cwd": str(Path.cwd()),
        "PHYSICAL_AI_DATA_DIR": os.environ.get("PHYSICAL_AI_DATA_DIR", "NOT SET"),
        "projects_dir": str(projects_dir),
        "projects_dir_exists": projects_dir.exists(),
        "yaml_files": [str(f) for f in projects_dir.glob("*.yaml")] if projects_dir.exists() else [],
        "manager": manager_info,
    }


@router.get("", response_model=ProjectListResponse)
async def list_projects():
    """List all available projects."""
    # Always use direct YAML file listing for reliability
    # ProjectManager from percus_ai may have different path configuration
    projects_dir = get_projects_dir()
    if projects_dir.exists():
        projects = sorted([f.stem for f in projects_dir.glob("*.yaml")])
    else:
        projects = []

    return ProjectListResponse(projects=projects, total=len(projects))


@router.get("/{project_name}", response_model=ProjectModel)
async def get_project(project_name: str):
    """Get project details."""
    import yaml

    # Load directly from YAML file for reliability
    projects_dir = get_projects_dir()
    yaml_path = projects_dir / f"{project_name}.yaml"

    if not yaml_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_name}"
        )

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        project_info = config.get("project", {})
        recording_info = config.get("recording", {})

        return ProjectModel(
            name=project_info.get("name", project_name),
            display_name=project_info.get("display_name", project_name),
            description=project_info.get("description", ""),
            version=project_info.get("version", "1.0"),
            created_at=project_info.get("created_at", ""),
            robot_type=project_info.get("robot_type", "so101"),
            episode_time_s=recording_info.get("episode_time_s", 60),
            reset_time_s=recording_info.get("reset_time_s", 10),
            cameras=config.get("cameras", {}),
            arms=config.get("arms", {}),
        )
    except Exception as e:
        logger.error(f"Failed to load project {project_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load project: {str(e)}"
        )


@router.post("", response_model=ProjectModel)
async def create_project(request: ProjectCreateRequest):
    """Create a new project."""
    manager = ProjectManager()

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
    manager = ProjectManager()

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
    manager = ProjectManager()

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
    loader = ConfigLoader()

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
    import shutil

    # Use dynamic path resolution
    projects_dir = get_projects_dir()
    project_yaml = projects_dir / f"{project_name}.yaml"

    if not project_yaml.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_name}"
        )

    # Delete project YAML
    project_yaml.unlink()

    deleted_items = ["project config"]

    if delete_data:
        # Delete dataset directory
        datasets_dir = get_datasets_dir()
        dataset_dir = datasets_dir / project_name
        if dataset_dir.exists():
            shutil.rmtree(dataset_dir)
            deleted_items.append("datasets")

        # Delete models directory
        models_dir = get_models_dir()
        model_dir = models_dir / project_name
        if model_dir.exists():
            shutil.rmtree(model_dir)
            deleted_items.append("models")

    return {
        "success": True,
        "message": f"Deleted: {', '.join(deleted_items)}",
        "project_name": project_name,
    }
