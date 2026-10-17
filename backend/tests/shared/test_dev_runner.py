"""Launcher ownership regression tests; no live providers/process kills."""

import json
import os
from pathlib import Path
import subprocess

import pytest

import dev_runner as runner


@pytest.fixture
def control(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "CONTROL_DIR", tmp_path)
    return tmp_path


def write_state(control, **changes):
    state = {
        "kind": runner.STATE_KIND,
        "workspace": runner.ROOT_DIR,
        "runner_pid": 12345,
        "token": "a" * 64,
    }
    state.update(changes)
    (control / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return state


def test_only_start_and_stop_wrappers_share_one_launcher():
    root = Path(runner.ROOT_DIR)
    assert {path.name for path in root.glob("*.bat")} == {"start.bat", "stop.bat"}
    start = (root / "start.bat").read_text()
    stop = (root / "stop.bat").read_text()
    assert 'dev_runner.py" start --open-browser' in start
    assert 'dev_runner.py" stop' in stop
    for source in (start, stop):
        assert "monitor.py" not in source
        for broad_operation in ("Stop-Process", "taskkill", "netstat", "rmdir", "Get-CimInstance"):
            assert broad_operation not in source


@pytest.mark.parametrize("changes", [
    {"workspace": "C:/another/project"}, {"kind": "another-app"},
    {"runner_pid": -1}, {"runner_pid": True}, {"token": "../../unsafe"},
])
def test_foreign_or_invalid_registry_refuses_stop(control, monkeypatch, changes):
    write_state(control, **changes)
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("stop must never kill"))
    with pytest.raises(ValueError):
        runner.stop(timeout=0)
    assert not (control / "stop.json").exists()


