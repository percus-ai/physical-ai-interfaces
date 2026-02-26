import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

from interfaces_backend.services.startup_operations import StartupOperationsService


def test_startup_operation_lifecycle():
    service = StartupOperationsService()
    accepted = service.create(user_id="user-a", kind="inference_start")
    operation_id = accepted.operation_id

    status = service.get(user_id="user-a", operation_id=operation_id)
    assert status.state == "queued"
    assert status.phase == "queued"

    service.set_running(
        operation_id=operation_id,
        phase="sync_model",
        progress_percent=63.5,
        message="syncing",
        detail={"files_done": 2, "total_files": 4},
    )
    status = service.get(user_id="user-a", operation_id=operation_id)
    assert status.state == "running"
    assert status.phase == "sync_model"
    assert status.progress_percent == 63.5
    assert status.detail.files_done == 2
    assert status.detail.total_files == 4

    service.complete(
        operation_id=operation_id,
        target_session_id="sess-1",
    )
    status = service.get(user_id="user-a", operation_id=operation_id)
    assert status.state == "completed"
    assert status.phase == "done"
    assert status.progress_percent == 100.0
    assert status.target_session_id == "sess-1"


def test_startup_operation_rejects_parallel_same_kind():
    service = StartupOperationsService()
    service.create(user_id="user-a", kind="recording_create")

    with pytest.raises(HTTPException) as exc_info:
        service.create(user_id="user-a", kind="recording_create")

    assert exc_info.value.status_code == 409
