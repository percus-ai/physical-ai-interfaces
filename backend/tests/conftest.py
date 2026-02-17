import os
import sys
import hashlib
import logging
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _find_repo_root(start: Path) -> Path:
    for parent in [start] + list(start.parents):
        if (parent / "AGENTS.md").exists():
            return parent
    return start


REPO_ROOT = _find_repo_root(Path(__file__).resolve())


def _ensure_sys_path(path: Path) -> None:
    resolved = str(path)
    if resolved not in sys.path:
        sys.path.insert(0, resolved)


_ensure_sys_path(REPO_ROOT / "interfaces" / "backend" / "src")
_ensure_sys_path(REPO_ROOT / "features")

LOGS_DIR = REPO_ROOT / "interfaces" / "backend" / "tests" / "logs"


@pytest.fixture(autouse=True)
def _per_test_log(request):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    raw_name = request.node.nodeid
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw_name)
    if len(safe_name) > 120:
        digest = hashlib.sha1(raw_name.encode("utf-8")).hexdigest()[:8]
        safe_name = f"{safe_name[:80]}_{digest}"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"{timestamp}__{safe_name}.log"

    logger = logging.getLogger()
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    try:
        yield
    finally:
        logger.removeHandler(handler)
        handler.close()
        rep_call = getattr(request.node, "rep_call", None)
        rep_setup = getattr(request.node, "rep_setup", None)
        rep_teardown = getattr(request.node, "rep_teardown", None)
        failed = any(
            rep is not None and rep.failed for rep in (rep_setup, rep_call, rep_teardown)
        )
        if not failed and log_path.exists():
            log_path.unlink()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture(scope="session", autouse=True)
def _isolate_env(tmp_path_factory):
    workspace = tmp_path_factory.mktemp("workspace")
    home_dir = tmp_path_factory.mktemp("home")

    prev_cwd = Path.cwd()
    prev_env = os.environ.copy()

    os.chdir(workspace)
    os.environ["HOME"] = str(home_dir)
    os.environ["PHYSICAL_AI_DATA_DIR"] = str(workspace)
    os.environ["PHYSICAL_AI_PROJECT_ROOT"] = str(REPO_ROOT)

    yield

    os.chdir(prev_cwd)
    os.environ.clear()
    os.environ.update(prev_env)


def _reset_backend_state() -> None:
    import interfaces_backend.api.calibration as calibration
    import interfaces_backend.api.recording as recording
    import interfaces_backend.services.inference_runtime as inference_runtime
    import interfaces_backend.services.startup_operations as startup_operations

    calibration._sessions.clear()
    calibration._motor_buses.clear()

    if hasattr(recording, "_sync_service"):
        recording._sync_service = None

    if inference_runtime._runtime_manager is not None:
        inference_runtime._runtime_manager.shutdown()
        inference_runtime._runtime_manager = None

    startup_operations.reset_startup_operations_service()



@pytest.fixture(autouse=True)
def _clean_storage():
    import shutil

    data_dir = Path(os.environ["PHYSICAL_AI_DATA_DIR"])
    for child in data_dir.iterdir():
        if child.name == "data":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    calib_dir = Path(os.environ["HOME"]) / ".cache" / "percus_ai" / "calibration"
    if calib_dir.exists():
        shutil.rmtree(calib_dir)

    yield


@pytest.fixture
def client():
    from interfaces_backend.main import app

    _reset_backend_state()

    with TestClient(app) as test_client:
        yield test_client
