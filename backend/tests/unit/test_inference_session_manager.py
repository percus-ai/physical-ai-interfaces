import asyncio
import os
from types import SimpleNamespace

from fastapi import HTTPException

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

from interfaces_backend.services.inference_session import InferenceSessionManager
from interfaces_backend.services.session_manager import SessionState


class _FakeRuntime:
    def __init__(self):
        self.stop_calls: list[str | None] = []

    def stop(self, session_id: str | None = None) -> bool:
        self.stop_calls.append(session_id)
        return True


class _FakeRecorder:
    def __init__(self, *, stop_exception: Exception | None = None, final_status: dict | None = None):
        self.stop_exception = stop_exception
        self.final_status = final_status
        self.stop_calls = 0
        self.wait_calls = 0

    def stop(self, *, save_current: bool = True) -> dict:
        _ = save_current
        self.stop_calls += 1
        if self.stop_exception is not None:
            raise self.stop_exception
        return {"success": True, "message": "stopped"}

    def wait_until_finalized(
        self,
        dataset_id: str,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.5,
    ) -> dict | None:
        _ = (dataset_id, timeout_s, poll_interval_s)
        self.wait_calls += 1
        return self.final_status


class _FakeDataset:
    def __init__(self):
        self.marked: list[str] = []
        self.uploaded: list[str] = []

    async def mark_active(self, dataset_id: str) -> None:
        self.marked.append(dataset_id)

    async def auto_upload(self, dataset_id: str) -> None:
        self.uploaded.append(dataset_id)


def _build_manager(*, recorder: _FakeRecorder, dataset: _FakeDataset, runtime: _FakeRuntime) -> InferenceSessionManager:
    manager = InferenceSessionManager(runtime=runtime, recorder=recorder, dataset=dataset)
    manager._sessions["session-1"] = SessionState(
        id="session-1",
        kind="inference",
        profile=SimpleNamespace(name="profile-a", snapshot={"raw": {}}),
        extras={
            "worker_session_id": "worker-1",
            "dataset_id": "dataset-1",
        },
    )
    return manager


def test_stop_treats_recorder_timeout_as_stopped_when_already_inactive() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder(
        stop_exception=HTTPException(status_code=503, detail="Recorder request timed out: /api/session/stop"),
        final_status={"state": "idle", "dataset_id": ""},
    )
    dataset = _FakeDataset()
    manager = _build_manager(recorder=recorder, dataset=dataset, runtime=runtime)

    state = asyncio.run(manager.stop("session-1"))

    assert state.status == "stopped"
    assert runtime.stop_calls == ["worker-1"]
    assert recorder.stop_calls == 1
    assert recorder.wait_calls == 1
    assert dataset.marked == ["dataset-1"]
    assert dataset.uploaded == ["dataset-1"]


def test_stop_keeps_dataset_unmarked_when_recorder_may_still_be_active() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder(
        stop_exception=HTTPException(status_code=503, detail="Recorder request timed out: /api/session/stop"),
        final_status={"state": "recording", "dataset_id": "dataset-1"},
    )
    dataset = _FakeDataset()
    manager = _build_manager(recorder=recorder, dataset=dataset, runtime=runtime)

    state = asyncio.run(manager.stop("session-1"))

    assert state.status == "stopped"
    assert runtime.stop_calls == ["worker-1"]
    assert recorder.stop_calls == 1
    assert recorder.wait_calls == 1
    assert dataset.marked == []
    assert dataset.uploaded == ["dataset-1"]
