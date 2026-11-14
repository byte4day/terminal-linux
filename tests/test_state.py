from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from terminal_linux import paths, session, state
from terminal_linux.errors import SessionError


def test_pid_alive_treats_zombie_as_dead():
    # An exited child that was never reaped still answers kill(pid, 0).
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        deadline = time.time() + 5
        while time.time() < deadline and state.pid_alive(child.pid):
            time.sleep(0.02)
        assert not state.pid_alive(child.pid)
    finally:
        child.wait()


def test_recycled_pid_is_not_a_running_session(fake_state):
    # xvfb_pid points at this test process: alive, but not Xvfb on :97.
    assert state.pid_alive(fake_state.xvfb_pid)
    assert not state.is_running(fake_state)


def test_is_xvfb_for_matches_display(monkeypatch):
    monkeypatch.setattr(state, "pid_alive", lambda pid: True)
    monkeypatch.setattr(state, "pid_cmdline", lambda pid: ["/usr/bin/Xvfb", ":97", "-screen", "0", "1x1x24"])
    assert state.is_xvfb_for(1234, 97)
    assert not state.is_xvfb_for(1234, 9)  # ':9' must not match ':97'
    monkeypatch.setattr(state, "pid_cmdline", lambda pid: [])
    assert not state.is_xvfb_for(1234, 97)


def test_state_roundtrip_and_old_files_load(fake_state):
    fake_state.app_pids = [11, 12]
    state.save_state(fake_state)
    assert state.load_state("t") == fake_state
    # A session.json written before app_pids existed still loads.
    path = state.state_path("t")
    data = json.loads(path.read_text())
    del data["app_pids"]
    path.write_text(json.dumps(data))
    assert state.load_state("t").app_pids == []
    assert not list(path.parent.glob("*.tmp"))


def test_load_state_survives_garbage(fake_state):
    state.save_state(fake_state)
    state.state_path("t").write_text("{ half a fi")
    assert state.load_state("t") is None


@pytest.mark.parametrize("name", ["../x", "a/b", "", ".hidden", "x" * 65, "a b"])
def test_session_name_cannot_escape_data_dir(name):
    with pytest.raises(SessionError) as err:
        paths.machine_dir(name)
    assert err.value.code == "bad_args"


def test_reading_an_unknown_session_creates_nothing(isolated_home):
    assert state.load_state("typo") is None
    from terminal_linux import actions

    assert actions.status_payload("typo")["running"] is False
    assert not (isolated_home / "machines" / "typo").exists()


def test_stopped_sessions_are_listed_as_stopped(isolated_home, fake_state):
    paths.machine_dir("old")  # logs left behind by a stopped session
    state.save_state(fake_state)  # stale record: pid is not Xvfb
    rows = {row["name"]: row["status"] for row in session.list_sessions()}
    assert rows == {"old": "stopped", "t": "stopped"}


def test_stop_never_signals_a_recycled_pid(fake_state, monkeypatch):
    fake_state.app_pids = [os.getpid()]
    state.save_state(fake_state)
    signalled: list[int] = []
    monkeypatch.setattr(session, "terminate_pid", lambda pid, **kw: signalled.append(pid))
    assert session.stop_session("t", force=True) is True
    assert signalled == []
    assert state.load_state("t") is None
    assert session.stop_session("t") is False


def test_stale_x_lock_does_not_block_a_display(tmp_path):
    (tmp_path / ".X11-unix").mkdir()
    lock = tmp_path / ".X90-lock"
    lock.write_text(f"{os.getpid():>10}\n")
    assert not session.display_free(90, tmp=tmp_path)  # live owner
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    lock.write_text(f"{dead.pid:>10}\n")
    assert session.display_free(90, tmp=tmp_path)  # owner is gone
    assert session.display_free(91, tmp=tmp_path)
    (tmp_path / ".X11-unix" / "X91").touch()
    assert not session.display_free(91, tmp=tmp_path)


def test_size_validation():
    assert session.parse_size("1920x1080") == (1920, 1080)
    for bad in ("big", "0x0", "100x100", "99999x99999", "-5x800"):
        with pytest.raises(SessionError):
            session.parse_size(bad)


def test_wallpaper_never_uses_blocking_x_root(monkeypatch, tmp_path):
    # `magick FILE x:root` opens a viewer and never returns; it cost 5 s per start.
    calls: list[list[str]] = []

    def fake_run(cmd, **kw):
        calls.append([str(c) for c in cmd])
        assert kw.get("timeout"), "every wallpaper step needs a timeout"
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(session.subprocess, "run", fake_run)
    monkeypatch.setattr(session.shutil, "which", lambda name: f"/usr/bin/{name}")
    session.paint_desktop({}, 640, 480, "t")
    assert not any("x:root" in arg for call in calls for arg in call)
    assert any(call[:3] == ["/usr/bin/display", "-window", "root"] for call in calls)


def test_open_app_missing_binary_is_a_json_error(fake_state, monkeypatch):
    monkeypatch.setattr(session, "get_running", lambda name: fake_state)
    with pytest.raises(SessionError) as err:
        session.open_app("t", ["definitely-not-a-real-binary-xyz"])
    assert err.value.code == "not_found"


def test_xvfb_that_exits_is_reported_as_display_taken():
    proc = subprocess.Popen([sys.executable, "-c", "raise SystemExit(1)"])
    proc.wait()
    with pytest.raises(SessionError) as err:
        session.wait_for_display(98, timeout=1.0, proc=proc)
    assert err.value.code == "display_taken"
