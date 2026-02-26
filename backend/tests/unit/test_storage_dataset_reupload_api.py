import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from postgrest.exceptions import APIError

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")


def _find_repo_root(start: Path) -> Path:
    for parent in [start] + list(start.parents):
        if (parent / "AGENTS.md").exists():
            return parent
    return start


def _install_lerobot_stubs() -> None:
    lerobot_module = sys.modules.setdefault("lerobot", ModuleType("lerobot"))
    datasets_module = sys.modules.setdefault("lerobot.datasets", ModuleType("lerobot.datasets"))
    aggregate_module = sys.modules.setdefault(
        "lerobot.datasets.aggregate",
        ModuleType("lerobot.datasets.aggregate"),
    )
    lerobot_dataset_module = sys.modules.setdefault(
        "lerobot.datasets.lerobot_dataset",
        ModuleType("lerobot.datasets.lerobot_dataset"),
    )

    setattr(aggregate_module, "aggregate_datasets", lambda **kwargs: None)

    class _DummyLeRobotDatasetMetadata:
        def __init__(self, *_args, **_kwargs):
            self.total_episodes = 0

    setattr(lerobot_dataset_module, "LeRobotDatasetMetadata", _DummyLeRobotDatasetMetadata)
    setattr(datasets_module, "aggregate", aggregate_module)
    setattr(datasets_module, "lerobot_dataset", lerobot_dataset_module)
    setattr(lerobot_module, "datasets", datasets_module)


def _load_storage_api_module():
    repo_root = _find_repo_root(Path(__file__).resolve())
    module_path = repo_root / "interfaces" / "backend" / "src" / "interfaces_backend" / "api" / "storage.py"
    spec = importlib.util.spec_from_file_location("storage_api_for_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load storage module spec: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_install_lerobot_stubs()
storage_api = _load_storage_api_module()


class _FakeLifecycleOk:
    async def reupload(self, dataset_id):
        assert dataset_id == "dataset-1"
        return True, ""


class _FakeLifecycleFail:
    async def reupload(self, dataset_id):
        _ = dataset_id
        return False, "upload failed"


def test_reupload_dataset_success(monkeypatch, tmp_path: Path):
    datasets_dir = tmp_path / "datasets"
    (datasets_dir / "dataset-1").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(storage_api, "get_datasets_dir", lambda: datasets_dir)
    monkeypatch.setattr(storage_api, "get_dataset_lifecycle", lambda: _FakeLifecycleOk())

    response = asyncio.run(storage_api.reupload_dataset("dataset-1"))

    assert response.id == "dataset-1"
    assert response.success is True
    assert response.message == "Dataset re-upload completed"


def test_reupload_dataset_requires_local_dataset(monkeypatch, tmp_path: Path):
    datasets_dir = tmp_path / "datasets"
    datasets_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(storage_api, "get_datasets_dir", lambda: datasets_dir)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(storage_api.reupload_dataset("missing-dataset"))

    assert exc_info.value.status_code == 404
    assert "Local dataset not found" in str(exc_info.value.detail)


def test_reupload_dataset_propagates_sync_failure(monkeypatch, tmp_path: Path):
    datasets_dir = tmp_path / "datasets"
    (datasets_dir / "dataset-1").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(storage_api, "get_datasets_dir", lambda: datasets_dir)
    monkeypatch.setattr(storage_api, "get_dataset_lifecycle", lambda: _FakeLifecycleFail())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(storage_api.reupload_dataset("dataset-1"))

    assert exc_info.value.status_code == 500
    assert "Dataset re-upload failed: upload failed" in str(exc_info.value.detail)


class _FakeTableQuery:
    def __init__(self, client, table_name: str):
        self._client = client
        self._table_name = table_name
        self._op = "select"
        self._payload = None
        self._filters: list[tuple[str, str]] = []

    def select(self, _fields: str):
        self._op = "select"
        return self

    def update(self, payload: dict):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, key: str, value: str):
        self._filters.append((key, value))
        return self

    async def execute(self):
        self._client.calls.append(
            {
                "table": self._table_name,
                "op": self._op,
                "payload": self._payload,
                "filters": list(self._filters),
            }
        )
        if (
            self._table_name == "training_jobs"
            and self._op == "update"
            and self._payload == {"new_dataset_id": None}
            and self._client.missing_new_dataset_id_column
        ):
            raise APIError(
                {
                    "message": "Could not find the 'new_dataset_id' column of 'training_jobs' in the schema cache",
                    "code": "PGRST204",
                    "details": None,
                    "hint": None,
                }
            )
        if self._op == "select" and self._table_name == "datasets":
            dataset_id = next((value for key, value in self._filters if key == "id"), "")
            row = self._client.dataset_rows.get(dataset_id)
            return SimpleNamespace(data=[row] if row else [])
        return SimpleNamespace(data=[])


