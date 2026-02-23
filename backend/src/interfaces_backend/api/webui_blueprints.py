"""WebUI blueprint management API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from interfaces_backend.models.webui_blueprints import (
    ResolveReason,
    SessionKind,
    WebuiBlueprintBindResponse,
    WebuiBlueprintCreateRequest,
    WebuiBlueprintDeleteResponse,
    WebuiBlueprintDetail,
    WebuiBlueprintListResponse,
    WebuiBlueprintResolveResponse,
    WebuiBlueprintSessionBindRequest,
    WebuiBlueprintSessionResolveRequest,
    WebuiBlueprintSummary,
    WebuiBlueprintUpdateRequest,
)
from percus_ai.db import get_current_user_id, get_supabase_async_client

router = APIRouter(prefix="/api/webui/blueprints", tags=["webui"])

_BLUEPRINTS_TABLE = "webui_blueprints"
_BINDINGS_TABLE = "webui_blueprint_session_bindings"


def _require_user_id() -> str:
    try:
        return get_current_user_id()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Login required") from exc


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_node_id() -> str:
    return uuid4().hex[:8]


def _default_blueprint() -> dict[str, Any]:
    camera = {
        "id": _new_node_id(),
        "type": "view",
        "viewType": "camera",
        "config": {"topic": ""},
    }
    joint = {
        "id": _new_node_id(),
        "type": "view",
        "viewType": "joint_state",
        "config": {"topic": ""},
    }
    left = {
        "id": _new_node_id(),
        "type": "split",
        "direction": "column",
        "sizes": [0.6, 0.4],
        "children": [camera, joint],
    }

    status_view = {
        "id": _new_node_id(),
        "type": "view",
        "viewType": "status",
        "config": {"topic": "/lerobot_recorder/status"},
    }
    controls_view = {
        "id": _new_node_id(),
        "type": "view",
        "viewType": "controls",
        "config": {},
    }
    progress_view = {
        "id": _new_node_id(),
        "type": "view",
        "viewType": "progress",
        "config": {},
    }
    settings_view = {
        "id": _new_node_id(),
        "type": "view",
        "viewType": "settings",
        "config": {},
    }
    status_tab_id = _new_node_id()
    controls_tab_id = _new_node_id()
    progress_tab_id = _new_node_id()
    settings_tab_id = _new_node_id()
    tabs = {
        "id": _new_node_id(),
        "type": "tabs",
        "activeId": status_tab_id,
        "tabs": [
            {"id": status_tab_id, "title": "Status", "child": status_view},
            {"id": controls_tab_id, "title": "Controls", "child": controls_view},
            {"id": progress_tab_id, "title": "Progress", "child": progress_view},
            {"id": settings_tab_id, "title": "Settings", "child": settings_view},
        ],
    }
    upper = {
        "id": _new_node_id(),
        "type": "split",
        "direction": "row",
        "sizes": [0.7, 0.3],
        "children": [left, tabs],
    }
    timeline_view = {
        "id": _new_node_id(),
        "type": "view",
        "viewType": "timeline",
        "config": {},
    }
    return {
        "id": _new_node_id(),
        "type": "split",
        "direction": "column",
        "sizes": [0.78, 0.22],
        "children": [upper, timeline_view],
    }


def _as_blueprint_summary(row: dict[str, Any]) -> WebuiBlueprintSummary:
    blueprint_id = row.get("id")
    name = row.get("name")
    if not blueprint_id:
        raise HTTPException(status_code=500, detail="Invalid blueprint row: missing id")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(status_code=500, detail="Invalid blueprint row: missing name")
    return WebuiBlueprintSummary(
        id=str(blueprint_id),
        name=name,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _as_blueprint_detail(row: dict[str, Any]) -> WebuiBlueprintDetail:
    summary = _as_blueprint_summary(row)
    blueprint = row.get("blueprint")
    if not isinstance(blueprint, dict):
        raise HTTPException(status_code=500, detail=f"Blueprint payload is invalid: {summary.id}")
    return WebuiBlueprintDetail(
        id=summary.id,
        name=summary.name,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        blueprint=blueprint,
    )


async def _list_blueprint_rows(client: Any, user_id: str) -> list[dict[str, Any]]:
    response = (
        await client.table(_BLUEPRINTS_TABLE)
        .select("*")
        .eq("owner_user_id", user_id)
        .order("updated_at", desc=True)
        .execute()
    )
    return response.data or []


async def _list_binding_rows(client: Any, user_id: str) -> list[dict[str, Any]]:
    response = (
        await client.table(_BINDINGS_TABLE)
        .select("*")
        .eq("owner_user_id", user_id)
        .order("last_used_at", desc=True)
        .execute()
    )
    return response.data or []


async def _get_blueprint_row(client: Any, user_id: str, blueprint_id: str) -> dict[str, Any]:
    rows = (
        await client.table(_BLUEPRINTS_TABLE)
        .select("*")
        .eq("owner_user_id", user_id)
        .eq("id", blueprint_id)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Blueprint not found: {blueprint_id}")
    return rows[0]


async def _get_binding_row(
    client: Any, user_id: str, session_kind: SessionKind, session_id: str
) -> dict[str, Any] | None:
    rows = (
        await client.table(_BINDINGS_TABLE)
        .select("*")
        .eq("owner_user_id", user_id)
        .eq("session_kind", session_kind)
        .eq("session_id", session_id)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        return None
    return rows[0]


def _select_latest_blueprint_id(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            str(row.get("updated_at") or ""),
            str(row.get("id") or ""),
        ),
        reverse=True,
    )
    latest_id = sorted_rows[0].get("id")
    return str(latest_id) if latest_id else None


def _derive_last_used_blueprint_id(
    binding_rows: list[dict[str, Any]],
    blueprint_by_id: dict[str, dict[str, Any]],
) -> str | None:
    if not binding_rows:
        return None

    first_last_used_at: str | None = None
    candidates: list[str] = []
    for row in binding_rows:
        blueprint_id = row.get("blueprint_id")
        if not blueprint_id:
            continue
        blueprint_id = str(blueprint_id)
        if blueprint_id not in blueprint_by_id:
            continue
        last_used_at = str(row.get("last_used_at") or "")
        if first_last_used_at is None:
            first_last_used_at = last_used_at
            candidates.append(blueprint_id)
            continue
        if last_used_at != first_last_used_at:
            break
        candidates.append(blueprint_id)

    if not candidates:
        return None

    unique_candidates = list(dict.fromkeys(candidates))
    ranked = sorted(
        unique_candidates,
        key=lambda blueprint_id: (
            str(blueprint_by_id[blueprint_id].get("updated_at") or ""),
            blueprint_id,
        ),
        reverse=True,
    )
    return ranked[0]


async def _insert_blueprint_row(
    client: Any,
    user_id: str,
    *,
    name: str,
    blueprint: dict[str, Any],
) -> dict[str, Any]:
    now = _now_iso()
    response = await client.table(_BLUEPRINTS_TABLE).insert(
        {
            "name": name,
            "blueprint": blueprint,
            "owner_user_id": user_id,
            "created_at": now,
            "updated_at": now,
        }
    ).execute()
    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=500, detail="Failed to create blueprint")
    return rows[0]


async def _upsert_binding(
    client: Any,
    user_id: str,
    *,
    session_kind: SessionKind,
    session_id: str,
    blueprint_id: str,
) -> None:
    now = _now_iso()
    existing = await _get_binding_row(client, user_id, session_kind, session_id)
    if existing:
        await (
            client.table(_BINDINGS_TABLE)
            .update(
                {
                    "blueprint_id": blueprint_id,
                    "last_used_at": now,
                    "updated_at": now,
                }
            )
            .eq("owner_user_id", user_id)
            .eq("session_kind", session_kind)
            .eq("session_id", session_id)
            .execute()
        )
        return

    await client.table(_BINDINGS_TABLE).insert(
        {
            "owner_user_id": user_id,
            "session_kind": session_kind,
            "session_id": session_id,
            "blueprint_id": blueprint_id,
            "last_used_at": now,
            "created_at": now,
            "updated_at": now,
        }
    ).execute()


async def _resolve_blueprint(
    client: Any,
    user_id: str,
    *,
    session_kind: SessionKind,
    session_id: str,
) -> tuple[dict[str, Any], ResolveReason]:
    blueprints = await _list_blueprint_rows(client, user_id)
    blueprint_by_id = {str(row["id"]): row for row in blueprints if row.get("id")}

    binding = await _get_binding_row(client, user_id, session_kind, session_id)
    if binding:
        bound_id = str(binding.get("blueprint_id") or "")
        if bound_id in blueprint_by_id:
            await _upsert_binding(
                client,
                user_id,
                session_kind=session_kind,
                session_id=session_id,
                blueprint_id=bound_id,
            )
            return blueprint_by_id[bound_id], "binding"

    binding_rows = await _list_binding_rows(client, user_id)
    last_used_id = _derive_last_used_blueprint_id(binding_rows, blueprint_by_id)
    if last_used_id and last_used_id in blueprint_by_id:
        await _upsert_binding(
            client,
            user_id,
            session_kind=session_kind,
            session_id=session_id,
            blueprint_id=last_used_id,
        )
        return blueprint_by_id[last_used_id], "last_used"

    latest_id = _select_latest_blueprint_id(blueprints)
    if latest_id and latest_id in blueprint_by_id:
        await _upsert_binding(
            client,
            user_id,
            session_kind=session_kind,
            session_id=session_id,
            blueprint_id=latest_id,
        )
        return blueprint_by_id[latest_id], "latest"

    created = await _insert_blueprint_row(
        client,
        user_id,
        name="Default Blueprint",
        blueprint=_default_blueprint(),
    )
    created_id = str(created["id"])
    await _upsert_binding(
        client,
        user_id,
        session_kind=session_kind,
        session_id=session_id,
        blueprint_id=created_id,
    )
    return created, "default_created"


@router.get("", response_model=WebuiBlueprintListResponse)
async def list_blueprints():
    user_id = _require_user_id()
    client = await get_supabase_async_client()
    blueprints = await _list_blueprint_rows(client, user_id)
    binding_rows = await _list_binding_rows(client, user_id)
    blueprint_by_id = {str(row["id"]): row for row in blueprints if row.get("id")}

    last_used_blueprint_id = _derive_last_used_blueprint_id(binding_rows, blueprint_by_id)

    return WebuiBlueprintListResponse(
        blueprints=[_as_blueprint_summary(row) for row in blueprints],
        last_used_blueprint_id=last_used_blueprint_id,
    )


@router.post("", response_model=WebuiBlueprintDetail)
async def create_blueprint(request: WebuiBlueprintCreateRequest):
    user_id = _require_user_id()
    client = await get_supabase_async_client()
    row = await _insert_blueprint_row(
        client,
        user_id,
        name=request.name,
        blueprint=request.blueprint,
    )
    return _as_blueprint_detail(row)


@router.post("/session/resolve", response_model=WebuiBlueprintResolveResponse)
async def resolve_session_blueprint(request: WebuiBlueprintSessionResolveRequest):
    user_id = _require_user_id()
    client = await get_supabase_async_client()
    row, resolved_by = await _resolve_blueprint(
        client,
        user_id,
        session_kind=request.session_kind,
        session_id=request.session_id,
    )
    return WebuiBlueprintResolveResponse(
        blueprint=_as_blueprint_detail(row),
        resolved_by=resolved_by,
    )


@router.put("/session/binding", response_model=WebuiBlueprintBindResponse)
async def bind_session_blueprint(request: WebuiBlueprintSessionBindRequest):
    user_id = _require_user_id()
    client = await get_supabase_async_client()
    row = await _get_blueprint_row(client, user_id, request.blueprint_id)
    await _upsert_binding(
        client,
        user_id,
        session_kind=request.session_kind,
        session_id=request.session_id,
        blueprint_id=str(row["id"]),
    )
    return WebuiBlueprintBindResponse(blueprint=_as_blueprint_detail(row))


@router.get("/{blueprint_id}", response_model=WebuiBlueprintDetail)
async def get_blueprint(blueprint_id: str):
    user_id = _require_user_id()
    client = await get_supabase_async_client()
    row = await _get_blueprint_row(client, user_id, blueprint_id)
    return _as_blueprint_detail(row)


@router.put("/{blueprint_id}", response_model=WebuiBlueprintDetail)
async def update_blueprint(blueprint_id: str, request: WebuiBlueprintUpdateRequest):
    user_id = _require_user_id()
    client = await get_supabase_async_client()
    await _get_blueprint_row(client, user_id, blueprint_id)

    if request.name is None and request.blueprint is None:
        raise HTTPException(status_code=400, detail="Nothing to update")

    update_payload: dict[str, Any] = {"updated_at": _now_iso()}
    if request.name is not None:
        update_payload["name"] = request.name
    if request.blueprint is not None:
        update_payload["blueprint"] = request.blueprint

    await (
        client.table(_BLUEPRINTS_TABLE)
        .update(update_payload)
        .eq("owner_user_id", user_id)
        .eq("id", blueprint_id)
        .execute()
    )
    updated = await _get_blueprint_row(client, user_id, blueprint_id)
    return _as_blueprint_detail(updated)


@router.delete("/{blueprint_id}", response_model=WebuiBlueprintDeleteResponse)
async def delete_blueprint(blueprint_id: str):
    user_id = _require_user_id()
    client = await get_supabase_async_client()
    await _get_blueprint_row(client, user_id, blueprint_id)

    target_bindings = (
        await client.table(_BINDINGS_TABLE)
        .select("*")
        .eq("owner_user_id", user_id)
        .eq("blueprint_id", blueprint_id)
        .execute()
    ).data or []

    rebound_count = len(target_bindings)
    replacement_blueprint_id: str | None = None

    if rebound_count > 0:
        all_blueprints = await _list_blueprint_rows(client, user_id)
        remaining_by_id = {
            str(row["id"]): row
            for row in all_blueprints
            if row.get("id") and str(row.get("id") or "") != blueprint_id
        }

        all_bindings = await _list_binding_rows(client, user_id)
        candidate_bindings = [
            row
            for row in all_bindings
            if str(row.get("blueprint_id") or "") != blueprint_id
        ]
        replacement_blueprint_id = _derive_last_used_blueprint_id(
            candidate_bindings, remaining_by_id
        )
        if not replacement_blueprint_id:
            created = await _insert_blueprint_row(
                client,
                user_id,
                name="Default Blueprint",
                blueprint=_default_blueprint(),
            )
            replacement_blueprint_id = str(created["id"])

        await (
            client.table(_BINDINGS_TABLE)
            .update(
                {
                    "blueprint_id": replacement_blueprint_id,
                    "last_used_at": _now_iso(),
                    "updated_at": _now_iso(),
                }
            )
            .eq("owner_user_id", user_id)
            .eq("blueprint_id", blueprint_id)
            .execute()
        )

    await (
        client.table(_BLUEPRINTS_TABLE)
        .delete()
        .eq("owner_user_id", user_id)
        .eq("id", blueprint_id)
        .execute()
    )

    return WebuiBlueprintDeleteResponse(
        success=True,
        replacement_blueprint_id=replacement_blueprint_id,
        rebound_session_count=rebound_count,
    )
