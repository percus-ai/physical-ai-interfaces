"""VLAbor profile helpers.

This module treats VLAbor profile YAML as the source of truth and stores only
selection/session snapshots on backend side.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import HTTPException

from percus_ai.db import get_current_user_id, get_supabase_async_client
from percus_ai.storage.paths import get_project_root

logger = logging.getLogger(__name__)

_SESSION_PROFILE_TABLE = "session_profile_bindings"
_ACTIVE_PROFILE_FILE_ENV = "VLABOR_ACTIVE_PROFILE_FILE"

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


def _active_profile_local_path() -> Path:
    configured = str(os.environ.get(_ACTIVE_PROFILE_FILE_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".vlabor" / "active_profile.json"


def _load_active_profile_name_local() -> str | None:
    path = _active_profile_local_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - fall back to default profile
        logger.warning("Failed to read local active profile file (%s): %s", path, exc)
        return None
    if not isinstance(payload, dict):
        logger.warning("Invalid local active profile payload: %s", path)
        return None
    return str(payload.get("profile_name") or "").strip() or None


def _save_active_profile_name_local(profile_name: str) -> None:
    path = _active_profile_local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "profile_name": profile_name,
        "updated_at": _now_iso(),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


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
    if not isinstance(lerobot, dict):
        return []
    cameras = lerobot.get("cameras")
    if not isinstance(cameras, list):
        return []

    results: list[dict[str, Any]] = []
    for camera in cameras:
        if not isinstance(camera, dict):
            continue
        name = str(
            _render_setting(camera.get("name") or camera.get("source") or "", settings)
        ).strip()
        topic = str(_render_setting(camera.get("topic") or "", settings)).strip()
        source = str(_render_setting(camera.get("source") or name or "", settings)).strip() or name
        enabled = _as_bool(_render_setting(camera.get("enabled", True), settings))
        if not name or not topic:
            continue
        results.append(
            {
                "name": name,
                "topic": topic,
                "source": source,
                "enabled": enabled,
                "package": "lerobot",
            }
        )
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


def _topic_suffix_for_namespace(topic: object, namespace: str, settings: dict[str, Any]) -> str | None:
    resolved_topic = str(_render_setting(topic, settings) or "").strip()
    if not resolved_topic:
        return None
    prefix = f"/{namespace}/"
    if not resolved_topic.startswith(prefix):
        return None
    suffix = resolved_topic[len(prefix) :].strip("/")
    return suffix or None


def _pick_common_topic_suffix(
    suffixes_by_namespace: dict[str, set[str]],
    arm_namespaces: list[str],
) -> str | None:
    if not arm_namespaces:
        return None

    resolved_per_namespace: list[str] = []
    for namespace in arm_namespaces:
        candidates = suffixes_by_namespace.get(namespace) or set()
        if len(candidates) != 1:
            return None
        resolved_per_namespace.append(next(iter(candidates)))

    unique = set(resolved_per_namespace)
    if len(unique) != 1:
        return None
    return resolved_per_namespace[0]


def extract_recorder_topic_suffixes(
    snapshot: dict[str, Any],
    *,
    arm_namespaces: Optional[list[str]] = None,
) -> dict[str, str]:
    """Extract recorder topic suffixes from profile snapshot.

    Recorder currently accepts one state/action suffix shared across all arms.
    This helper returns suffixes only when all target arms can resolve to a
    single common value.
    """
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return {}

    target_namespaces: list[str] = []
    for namespace in arm_namespaces or extract_arm_namespaces(snapshot):
        text = str(namespace or "").strip()
        if text and text not in target_namespaces:
            target_namespaces.append(text)
    if not target_namespaces:
        return {}

    settings = build_profile_settings(snapshot)
    state_suffixes: dict[str, set[str]] = {namespace: set() for namespace in target_namespaces}
    action_suffixes: dict[str, set[str]] = {namespace: set() for namespace in target_namespaces}

    lerobot = profile.get("lerobot")
    if isinstance(lerobot, dict):
        for key, value in lerobot.items():
            if key == "cameras" or not isinstance(value, dict):
                continue
            namespace = str(_render_setting(value.get("namespace"), settings) or "").strip()
            if namespace not in state_suffixes:
                continue

            state_suffix = _topic_suffix_for_namespace(value.get("topic"), namespace, settings)
            if state_suffix:
                state_suffixes[namespace].add(state_suffix)

            action_suffix = _topic_suffix_for_namespace(value.get("action_topic"), namespace, settings)
            if action_suffix:
                action_suffixes[namespace].add(action_suffix)

    teleop = profile.get("teleop")
    if isinstance(teleop, dict):
        mappings = teleop.get("topic_mappings")
        if isinstance(mappings, list):
            for mapping in mappings:
                if not isinstance(mapping, dict):
                    continue
                dst = mapping.get("dst")
                for namespace in target_namespaces:
                    action_suffix = _topic_suffix_for_namespace(dst, namespace, settings)
                    if action_suffix:
                        action_suffixes[namespace].add(action_suffix)

    result: dict[str, str] = {}
    state_topic_suffix = _pick_common_topic_suffix(state_suffixes, target_namespaces)
    if state_topic_suffix:
        result["state_topic_suffix"] = state_topic_suffix

    action_topic_suffix = _pick_common_topic_suffix(action_suffixes, target_namespaces)
    if action_topic_suffix:
        result["action_topic_suffix"] = action_topic_suffix

    return result


def build_inference_bridge_config(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build inference bridge stream config from VLAbor profile snapshot.

    This uses the same profile-derived source of truth as recording:
    arm namespaces, recorder topic suffixes, and lerobot camera definitions.
    """
    arm_namespaces: list[str] = []
    for namespace in extract_arm_namespaces(snapshot):
        text = str(namespace or "").strip()
        if text and text not in arm_namespaces:
            arm_namespaces.append(text)

    topic_suffixes = extract_recorder_topic_suffixes(
        snapshot,
        arm_namespaces=arm_namespaces,
    )

    camera_streams: list[dict[str, str]] = []
    seen_camera_names: set[str] = set()
    for spec in extract_camera_specs(snapshot):
        if not _as_bool(spec.get("enabled", True)):
            continue
        topic = str(spec.get("topic") or "").strip()
        # Inference worker alias mapping is based on "source" camera names.
        # Prefer source and fallback to display name when source is not present.
        name = str(spec.get("source") or spec.get("name") or "").strip()
        if not name or not topic or name in seen_camera_names:
            continue
        seen_camera_names.add(name)
        camera_streams.append({"name": name, "topic": topic})

    return {
        "arm_namespaces": arm_namespaces,
        "state_topic_suffix": str(topic_suffixes.get("state_topic_suffix") or "").strip(),
        "action_topic_suffix": str(topic_suffixes.get("action_topic_suffix") or "").strip(),
        "camera_streams": camera_streams,
    }


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
    aliases: dict[str, str] = {}
    for spec in extract_camera_specs(snapshot):
        if not _as_bool(spec.get("enabled", True)):
            continue
        source_name = str(spec.get("source") or "").strip()
        camera_name = str(spec.get("name") or "").strip()
        if not source_name or not camera_name:
            continue
        aliases[source_name] = camera_name
    return aliases


async def get_active_profile_spec() -> VlaborProfileSpec:
    profiles = list_vlabor_profiles()
    if not profiles:
        raise HTTPException(status_code=404, detail="VLAbor profiles not found")

    by_name = {profile.name: profile for profile in profiles}
    selected_name = _load_active_profile_name_local()

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

    try:
        _save_active_profile_name_local(profile.name)
    except Exception as exc:  # noqa: BLE001 - surfaced as API detail
        raise HTTPException(status_code=500, detail=f"Failed to save active profile locally: {exc}") from exc
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
