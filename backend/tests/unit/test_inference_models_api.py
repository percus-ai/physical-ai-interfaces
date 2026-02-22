import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

import interfaces_backend.api.inference as inference_api
from interfaces_backend.models.inference import (
    GpuHostStatus,
    InferenceModelInfo,
    InferenceModelSyncStatus,
    InferenceRunnerStatus,
    InferenceRunnerStatusResponse,
    InferenceRunnerStartRequest,
)
from interfaces_backend.models.startup import StartupOperationAcceptedResponse


def test_list_models_merges_db_and_runtime(monkeypatch):
    class _FakeRuntime:
        def list_models(self):
            return [
                InferenceModelInfo(
                    model_id="model_shared",
                    name="model_shared",
                    policy_type="pi05",
                    source="local",
                    size_mb=64.0,
                    is_loaded=True,
                    is_local=True,
                ),
                InferenceModelInfo(
                    model_id="model_local_only",
                    name="model_local_only",
                    policy_type="act",
                    source="local",
                    size_mb=8.0,
                    is_loaded=False,
                    is_local=True,
                ),
            ]

    async def _fake_db_models():
        return [
            InferenceModelInfo(
                model_id="model_shared",
                name="shared_display",
                policy_type=None,
                source="r2",
                size_mb=0.0,
                is_loaded=False,
                is_local=False,
            ),
            InferenceModelInfo(
                model_id="model_remote_only",
                name="model_remote_only",
                policy_type="pi0",
                source="r2",
                size_mb=12.0,
                is_loaded=False,
                is_local=False,
            ),
        ]

    monkeypatch.setattr(inference_api, "get_inference_runtime_manager", lambda: _FakeRuntime())
    monkeypatch.setattr(inference_api, "_list_db_models", _fake_db_models)

    response = asyncio.run(inference_api.list_models())
    models = {item.model_id: item for item in response.models}

    assert "model_shared" in models
    assert models["model_shared"].is_local is True
    assert models["model_shared"].is_loaded is True
    assert models["model_shared"].policy_type == "pi05"

    assert "model_remote_only" in models
    assert models["model_remote_only"].is_local is False
    assert models["model_remote_only"].source == "r2"

    assert "model_local_only" in models
    assert models["model_local_only"].is_local is True


def test_list_db_models_marks_unsynced_models(monkeypatch, tmp_path: Path):
    models_dir = tmp_path / "models"
    (models_dir / "model_local").mkdir(parents=True, exist_ok=True)

    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def select(self, _fields):
            return self

        def eq(self, _key, _value):
            return self

        async def execute(self):
            return type("Result", (), {"data": self._rows})()

    class _FakeClient:
        def __init__(self, rows):
            self._rows = rows

        def table(self, _name):
            return _FakeQuery(self._rows)

    async def _fake_db_client():
        return _FakeClient(
            [
                {
                    "id": "model_local",
                    "name": "model_local",
                    "policy_type": "pi05",
                    "size_bytes": 0,
                    "source": "r2",
                    "status": "active",
                },
                {
                    "id": "model_remote",
                    "name": "model_remote",
                    "policy_type": "pi0",
                    "size_bytes": 0,
                    "source": "r2",
                    "status": "active",
                },
            ]
        )

    async def _fake_task_candidates(_client, _rows):
        return {
            "model_remote": ["pick and place"],
        }

    monkeypatch.setattr(inference_api, "get_supabase_async_client", _fake_db_client)
    monkeypatch.setattr(inference_api, "get_models_dir", lambda: models_dir)
    monkeypatch.setattr(inference_api, "_load_task_candidates_by_model", _fake_task_candidates)

    models = asyncio.run(inference_api._list_db_models())
    mapped = {item.model_id: item for item in models}

    assert mapped["model_local"].is_local is True
    assert mapped["model_remote"].is_local is False
    assert mapped["model_remote"].task_candidates == ["pick and place"]


