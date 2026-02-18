from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import interfaces_backend.services.vlabor_profiles as vlabor_profiles
from interfaces_backend.services.vlabor_profiles import VlaborProfileSpec


@dataclass
class _Result:
    data: list[dict[str, Any]]


class _Query:
    def __init__(self, tables: dict[str, list[dict[str, Any]]], table_name: str) -> None:
        self._tables = tables
        self._table_name = table_name
        self._filters: list[tuple[str, Any]] = []
        self._limit: int | None = None
        self._order_field: str | None = None
        self._order_desc = False
        self._mode = "select"
        self._payload: dict[str, Any] | None = None

    def select(self, _columns: str) -> "_Query":
        self._mode = "select"
        return self

    def eq(self, field: str, value: Any) -> "_Query":
        self._filters.append((field, value))
        return self

    def limit(self, value: int) -> "_Query":
        self._limit = value
        return self

    def order(self, field: str, *, desc: bool = False) -> "_Query":
        self._order_field = field
        self._order_desc = desc
        return self

    def update(self, payload: dict[str, Any]) -> "_Query":
        self._mode = "update"
        self._payload = dict(payload)
        return self

    def insert(self, payload: dict[str, Any]) -> "_Query":
        self._mode = "insert"
        self._payload = dict(payload)
        return self

    async def execute(self) -> _Result:
        rows = self._tables.setdefault(self._table_name, [])

        def _matches(row: dict[str, Any]) -> bool:
            for field, value in self._filters:
                if row.get(field) != value:
                    return False
            return True

        if self._mode == "update":
            assert self._payload is not None
            for row in rows:
                if _matches(row):
                    row.update(self._payload)
            return _Result([])

        if self._mode == "insert":
            assert self._payload is not None
            rows.append(dict(self._payload))
            return _Result([])

        selected = [dict(row) for row in rows if _matches(row)]
        if self._order_field:
            selected.sort(
                key=lambda row: row.get(self._order_field) or "",
                reverse=self._order_desc,
            )
        if self._limit is not None:
            selected = selected[: self._limit]
        return _Result(selected)


class _Client:
    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self._tables = tables

    def table(self, table_name: str) -> _Query:
        return _Query(self._tables, table_name)


def _profile(name: str) -> VlaborProfileSpec:
    return VlaborProfileSpec(
        name=name,
        description=name,
        snapshot={"name": name, "profile": {"name": name}},
        source_path=f"/tmp/{name}.yaml",
        updated_at=None,
    )


def test_get_active_profile_uses_latest_when_scope_changes(monkeypatch):
    tables = {
        "vlabor_profile_selections": [
            {
                "scope_id": "host:old-backend",
                "profile_name": "so101_single_teleop",
                "updated_at": "2026-02-18T10:00:00+00:00",
            },
            {
                "scope_id": "host:older-backend",
                "profile_name": "so101_dual_teleop",
                "updated_at": "2026-02-17T10:00:00+00:00",
            },
        ]
    }

    async def _fake_client() -> _Client:
        return _Client(tables)

    monkeypatch.delenv("VLABOR_PROFILE_SCOPE_ID", raising=False)
    monkeypatch.setattr(vlabor_profiles.socket, "gethostname", lambda: "new-backend")
    monkeypatch.setattr(vlabor_profiles, "get_supabase_async_client", _fake_client)
    monkeypatch.setattr(
        vlabor_profiles,
        "list_vlabor_profiles",
        lambda: [_profile("so101_dual_teleop"), _profile("so101_single_teleop")],
    )

    active = asyncio.run(vlabor_profiles.get_active_profile_spec())
    assert active.name == "so101_single_teleop"


def test_set_active_profile_writes_host_and_global_scope(monkeypatch):
    tables: dict[str, list[dict[str, Any]]] = {"vlabor_profile_selections": []}

    async def _fake_client() -> _Client:
        return _Client(tables)

    monkeypatch.delenv("VLABOR_PROFILE_SCOPE_ID", raising=False)
    monkeypatch.setattr(vlabor_profiles.socket, "gethostname", lambda: "backend-a")
    monkeypatch.setattr(vlabor_profiles, "get_supabase_async_client", _fake_client)
    monkeypatch.setattr(vlabor_profiles, "list_vlabor_profiles", lambda: [_profile("so101_single_teleop")])

    asyncio.run(vlabor_profiles.set_active_profile_spec("so101_single_teleop"))

    rows = tables["vlabor_profile_selections"]
    assert len(rows) == 2
    assert {row["scope_id"] for row in rows} == {"host:backend-a", "global"}
    assert {row["profile_name"] for row in rows} == {"so101_single_teleop"}


def test_set_active_profile_respects_explicit_scope(monkeypatch):
    tables: dict[str, list[dict[str, Any]]] = {"vlabor_profile_selections": []}

    async def _fake_client() -> _Client:
        return _Client(tables)

    monkeypatch.setenv("VLABOR_PROFILE_SCOPE_ID", "scope:rig-1")
    monkeypatch.setattr(vlabor_profiles.socket, "gethostname", lambda: "backend-a")
    monkeypatch.setattr(vlabor_profiles, "get_supabase_async_client", _fake_client)
    monkeypatch.setattr(vlabor_profiles, "list_vlabor_profiles", lambda: [_profile("so101_single_teleop")])

    asyncio.run(vlabor_profiles.set_active_profile_spec("so101_single_teleop"))

    rows = tables["vlabor_profile_selections"]
    assert len(rows) == 1
    assert rows[0]["scope_id"] == "scope:rig-1"
    assert rows[0]["profile_name"] == "so101_single_teleop"
