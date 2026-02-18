import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

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
