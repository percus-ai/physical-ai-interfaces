"""VLAbor profile helpers.

This module treats VLAbor profile YAML as the source of truth and stores only
selection/session snapshots on backend side.
"""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import HTTPException

from percus_ai.db import get_current_user_id, get_supabase_async_client
from percus_ai.storage.paths import get_project_root

logger = logging.getLogger(__name__)

_ACTIVE_PROFILE_TABLE = "vlabor_profile_selections"
_SESSION_PROFILE_TABLE = "session_profile_bindings"
_ACTIVE_PROFILE_SCOPE_ENV = "VLABOR_PROFILE_SCOPE_ID"

_SO101_DEFAULT_JOINT_SUFFIXES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]


@dataclass(frozen=True)
class VlaborProfileSpec:
    name: str
    description: str
    snapshot: dict[str, Any]
    source_path: str
    updated_at: Optional[str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _active_profile_scope_id() -> str:
    configured = str(os.environ.get(_ACTIVE_PROFILE_SCOPE_ENV) or "").strip()
    if configured:
        return configured
    hostname = socket.gethostname().strip().lower()
    if hostname:
        return f"host:{hostname}"
    return "host:unknown"


def _resolve_profiles_dir() -> Optional[Path]:
    env_override = os.environ.get("VLABOR_PROFILES_DIR")
    candidates = [
        Path(env_override).expanduser() if env_override else None,
        Path.home() / ".vlabor" / "profiles",
        get_project_root() / "ros2_ws" / "src" / "vlabor_ros2" / "vlabor_launch" / "config" / "profiles",
        Path.home() / "ros2_ws" / "src" / "vlabor_ros2" / "vlabor_launch" / "config" / "profiles",
        Path("/home/aspa/ros2_ws/src/vlabor_ros2/vlabor_launch/config/profiles"),
        Path.home() / "vlabor_ros2" / "vlabor_launch" / "config" / "profiles",
        Path("/home/aspa/vlabor_ros2/vlabor_launch/config/profiles"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate
    return None


def _resolve_defaults_path() -> Optional[Path]:
    env_override = os.environ.get("VLABOR_DEFAULTS_FILE")
    candidates = [
        Path(env_override).expanduser() if env_override else None,
        Path.home() / ".vlabor" / "vlabor_profiles.yaml",
        get_project_root() / "ros2_ws" / "src" / "vlabor_ros2" / "vlabor_launch" / "config" / "vlabor_profiles.yaml",
        Path.home() / "ros2_ws" / "src" / "vlabor_ros2" / "vlabor_launch" / "config" / "vlabor_profiles.yaml",
        Path("/home/aspa/ros2_ws/src/vlabor_ros2/vlabor_launch/config/vlabor_profiles.yaml"),
        Path.home() / "vlabor_ros2" / "vlabor_launch" / "config" / "vlabor_profiles.yaml",
        Path("/home/aspa/vlabor_ros2/vlabor_launch/config/vlabor_profiles.yaml"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if candidate.is_file():
            return candidate
    return None


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 - surfaced as API detail
        raise HTTPException(status_code=500, detail=f"Failed to load profile yaml: {path}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail=f"Invalid yaml format: {path}")
    return payload


def _build_profile_snapshot(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    profile = payload.get("profile")
    if not isinstance(profile, dict):
        profile = {}

    name = str(profile.get("name") or path.stem).strip()
    if not name:
        name = path.stem
    description = str(profile.get("description") or "").strip()

    return {
        "name": name,
        "description": description,
        "profile": profile,
        "raw": payload,
        "source_path": str(path),
        "loaded_at": _now_iso(),
    }


def list_vlabor_profiles() -> list[VlaborProfileSpec]:
    profiles_dir = _resolve_profiles_dir()
    if not profiles_dir:
        return []

    profiles: list[VlaborProfileSpec] = []
    for path in sorted(profiles_dir.glob("*.yaml")):
        payload = _load_yaml(path)
        snapshot = _build_profile_snapshot(path, payload)
        profiles.append(
            VlaborProfileSpec(
                name=str(snapshot.get("name") or path.stem),
                description=str(snapshot.get("description") or ""),
                snapshot=snapshot,
                source_path=str(path),
                updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            )
        )
    return profiles


def _default_profile_name(available_names: list[str]) -> Optional[str]:
    if not available_names:
        return None
    if "so101_dual_teleop" in available_names:
        return "so101_dual_teleop"
    return sorted(available_names)[0]


def _profile_by_name(profile_name: str) -> Optional[VlaborProfileSpec]:
    normalized = profile_name.strip()
    if not normalized:
        return None
    for profile in list_vlabor_profiles():
        if profile.name == normalized:
            return profile
    return None


def _load_default_settings() -> dict[str, Any]:
    path = _resolve_defaults_path()
    if not path:
        return {}
    payload = _load_yaml(path)
    defaults = payload.get("defaults")
    if isinstance(defaults, dict):
        return dict(defaults)
    return {}


def build_profile_settings(snapshot: dict[str, Any]) -> dict[str, Any]:
    settings = _load_default_settings()
    profile = snapshot.get("profile")
    if isinstance(profile, dict):
        variables = profile.get("variables")
        if isinstance(variables, dict):
            settings.update(variables)
    return settings


def _render_setting(value: object, settings: dict[str, Any]) -> object:
    if not isinstance(value, str) or "${" not in value:
        return value
    rendered = value
    for key, current in settings.items():
        rendered = rendered.replace(f"${{{key}}}", str(current))
    return rendered


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return bool(value)


def _append_unique(items: list[str], value: object) -> None:
    text = str(value or "").strip()
    if text and text not in items:
        items.append(text)


def _topic_candidates(topic: object) -> list[str]:
    text = str(topic or "").strip()
    if not text:
        return []
    candidates = [text]
    if text.endswith("/compressed"):
        raw = text[: -len("/compressed")]
        if raw:
            candidates.append(raw)
    else:
        candidates.append(f"{text}/compressed")
    return candidates


def extract_status_camera_specs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract camera specs for device status UI.

    This intentionally includes both operator-facing camera nodes and recorder
    camera topics so setup UI can show per-camera connectivity.
    """
    settings = build_profile_settings(snapshot)
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return []

    order: list[str] = []
    merged: dict[str, dict[str, Any]] = {}

    def add_camera(
        name: object,
        *,
        enabled: object = True,
        topics: Optional[list[str]] = None,
        label: object = None,
    ) -> None:
        key = str(name or "").strip()
        if not key:
            return
        entry = merged.get(key)
        if entry is None:
            resolved_label = str(label or "").strip() or key
            entry = {
                "name": key,
                "label": resolved_label,
                "enabled": _as_bool(enabled),
                "topics": [],
            }
            merged[key] = entry
            order.append(key)
        else:
            entry["enabled"] = bool(entry.get("enabled", True) or _as_bool(enabled))
            label_text = str(label or "").strip()
            if label_text and entry.get("label") == key:
                entry["label"] = label_text

        for topic in topics or []:
            _append_unique(entry["topics"], topic)

    lerobot = profile.get("lerobot")
    if isinstance(lerobot, dict):
        cameras = lerobot.get("cameras")
        if isinstance(cameras, list):
            for camera in cameras:
                if not isinstance(camera, dict):
                    continue
                source_name = _render_setting(
                    camera.get("source") or camera.get("name") or "", settings
                )
                topic = _render_setting(camera.get("topic") or "", settings)
                add_camera(
                    source_name,
                    enabled=True,
                    topics=_topic_candidates(topic),
                    label=_render_setting(camera.get("name") or "", settings),
                )

    actions = profile.get("actions")
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            if action.get("type") != "include":
                continue

            package = str(action.get("package") or "").strip()
            launch_name = str(action.get("launch") or "").strip().lower()
            if package not in {"fv_camera", "fv_realsense", "vlabor_launch"}:
                continue
            if package == "vlabor_launch" and "camera" not in launch_name:
                continue

            args = action.get("args")
            if not isinstance(args, dict):
                continue

            node_name = _render_setting(args.get("node_name"), settings)
            enabled = _render_setting(action.get("enabled", True), settings)
            if package == "fv_realsense":
                base_topic = f"/{node_name}/color/image_raw"
            else:
                base_topic = f"/{node_name}/image_raw"
            add_camera(node_name, enabled=enabled, topics=_topic_candidates(base_topic))

    results: list[dict[str, Any]] = []
    for key in order:
        entry = dict(merged[key])
        topics = list(entry.get("topics") or [])
        if not topics:
            topics = _topic_candidates(f"/{key}/image_raw")
        entry["topics"] = topics
        results.append(entry)
    return results


def extract_status_arm_specs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract arm specs for device status UI."""
    settings = build_profile_settings(snapshot)
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return []

    order: list[str] = []
    merged: dict[str, dict[str, Any]] = {}

    def infer_role(namespace: str) -> Optional[str]:
        lowered = namespace.lower()
        if "leader" in lowered:
            return "leader"
        if "follower" in lowered:
            return "follower"
        return None

    def add_arm(
        namespace: object,
        *,
        enabled: object = True,
        label: object = None,
        role: object = None,
        topics: Optional[list[str]] = None,
    ) -> None:
        key = str(namespace or "").strip()
        if not key:
            return

        entry = merged.get(key)
        role_text = str(role or "").strip() or infer_role(key)
        label_text = str(label or "").strip() or key
        if entry is None:
            entry = {
                "name": key,
                "label": label_text,
                "role": role_text,
                "enabled": _as_bool(enabled),
                "topics": [],
            }
            merged[key] = entry
            order.append(key)
        else:
            entry["enabled"] = bool(entry.get("enabled", True) or _as_bool(enabled))
            if label_text and entry.get("label") == key:
                entry["label"] = label_text
            if role_text and not entry.get("role"):
                entry["role"] = role_text

        for topic in topics or []:
            _append_unique(entry["topics"], topic)

    dashboard = profile.get("dashboard")
    if isinstance(dashboard, dict):
        arms = dashboard.get("arms")
        if isinstance(arms, list):
            for arm in arms:
                if not isinstance(arm, dict):
                    continue
                add_arm(
                    _render_setting(arm.get("namespace"), settings),
                    label=_render_setting(arm.get("label"), settings),
                    role=_render_setting(arm.get("role"), settings),
                )

    teleop = profile.get("teleop")
    if isinstance(teleop, dict):
        follower_arms = teleop.get("follower_arms")
        if isinstance(follower_arms, list):
            for arm in follower_arms:
                if not isinstance(arm, dict):
                    continue
                add_arm(
                    _render_setting(arm.get("namespace"), settings),
                    label=_render_setting(arm.get("label"), settings),
                    role="follower",
                )

    lerobot = profile.get("lerobot")
    if isinstance(lerobot, dict):
        for key, value in lerobot.items():
            if key == "cameras" or not isinstance(value, dict):
                continue
            add_arm(_render_setting(value.get("namespace"), settings), role="follower")

    actions = profile.get("actions")
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            if action.get("type") != "node":
                continue
            package = str(action.get("package") or "").strip()
            if package not in {"unity_robot_control", "piper"}:
                continue
            add_arm(_render_setting(action.get("namespace"), settings))

    results: list[dict[str, Any]] = []
    for key in order:
        entry = dict(merged[key])
        topics = list(entry.get("topics") or [])
        if not topics:
            _append_unique(topics, f"/{key}/joint_states")
            _append_unique(topics, f"/{key}/joint_states_single")
        entry["topics"] = topics
        results.append(entry)
    return results


def extract_camera_specs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    settings = build_profile_settings(snapshot)
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return []

    lerobot = profile.get("lerobot")
    if isinstance(lerobot, dict):
        cameras = lerobot.get("cameras")
        if isinstance(cameras, list):
            results: list[dict[str, Any]] = []
            for camera in cameras:
                if not isinstance(camera, dict):
                    continue
                name = str(camera.get("name") or camera.get("source") or "").strip()
                topic = str(camera.get("topic") or "").strip()
                if not name or not topic:
                    continue
                results.append({"name": name, "topic": topic, "enabled": True, "package": "lerobot"})
            if results:
                return results

    actions = profile.get("actions")
    if not isinstance(actions, list):
        return []

    results: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("type") != "include":
            continue

        package = str(action.get("package") or "").strip()
        if package not in {"fv_camera", "fv_realsense", "vlabor_launch"}:
            continue

        args = action.get("args")
        if not isinstance(args, dict):
            continue
        name_raw = _render_setting(args.get("node_name"), settings)
        node_name = str(name_raw or "").strip()
        if not node_name:
            continue

        enabled_raw = _render_setting(action.get("enabled", True), settings)
        enabled = _as_bool(enabled_raw)

        if package == "fv_realsense":
            topic = f"/{node_name}/color/image_raw/compressed"
        else:
            topic = f"/{node_name}/image_raw/compressed"

        results.append({"name": node_name, "topic": topic, "enabled": enabled, "package": package})
    return results


def extract_arm_namespaces(snapshot: dict[str, Any]) -> list[str]:
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return []

    namespaces: list[str] = []

    lerobot = profile.get("lerobot")
    if isinstance(lerobot, dict):
        for key, value in lerobot.items():
            if key == "cameras" or not isinstance(value, dict):
                continue
            namespace = str(value.get("namespace") or "").strip()
            if namespace and namespace not in namespaces:
                namespaces.append(namespace)
        if namespaces:
            return namespaces

    teleop = profile.get("teleop")
    if isinstance(teleop, dict):
        follower_arms = teleop.get("follower_arms")
        if isinstance(follower_arms, list):
            for arm in follower_arms:
                if not isinstance(arm, dict):
                    continue
                namespace = str(arm.get("namespace") or "").strip()
                if namespace and namespace not in namespaces:
                    namespaces.append(namespace)
            if namespaces:
                return namespaces

    dashboard = profile.get("dashboard")
    if isinstance(dashboard, dict):
        arms = dashboard.get("arms")
        if isinstance(arms, list):
            for arm in arms:
                if not isinstance(arm, dict):
                    continue
                namespace = str(arm.get("namespace") or "").strip()
                if namespace and namespace not in namespaces:
                    namespaces.append(namespace)
    return namespaces


def build_inference_joint_names(snapshot: dict[str, Any]) -> list[str]:
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return []

    lerobot = profile.get("lerobot")
    if isinstance(lerobot, dict):
        names: list[str] = []
        for key, value in lerobot.items():
            if key == "cameras" or not isinstance(value, dict):
                continue
            namespace = str(value.get("namespace") or "").strip()
            joints = value.get("joints")
            if namespace and isinstance(joints, list):
                for joint in joints:
                    joint_name = str(joint).strip()
                    if not joint_name:
                        continue
                    names.append(f"{namespace}_{joint_name}")
        if names:
            return names

    names: list[str] = []
    for namespace in extract_arm_namespaces(snapshot):
        names.extend(f"{namespace}_{suffix}" for suffix in _SO101_DEFAULT_JOINT_SUFFIXES)
    return names


def build_inference_camera_aliases(snapshot: dict[str, Any]) -> dict[str, str]:
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return {}

    canonical_names = ["top_camera", "arm_camera_1", "arm_camera_2", "arm_camera_3"]
    source_names: list[str] = []

    lerobot = profile.get("lerobot")
    if isinstance(lerobot, dict):
        cameras = lerobot.get("cameras")
        if isinstance(cameras, list):
            for camera in cameras:
                if not isinstance(camera, dict):
                    continue
                source_name = str(camera.get("source") or camera.get("name") or "").strip()
                if source_name and source_name not in source_names:
                    source_names.append(source_name)
    if not source_names:
        for spec in extract_camera_specs(snapshot):
            source_name = str(spec.get("name") or "").strip()
            if source_name and source_name not in source_names:
                source_names.append(source_name)

    aliases: dict[str, str] = {}
    for index, source_name in enumerate(source_names):
        if index >= len(canonical_names):
            break
        aliases[source_name] = canonical_names[index]
    return aliases


async def get_active_profile_spec() -> VlaborProfileSpec:
    profiles = list_vlabor_profiles()
    if not profiles:
        raise HTTPException(status_code=404, detail="VLAbor profiles not found")

    by_name = {profile.name: profile for profile in profiles}
    scope_id = _active_profile_scope_id()
    selected_name: Optional[str] = None
    client = await get_supabase_async_client()
    try:
        rows = (
            await client.table(_ACTIVE_PROFILE_TABLE)
            .select("profile_name")
            .eq("scope_id", scope_id)
            .limit(1)
            .execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001 - fallback to default profile if table is unavailable
        logger.warning("Failed to load active VLAbor profile from DB: %s", exc)
        rows = []
    if rows:
        selected_name = str(rows[0].get("profile_name") or "").strip() or None

    if selected_name and selected_name in by_name:
        return by_name[selected_name]

    fallback_name = _default_profile_name(list(by_name.keys()))
    if not fallback_name:
        raise HTTPException(status_code=404, detail="VLAbor profiles not found")
    return by_name[fallback_name]


async def set_active_profile_spec(profile_name: str) -> VlaborProfileSpec:
    profile = _profile_by_name(profile_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"VLAbor profile not found: {profile_name}")

    scope_id = _active_profile_scope_id()
    client = await get_supabase_async_client()
    now = _now_iso()
    existing = (
        await client.table(_ACTIVE_PROFILE_TABLE)
        .select("scope_id")
        .eq("scope_id", scope_id)
        .limit(1)
        .execute()
    ).data or []
    payload = {
        "profile_name": profile.name,
        "profile_snapshot": profile.snapshot,
        "updated_at": now,
    }
    if existing:
        await client.table(_ACTIVE_PROFILE_TABLE).update(payload).eq("scope_id", scope_id).execute()
    else:
        await client.table(_ACTIVE_PROFILE_TABLE).insert(
            {
                "scope_id": scope_id,
                "profile_name": profile.name,
                "profile_snapshot": profile.snapshot,
                "created_at": now,
                "updated_at": now,
            }
        ).execute()
    return profile


async def save_session_profile_binding(
    *,
    session_kind: str,
    session_id: str,
    profile: VlaborProfileSpec,
) -> None:
    user_id = get_current_user_id()
    if not session_id:
        return

    client = await get_supabase_async_client()
    now = _now_iso()
    existing = (
        await client.table(_SESSION_PROFILE_TABLE)
        .select("session_id")
        .eq("owner_user_id", user_id)
        .eq("session_kind", session_kind)
        .eq("session_id", session_id)
        .limit(1)
        .execute()
    ).data or []

    payload = {
        "profile_name": profile.name,
        "profile_snapshot": profile.snapshot,
        "profile_source_path": profile.source_path,
        "updated_at": now,
    }
    if existing:
        await (
            client.table(_SESSION_PROFILE_TABLE)
            .update(payload)
            .eq("owner_user_id", user_id)
            .eq("session_kind", session_kind)
            .eq("session_id", session_id)
            .execute()
        )
    else:
        await client.table(_SESSION_PROFILE_TABLE).insert(
            {
                "owner_user_id": user_id,
                "session_kind": session_kind,
                "session_id": session_id,
                "profile_name": profile.name,
                "profile_snapshot": profile.snapshot,
                "profile_source_path": profile.source_path,
                "created_at": now,
                "updated_at": now,
            }
        ).execute()


def resolve_profile_spec(profile_name: Optional[str]) -> VlaborProfileSpec:
    if profile_name:
        profile = _profile_by_name(profile_name)
        if profile:
            return profile
        raise HTTPException(status_code=404, detail=f"VLAbor profile not found: {profile_name}")

    profiles = list_vlabor_profiles()
    if not profiles:
        raise HTTPException(status_code=404, detail="VLAbor profiles not found")
    by_name = {profile.name: profile for profile in profiles}
    fallback_name = _default_profile_name(list(by_name.keys()))
    if not fallback_name:
        raise HTTPException(status_code=404, detail="VLAbor profiles not found")
    return by_name[fallback_name]