def test_load_task_candidates_by_model_uses_related_active_datasets():
    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows
            self._eq_filters: list[tuple[str, object]] = []
            self._in_filters: list[tuple[str, set[object]]] = []
            self._order_key: str | None = None
            self._order_desc = False

        def select(self, _fields):
            return self

        def eq(self, key, value):
            self._eq_filters.append((key, value))
            return self

        def in_(self, key, values):
            self._in_filters.append((key, set(values)))
            return self

        def order(self, key, desc=False):
            self._order_key = key
            self._order_desc = desc
            return self

        async def execute(self):
            rows = list(self._rows)
            for key, value in self._eq_filters:
                rows = [row for row in rows if row.get(key) == value]
            for key, values in self._in_filters:
                rows = [row for row in rows if row.get(key) in values]
            if self._order_key:
                rows.sort(key=lambda row: row.get(self._order_key) or "", reverse=self._order_desc)
            return type("Result", (), {"data": rows})()

    class _FakeClient:
        def __init__(self, rows_by_table):
            self._rows_by_table = rows_by_table

        def table(self, name):
            return _FakeQuery(self._rows_by_table.get(name, []))

    client = _FakeClient(
        {
            "training_jobs": [
                {
                    "model_id": "model-a",
                    "dataset_id": "dataset-b",
                    "updated_at": "2026-02-21T00:00:00Z",
                    "deleted_at": None,
                },
                {
                    "model_id": "model-a",
                    "dataset_id": "dataset-c",
                    "updated_at": "2026-02-20T00:00:00Z",
                    "deleted_at": None,
                },
                {
                    "model_id": "model-a",
                    "dataset_id": "dataset-d",
                    "updated_at": "2026-02-19T00:00:00Z",
                    "deleted_at": "2026-02-19T00:00:00Z",
                },
            ],
            "datasets": [
                {"id": "dataset-a", "task_detail": "pick and place", "status": "active"},
                {"id": "dataset-b", "task_detail": "stack blocks", "status": "active"},
                {"id": "dataset-c", "task_detail": "archived task", "status": "archived"},
                {"id": "dataset-d", "task_detail": "should not use", "status": "active"},
            ],
        }
    )

    candidates = asyncio.run(
        inference_api._load_task_candidates_by_model(
            client,
            [
                {"id": "model-a", "dataset_id": "dataset-a"},
            ],
        )
    )

    assert candidates["model-a"] == ["pick and place", "stack blocks"]


def test_get_inference_runner_status_includes_model_sync(monkeypatch):
    class _FakeRuntime:
        def get_status(self):
            return InferenceRunnerStatusResponse(
                runner_status=InferenceRunnerStatus(
                    active=False,
                    session_id=None,
                    task=None,
                    queue_length=0,
                    last_error=None,
                ),
                gpu_host_status=GpuHostStatus(
                    status="idle",
                    session_id=None,
                    pid=None,
                    last_error=None,
                ),
            )

    class _FakeLifecycle:
        def get_model_sync_status(self):
            return InferenceModelSyncStatus(
                active=True,
                status="syncing",
                model_id="model_remote",
                message="syncing",
                progress_percent=42.5,
                total_files=8,
                files_done=3,
                total_bytes=1024,
                transferred_bytes=435,
            )

    monkeypatch.setattr(inference_api, "get_inference_runtime_manager", lambda: _FakeRuntime())
    monkeypatch.setattr(inference_api, "get_dataset_lifecycle", lambda: _FakeLifecycle())

    response = asyncio.run(inference_api.get_inference_runner_status())
    assert response.model_sync.active is True
    assert response.model_sync.status == "syncing"
    assert response.model_sync.model_id == "model_remote"
    assert response.model_sync.progress_percent == 42.5


def test_start_inference_runner_returns_operation_id(monkeypatch):
    accepted = StartupOperationAcceptedResponse(operation_id="op-infer", message="accepted")

    class _FakeOperations:
        def create(self, *, user_id: str, kind: str):
            assert user_id == "user-1"
            assert kind == "inference_start"
            return accepted

    def _fake_create_task(coro):
        coro.close()
        return None

    monkeypatch.setattr(inference_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(inference_api, "get_startup_operations_service", lambda: _FakeOperations())
    monkeypatch.setattr(inference_api.asyncio, "create_task", _fake_create_task)

    response = asyncio.run(
        inference_api.start_inference_runner(
            InferenceRunnerStartRequest(model_id="model-a", device="cpu", task="pick")
        )
    )
    assert response.operation_id == "op-infer"


def test_run_inference_start_operation_passes_policy_options(monkeypatch):
    created_kwargs: dict[str, object] = {}
    completed: dict[str, object] = {}

    class _FakeManager:
        async def create(self, **kwargs):
            created_kwargs.update(kwargs)
            return SimpleNamespace(extras={"worker_session_id": "worker-session-1"})

    class _FakeOperations:
        def build_progress_callback(self, _operation_id: str):
            return lambda *_args, **_kwargs: None

        def complete(self, **kwargs):
            completed.update(kwargs)

        def fail(self, **_kwargs):
            raise AssertionError("fail should not be called")

    monkeypatch.setattr(inference_api, "get_inference_session_manager", lambda: _FakeManager())
    monkeypatch.setattr(inference_api, "get_startup_operations_service", lambda: _FakeOperations())

    asyncio.run(
        inference_api._run_inference_start_operation(
            "op-1",
            model_id="model-a",
            device="cpu",
            task="pick",
            policy_options={"pi0": {"denoising_steps": 12}},
        )
    )

    assert created_kwargs["model_id"] == "model-a"
    assert created_kwargs["policy_options"] == {"pi0": {"denoising_steps": 12}}
    assert completed["target_session_id"] == "worker-session-1"
