"""CLI session storage for Supabase tokens."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from percus_ai.storage import get_cache_dir


def _session_dir() -> Path:
    return get_cache_dir() / "cli"


def session_path() -> Path:
    return _session_dir() / "session.json"


def load_session() -> Optional[Dict[str, Any]]:
    path = session_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def save_session(session: Dict[str, Any]) -> None:
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session, ensure_ascii=True), encoding="utf-8")


def clear_session() -> None:
    path = session_path()
    if path.exists():
        path.unlink()
