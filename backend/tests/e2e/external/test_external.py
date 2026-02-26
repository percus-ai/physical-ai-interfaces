from importlib.util import find_spec
from pathlib import Path
import os

import pytest


def _find_repo_root(start: Path) -> Path:
    for parent in [start] + list(start.parents):
        if (parent / "AGENTS.md").exists():
            return parent
    return start


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            values[key] = value
    return values


@pytest.fixture(autouse=True)
def _load_repo_env(monkeypatch):
    repo_root = _find_repo_root(Path(__file__).resolve())
    env_path = repo_root / "data" / ".env"
    for key, value in _load_env_file(env_path).items():
        if value and key not in os.environ:
            monkeypatch.setenv(key, value)


def _get_env(key: str) -> str | None:
    import os

    return os.environ.get(key)


@pytest.mark.external
def test_huggingface_search(client):
    if find_spec("huggingface_hub") is None:
        pytest.skip("huggingface_hub not installed")

    resp = client.get("/api/storage/search/datasets", params={"query": "lerobot", "limit": 1})
    assert resp.status_code == 200
    payload = resp.json()
    assert "results" in payload


@pytest.mark.external
def test_verda_storage_list(client):
    if find_spec("verda") is None:
        pytest.skip("verda not installed")
    if not (_get_env("DATACRUNCH_CLIENT_ID") and _get_env("DATACRUNCH_CLIENT_SECRET")):
        pytest.skip("Verda credentials not set")

    resp = client.get("/api/training/verda/storage")
    assert resp.status_code == 200
    payload = resp.json()
    assert "items" in payload
