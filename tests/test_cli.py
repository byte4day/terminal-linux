from __future__ import annotations

import json

import pytest

from terminal_linux import actions, agent_tools, cli, session
from terminal_linux.errors import SessionError


def run(capsys, *argv):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(list(argv))
    out = capsys.readouterr().out
    return exit_info.value.code, json.loads(out)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["action", "click", "10", "20"], ["action", "default", "click", "10", "20"]),
        (["action", "screenshot"], ["action", "default", "screenshot"]),
        (["action", "work", "click", "1", "2"], ["action", "work", "click", "1", "2"]),
        (["action", "status", "status"], ["action", "status", "status"]),  # session named 'status'
        (["open", "--", "firefox"], ["open", "default", "--", "firefox"]),
        (["open", "work", "--", "firefox"], ["open", "work", "--", "firefox"]),
        (["stop"], ["stop"]),
    ],
)
def test_normalize_argv(argv, expected):
    assert cli.normalize_argv(argv) == expected


def test_usage_errors_are_json(capsys):
    code, out = run(capsys, "action", "t", "explode")
    assert code == 2 and out["ok"] is False and out["code"] == "usage"
    code, out = run(capsys, "nonsense")
    assert code == 2 and out["code"] == "usage"


def test_not_running_is_json_with_code(capsys):
    for argv in (["action", "t", "windows"], ["action", "t", "click", "1", "2"], ["action", "click", "1", "2"]):
        code, out = run(capsys, *argv)
        assert code == 1 and out["code"] == "not_running", argv


def test_bad_coordinates_are_json_not_a_traceback(capsys, fake_state, monkeypatch):
    monkeypatch.setattr(session, "get_running", lambda name="default": fake_state)
    code, out = run(capsys, "action", "t", "click", "a", "b")
    assert code == 1 and out["code"] == "bad_args"
    code, out = run(capsys, "action", "t", "click", "5")
    assert code == 2 and out["code"] == "usage"


def test_out_of_bounds_reaches_the_caller(capsys, fake_state, monkeypatch):
    monkeypatch.setattr(session, "get_running", lambda name="default": fake_state)
    monkeypatch.setattr(actions, "_run_xdotool", lambda state, args: None)
    code, out = run(capsys, "action", "t", "click", "5000", "5000")
    assert code == 1 and out["code"] == "out_of_bounds"
    code, out = run(capsys, "action", "t", "click", "10", "10", "--double")
    assert code == 0 and out["clicks"] == 2


def test_wait_takes_seconds_positionally(capsys, monkeypatch):
    # Regression: `action NAME wait 3` waited 1 second.
    seen: list[float] = []
    monkeypatch.setattr(agent_tools, "wait", lambda name, seconds: seen.append(seconds) or {"ok": True})
    run(capsys, "action", "t", "wait", "3")
    run(capsys, "action", "t", "wait", "--seconds", "0.5")
    run(capsys, "action", "t", "wait")
    assert seen == [3.0, 0.5, 1.0]


def test_invalid_session_name_is_json(capsys):
    code, out = run(capsys, "status", "../../etc")
    assert code == 1 and out["code"] == "bad_args"


def test_unexpected_exception_is_json(capsys, monkeypatch):
    def boom(name):
        raise RuntimeError("kaput")

    monkeypatch.setattr(actions, "status_payload", boom)
    code, out = run(capsys, "status", "t")
    assert code == 1 and out["code"] == "internal_error" and "kaput" in out["error"]


def test_up_without_a_terminal_skips_the_viewer(capsys, fake_state, monkeypatch):
    # Regression: an agent running `terminal-linux up` crashed in termios after
    # the session had started.
    monkeypatch.setattr(cli, "start_session", lambda name, **kw: fake_state)
    monkeypatch.setattr(actions, "status_payload", lambda name: {"running": True})
    code, out = run(capsys, "up", "t")
    assert code == 0 and out["ok"] is True and out["reused"] is True and "note" in out


def test_up_size_flag(capsys, fake_state, monkeypatch):
    seen: dict = {}

    def fake_start(name, **kw):
        seen.update(kw)
        return fake_state

    monkeypatch.setattr(cli, "start_session", fake_start)
    monkeypatch.setattr(actions, "status_payload", lambda name: {"running": True})
    run(capsys, "up", "t", "--no-view", "--size", "1920x1080")
    assert (seen["width"], seen["height"]) == (1920, 1080)
    code, out = run(capsys, "up", "t", "--no-view", "--size", "huge")
    assert code == 1 and out["code"] == "bad_args"


def test_view_without_a_terminal_is_json(capsys):
    code, out = run(capsys, "view", "t")
    assert code == 1 and out["code"] == "no_tty"


def test_open_missing_binary_is_json(capsys, fake_state, monkeypatch):
    monkeypatch.setattr(session, "get_running", lambda name="default": fake_state)
    code, out = run(capsys, "open", "--", "definitely-not-a-real-binary-xyz")
    assert code == 1 and out["code"] == "not_found"


def test_batch_cli(capsys, monkeypatch, tmp_path):
    from terminal_linux import batch

    monkeypatch.setattr(batch, "run_batch", lambda name, steps: {"ok": True, "completed": len(steps), "name": name})
    code, out = run(capsys, "batch", "t", "--no-screenshot", "--steps", '[{"action":"key","key":"a"}]')
    assert code == 0 and out["completed"] == 1 and out["name"] == "t"
    steps = tmp_path / "steps.json"
    steps.write_text('[{"action":"key","key":"a"},{"action":"key","key":"b"}]')
    code, out = run(capsys, "batch", "--no-screenshot", "--file", str(steps))
    assert out["completed"] == 2 and out["name"] == "default"
    code, out = run(capsys, "batch", "t", "--steps", "not json")
    assert code == 1 and out["code"] == "bad_args"
    monkeypatch.setattr(batch, "run_batch", lambda name, steps: {"ok": False, "failed_step": 0})
    code, out = run(capsys, "batch", "t", "--no-screenshot", "--steps", "[{}]")
    assert code == 1


def test_wait_window_cli_exit_code(capsys, monkeypatch):
    seen: dict = {}

    def fake(name, **kw):
        seen.update(kw)
        return {"ok": True, "found": False, "timeout": True}

    monkeypatch.setattr(agent_tools, "wait_window", fake)
    code, out = run(capsys, "action", "t", "wait-window", "--class", "firefox", "--timeout", "2")
    assert code == 1 and out["timeout"] is True
    assert seen == {"title": None, "cls": "firefox", "timeout": 2.0, "gone": False}


def test_stop_reports_whether_anything_ran(capsys):
    code, out = run(capsys, "stop", "t")
    assert code == 0 and out["was_running"] is False


def test_session_error_code_passes_through(capsys, monkeypatch):
    def boom(name):
        raise SessionError("x", code="timeout")

    monkeypatch.setattr(agent_tools, "list_windows", boom)
    code, out = run(capsys, "action", "t", "windows")
    assert out["code"] == "timeout"
