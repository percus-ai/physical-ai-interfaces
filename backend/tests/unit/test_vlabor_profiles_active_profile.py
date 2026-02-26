from __future__ import annotations

import asyncio
import json

from interfaces_backend.services.vlabor_profiles import (
    VlaborProfileSpec,
    get_active_profile_spec,
    set_active_profile_spec,
)
import interfaces_backend.services.vlabor_profiles as vlabor_profiles


def _profile(name: str) -> VlaborProfileSpec:
    return VlaborProfileSpec(
        name=name,
        description=name,
        snapshot={"name": name, "profile": {"name": name}},
        source_path=f"/tmp/{name}.yaml",
        updated_at=None,
    )


def test_get_active_profile_reads_local_file(monkeypatch, tmp_path):
    active_file = tmp_path / "active_profile.json"
    active_file.write_text(
        json.dumps({"profile_name": "so101_single_teleop"}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("VLABOR_ACTIVE_PROFILE_FILE", str(active_file))
    monkeypatch.setattr(
        vlabor_profiles,
        "list_vlabor_profiles",
        lambda: [_profile("so101_dual_teleop"), _profile("so101_single_teleop")],
    )

    active = asyncio.run(get_active_profile_spec())
    assert active.name == "so101_single_teleop"


def test_get_active_profile_falls_back_to_default_when_local_missing(monkeypatch, tmp_path):
    active_file = tmp_path / "missing_active_profile.json"
    monkeypatch.setenv("VLABOR_ACTIVE_PROFILE_FILE", str(active_file))
    monkeypatch.setattr(
        vlabor_profiles,
        "list_vlabor_profiles",
        lambda: [_profile("so101_dual_teleop"), _profile("so101_single_teleop")],
    )

    active = asyncio.run(get_active_profile_spec())
    assert active.name == "so101_dual_teleop"


def test_set_active_profile_persists_local_file(monkeypatch, tmp_path):
    active_file = tmp_path / "nested" / "active_profile.json"
    monkeypatch.setenv("VLABOR_ACTIVE_PROFILE_FILE", str(active_file))
    monkeypatch.setattr(
        vlabor_profiles,
        "list_vlabor_profiles",
        lambda: [_profile("so101_dual_teleop"), _profile("so101_single_teleop")],
    )

    saved = asyncio.run(set_active_profile_spec("so101_single_teleop"))
    assert saved.name == "so101_single_teleop"

    payload = json.loads(active_file.read_text(encoding="utf-8"))
    assert payload["profile_name"] == "so101_single_teleop"

    active = asyncio.run(get_active_profile_spec())
    assert active.name == "so101_single_teleop"