def test_malformed_registry_fails_closed(control):
    (control / "state.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError):
        runner._load_state()


def test_second_launcher_does_not_start_duplicate(control, monkeypatch):
    original = write_state(control)
    monkeypatch.setattr(runner, "_pid_is_alive", lambda pid: True)
    monkeypatch.setattr(runner, "_existing_backend_is_ours", lambda: True)
    monkeypatch.setattr(runner, "_existing_frontend_is_ours", lambda: True)
    monkeypatch.setattr(runner, "_run_servers", lambda *a, **k: pytest.fail("duplicate start"))
    assert runner.start() == 0
    assert runner._load_state() == original


def test_second_click_opens_browser_without_duplicate_or_state_change(control, monkeypatch):
    original = write_state(control)
    monkeypatch.setattr(runner, "_pid_is_alive", lambda pid: True)
    monkeypatch.setattr(runner, "_existing_backend_is_ours", lambda: True)
    monkeypatch.setattr(runner, "_existing_frontend_is_ours", lambda: True)
    monkeypatch.setattr(runner, "_run_servers", lambda *a, **k: pytest.fail("duplicate server"))
    opened = []
    monkeypatch.setattr(runner.webbrowser, "open", lambda url: opened.append(url) or True)
    assert runner.start(open_browser=True) == 0
    assert opened == [runner.FRONTEND_URL]
    assert runner._load_state() == original


def test_repeated_click_waits_until_original_server_is_ready(control, monkeypatch):
    write_state(control)
    monkeypatch.setattr(runner, "_pid_is_alive", lambda pid: True)
    health = iter((False, True))
    monkeypatch.setattr(runner, "_existing_backend_is_ours", lambda: next(health))
    monkeypatch.setattr(runner, "_existing_frontend_is_ours", lambda: True)
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    opened = []
    monkeypatch.setattr(runner, "_open_browser", lambda: opened.append(True))
    assert runner.start(open_browser=True) == 0
    assert opened == [True]


def test_repeated_click_does_not_open_browser_when_launcher_exits(control, monkeypatch):
    write_state(control)
    alive = iter((True, False))
    monkeypatch.setattr(runner, "_pid_is_alive", lambda pid: next(alive))
    monkeypatch.setattr(runner, "_open_browser", lambda: pytest.fail("server not ready"))
    assert runner.start(open_browser=True) == 1


def test_repeated_click_times_out_without_false_success(control, monkeypatch):
    write_state(control)
    monkeypatch.setattr(runner, "_pid_is_alive", lambda pid: True)
    monkeypatch.setattr(runner, "STARTUP_TIMEOUT_SEC", 0)
    monkeypatch.setattr(runner, "_open_browser", lambda: pytest.fail("server not ready"))
    assert runner.start(open_browser=True) == 1


@pytest.mark.parametrize("failure", [False, OSError("No browser association")])
def test_browser_failure_is_not_a_server_failure(monkeypatch, capsys, failure):
    def browser(_url):
        if isinstance(failure, Exception):
            raise failure
        return failure
    monkeypatch.setattr(runner.webbrowser, "open", browser)
    runner._open_browser()
    assert runner.FRONTEND_URL in capsys.readouterr().out


def test_windows_launcher_keeps_errors_visible_without_duplicate_scripts():
    source = (Path(runner.ROOT_DIR) / "start.bat").read_text()
    assert 'set "EXIT_CODE=%errorlevel%"' in source
    assert 'if not "%COC_NO_PAUSE%"=="1" pause' in source
    assert 'exit /b %EXIT_CODE%' in source


@pytest.mark.skipif(os.name != "nt", reason="Windows batch launcher")
def test_batch_missing_python_returns_visible_error_without_hanging(tmp_path):
    root = Path(runner.ROOT_DIR)
    if any((root / prefix / "Scripts/python.exe").exists() for prefix in (".venv", "backend/.venv")):
        pytest.skip("workspace has its own Python; missing PATH Python is irrelevant")
    env = {**os.environ, "PATH": str(Path(os.environ["SystemRoot"]) / "System32"), "COC_NO_PAUSE": "1"}
    result = subprocess.run(
        [str(Path(os.environ["SystemRoot"]) / "System32/cmd.exe"), "/d", "/c", str(root / "start.bat")],
        cwd=tmp_path, env=env, capture_output=True, encoding="utf-8", timeout=15,
    )
    assert result.returncode == 1
    assert "Khong tim thay Python" in result.stdout
    assert "Launcher khong chay thanh cong" in result.stdout


@pytest.mark.skipif(os.name != "nt", reason="Windows batch launcher")
def test_batch_preserves_cli_failure_exit_code_and_log(tmp_path):
    env = {**os.environ, "COC_NO_PAUSE": "1"}
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(Path(runner.ROOT_DIR) / "start.bat"), "--not-a-valid-flag"],
        cwd=tmp_path, env=env, capture_output=True, encoding="utf-8", timeout=15,
    )
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
    assert "Launcher khong chay thanh cong" in result.stdout


def test_dead_launcher_metadata_archived_not_used_to_kill(control, monkeypatch):
    old = write_state(control)
    monkeypatch.setattr(runner, "_pid_is_alive", lambda pid: False)
    new = runner._claim_runner()
    assert new["token"] != old["token"]
    assert json.loads((control / f"stale-{old['token']}.json").read_text()) == old


def test_stop_requests_owner_without_killing(control, monkeypatch):
    state = write_state(control)
    monkeypatch.setattr(runner, "_pid_is_alive", lambda pid: True)
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("stop must not kill"))
    # No acknowledgement yet; must not claim the service already stopped.
    assert runner.stop(timeout=0) == 1
    assert runner._stop_requested(state)
    assert runner._load_state() == state


def test_stop_waits_for_owner_acknowledgement(control, monkeypatch):
    state = write_state(control)
    reads = iter((state, None))
    monkeypatch.setattr(runner, "_load_state", lambda: next(reads))
    monkeypatch.setattr(runner, "_pid_is_alive", lambda pid: True)
    assert runner.stop(timeout=1) == 0
    assert runner._stop_requested(state)


