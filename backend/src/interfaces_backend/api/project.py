"""Project management API router."""

import logging
from datetime import datetime
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException
from interfaces_backend.models.project import (
    ProjectCreateRequest,
    ProjectDeviceValidation,
    ProjectImportRequest,
    ProjectListResponse,
    ProjectModel,
    ProjectStatsModel,
    ProjectValidateResponse,
)
from percus_ai.core.project import ProjectManager, ConfigLoader
from percus_ai.db import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["projects"])


# --- Project Endpoints ---


@router.get("/debug-paths")
async def debug_paths():
    """Debug endpoint to check DB connectivity."""
    manager = ProjectManager()
    client = get_supabase_client()
    projects = client.table("projects").select("id").limit(5).execute().data or []
    return {
        "projects_sample": [p.get("id") for p in projects],
        "manager_projects": manager.list_projects(),
    }


@router.get("", response_model=ProjectListResponse)
async def list_projects():
    """List all available projects."""
    projects = ProjectManager().list_projects()
    return ProjectListResponse(projects=projects, total=len(projects))


@router.get("/{project_name}", response_model=ProjectModel)
async def get_project(project_name: str):
    """Get project details."""
    manager = ProjectManager()
    try:
        project = manager.get_project(project_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_name}")
    except Exception as e:
        logger.error(f"Failed to load project {project_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load project: {str(e)}")

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


def _build_project_record_from_yaml(content: str) -> dict:
    data = yaml.safe_load(content) or {}
    project = data.get("project", {}) or {}
    recording = data.get("recording", {}) or {}
    cameras = data.get("cameras", {}) or {}
    arms = data.get("arms", {}) or {}

    project_id = project.get("name")
    if not project_id:
        raise HTTPException(status_code=400, detail="project.name is required")

    created_at = project.get("created_at") or datetime.now().isoformat()
    updated_at = datetime.now().isoformat()

    return {
        "id": project_id,
        "name": project_id,
        "display_name": project.get("display_name") or project_id,
        "description": project.get("description") or "",
        "version": project.get("version") or "1.0",
        "robot_type": project.get("robot_type") or "so101",
        "episode_time_s": recording.get("episode_time_s", 20),
        "reset_time_s": recording.get("reset_time_s", 10),
        "cameras": cameras,
        "arms": arms,
        "created_at": created_at,
        "updated_at": updated_at,
    }


@router.post("/import", response_model=ProjectModel)
async def import_project(request: ProjectImportRequest):
    """Import a project from YAML content."""
    try:
        record = _build_project_record_from_yaml(request.yaml_content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")

    client = get_supabase_client()
    project_id = record["id"]
    existing = client.table("projects").select("id").eq("id", project_id).execute().data or []
    if existing and not request.force:
        raise HTTPException(status_code=409, detail=f"Project already exists: {project_id}")

    client.table("projects").upsert(record, on_conflict="id").execute()

    return ProjectModel(
        name=record["id"],
        display_name=record["display_name"],
        description=record["description"],
        version=record["version"],
        created_at=record["created_at"],
        robot_type=record["robot_type"],
        episode_time_s=record["episode_time_s"],
        reset_time_s=record["reset_time_s"],
        cameras=record["cameras"],
        arms=record["arms"],
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
            episodes=stats.get("episodes", []),
            models=stats.get("models", []),
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
    client = get_supabase_client()
    existing = client.table("projects").select("id").eq("id", project_name).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_name}")

    deleted_items = ["project"]
    if delete_data:
        client.table("datasets").delete().eq("project_id", project_name).execute()
        client.table("models").delete().eq("project_id", project_name).execute()
        client.table("training_jobs").delete().eq("project_id", project_name).execute()
        deleted_items.extend(["datasets", "models", "training_jobs"])

    client.table("projects").delete().eq("id", project_name).execute()

    return {
        "success": True,
        "message": f"Deleted: {', '.join(deleted_items)}",
        "project_name": project_name,
    }
