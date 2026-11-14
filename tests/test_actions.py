from __future__ import annotations

import pytest

from terminal_linux import actions
from terminal_linux.errors import SessionError


@pytest.fixture
def xdo(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(actions, "_run_xdotool", lambda state, args: calls.append(args))
    return calls


@pytest.mark.parametrize("point", [(1280, 10), (10, 800), (-1, 5), (5000, 5000)])
def test_click_outside_screen_is_refused_not_clamped(fake_state, xdo, point):
    with pytest.raises(SessionError) as err:
        actions.click(fake_state, *point)
    assert err.value.code == "out_of_bounds"
    assert xdo == []  # nothing was sent to the guest


def test_click_edges_are_inside(fake_state, xdo):
    actions.click(fake_state, 0, 0)
    actions.click(fake_state, 1279, 799)
    assert len(xdo) == 4


def test_double_click_is_one_xdotool_call(fake_state, xdo):
    actions.click(fake_state, 10, 20, clicks=2, button="right")
    assert xdo == [
        ["mousemove", "--sync", "10", "20"],
        ["click", "--repeat", "2", "--delay", "80", "3"],
    ]


def test_bad_button_and_clicks(fake_state, xdo):
    for kwargs in ({"button": "side"}, {"clicks": 0}, {"clicks": 4}):
        with pytest.raises(SessionError) as err:
            actions.click(fake_state, 1, 1, **kwargs)
        assert err.value.code == "bad_args"


def test_drag_releases_button_when_a_move_fails(fake_state, monkeypatch):
    calls: list[list[str]] = []

    def run(state, args):
        calls.append(args)
        if args[0] == "mousemove" and len(calls) > 2:
            raise SessionError("X went away")

    monkeypatch.setattr(actions, "_run_xdotool", run)
    with pytest.raises(SessionError):
        actions.drag(fake_state, 10, 10, 200, 200)
    assert calls[-1] == ["mouseup", "1"]


def test_drag_checks_both_ends(fake_state, xdo):
    with pytest.raises(SessionError):
        actions.drag(fake_state, 10, 10, 9999, 10)
    assert xdo == []


def test_scroll_direction_and_notches(fake_state, xdo):
    actions.scroll(fake_state, dy=-300, x=5, y=6)
    assert xdo == [
        ["mousemove", "--sync", "5", "6"],
        ["click", "--repeat", "7", "--delay", "8", "5"],  # negative dy → button 5 (down)
    ]
    xdo.clear()
    actions.scroll(fake_state, dy=40)
    assert xdo == [["click", "--repeat", "1", "--delay", "8", "4"]]


def test_scroll_needs_both_coordinates(fake_state, xdo):
    with pytest.raises(SessionError) as err:
        actions.scroll(fake_state, dy=-40, x=5)
    assert err.value.code == "bad_args"


def test_press_key_sends_normalised_chords(fake_state, xdo):
    actions.press_key(fake_state, "cmd+a ctrl++")
    assert xdo == [["key", "--clearmodifiers", "--delay", "40", "ctrl+a", "ctrl+plus"]]


def test_status_of_stale_session_is_not_ready(fake_state):
    from terminal_linux import state

    state.save_state(fake_state)  # pids alive but not ours
    payload = actions.status_payload("t")
    assert payload["running"] is False and payload["ready"] is False
    assert payload["version"]
