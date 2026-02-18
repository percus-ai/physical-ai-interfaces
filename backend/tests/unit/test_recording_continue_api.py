import asyncio
import importlib.util
import os
from pathlib import Path
import sys

from fastapi import HTTPException

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")



def _load_recording_api_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "interfaces_backend"
        / "api"
        / "recording.py"
    )
    spec = importlib.util.spec_from_file_location("interfaces_backend_api_recording_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


recording_api = _load_recording_api_module()


def _base_row() -> dict:
    return {
        "id": "dataset-1",
        "name": "dataset_name",
        "task_detail": "pick and place",
        "profile_snapshot": {"name": "profile-a"},
        "episode_count": 3,
        "target_total_episodes": 8,
        "episode_time_s": 60.0,
        "reset_time_s": 10.0,
        "size_bytes": 0,
        "created_at": "2026-01-01T00:00:00Z",
        "dataset_type": "recorded",
        "status": "active",
    }


def test_build_continue_plan_blocks_when_remaining_not_positive(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(recording_api, "get_datasets_dir", lambda: tmp_path)
    row = _base_row()
    row["target_total_episodes"] = 3

    plan = recording_api._build_continue_plan_from_row(row)

    assert plan.continuable is False
    assert plan.remaining_episodes == 0
    assert plan.reason == "残りエピソードがありません"


def test_build_continue_plan_blocks_without_local_dataset(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(recording_api, "get_datasets_dir", lambda: tmp_path)
    row = _base_row()

    plan = recording_api._build_continue_plan_from_row(row)

    assert plan.continuable is False
    assert plan.reason == "ローカルデータセットが見つかりません"


def test_build_continue_plan_allows_when_configured(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(recording_api, "get_datasets_dir", lambda: tmp_path)
    row = _base_row()
    (tmp_path / row["id"]).mkdir(parents=True, exist_ok=True)

    plan = recording_api._build_continue_plan_from_row(row)

    assert plan.continuable is True
    assert plan.remaining_episodes == 5
    assert plan.target_total_episodes == 8


def test_create_session_rejects_non_continuable(monkeypatch, tmp_path: Path):
    async def fake_fetch(_recording_id: str) -> dict:
        row = _base_row()
        row["target_total_episodes"] = row["episode_count"]
        return row

    monkeypatch.setattr(recording_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(recording_api, "get_datasets_dir", lambda: tmp_path)
    monkeypatch.setattr(recording_api, "_fetch_recording_row", fake_fetch)

    request = recording_api.RecordingSessionCreateRequest(
        dataset_name="ignored_name",
        task="ignored_task",
        num_episodes=1,
        episode_time_s=30.0,
        reset_time_s=5.0,
        continue_from_dataset_id="dataset-1",
    )

    try:
        asyncio.run(recording_api.create_session(request))
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "残りエピソードがありません" in str(exc.detail)


def test_run_create_operation_continue_uses_plan_values(monkeypatch, tmp_path: Path):
    captured: dict = {}
    completed: dict = {}

    class _FakeManager:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return type("State", (), {"id": kwargs["session_id"]})()

    class _FakeOperations:
        def build_progress_callback(self, _operation_id: str):
            return None

        def complete(self, **kwargs):
            completed.update(kwargs)

        def fail(self, **_kwargs):
            assert False, "operation should not fail"

    async def fake_fetch(_recording_id: str) -> dict:
        return _base_row()

    monkeypatch.setattr(recording_api, "get_datasets_dir", lambda: tmp_path)
    (tmp_path / "dataset-1").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(recording_api, "_fetch_recording_row", fake_fetch)
    monkeypatch.setattr(recording_api, "get_recording_session_manager", lambda: _FakeManager())
    monkeypatch.setattr(recording_api, "get_startup_operations_service", lambda: _FakeOperations())

    request = recording_api.RecordingSessionCreateRequest(
        dataset_name="ignored_name",
        task="ignored_task",
        num_episodes=999,
        episode_time_s=45.0,
        reset_time_s=7.0,
        continue_from_dataset_id="dataset-1",
    )

    asyncio.run(recording_api._run_recording_create_operation("op-1", request))

    assert captured["session_id"] == "dataset-1"
    assert captured["dataset_name"] == "dataset_name"
    assert captured["task"] == "pick and place"
    assert captured["num_episodes"] == 5
    assert captured["target_total_episodes"] == 8
    assert captured["episode_time_s"] == 45.0
    assert captured["reset_time_s"] == 7.0
    assert completed["target_session_id"] == "dataset-1"


def test_start_session_resumes_from_existing_recording(monkeypatch, tmp_path: Path):
    created: dict = {}

    class _FakeManager:
        def status(self, _dataset_id: str):
            return None

        async def create(self, **kwargs):
            created.update(kwargs)
            return type("State", (), {"id": kwargs["session_id"]})()

        async def start(self, dataset_id: str):
            return type(
                "State",
                (),
                {
                    "id": dataset_id,
                    "extras": {"recorder_result": {"success": True, "message": "started"}},
                },
            )()

    async def fake_fetch(_recording_id: str) -> dict:
        return _base_row()

    monkeypatch.setattr(recording_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(recording_api, "get_recording_session_manager", lambda: _FakeManager())
    monkeypatch.setattr(recording_api, "get_datasets_dir", lambda: tmp_path)
    monkeypatch.setattr(recording_api, "_fetch_recording_row", fake_fetch)
    (tmp_path / "dataset-1").mkdir(parents=True, exist_ok=True)

    response = asyncio.run(
        recording_api.start_session(recording_api.RecordingSessionStartRequest(dataset_id="dataset-1"))
    )

    assert created["session_id"] == "dataset-1"
    assert created["num_episodes"] == 5
    assert response.success is True
    assert response.message == "Recording session resumed"
    assert response.dataset_id == "dataset-1"


def test_start_session_rejects_non_continuable_recording(monkeypatch, tmp_path: Path):
    class _FakeManager:
        def status(self, _dataset_id: str):
            return None

    async def fake_fetch(_recording_id: str) -> dict:
        row = _base_row()
        row["target_total_episodes"] = row["episode_count"]
        return row

    monkeypatch.setattr(recording_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(recording_api, "get_recording_session_manager", lambda: _FakeManager())
    monkeypatch.setattr(recording_api, "get_datasets_dir", lambda: tmp_path)
    monkeypatch.setattr(recording_api, "_fetch_recording_row", fake_fetch)
    (tmp_path / "dataset-1").mkdir(parents=True, exist_ok=True)

    try:
        asyncio.run(recording_api.start_session(recording_api.RecordingSessionStartRequest(dataset_id="dataset-1")))
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "残りエピソードがありません" in str(exc.detail)