def test_unmanaged_or_dead_runner_is_not_killed(control, monkeypatch):
    assert runner.stop(timeout=0) == 0
    write_state(control)
    monkeypatch.setattr(runner, "_pid_is_alive", lambda pid: False)
    assert runner.stop(timeout=0) == 0
    assert not (control / "stop.json").exists()


def test_stale_stop_token_ignored(control):
    state = write_state(control)
    (control / "stop.json").write_text(json.dumps({"workspace": runner.ROOT_DIR, "token": "b" * 64}))
    runner._checkpoint(state)
    (control / "stop.json").write_text(json.dumps({"workspace": runner.ROOT_DIR, "token": state["token"]}))
    with pytest.raises(runner.StopRequested):
        runner._checkpoint(state)


def test_release_only_own_metadata_not_session_cache(control):
    state = write_state(control)
    cache = control / "user-session.json"
    cache.write_text("keep this context")
    (control / "stop.json").write_text(json.dumps({"workspace": runner.ROOT_DIR, "token": state["token"]}))
    runner._release_runner(state)
    assert not (control / "state.json").exists()
    assert not (control / "stop.json").exists()
    assert cache.read_text() == "keep this context"


def test_release_cannot_remove_newer_owner(control):
    old = write_state(control)
    new = write_state(control, token="b" * 64)
    runner._release_runner(old)
    assert runner._load_state() == new


def test_missing_dependencies_releases_registry(control, monkeypatch):
    monkeypatch.setattr(runner, "_check_prerequisites", lambda: False)
    assert runner.start() == 1
    assert runner._load_state() is None


def test_busy_ports_not_killed_or_reused_by_default(control, monkeypatch):
    monkeypatch.setattr(runner, "_check_prerequisites", lambda: True)
    monkeypatch.setattr(runner, "_port_is_open", lambda port: True)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: pytest.fail("occupied ports"))
    assert runner.start() == 1
    assert runner._load_state() is None


def test_explicitly_reused_servers_never_stopped(control, monkeypatch):
    monkeypatch.setattr(runner, "_check_prerequisites", lambda: True)
    monkeypatch.setattr(runner, "_port_is_open", lambda port: True)
    monkeypatch.setattr(runner, "_existing_backend_is_ours", lambda: True)
    monkeypatch.setattr(runner, "_existing_frontend_is_ours", lambda: True)
    def stop_during_startup(*args):
        raise runner.StopRequested
    monkeypatch.setattr(runner, "_wait_until_ready", stop_during_startup)
    stopped = []
    monkeypatch.setattr(runner, "_stop_process", stopped.append)
    assert runner.start(reuse_existing=True) == 0
    assert stopped == [None, None]


def test_partial_spawn_failure_cleans_only_owned_child(control, monkeypatch):
    monkeypatch.setattr(runner, "_check_prerequisites", lambda: True)
    monkeypatch.setattr(runner, "_port_is_open", lambda port: False)
    child = object()
    calls = []
    def spawn(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            return child
        raise OSError("frontend launch failed")
    monkeypatch.setattr(runner.subprocess, "Popen", spawn)
    stopped = []
    monkeypatch.setattr(runner, "_stop_process", stopped.append)
    with pytest.raises(OSError):
        runner.start()
    assert stopped == [None, child]
    assert runner._load_state() is None


def test_stop_during_readiness_does_not_wait_for_timeout(control):
    state = write_state(control)
    (control / "stop.json").write_text(json.dumps({"workspace": runner.ROOT_DIR, "token": state["token"]}))
    with pytest.raises(runner.StopRequested):
        runner._wait_until_ready(None, None, state)


def test_commands_bind_localhost_and_use_current_paths():
    backend, frontend = runner._backend_command(), runner._frontend_command()
    assert "--reload" in backend and "127.0.0.1" in backend
    assert "127.0.0.1" in frontend and "3000" in frontend
    assert Path(frontend[1]).is_relative_to(Path(runner.ROOT_DIR))
    assert "npm.cmd" not in frontend
