from __future__ import annotations

import subprocess

import pytest
from PIL import Image

from terminal_linux import agent_tools
from terminal_linux.errors import SessionError

WMCTRL = """\
0x00400004  0 320  180  640  440  Alacritty.Alacritty   arch agent-terminal
0x00e00016  0 0    0    1280 800  Navigator.firefox     arch Welcome to Firefox — Mozilla Firefox
0x01000003  0 10   20   300  200  thunar.Thunar         arch
garbage line
"""


def test_parse_wmctrl_geometry_and_titles():
    rows = agent_tools.parse_wmctrl(WMCTRL)
    assert [r["id"] for r in rows] == ["0x00400004", "0x00e00016", "0x01000003"]
    term = rows[0]
    assert (term["x"], term["y"], term["width"], term["height"]) == (320, 180, 640, 440)
    assert term["center"] == [640, 400]
    assert term["class"] == "Alacritty.Alacritty"
    assert rows[1]["title"] == "Welcome to Firefox — Mozilla Firefox"
    assert rows[2]["title"] == ""  # a window with no title is still listed


def test_find_window_by_title_and_class():
    rows = agent_tools.parse_wmctrl(WMCTRL)
    assert agent_tools.find_window(rows, title="FIREFOX")["id"] == "0x00e00016"
    assert agent_tools.find_window(rows, cls="alacritty")["id"] == "0x00400004"
    assert agent_tools.find_window(rows, title="nope") is None
    assert agent_tools.find_window(rows) is None


def test_same_window_hex_vs_decimal():
    assert agent_tools._same_window("0x00400004", "4194308")
    assert not agent_tools._same_window("0x00400004", "5")
    assert not agent_tools._same_window("junk", "5")


def test_terminal_is_matched_by_class_not_title(monkeypatch):
    # A browser tab titled "kitty docs" must not receive typed shell commands.
    rows = [
        {"id": "0x1", "class": "Navigator.firefox", "title": "kitty terminal docs"},
        {"id": "0x2", "class": "kitty.kitty", "title": "~"},
    ]
    focused: list[str] = []
    monkeypatch.setattr(agent_tools, "list_windows", lambda name: rows)
    monkeypatch.setattr(agent_tools, "focus_window", lambda name, window_id=None, **kw: focused.append(window_id))
    assert agent_tools._focus_terminal("t") is True
    assert focused == ["0x2"]
    rows.pop()
    assert agent_tools._focus_terminal("t") is False


def _frames(*colors):
    it = iter(colors)
    last = [None]

    def grab():
        try:
            last[0] = Image.new("RGB", (40, 40), next(it))
        except StopIteration:
            pass
        return last[0]

    return grab


def test_wait_stable_settles():
    grab = _frames((1, 1, 1), (2, 2, 2), (3, 3, 3))  # then (3,3,3) forever
    out = agent_tools.wait_stable("t", timeout=5, settle=0.05, interval=0.01, grab=grab)
    assert out["stable"] is True and out["checks"] >= 4


def test_wait_stable_times_out_on_a_changing_screen():
    n = [0]

    def grab():
        n[0] += 1
        return Image.new("RGB", (40, 40), (n[0] % 255, 0, 0))

    out = agent_tools.wait_stable("t", timeout=0.5, settle=0.2, interval=0.01, grab=grab)
    assert out["stable"] is False and out["timeout"] is True


def test_wait_stable_ignores_a_blinking_cursor():
    n = [0]

    def grab():
        n[0] += 1
        im = Image.new("RGB", (200, 200), (0, 0, 0))
        if n[0] % 2:  # 4 of 40000 pixels flip every frame
            for x in range(4):
                im.putpixel((x, 0), (255, 255, 255))
        return im

    out = agent_tools.wait_stable("t", timeout=2, settle=0.05, interval=0.01, grab=grab)
    assert out["stable"] is True


def test_wait_window_appears_then_reports_geometry():
    calls = [0]

    def lister():
        calls[0] += 1
        return agent_tools.parse_wmctrl(WMCTRL) if calls[0] >= 3 else []

    out = agent_tools.wait_window("t", title="firefox", timeout=5, interval=0.01, lister=lister)
    assert out["found"] is True and out["window"]["width"] == 1280 and calls[0] == 3


def test_wait_window_timeout_and_gone():
    out = agent_tools.wait_window("t", cls="gimp", timeout=0.05, interval=0.01, lister=lambda: [])
    assert out == {"ok": True, "found": False, "timeout": True, "waited": out["waited"]}
    out = agent_tools.wait_window("t", cls="gimp", gone=True, timeout=1, interval=0.01, lister=lambda: [])
    assert out["gone"] is True
    rows = agent_tools.parse_wmctrl(WMCTRL)
    out = agent_tools.wait_window("t", cls="firefox", gone=True, timeout=0.05, interval=0.01, lister=lambda: rows)
    assert out["gone"] is False and out["timeout"] is True


def test_wait_window_needs_a_target():
    with pytest.raises(SessionError) as err:
        agent_tools.wait_window("t", lister=lambda: [])
    assert err.value.code == "bad_args"


def test_clipboard_set_does_not_leak_stdout_to_xclip(fake_state, monkeypatch):
    # xclip stays in the background holding the selection. If it inherits our
    # stdout, `terminal-linux action clipboard-set x | cat` never finishes.
    seen: dict = {}

    def fake_run(cmd, **kw):
        seen.update(kw, cmd=cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(agent_tools, "get_running", lambda name: fake_state)
    monkeypatch.setattr(agent_tools.shutil, "which", lambda name: "/usr/bin/xclip")
    monkeypatch.setattr(agent_tools.subprocess, "run", fake_run)
    assert agent_tools.clipboard_set("t", "héllo") == {"ok": True, "chars": 5}
    assert seen["stdout"] is subprocess.DEVNULL and seen["stderr"] is subprocess.DEVNULL
    assert seen["input"] == "héllo" and seen["timeout"]


def test_helper_timeout_becomes_session_error(fake_state, monkeypatch):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr(agent_tools.subprocess, "run", boom)
    with pytest.raises(SessionError) as err:
        agent_tools._run(fake_state, ["wmctrl", "-l"])
    assert err.value.code == "timeout"


def test_open_url_rejects_option_like_and_empty(fake_state, monkeypatch):
    monkeypatch.setattr(agent_tools, "get_running", lambda name: fake_state)
    for bad in ("", "  ", "--private-window"):
        with pytest.raises(SessionError):
            agent_tools.open_url("t", bad)
