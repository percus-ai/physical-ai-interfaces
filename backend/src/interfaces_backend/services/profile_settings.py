"""Profile settings helpers for operate/teleop."""

from __future__ import annotations

from fastapi import HTTPException

from interfaces_backend.api.profiles import (
    _bootstrap_default_profile,
    _ensure_profile_instances,
    _resolve_profile_settings,
    _row_to_profile_instance,
)
from percus_ai.db import get_supabase_async_client
from percus_ai.profiles.registry import ProfileRegistry


_SO101_JOINT_SUFFIXES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _render_setting(value: object, settings: dict) -> object:
    if not isinstance(value, str) or "${" not in value:
        return value
    rendered = value
    for key, current in settings.items():
        rendered = rendered.replace(f"${{{key}}}", str(current))
    return rendered


def _normalize_arm_namespaces(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        ns = str(item).strip()
        if ns not in {"left_arm", "right_arm"}:
            continue
        if ns in normalized:
            continue
        normalized.append(ns)
    return normalized


def _extract_dashboard_arm_namespaces(profile_class: object) -> list[str]:
    profile = getattr(profile_class, "profile", None)
    if not isinstance(profile, dict):
        return []
    actions = profile.get("actions")
    if not isinstance(actions, list):
        return []
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("type") != "node":
            continue
        if action.get("package") != "vlabor_dashboard":
            continue
        if action.get("executable") != "vlabor_dashboard_node":
            continue
        parameters = action.get("parameters")
        if not isinstance(parameters, dict):
            continue
        arm_namespaces = _normalize_arm_namespaces(parameters.get("arm_namespaces"))
        if arm_namespaces:
            return arm_namespaces
    return []


def resolve_inference_arm_namespaces(profile_class: object, settings: dict) -> list[str]:
    arm_namespaces = _normalize_arm_namespaces(settings.get("inference_arm_namespaces"))
    if arm_namespaces:
        return arm_namespaces

    arm_namespaces = _extract_dashboard_arm_namespaces(profile_class)
    if arm_namespaces:
        return arm_namespaces

    inferred: list[str] = []
    if bool(settings.get("left_arm_enabled", True)):
        inferred.append("left_arm")
    if bool(settings.get("right_arm_enabled", True)):
        inferred.append("right_arm")
    return inferred


def build_inference_joint_names(profile_class: object, settings: dict) -> list[str]:
    joint_names: list[str] = []
    for namespace in resolve_inference_arm_namespaces(profile_class, settings):
        joint_names.extend(f"{namespace}_{suffix}" for suffix in _SO101_JOINT_SUFFIXES)
    return joint_names


def _extract_enabled_camera_names(profile_class: object, settings: dict) -> list[str]:
    profile = getattr(profile_class, "profile", None)
    if not isinstance(profile, dict):
        return []
    actions = profile.get("actions")
    if not isinstance(actions, list):
        return []

    names: list[str] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("type") != "include":
            continue
        package = str(action.get("package") or "").strip()
        if package not in {"fv_camera", "fv_realsense"}:
            continue
        if not _as_bool(_render_setting(action.get("enabled", True), settings)):
            continue
        args = action.get("args")
        if not isinstance(args, dict):
            continue
        name_raw = _render_setting(args.get("node_name"), settings)
        name = str(name_raw or "").strip()
        if not name:
            continue
        names.append(name)
    return names


def build_inference_camera_aliases(profile_class: object, settings: dict) -> dict[str, str]:
    aliases: dict[str, str] = {}
    canonical_names = ["top_camera", "arm_camera_1", "arm_camera_2", "arm_camera_3"]
    for index, name in enumerate(_extract_enabled_camera_names(profile_class, settings)):
        if index >= len(canonical_names):
            break
        aliases[name] = canonical_names[index]
    return aliases


async def get_active_profile_settings() -> tuple[object, object, dict]:
    """Return (instance, profile_class, merged_settings) for the active profile."""
    await _ensure_profile_instances()
    client = await get_supabase_async_client()
    rows = (
        await client.table("profile_instances").select("*").eq("is_active", True).limit(1).execute()
    ).data or []

    if not rows:
        instance = await _bootstrap_default_profile()
        profile_class = await ProfileRegistry().get_class(instance.class_id)
        settings = _resolve_profile_settings(profile_class, instance)
        return instance, profile_class, settings

    instance_row = rows[0]
    class_id = instance_row.get("class_id")
    if not class_id:
        raise HTTPException(status_code=404, detail="Profile class not found")

    profile_class = await ProfileRegistry().get_class(str(class_id))
    instance = _row_to_profile_instance(instance_row)
    settings = _resolve_profile_settings(profile_class, instance)
    return instance, profile_class, settings
