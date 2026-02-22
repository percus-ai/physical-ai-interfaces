import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import types

from fastapi import HTTPException

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")


def _load_training_api_module():
    training_pkg = types.ModuleType("percus_ai.training")
    ssh_pkg = types.ModuleType("percus_ai.training.ssh")
    ssh_client_module = types.ModuleType("percus_ai.training.ssh.client")
    ssh_executor_module = types.ModuleType("percus_ai.training.ssh.executor")

    class _StubSSHConnection:
        pass

    class _StubRemoteExecutor:
        pass

    def _stub_run_remote_command(*_args, **_kwargs):
        return 0, "", ""

    ssh_client_module.SSHConnection = _StubSSHConnection
    ssh_executor_module.RemoteExecutor = _StubRemoteExecutor
    ssh_executor_module.run_remote_command = _stub_run_remote_command

    sys.modules.setdefault("percus_ai.training", training_pkg)
    sys.modules.setdefault("percus_ai.training.ssh", ssh_pkg)
    sys.modules.setdefault("percus_ai.training.ssh.client", ssh_client_module)
    sys.modules.setdefault("percus_ai.training.ssh.executor", ssh_executor_module)

    module_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "interfaces_backend"
        / "api"
        / "training.py"
    )
    spec = importlib.util.spec_from_file_location("interfaces_backend_api_training_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


training = _load_training_api_module()


class _DummySync:
    bucket = "daihen"

    @staticmethod
    def _get_prefix() -> str:
        return "v2/"


class _DummyCheckpointManager:
    def __init__(self, existing_steps: list[int] | None = None) -> None:
        self.sync = _DummySync()
        self._existing_steps = list(existing_steps or [])
        self.upload_calls: list[dict] = []

    def upload_step_checkpoint(self, **kwargs):
        self.upload_calls.append(kwargs)
        return True, ""

    def get_job_steps(self, _job_name: str):
        return list(self._existing_steps)


class _DummyConn:
    def __init__(self) -> None:
        self.disconnected = False

    def exec_command(self, _cmd: str, timeout: int = 0):
        return 0, "", ""

    def download_directory(self, _remote_path: str, _local_path):
        return None

    def disconnect(self):
        self.disconnected = True


def _job() -> dict:
    return {
        "job_id": "job-1",
        "dataset_id": "dataset-1",
        "policy_type": "pi0",
        "training_config": {"policy": {"type": "pi0"}, "dataset": {"id": "dataset-1"}},
        "remote_base_dir": "/root/.physical-ai",
    }


def test_upload_selected_remote_checkpoint_registers_model(monkeypatch):
    manager = _DummyCheckpointManager(existing_steps=[])
    conn = _DummyConn()
    saved_jobs: list[dict] = []
    upserted: list[dict] = []
    progress: list[dict] = []

    async def fake_load_job(_job_id: str, include_deleted: bool = False):
        assert include_deleted is True
        return _job()

    async def fake_save_job(job_data: dict):
        saved_jobs.append(dict(job_data))

    async def fake_upsert_model(job_data: dict):
        upserted.append(dict(job_data))

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(training, "_get_ssh_connection_for_job", lambda *_args, **_kwargs: conn)
    monkeypatch.setattr(training, "_get_checkpoint_index_manager", lambda: manager)
    monkeypatch.setattr(training, "_register_job_for_checkpoint_if_needed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        training,
        "_ensure_model_artifact_in_r2_from_checkpoint",
        lambda *_args, **_kwargs: ("s3://daihen/v2/models/job-1", 1234, True),
    )
    monkeypatch.setattr(training, "_save_job", fake_save_job)
    monkeypatch.setattr(training, "_upsert_model_for_job", fake_upsert_model)

    result = asyncio.run(
        training._upload_selected_remote_checkpoint_with_progress(
            "job-1",
            "001000",
            progress.append,
        )
    )

    assert result["job_id"] == "job-1"
    assert result["step"] == 1000
    assert result["model_id"] == "job-1"
    assert result["db_registered"] is True
    assert saved_jobs and saved_jobs[-1]["model_id"] == "job-1"
    assert saved_jobs[-1]["model_size_bytes"] == 1234
    assert upserted and upserted[-1]["model_id"] == "job-1"
    assert any(msg.get("type") == "model_registered" for msg in progress)
    assert conn.disconnected is True


def test_upload_selected_remote_checkpoint_reports_db_failure(monkeypatch):
    manager = _DummyCheckpointManager(existing_steps=[])
    conn = _DummyConn()

    async def fake_load_job(_job_id: str, include_deleted: bool = False):
        return _job()

    async def fake_save_job(_job_data: dict):
        return None

    async def fake_upsert_model(_job_data: dict):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(training, "_get_ssh_connection_for_job", lambda *_args, **_kwargs: conn)
    monkeypatch.setattr(training, "_get_checkpoint_index_manager", lambda: manager)
    monkeypatch.setattr(training, "_register_job_for_checkpoint_if_needed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        training,
        "_ensure_model_artifact_in_r2_from_checkpoint",
        lambda *_args, **_kwargs: ("s3://daihen/v2/models/job-1", 1234, True),
    )
    monkeypatch.setattr(training, "_save_job", fake_save_job)
    monkeypatch.setattr(training, "_upsert_model_for_job", fake_upsert_model)

    try:
        asyncio.run(
            training._upload_selected_remote_checkpoint_with_progress(
                "job-1",
                "001000",
                lambda _msg: None,
            )
        )
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 500
        assert "R2登録は完了しましたが、モデルのDB登録に失敗しました" in str(exc.detail)
    assert conn.disconnected is True


def test_upload_selected_remote_checkpoint_skips_r2_reupload_if_step_exists(monkeypatch):
    manager = _DummyCheckpointManager(existing_steps=[1000])
    saved_jobs: list[dict] = []
    upserted: list[dict] = []

    async def fake_load_job(_job_id: str, include_deleted: bool = False):
        assert include_deleted is True
        return _job()

    async def fake_save_job(job_data: dict):
        saved_jobs.append(dict(job_data))

    async def fake_upsert_model(job_data: dict):
        upserted.append(dict(job_data))

    def fail_if_called(*_args, **_kwargs):
        assert False, "SSH should not be used when checkpoint already exists in R2 index"

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(training, "_get_ssh_connection_for_job", fail_if_called)
    monkeypatch.setattr(training, "_get_checkpoint_index_manager", lambda: manager)
    monkeypatch.setattr(
        training,
        "_ensure_model_artifact_in_r2_from_checkpoint",
        lambda *_args, **_kwargs: ("s3://daihen/v2/models/job-1", 1234, False),
    )
    monkeypatch.setattr(training, "_save_job", fake_save_job)
    monkeypatch.setattr(training, "_upsert_model_for_job", fake_upsert_model)

    result = asyncio.run(
        training._upload_selected_remote_checkpoint_with_progress(
            "job-1",
            "001000",
            lambda _msg: None,
        )
    )

    assert result["step"] == 1000
    assert result["db_registered"] is True
    assert manager.upload_calls == []
    assert saved_jobs and upserted


def test_resolve_ssh_private_key_path_supports_project_relative(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "repo"
    key_path = project_root / "data" / "id_verda"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(training, "get_project_root", lambda: project_root)

    resolved = training._resolve_ssh_private_key_path("./data/id_verda")
    assert resolved == str(key_path)


def test_build_ssh_private_key_candidates_reads_relative_env_key(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "repo"
    key_path = project_root / "data" / "id_env"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text("dummy", encoding="utf-8")
    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(training, "get_project_root", lambda: project_root)
    monkeypatch.setattr(training.Path, "home", staticmethod(lambda: home_dir))
    monkeypatch.setenv("VERDA_SSH_PRIVATE_KEY", "./data/id_env")
    monkeypatch.delenv("VERDA_SSH_PRIVATE_KEYS", raising=False)
    monkeypatch.delenv("PHYSICAL_AI_DATA_DIR", raising=False)

    candidates = training._build_ssh_private_key_candidates(None)
    assert candidates
    assert candidates[0] == key_path


def test_build_ssh_private_key_candidates_discovers_keys_in_data_dir(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "repo"
    data_dir = project_root / "data"
    key_path = data_dir / "id_team_shared"
    data_dir.mkdir(parents=True, exist_ok=True)
    key_path.write_text("dummy", encoding="utf-8")
    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(training, "get_project_root", lambda: project_root)
    monkeypatch.setattr(training.Path, "home", staticmethod(lambda: home_dir))
    monkeypatch.delenv("VERDA_SSH_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("VERDA_SSH_PRIVATE_KEYS", raising=False)
    monkeypatch.setenv("PHYSICAL_AI_DATA_DIR", "./data")

    candidates = training._build_ssh_private_key_candidates(None)
    assert key_path in candidates


def test_refresh_job_ssh_target_if_needed_rebinds_to_running_revive(monkeypatch):
    saved_jobs: list[dict] = []

    class _Inst:
        def __init__(self, iid: str, hostname: str, status: str, ip: str, created_at: str):
            self.id = iid
            self.hostname = hostname
            self.status = status
            self.ip = ip
            self.created_at = created_at

    class _Instances:
        @staticmethod
        def get():
            return [
                _Inst("old-revive", "revive-d2f7cdb2", "running", "86.38.238.109", "2026-02-19T12:30:00Z"),
                _Inst("new-revive", "revive-d2f7cdb2", "running", "86.38.238.110", "2026-02-19T12:33:52Z"),
            ]

    class _Client:
        instances = _Instances()

    async def fake_save_job(job_data: dict):
        saved_jobs.append(dict(job_data))

    monkeypatch.setattr(training, "_check_instance_via_api", lambda _instance_id: "discontinued")
    monkeypatch.setattr(training, "_get_verda_client", lambda: _Client())
    monkeypatch.setattr(training, "_select_preferred_ssh_private_key", lambda _path: "/tmp/key")
    monkeypatch.setattr(training, "_save_job", fake_save_job)

    job = {
        "job_id": "d2f7cdb2-0b87-438a-b195-5b5cc70f4a67",
        "instance_id": "old-instance",
        "ip": "86.38.238.114",
        "ssh_user": "root",
        "ssh_private_key": "/old/key",
    }

    updated = asyncio.run(training._refresh_job_ssh_target_if_needed(dict(job)))
    assert updated["instance_id"] == "new-revive"
    assert updated["ip"] == "86.38.238.110"
    assert updated["ssh_private_key"] == "/tmp/key"
    assert saved_jobs


def test_refresh_job_ssh_target_if_needed_keeps_current_when_not_stale(monkeypatch):
    async def fake_save_job(_job_data: dict):
        assert False, "should not persist when refresh is unnecessary"

    monkeypatch.setattr(training, "_check_instance_via_api", lambda _instance_id: "running")
    monkeypatch.setattr(training, "_get_verda_client", lambda: None)
    monkeypatch.setattr(training, "_save_job", fake_save_job)

    job = {
        "job_id": "d2f7cdb2-0b87-438a-b195-5b5cc70f4a67",
        "instance_id": "inst-running",
        "ip": "86.38.238.110",
        "ssh_user": "root",
        "ssh_private_key": "/tmp/key",
    }

    updated = asyncio.run(training._refresh_job_ssh_target_if_needed(dict(job)))
    assert updated["instance_id"] == "inst-running"
    assert updated["ip"] == "86.38.238.110"


def test_upsert_model_for_job_includes_checkpoint_size_and_latest_step(monkeypatch):
    captured: dict = {}

    class _Entry:
        latest_step = 1000
        size_mb = 18.5

    class _CheckpointMgr:
        @staticmethod
        def get_job_info(job_name: str):
            if job_name == "job-1":
                return _Entry()
            return None

    async def fake_upsert_with_owner(_table: str, _key: str, payload: dict):
        captured.update(payload)

    monkeypatch.setattr(training, "_get_checkpoint_index_manager", lambda: _CheckpointMgr())
    monkeypatch.setattr(training, "upsert_with_owner", fake_upsert_with_owner)

    job_data = {
        "job_id": "job-1",
        "dataset_id": "dataset-1",
        "policy_type": "pi0",
        "training_config": {"training": {"steps": 9999, "batch_size": 4}},
        "profile_instance_id": "profile-1",
        "profile_snapshot": {"name": "so101_dual_teleop"},
    }
    asyncio.run(training._upsert_model_for_job(job_data))

    assert captured["id"] == "job-1"
    assert captured["training_steps"] == 1000
    assert captured["size_bytes"] == int(18.5 * 1024 * 1024)


def test_upsert_model_for_job_skips_size_when_checkpoint_missing(monkeypatch):
    captured: dict = {}

    class _CheckpointMgr:
        @staticmethod
        def get_job_info(_job_name: str):
            return None

    async def fake_upsert_with_owner(_table: str, _key: str, payload: dict):
        captured.update(payload)

    monkeypatch.setattr(training, "_get_checkpoint_index_manager", lambda: _CheckpointMgr())
    monkeypatch.setattr(training, "upsert_with_owner", fake_upsert_with_owner)

    job_data = {
        "job_id": "job-2",
        "dataset_id": "dataset-2",
        "policy_type": "pi0",
        "training_config": {"training": {"steps": 3000, "batch_size": 4}},
        "profile_instance_id": "profile-1",
        "profile_snapshot": {"name": "so101_dual_teleop"},
    }
    asyncio.run(training._upsert_model_for_job(job_data))

    assert captured["id"] == "job-2"
    assert captured["training_steps"] == 3000
    assert "size_bytes" not in captured


def test_ensure_model_artifact_in_r2_from_checkpoint_skips_when_model_exists():
    class _CopyClient:
        calls: list[tuple[dict, str, str]] = []

        def copy(self, source: dict, bucket: str, key: str):
            self.calls.append((source, bucket, key))

    class _S3:
        def __init__(self):
            self.client = _CopyClient()

        @staticmethod
        def list_objects(path: str):
            if path == "s3://daihen/v2/models/job-1/":
                return [{"Key": "v2/models/job-1/config.json", "Size": 10}]
            return []

    class _Sync:
        bucket = "daihen"
        s3 = _S3()

        @staticmethod
        def _get_prefix() -> str:
            return "v2/"

    class _Mgr:
        sync = _Sync()

    path, size_bytes, copied = training._ensure_model_artifact_in_r2_from_checkpoint(
        _Mgr(),
        job_id="job-1",
        model_id="job-1",
        step=1000,
    )

    assert path == "s3://daihen/v2/models/job-1"
    assert size_bytes == 10
    assert copied is False
    assert _Mgr.sync.s3.client.calls == []


def test_ensure_model_artifact_in_r2_from_checkpoint_copies_from_checkpoint():
    class _CopyClient:
        def __init__(self):
            self.calls: list[tuple[dict, str, str]] = []

        def copy(self, source: dict, bucket: str, key: str):
            self.calls.append((source, bucket, key))

    class _S3:
        def __init__(self):
            self.client = _CopyClient()

        @staticmethod
        def list_objects(path: str):
            if path == "s3://daihen/v2/models/job-1/":
                return []
            if path == "s3://daihen/v2/checkpoints/job-1/step_001000/pretrained_model/":
                return [
                    {"Key": "v2/checkpoints/job-1/step_001000/pretrained_model/config.json", "Size": 3},
                    {"Key": "v2/checkpoints/job-1/step_001000/pretrained_model/model.safetensors", "Size": 7},
                ]
            return []

    class _Sync:
        bucket = "daihen"

        def __init__(self):
            self.s3 = _S3()

        @staticmethod
        def _get_prefix() -> str:
            return "v2/"

    class _Mgr:
        def __init__(self):
            self.sync = _Sync()

    mgr = _Mgr()
    path, size_bytes, copied = training._ensure_model_artifact_in_r2_from_checkpoint(
        mgr,
        job_id="job-1",
        model_id="job-1",
        step=1000,
    )

    assert path == "s3://daihen/v2/models/job-1"
    assert size_bytes == 10
    assert copied is True
    assert len(mgr.sync.s3.client.calls) == 2
    assert mgr.sync.s3.client.calls[0][2] == "v2/models/job-1/config.json"
    assert mgr.sync.s3.client.calls[1][2] == "v2/models/job-1/model.safetensors"
