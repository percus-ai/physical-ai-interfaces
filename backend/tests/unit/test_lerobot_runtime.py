from __future__ import annotations

import interfaces_backend.services.lerobot_runtime as lerobot_runtime


def test_start_lerobot_starts_all_compose_services(monkeypatch, tmp_path):
    compose_file = tmp_path / "docker-compose.ros2.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    called: dict[str, object] = {}

    monkeypatch.setattr(lerobot_runtime, "get_lerobot_compose_file", lambda: compose_file)
    monkeypatch.setattr(
        lerobot_runtime,
        "build_compose_command",
        lambda _compose_file: ["docker", "compose", "-f", str(compose_file)],
    )

    def _fake_run(cmd, **kwargs):
        called["cmd"] = cmd
        called["capture_output"] = kwargs.get("capture_output")
        called["text"] = kwargs.get("text")
        return lerobot_runtime.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(lerobot_runtime.subprocess, "run", _fake_run)

    result = lerobot_runtime.start_lerobot(strict=True)

    assert result.returncode == 0
    assert called["cmd"] == ["docker", "compose", "-f", str(compose_file), "up", "-d", "--build"]
    assert called["capture_output"] is True
    assert called["text"] is True
