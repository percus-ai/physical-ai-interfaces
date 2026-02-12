"""Profile class/instance API."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
from uuid import uuid4

import yaml

from fastapi import APIRouter, HTTPException

from interfaces_backend.models.profile import (
    ProfileClassDetailResponse,
    ProfileClassInfo,
    ProfileClassCreateRequest,
    ProfileClassUpdateRequest,
    ProfileClassesResponse,
    ProfileInstanceCreateRequest,
    ProfileInstanceModel,
    ProfileInstanceResponse,
    ProfileInstancesResponse,
    ProfileInstanceUpdateRequest,
    ProfileInstanceStatusResponse,
    ProfileDeviceStatusCamera,
    ProfileDeviceStatusArm,
    VlaborStatusResponse,
)
from interfaces_backend.services.vlabor_runtime import (
    VlaborCommandError,
    restart_vlabor as run_vlabor_restart,
    start_vlabor as run_vlabor_start,
    stop_vlabor as run_vlabor_stop,
)
from interfaces_backend.utils.docker_compose import (
    build_compose_command,
    get_vlabor_compose_file,
    get_vlabor_env_file,
)
from percus_ai.db import get_current_user_id, get_supabase_async_client
from percus_ai.profiles.models import ProfileClass, ProfileInstance
from percus_ai.profiles.registry import ProfileRegistry
from percus_ai.profiles.paths import get_profile_classes_dir
from percus_ai.profiles.writer import (
    write_profile_class_yaml,
    write_current_profile_config,
    write_profile_instance_snapshot,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _require_user_id() -> str:
    try:
        return get_current_user_id()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Login required") from exc


def _optional_user_id() -> str | None:
    try:
        return get_current_user_id()
    except ValueError:
        return None


def _get_vlabor_compose_cmd(*, strict: bool) -> tuple[list[str], Path]:
    compose_file = get_vlabor_compose_file()
    if strict and not compose_file.exists():
        raise HTTPException(status_code=500, detail=f"{compose_file} not found")
    return build_compose_command(compose_file, get_vlabor_env_file()), compose_file


def _start_vlabor() -> None:
    try:
        run_vlabor_start()
    except VlaborCommandError as exc:
        raise HTTPException(status_code=500, detail=f"vlabor start failed: {exc}") from exc


def _restart_vlabor() -> None:
    try:
        run_vlabor_restart()
    except VlaborCommandError as exc:
        raise HTTPException(status_code=500, detail=f"vlabor restart failed: {exc}") from exc


def _stop_vlabor() -> None:
    try:
        run_vlabor_stop()
    except VlaborCommandError as exc:
        raise HTTPException(status_code=500, detail=f"vlabor stop failed: {exc}") from exc


def _get_vlabor_status() -> dict:
    compose_cmd, compose_file = _get_vlabor_compose_cmd(strict=False)
    if not compose_file.exists():
        return {"status": "unknown", "service": "vlabor"}
    result = subprocess.run(
        [*compose_cmd, "ps", "--format", "json", "vlabor"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {"status": "unknown", "service": "vlabor"}
    try:
        data = json.loads(result.stdout)
    except Exception:
        return {"status": "unknown", "service": "vlabor"}

    entry = None
    if isinstance(data, list):
        entry = data[0] if data else None
    elif isinstance(data, dict):
        entry = data

    if entry:
        state_raw = (entry.get("State") or "").lower()
        status_value = "unknown"
        if "restarting" in state_raw:
            status_value = "restarting"
        elif "running" in state_raw:
            status_value = "running"
        elif "exited" in state_raw or "stopped" in state_raw:
            status_value = "stopped"
        return {
            "status": status_value,
            "service": "vlabor",
            "state": entry.get("State"),
            "status_detail": entry.get("Status"),
            "running_for": entry.get("RunningFor"),
            "created_at": entry.get("CreatedAt"),
            "container_id": entry.get("ID"),
        }
    return {"status": "unknown", "service": "vlabor"}


def _load_profile_class_from_yaml(path: Path) -> ProfileClass:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    class_data = payload.get("class") or {}
    class_key = class_data.get("id") or path.stem
    if not class_key:
        raise ValueError("class id missing")
    return ProfileClass(
        id=None,
        class_key=class_key,
        version=int(class_data.get("version") or 1),
        description=str(class_data.get("description") or ""),
        defaults=class_data.get("defaults") or {},
        profile=class_data.get("profile") or {},
        metadata=class_data.get("metadata") or {},
    )


async def _ensure_profile_class(profile_class: ProfileClass) -> ProfileClass:
    client = await get_supabase_async_client()
    rows = (
        await client.table("profile_classes")
        .select("*")
        .eq("class_key", profile_class.class_key)
        .limit(1)
        .execute()
    ).data or []
    if rows:
        row = rows[0]
        return ProfileClass(
            id=str(row.get("id")),
            class_key=row.get("class_key") or profile_class.class_key,
            version=row.get("version") or profile_class.version,
            description=row.get("description") or profile_class.description,
            defaults=row.get("defaults") or profile_class.defaults,
            profile=row.get("profile") or profile_class.profile,
            metadata=row.get("metadata") or profile_class.metadata,
        )

    record = {
        "class_key": profile_class.class_key,
        "version": profile_class.version,
        "description": profile_class.description,
        "defaults": profile_class.defaults,
        "profile": profile_class.profile,
        "metadata": profile_class.metadata,
    }
    await client.table("profile_classes").insert(record).execute()
    rows = (
        await client.table("profile_classes")
        .select("*")
        .eq("class_key", profile_class.class_key)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=500, detail="Failed to load profile class")
    row = rows[0]
    return ProfileClass(
        id=str(row.get("id")),
        class_key=row.get("class_key") or profile_class.class_key,
        version=row.get("version") or profile_class.version,
        description=row.get("description") or profile_class.description,
        defaults=row.get("defaults") or profile_class.defaults,
        profile=row.get("profile") or profile_class.profile,
        metadata=row.get("metadata") or profile_class.metadata,
    )


async def _bootstrap_default_profile() -> ProfileInstance:
    classes_dir = get_profile_classes_dir()
    if not classes_dir.exists():
        raise HTTPException(status_code=404, detail="Profile class not found")
    yaml_files = sorted(classes_dir.glob("*.yaml"))
    if not yaml_files:
        raise HTTPException(status_code=404, detail="Profile class not found")

    profile_class = _load_profile_class_from_yaml(yaml_files[0])
    profile_class = await _ensure_profile_class(profile_class)

    instance_id = str(uuid4())
    instance = ProfileInstance(
        id=instance_id,
        class_id=profile_class.id or "",
        class_version=profile_class.version,
        name="active",
        variables={},
        metadata={},
        thumbnail_key=None,
    )
    instance.touch()

    write_current_profile_config(profile_class, instance)
    write_profile_instance_snapshot(profile_class, instance)

    now = datetime.now(timezone.utc).isoformat()
    record = {
        "id": instance.id,
        "class_id": instance.class_id,
        "class_version": instance.class_version,
        "name": instance.name,
        "variables": instance.variables,
        "metadata": instance.metadata,
        "thumbnail_key": instance.thumbnail_key,
        "is_active": True,
        "created_at": instance.created_at or now,
        "updated_at": instance.updated_at or now,
    }
    owner = _optional_user_id()
    if owner:
        record["owner_user_id"] = owner

    client = await get_supabase_async_client()
    await client.table("profile_instances").insert(record).execute()
    await _set_active_instance(client, instance.id)
    return instance


async def _ensure_profile_instances() -> None:
    classes_dir = get_profile_classes_dir()
    if not classes_dir.exists():
        return
    yaml_files = sorted(classes_dir.glob("*.yaml"))
    if not yaml_files:
        return
    client = await get_supabase_async_client()
    owner = _optional_user_id()
    for path in yaml_files:
        try:
            profile_class = _load_profile_class_from_yaml(path)
        except Exception:
            continue
        profile_class = await _ensure_profile_class(profile_class)
        rows = (
            await client.table("profile_instances")
            .select("id")
            .eq("class_id", profile_class.id)
            .limit(1)
            .execute()
        ).data or []
        if rows:
            continue
        instance = ProfileInstance(
            id=str(uuid4()),
            class_id=profile_class.id or "",
            class_version=profile_class.version,
            name="active",
            variables={},
            metadata={},
            thumbnail_key=None,
        )
        instance.touch()
        record = {
            "id": instance.id,
            "class_id": instance.class_id,
            "class_version": instance.class_version,
            "name": instance.name,
            "variables": instance.variables,
            "metadata": instance.metadata,
            "thumbnail_key": instance.thumbnail_key,
            "is_active": False,
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
        }
        if owner:
            record["owner_user_id"] = owner
        await client.table("profile_instances").insert(record).execute()


def _resolve_profile_settings(profile_class, instance: ProfileInstance) -> dict:
    settings: dict = {}
    if profile_class.defaults:
        settings.update(profile_class.defaults)
    if instance.variables:
        settings.update(instance.variables)
    return settings


def _render_value(value, settings: dict):
    if isinstance(value, str) and "${" in value:
        rendered = value
        for key, val in settings.items():
            rendered = rendered.replace(f"${{{key}}}", str(val))
        return rendered
    return value


def _extract_camera_specs(profile_class, settings: dict) -> list[dict]:
    cameras = []
    profile = profile_class.profile or {}
    actions = profile.get("actions") or []
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("type") != "include":
            continue
        package = action.get("package")
        if package not in ("fv_camera", "fv_realsense"):
            continue
        args = action.get("args") or {}
        node_name = _render_value(args.get("node_name"), settings) or ""
        enabled_raw = action.get("enabled", True)
        enabled = bool(_render_value(enabled_raw, settings))
        if not node_name:
            continue
        cameras.append({
            "name": node_name,
            "package": package,
            "enabled": enabled,
        })
    return cameras


def _extract_arm_specs(settings: dict) -> list[dict]:
    arms = []
    left_enabled = bool(settings.get("left_arm_enabled", True))
    right_enabled = bool(settings.get("right_arm_enabled", True))
    arms.append({"name": "left_arm", "enabled": left_enabled})
    arms.append({"name": "right_arm", "enabled": right_enabled})
    return arms


def _fetch_ros2_topics() -> list[str]:
    compose_cmd, compose_file = _get_vlabor_compose_cmd(strict=False)
    if not compose_file.exists():
        return []
    cmd = [
        *compose_cmd,
        "exec",
        "-T",
        "vlabor",
        "bash",
        "-lc",
        "source /opt/ros/humble/setup.sh && ros2 topic list",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _record_to_instance(row: Dict, class_key: str) -> ProfileInstanceModel:
    return ProfileInstanceModel(
        id=row.get("id"),
        class_id=row.get("class_id") or "",
        class_key=class_key,
        class_version=row.get("class_version") or 1,
        name=row.get("name") or "active",
        variables=row.get("variables") or {},
        metadata=row.get("metadata") or {},
        thumbnail_key=row.get("thumbnail_key"),
        is_active=bool(row.get("is_active")),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _row_to_profile_instance(row: Dict) -> ProfileInstance:
    return ProfileInstance(
        id=row.get("id"),
        class_id=row.get("class_id"),
        class_version=row.get("class_version") or 1,
        name=row.get("name") or "active",
        variables=row.get("variables") or {},
        metadata=row.get("metadata") or {},
        thumbnail_key=row.get("thumbnail_key"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


async def _set_active_instance(client, instance_id: str) -> None:
    await client.table("profile_instances").update({"is_active": False}).neq("id", instance_id).execute()
    await client.table("profile_instances").update({"is_active": True}).eq("id", instance_id).execute()


@router.get("/classes", response_model=ProfileClassesResponse)
async def list_profile_classes():
    registry = ProfileRegistry()
    classes = await registry.list_classes()
    items = [
        ProfileClassInfo(
            id=cls.id or "",
            class_key=cls.class_key,
            version=cls.version,
            description=cls.description,
        )
        for cls in classes
    ]
    return ProfileClassesResponse(classes=items, total=len(items))


@router.get("/classes/{class_id}", response_model=ProfileClassDetailResponse)
async def get_profile_class(class_id: str):
    registry = ProfileRegistry()
    profile_class = await registry.get_class(class_id)
    return ProfileClassDetailResponse(profile_class=profile_class.model_dump())


@router.post("/classes", response_model=ProfileClassDetailResponse)
async def create_profile_class(request: ProfileClassCreateRequest):
    _require_user_id()
    client = await get_supabase_async_client()
    record = {
        "class_key": request.class_key,
        "version": request.version,
        "description": request.description,
        "defaults": request.defaults,
        "profile": request.profile,
        "metadata": request.metadata,
    }
    await client.table("profile_classes").insert(record).execute()
    rows = (
        await client.table("profile_classes")
        .select("*")
        .eq("class_key", request.class_key)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=500, detail="Failed to create profile class")
    row = rows[0]
    profile_class = await ProfileRegistry().get_class(str(row.get("id")))
    write_profile_class_yaml(profile_class)
    return ProfileClassDetailResponse(profile_class=profile_class.model_dump())


@router.put("/classes/{class_id}", response_model=ProfileClassDetailResponse)
async def update_profile_class(class_id: str, request: ProfileClassUpdateRequest):
    _require_user_id()
    client = await get_supabase_async_client()
    rows = (
        await client.table("profile_classes")
        .select("*")
        .eq("id", class_id)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Profile class not found")
    row = rows[0]
    updated = dict(row)
    if request.version is not None:
        updated["version"] = request.version
    if request.description is not None:
        updated["description"] = request.description
    if request.defaults is not None:
        updated["defaults"] = request.defaults
    if request.profile is not None:
        updated["profile"] = request.profile
    if request.metadata is not None:
        updated["metadata"] = request.metadata
    updated["updated_at"] = datetime.now(timezone.utc).isoformat()

    await client.table("profile_classes").update(updated).eq("id", class_id).execute()

    profile_class = await ProfileRegistry().get_class(class_id)
    write_profile_class_yaml(profile_class)
    return ProfileClassDetailResponse(profile_class=profile_class.model_dump())


@router.delete("/classes/{class_id}")
async def delete_profile_class(class_id: str):
    _require_user_id()
    client = await get_supabase_async_client()
    rows = (
        await client.table("profile_classes")
        .select("id,class_key")
        .eq("id", class_id)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Profile class not found")
    class_key = rows[0].get("class_key")
    await client.table("profile_classes").delete().eq("id", class_id).execute()
    if class_key:
        yaml_path = get_profile_classes_dir() / f"{class_key}.yaml"
        if yaml_path.exists():
            yaml_path.unlink()
    return {"success": True}


@router.get("/instances", response_model=ProfileInstancesResponse)
async def list_profile_instances():
    await _ensure_profile_instances()
    client = await get_supabase_async_client()
    rows = (
        await client.table("profile_instances").select("*").order("created_at", desc=True).execute()
    ).data or []
    class_rows = (await client.table("profile_classes").select("id,class_key").execute()).data or []
    class_key_map = {str(c.get("id")): c.get("class_key") for c in class_rows}
    items = [
        _record_to_instance(row, class_key_map.get(str(row.get("class_id")), ""))
        for row in rows
    ]
    return ProfileInstancesResponse(instances=items, total=len(items))


@router.get("/instances/active", response_model=ProfileInstanceResponse)
async def get_active_instance():
    await _ensure_profile_instances()
    client = await get_supabase_async_client()
    rows = (
        await client.table("profile_instances").select("*").eq("is_active", True).limit(1).execute()
    ).data or []
    if not rows:
        instance = await _bootstrap_default_profile()
        class_row = (
            await client.table("profile_classes")
            .select("class_key")
            .eq("id", instance.class_id)
            .limit(1)
            .execute()
        ).data or []
        class_key = class_row[0].get("class_key") if class_row else ""
        instance_model = ProfileInstanceModel(
            id=instance.id,
            class_id=instance.class_id,
            class_key=class_key,
            class_version=instance.class_version,
            name=instance.name,
            variables=instance.variables,
            metadata=instance.metadata,
            thumbnail_key=instance.thumbnail_key,
            is_active=True,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
        )
        return ProfileInstanceResponse(instance=instance_model)
    class_row = (
        await client.table("profile_classes")
        .select("class_key")
        .eq("id", rows[0].get("class_id"))
        .limit(1)
        .execute()
    ).data or []
    class_key = class_row[0].get("class_key") if class_row else ""
    instance = _record_to_instance(rows[0], class_key)
    return ProfileInstanceResponse(instance=instance)


@router.get("/instances/active/status", response_model=ProfileInstanceStatusResponse)
async def get_active_instance_status():
    await _ensure_profile_instances()
    client = await get_supabase_async_client()
    rows = (
        await client.table("profile_instances").select("*").eq("is_active", True).limit(1).execute()
    ).data or []
    if not rows:
        instance = await _bootstrap_default_profile()
        rows = [
            {
                "id": instance.id,
                "class_id": instance.class_id,
                "class_version": instance.class_version,
                "name": instance.name,
                "variables": instance.variables,
                "metadata": instance.metadata,
                "thumbnail_key": instance.thumbnail_key,
                "created_at": instance.created_at,
                "updated_at": instance.updated_at,
            }
        ]
    instance_row = rows[0]
    class_row = (
        await client.table("profile_classes")
        .select("*")
        .eq("id", instance_row.get("class_id"))
        .limit(1)
        .execute()
    ).data or []
    if not class_row:
        raise HTTPException(status_code=404, detail="Profile class not found")
    profile_class = await ProfileRegistry().get_class(str(instance_row.get("class_id")))
    instance = _row_to_profile_instance(instance_row)
    settings = _resolve_profile_settings(profile_class, instance)

    topics = _fetch_ros2_topics()
    topic_set = set(topics)

    camera_specs = _extract_camera_specs(profile_class, settings)
    cameras = []
    for cam in camera_specs:
        name = cam["name"]
        expected_topics = []
        if cam["package"] == "fv_realsense":
            expected_topics = [
                f"/{name}/color/image_raw",
                f"/{name}/depth/image_rect_raw",
            ]
        else:
            expected_topics = [
                f"/{name}/image_raw",
                f"/{name}/image_raw/compressed",
            ]
        connected = any(topic in topic_set for topic in expected_topics)
        cameras.append(ProfileDeviceStatusCamera(
            name=name,
            enabled=bool(cam.get("enabled", True)),
            connected=connected,
            topics=expected_topics,
        ))

    arm_specs = _extract_arm_specs(settings)
    arms = []
    for arm in arm_specs:
        ns = arm["name"]
        expected = f"/{ns}/joint_states"
        connected = expected in topic_set
        arms.append(ProfileDeviceStatusArm(
            name=ns,
            enabled=bool(arm.get("enabled", True)),
            connected=connected,
        ))

    return ProfileInstanceStatusResponse(
        profile_id=instance.id,
        profile_class_key=profile_class.class_key,
        cameras=cameras,
        arms=arms,
        topics=topics,
    )


@router.get("/vlabor/status", response_model=VlaborStatusResponse)
async def get_vlabor_status():
    return VlaborStatusResponse(**_get_vlabor_status())


@router.post("/vlabor/start", response_model=VlaborStatusResponse)
async def start_vlabor():
    _start_vlabor()
    return VlaborStatusResponse(**_get_vlabor_status())


@router.post("/vlabor/stop", response_model=VlaborStatusResponse)
async def stop_vlabor():
    _stop_vlabor()
    return VlaborStatusResponse(**_get_vlabor_status())




@router.post("/instances", response_model=ProfileInstanceResponse)
async def create_profile_instance(request: ProfileInstanceCreateRequest):
    _require_user_id()
    registry = ProfileRegistry()
    profile_class = await registry.get_class(request.class_id)

    instance_id = str(uuid4())
    instance = ProfileInstance(
        id=instance_id,
        class_id=profile_class.id,
        class_version=profile_class.version,
        name=request.name or "active",
        variables=request.variables or {},
        metadata=request.metadata or {},
        thumbnail_key=request.thumbnail_key,
    )
    instance.touch()

    if request.activate:
        write_current_profile_config(profile_class, instance)
    write_profile_instance_snapshot(profile_class, instance)

    now = datetime.now(timezone.utc).isoformat()
    record = {
        "id": instance.id,
        "class_id": instance.class_id,
        "class_version": instance.class_version,
        "name": instance.name,
        "variables": instance.variables,
        "metadata": instance.metadata,
        "thumbnail_key": instance.thumbnail_key,
        "is_active": bool(request.activate),
        "created_at": instance.created_at or now,
        "updated_at": instance.updated_at or now,
        "owner_user_id": get_current_user_id(),
    }

    client = await get_supabase_async_client()
    await client.table("profile_instances").insert(record).execute()
    if request.activate:
        await _set_active_instance(client, instance.id)
        _restart_vlabor()

    return ProfileInstanceResponse(
        instance=_record_to_instance(record, profile_class.class_key),
        message="Profile instance created",
    )


@router.put("/instances/{instance_id}", response_model=ProfileInstanceResponse)
async def update_profile_instance(instance_id: str, request: ProfileInstanceUpdateRequest):
    _require_user_id()
    client = await get_supabase_async_client()
    rows = (
        await client.table("profile_instances").select("*").eq("id", instance_id).limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Profile instance not found")
    row = rows[0]

    updated = dict(row)
    if request.name is not None:
        updated["name"] = request.name
    if request.variables is not None:
        updated["variables"] = request.variables
    if request.metadata is not None:
        updated["metadata"] = request.metadata
    if request.thumbnail_key is not None:
        updated["thumbnail_key"] = request.thumbnail_key
    updated["updated_at"] = datetime.now(timezone.utc).isoformat()

    await client.table("profile_instances").update(updated).eq("id", instance_id).execute()

    registry = ProfileRegistry()
    profile_class = await registry.get_class(updated["class_id"])
    instance = ProfileInstance(
        id=instance_id,
        class_id=profile_class.id,
        class_version=profile_class.version,
        name=updated.get("name") or "active",
        variables=updated.get("variables") or {},
        metadata=updated.get("metadata") or {},
        thumbnail_key=updated.get("thumbnail_key"),
        created_at=updated.get("created_at"),
        updated_at=updated.get("updated_at"),
    )

    if request.activate:
        write_current_profile_config(profile_class, instance)
        write_profile_instance_snapshot(profile_class, instance)
        await _set_active_instance(client, instance_id)
        _restart_vlabor()

    return ProfileInstanceResponse(
        instance=_record_to_instance(updated, profile_class.class_key),
        message="Profile instance updated",
    )
