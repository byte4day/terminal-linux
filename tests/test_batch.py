from __future__ import annotations

import pytest

from terminal_linux import batch
from terminal_linux.errors import SessionError


def _handlers(log, fail_on=None):
    def make(action):
        def handler(name, step):
            if action == fail_on:
                raise SessionError("nope", code="out_of_bounds")
            log.append((action, {k: v for k, v in step.items() if k != "action"}))
            return {"ok": True, "echo": action}

        return handler

    return {a: make(a) for a in ("click", "type", "key", "wait_stable")}


def test_batch_runs_in_order():
    log: list = []
    steps = [
        {"action": "click", "x": 1, "y": 2},
        {"action": "type", "text": "hi"},
        {"action": "wait-stable"},  # '-' and '_' are interchangeable
    ]
    out = batch.run_batch("t", steps, handlers=_handlers(log))
    assert out["ok"] is True and out["completed"] == 3
    assert [a for a, _ in log] == ["click", "type", "wait_stable"]
    assert out["results"][0] == {"step": 0, "action": "click", "echo": "click", "ok": True}


def test_batch_stops_at_first_failure():
    log: list = []
    steps = [{"action": "click"}, {"action": "type"}, {"action": "key"}]
    out = batch.run_batch("t", steps, handlers=_handlers(log, fail_on="type"))
    assert out["ok"] is False
    assert out["failed_step"] == 1 and out["completed"] == 1 and out["code"] == "out_of_bounds"
    assert [a for a, _ in log] == ["click"]  # the step after the failure never ran
    assert out["results"][-1]["ok"] is False


def test_batch_validates_every_step_before_running_any():
    log: list = []
    steps = [{"action": "click"}, {"action": "explode"}]
    with pytest.raises(SessionError) as err:
        batch.run_batch("t", steps, handlers=_handlers(log))
    assert err.value.code == "bad_args" and "step 1" in str(err.value)
    assert log == []


@pytest.mark.parametrize("steps", [[], None, "click", [{"x": 1}], ["click"], [{"action": "click"}] * 51])
def test_batch_rejects_bad_input(steps):
    with pytest.raises(SessionError) as err:
        batch.run_batch("t", steps, handlers=_handlers([]))
    assert err.value.code == "bad_args"


def test_real_handlers_check_arguments(fake_state, monkeypatch):
    monkeypatch.setattr(batch, "get_running", lambda name: fake_state)
    out = batch.run_batch("t", [{"action": "click", "x": "left", "y": 3}])
    assert out["ok"] is False and out["code"] == "bad_args"
    out = batch.run_batch("t", [{"action": "type"}])
    assert out["ok"] is False and out["code"] == "bad_args"


def test_every_documented_action_has_a_handler():
    assert set(batch.STEP_HANDLERS) == {
        "click", "move", "drag", "scroll", "type", "key", "wait", "wait_stable",
        "wait_window", "focus", "open", "open_url", "run_in_terminal",
        "clipboard_set", "clipboard_get",
    }