class _FakeStorageDbClient:
    def __init__(self):
        self.dataset_rows: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.missing_new_dataset_id_column = False

    def table(self, table_name: str):
        return _FakeTableQuery(self, table_name)


def test_delete_archived_items_detaches_training_job_dataset_refs(monkeypatch):
    fake_client = _FakeStorageDbClient()
    fake_client.dataset_rows["dataset-1"] = {"id": "dataset-1", "status": "archived"}

    class _FakeSyncService:
        def delete_dataset_remote(self, _dataset_id: str) -> None:
            return None

        def delete_model_remote(self, _model_id: str) -> None:
            return None

    async def _fake_get_supabase():
        return fake_client

    monkeypatch.setattr(storage_api, "get_supabase_async_client", _fake_get_supabase)
    monkeypatch.setattr(storage_api, "R2DBSyncService", _FakeSyncService)
    monkeypatch.setattr(storage_api, "_delete_local_dataset", lambda _dataset_id: None)
    monkeypatch.setattr(storage_api, "_delete_local_model", lambda _model_id: None)

    response = asyncio.run(
        storage_api.delete_archived_items(
            storage_api.ArchiveBulkRequest(dataset_ids=["dataset-1"], model_ids=[])
        )
    )

    assert response.success is True
    assert response.deleted == ["dataset-1"]
    assert response.errors == []

    expected_calls = [
        {"table": "models", "op": "update", "payload": {"dataset_id": None}, "filters": [("dataset_id", "dataset-1")]},
        {
            "table": "training_jobs",
            "op": "update",
            "payload": {"dataset_id": None},
            "filters": [("dataset_id", "dataset-1")],
        },
        {
            "table": "training_jobs",
            "op": "update",
            "payload": {"new_dataset_id": None},
            "filters": [("new_dataset_id", "dataset-1")],
        },
        {"table": "datasets", "op": "delete", "payload": None, "filters": [("id", "dataset-1")]},
    ]

    mutation_calls = [
        call
        for call in fake_client.calls
        if call["table"] in {"models", "training_jobs", "datasets"} and call["op"] in {"update", "delete"}
    ]
    assert mutation_calls == expected_calls


def test_delete_archived_items_ignores_missing_new_dataset_id_column(monkeypatch):
    fake_client = _FakeStorageDbClient()
    fake_client.dataset_rows["dataset-1"] = {"id": "dataset-1", "status": "archived"}
    fake_client.missing_new_dataset_id_column = True

    class _FakeSyncService:
        def delete_dataset_remote(self, _dataset_id: str) -> None:
            return None

        def delete_model_remote(self, _model_id: str) -> None:
            return None

    async def _fake_get_supabase():
        return fake_client

    monkeypatch.setattr(storage_api, "get_supabase_async_client", _fake_get_supabase)
    monkeypatch.setattr(storage_api, "R2DBSyncService", _FakeSyncService)
    monkeypatch.setattr(storage_api, "_delete_local_dataset", lambda _dataset_id: None)
    monkeypatch.setattr(storage_api, "_delete_local_model", lambda _model_id: None)

    response = asyncio.run(
        storage_api.delete_archived_items(
            storage_api.ArchiveBulkRequest(dataset_ids=["dataset-1"], model_ids=[])
        )
    )

    assert response.success is True
    assert response.deleted == ["dataset-1"]
    assert response.errors == []
