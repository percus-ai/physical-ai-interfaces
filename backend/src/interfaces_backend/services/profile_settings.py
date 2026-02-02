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
