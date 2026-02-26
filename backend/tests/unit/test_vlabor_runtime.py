import interfaces_backend.services.vlabor_runtime as vlabor_runtime


def test_start_vlabor_invokes_up_script_with_profile(tmp_path, monkeypatch):
    repo_root = tmp_path
    script = repo_root / "docker" / "vlabor" / "up"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)

    calls: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["cwd"] = kwargs.get("cwd")
        return vlabor_runtime.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(vlabor_runtime, "get_project_root", lambda: repo_root)
    monkeypatch.setattr(vlabor_runtime.subprocess, "run", fake_run)

    vlabor_runtime.start_vlabor(profile="so101_dual_teleop", domain_id=3)

    assert calls["cmd"] == [str(script), "so101_dual_teleop", "--domain-id", "3"]
    assert calls["cwd"] == repo_root


def test_stop_vlabor_on_backend_startup_skips_without_docker(monkeypatch):
    called = {"stop": False}

    monkeypatch.setattr(vlabor_runtime.shutil, "which", lambda _name: None)

    def fake_stop_vlabor(*, strict: bool = True):
        called["stop"] = True
        return vlabor_runtime.subprocess.CompletedProcess(["down"], 0, "", "")

    monkeypatch.setattr(vlabor_runtime, "stop_vlabor", fake_stop_vlabor)
    vlabor_runtime.stop_vlabor_on_backend_startup()
    assert called["stop"] is False
