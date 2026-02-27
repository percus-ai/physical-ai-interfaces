import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

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
    spec = importlib.util.spec_from_file_location("storage_api_model_sync_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load storage module spec: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_install_lerobot_stubs()
storage_api = _load_storage_api_module()


class _FakeTableQuery:
    def __init__(self, client, table_name: str):
        self._client = client
        self._table_name = table_name
        self._filters: list[tuple[str, str]] = []

    def select(self, _fields: str):
        return self

    def eq(self, key: str, value: str):
        self._filters.append((key, value))
        return self

    async def execute(self):
        if self._table_name != "models":
            return SimpleNamespace(data=[])
        rows = list(self._client.model_rows)
        for key, value in self._filters:
            rows = [row for row in rows if str(row.get(key)) == value]
        return SimpleNamespace(data=rows)


class _FakeStorageDbClient:
    def __init__(self):
        self.model_rows: list[dict] = []

    def table(self, table_name: str):
        return _FakeTableQuery(self, table_name)


def _install_db_client(monkeypatch: pytest.MonkeyPatch, client: _FakeStorageDbClient) -> None:
    async def _fake_get_supabase():
        return client

    monkeypatch.setattr(storage_api, "get_supabase_async_client", _fake_get_supabase)


def test_sync_model_success(monkeypatch: pytest.MonkeyPatch):
    fake_client = _FakeStorageDbClient()
    fake_client.model_rows = [{"id": "model-1", "status": "active"}]
    _install_db_client(monkeypatch, fake_client)

    class _FakeLifecycle:
        def __init__(self) -> None:
            self.synced_model_id: str | None = None

        async def ensure_model_local(self, model_id: str):
            self.synced_model_id = model_id

        def get_model_sync_status(self):
            return SimpleNamespace(message="モデル同期が完了しました。")

    fake_lifecycle = _FakeLifecycle()
    monkeypatch.setattr(storage_api, "get_dataset_lifecycle", lambda: fake_lifecycle)

    response = asyncio.run(storage_api.sync_model("model-1"))
    assert fake_lifecycle.synced_model_id == "model-1"
    assert response.result.model_id == "model-1"
    assert response.result.success is True
    assert response.result.skipped is False
    assert response.result.message == "モデル同期が完了しました。"


def test_sync_model_not_found(monkeypatch: pytest.MonkeyPatch):
    fake_client = _FakeStorageDbClient()
    _install_db_client(monkeypatch, fake_client)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(storage_api.sync_model("missing-model"))

    assert exc_info.value.status_code == 404
    assert "Model not found" in str(exc_info.value.detail)


def test_sync_model_rejects_archived(monkeypatch: pytest.MonkeyPatch):
    fake_client = _FakeStorageDbClient()
    fake_client.model_rows = [{"id": "model-archived", "status": "archived"}]
    _install_db_client(monkeypatch, fake_client)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(storage_api.sync_model("model-archived"))

    assert exc_info.value.status_code == 400
    assert "Model is not active" in str(exc_info.value.detail)
