from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Load the router module directly to avoid importing all API packages for this test.
MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "interfaces_backend"
    / "api"
    / "webui_blueprints.py"
)
MODULE_SPEC = spec_from_file_location("webui_blueprints_module", MODULE_PATH)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("Failed to load webui_blueprints module spec")
webui_api = module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(webui_api)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(webui_api.router)
    with TestClient(app) as test_client:
        yield test_client


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeTableQuery:
    def __init__(self, client: "_FakeSupabaseClient", table_name: str):
        self._client = client
        self._table_name = table_name
        self._action = "select"
        self._payload = None
        self._filters: list[tuple[str, object]] = []
        self._orders: list[tuple[str, bool]] = []
        self._limit: int | None = None

    def select(self, _columns: str = "*"):
        self._action = "select"
        return self

    def insert(self, payload):
        self._action = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._action = "update"
        self._payload = payload
        return self

    def delete(self):
        self._action = "delete"
        return self

    def eq(self, field: str, value: object):
        self._filters.append((field, value))
        return self

    def order(self, field: str, desc: bool = False):
        self._orders.append((field, desc))
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def _rows(self) -> list[dict]:
        return self._client.tables.setdefault(self._table_name, [])

    def _matches(self, row: dict) -> bool:
        for field, value in self._filters:
            if row.get(field) != value:
                return False
        return True

    def _filtered_rows(self) -> list[dict]:
        rows = [row for row in self._rows() if self._matches(row)]
        for field, desc in reversed(self._orders):
            rows.sort(key=lambda row: str(row.get(field) or ""), reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _normalize_insert_row(self, row: dict) -> dict:
        copied = deepcopy(row)
        if self._table_name == "webui_blueprints":
            copied.setdefault("id", str(uuid4()))
            copied.setdefault("created_at", self._now())
            copied.setdefault("updated_at", copied["created_at"])
        if self._table_name == "webui_blueprint_session_bindings":
            now = self._now()
            copied.setdefault("created_at", now)
            copied.setdefault("updated_at", now)
            copied.setdefault("last_used_at", now)
        return copied

    async def execute(self):
        if self._action == "select":
            return _FakeResponse([deepcopy(row) for row in self._filtered_rows()])

        if self._action == "insert":
            payload = self._payload
            rows_to_insert = payload if isinstance(payload, list) else [payload]
            inserted = [self._normalize_insert_row(row) for row in rows_to_insert]
            self._rows().extend(inserted)
            return _FakeResponse([deepcopy(row) for row in inserted])

        if self._action == "update":
            updated = []
            now = self._now()
            for row in self._rows():
                if not self._matches(row):
                    continue
                row.update(deepcopy(self._payload))
                row.setdefault("updated_at", now)
                updated.append(deepcopy(row))
            return _FakeResponse(updated)

        if self._action == "delete":
            remaining = []
            deleted = []
            for row in self._rows():
                if self._matches(row):
                    deleted.append(deepcopy(row))
                else:
                    remaining.append(row)
            self._client.tables[self._table_name] = remaining
            return _FakeResponse(deleted)

        raise RuntimeError(f"Unsupported action: {self._action}")


class _FakeSupabaseClient:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {
            "webui_blueprints": [],
            "webui_blueprint_session_bindings": [],
        }

    def table(self, table_name: str) -> _FakeTableQuery:
        return _FakeTableQuery(self, table_name)


def _setup_fake_backend(monkeypatch):
    fake_client = _FakeSupabaseClient()

    async def _get_client():
        return fake_client

    monkeypatch.setattr(webui_api, "_require_user_id", lambda: "user-1")
    monkeypatch.setattr(webui_api, "get_supabase_async_client", _get_client)
    return fake_client


def _collect_view_types(node: dict) -> list[str]:
    node_type = node.get("type")
    if node_type == "view":
        return [str(node.get("viewType"))]
    if node_type == "split":
        children = node.get("children") or []
        return _collect_view_types(children[0]) + _collect_view_types(children[1])
    if node_type == "tabs":
        types: list[str] = []
        for tab in node.get("tabs") or []:
            child = tab.get("child")
            if isinstance(child, dict):
                types.extend(_collect_view_types(child))
        return types
    return []


def test_default_blueprint_contains_timeline_as_bottom_pane():
    blueprint = webui_api._default_blueprint()
    assert blueprint["type"] == "split"
    assert blueprint["direction"] == "column"
    assert blueprint["children"][1]["type"] == "view"
    assert blueprint["children"][1]["viewType"] == "timeline"
    assert "timeline" in _collect_view_types(blueprint)


def test_webui_blueprints_resolve_updates_last_used_at(client, monkeypatch):
    fake = _setup_fake_backend(monkeypatch)

    created = client.post(
        "/api/webui/blueprints",
        json={"name": "Main", "blueprint": webui_api._default_blueprint()},
    )
    assert created.status_code == 200
    blueprint_id = created.json()["id"]

    bind = client.put(
        "/api/webui/blueprints/session/binding",
        json={
            "session_kind": "recording",
            "session_id": "sess-001",
            "blueprint_id": blueprint_id,
        },
    )
    assert bind.status_code == 200

    binding_row = fake.tables["webui_blueprint_session_bindings"][0]
    binding_row["last_used_at"] = "2000-01-01T00:00:00+00:00"

    resolved = client.post(
        "/api/webui/blueprints/session/resolve",
        json={"session_kind": "recording", "session_id": "sess-001"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolved_by"] == "binding"
    assert resolved.json()["blueprint"]["id"] == blueprint_id

    updated_row = fake.tables["webui_blueprint_session_bindings"][0]
    assert updated_row["last_used_at"] != "2000-01-01T00:00:00+00:00"


def test_webui_blueprints_binding_updates_last_used_at(client, monkeypatch):
    fake = _setup_fake_backend(monkeypatch)

    created_a = client.post(
        "/api/webui/blueprints",
        json={"name": "A", "blueprint": webui_api._default_blueprint()},
    )
    created_b = client.post(
        "/api/webui/blueprints",
        json={"name": "B", "blueprint": webui_api._default_blueprint()},
    )
    assert created_a.status_code == 200
    assert created_b.status_code == 200

    first_bind = client.put(
        "/api/webui/blueprints/session/binding",
        json={
            "session_kind": "teleop",
            "session_id": "sess-teleop",
            "blueprint_id": created_a.json()["id"],
        },
    )
    assert first_bind.status_code == 200

    binding_row = fake.tables["webui_blueprint_session_bindings"][0]
    binding_row["last_used_at"] = "2000-01-01T00:00:00+00:00"

    second_bind = client.put(
        "/api/webui/blueprints/session/binding",
        json={
            "session_kind": "teleop",
            "session_id": "sess-teleop",
            "blueprint_id": created_b.json()["id"],
        },
    )
    assert second_bind.status_code == 200

    updated_row = fake.tables["webui_blueprint_session_bindings"][0]
    assert updated_row["blueprint_id"] == created_b.json()["id"]
    assert updated_row["last_used_at"] != "2000-01-01T00:00:00+00:00"


def test_webui_blueprints_list_returns_sql_derived_last_used(client, monkeypatch):
    _setup_fake_backend(monkeypatch)

    created_a = client.post(
        "/api/webui/blueprints",
        json={"name": "A", "blueprint": webui_api._default_blueprint()},
    )
    created_b = client.post(
        "/api/webui/blueprints",
        json={"name": "B", "blueprint": webui_api._default_blueprint()},
    )
    assert created_a.status_code == 200
    assert created_b.status_code == 200

    bind_a = client.put(
        "/api/webui/blueprints/session/binding",
        json={
            "session_kind": "recording",
            "session_id": "sess-a",
            "blueprint_id": created_a.json()["id"],
        },
    )
    assert bind_a.status_code == 200

    bind_b = client.put(
        "/api/webui/blueprints/session/binding",
        json={
            "session_kind": "inference",
            "session_id": "sess-b",
            "blueprint_id": created_b.json()["id"],
        },
    )
    assert bind_b.status_code == 200

    listing = client.get("/api/webui/blueprints")
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["last_used_blueprint_id"] == created_b.json()["id"]
    assert len(payload["blueprints"]) == 2


def test_webui_blueprints_list_tie_breaks_by_updated_at_then_id(client, monkeypatch):
    fake = _setup_fake_backend(monkeypatch)

    created_a = client.post(
        "/api/webui/blueprints",
        json={"name": "A", "blueprint": webui_api._default_blueprint()},
    )
    created_b = client.post(
        "/api/webui/blueprints",
        json={"name": "B", "blueprint": webui_api._default_blueprint()},
    )
    assert created_a.status_code == 200
    assert created_b.status_code == 200
    blueprint_a_id = created_a.json()["id"]
    blueprint_b_id = created_b.json()["id"]

    client.put(
        "/api/webui/blueprints/session/binding",
        json={
            "session_kind": "recording",
            "session_id": "sess-a",
            "blueprint_id": blueprint_a_id,
        },
    )
    client.put(
        "/api/webui/blueprints/session/binding",
        json={
            "session_kind": "teleop",
            "session_id": "sess-b",
            "blueprint_id": blueprint_b_id,
        },
    )

    same_last_used = "2100-01-01T00:00:00+00:00"
    for row in fake.tables["webui_blueprint_session_bindings"]:
        row["last_used_at"] = same_last_used

    for row in fake.tables["webui_blueprints"]:
        if row["id"] == blueprint_a_id:
            row["updated_at"] = "2000-01-01T00:00:00+00:00"
        if row["id"] == blueprint_b_id:
            row["updated_at"] = "2001-01-01T00:00:00+00:00"

    listing = client.get("/api/webui/blueprints")
    assert listing.status_code == 200
    assert listing.json()["last_used_blueprint_id"] == blueprint_b_id

    for row in fake.tables["webui_blueprints"]:
        row["updated_at"] = "2002-01-01T00:00:00+00:00"

    listing_with_id_tie_break = client.get("/api/webui/blueprints")
    assert listing_with_id_tie_break.status_code == 200
    assert listing_with_id_tie_break.json()["last_used_blueprint_id"] == max(
        blueprint_a_id, blueprint_b_id
    )


def test_webui_blueprints_delete_rebinds_sessions_by_last_used_priority(client, monkeypatch):
    fake = _setup_fake_backend(monkeypatch)

    created_a = client.post(
        "/api/webui/blueprints",
        json={"name": "Target", "blueprint": webui_api._default_blueprint()},
    )
    created_b = client.post(
        "/api/webui/blueprints",
        json={"name": "Preferred", "blueprint": webui_api._default_blueprint()},
    )
    created_c = client.post(
        "/api/webui/blueprints",
        json={"name": "LatestOnly", "blueprint": webui_api._default_blueprint()},
    )
    assert created_a.status_code == 200
    assert created_b.status_code == 200
    assert created_c.status_code == 200

    target_id = created_a.json()["id"]
    preferred_id = created_b.json()["id"]

    client.put(
        "/api/webui/blueprints/session/binding",
        json={
            "session_kind": "recording",
            "session_id": "sess-1",
            "blueprint_id": target_id,
        },
    )
    client.put(
        "/api/webui/blueprints/session/binding",
        json={
            "session_kind": "teleop",
            "session_id": "sess-2",
            "blueprint_id": target_id,
        },
    )
    client.put(
        "/api/webui/blueprints/session/binding",
        json={
            "session_kind": "inference",
            "session_id": "sess-3",
            "blueprint_id": preferred_id,
        },
    )

    # Keep preferred blueprint as most recently used candidate.
    for row in fake.tables["webui_blueprint_session_bindings"]:
        if row["session_id"] == "sess-3":
            row["last_used_at"] = "2100-01-01T00:00:00+00:00"
        elif row["blueprint_id"] == target_id:
            row["last_used_at"] = "2000-01-01T00:00:00+00:00"

    deleted = client.delete(f"/api/webui/blueprints/{target_id}")
    assert deleted.status_code == 200
    payload = deleted.json()
    assert payload["success"] is True
    assert payload["replacement_blueprint_id"] == preferred_id
    assert payload["rebound_session_count"] == 2

    rebound_rows = [row for row in fake.tables["webui_blueprint_session_bindings"] if row["session_id"] in {"sess-1", "sess-2"}]
    assert all(row["blueprint_id"] == preferred_id for row in rebound_rows)
    assert all(row["last_used_at"] != "2000-01-01T00:00:00+00:00" for row in rebound_rows)


def test_webui_blueprints_delete_creates_default_when_no_last_used_candidate(client, monkeypatch):
    fake = _setup_fake_backend(monkeypatch)

    created_target = client.post(
        "/api/webui/blueprints",
        json={"name": "Target", "blueprint": webui_api._default_blueprint()},
    )
    created_unbound = client.post(
        "/api/webui/blueprints",
        json={"name": "Unbound", "blueprint": webui_api._default_blueprint()},
    )
    assert created_target.status_code == 200
    assert created_unbound.status_code == 200

    target_id = created_target.json()["id"]
    unbound_id = created_unbound.json()["id"]

    client.put(
        "/api/webui/blueprints/session/binding",
        json={
            "session_kind": "recording",
            "session_id": "sess-1",
            "blueprint_id": target_id,
        },
    )
    client.put(
        "/api/webui/blueprints/session/binding",
        json={
            "session_kind": "teleop",
            "session_id": "sess-2",
            "blueprint_id": target_id,
        },
    )

    deleted = client.delete(f"/api/webui/blueprints/{target_id}")
    assert deleted.status_code == 200
    payload = deleted.json()
    assert payload["success"] is True
    assert payload["rebound_session_count"] == 2
    assert payload["replacement_blueprint_id"] not in {None, unbound_id}

    replacement_id = payload["replacement_blueprint_id"]
    replacement_row = next(
        (row for row in fake.tables["webui_blueprints"] if row["id"] == replacement_id),
        None,
    )
    assert replacement_row is not None
    assert replacement_row["name"] == "Default Blueprint"

    rebound_rows = [
        row
        for row in fake.tables["webui_blueprint_session_bindings"]
        if row["session_id"] in {"sess-1", "sess-2"}
    ]
    assert all(row["blueprint_id"] == replacement_id for row in rebound_rows)
