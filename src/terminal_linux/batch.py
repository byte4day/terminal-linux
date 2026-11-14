"""Run several computer-use steps in one call.

A round trip per click is slow for an agent. ``run_batch`` executes a list of
steps in order, stops at the first failure and lets the caller take a single
screenshot at the end.
"""

from __future__ import annotations

from typing import Any, Callable

from . import actions, agent_tools
from .errors import SessionError
from .session import get_running, open_app

MAX_STEPS = 50


def _int(step: dict[str, Any], key: str, default: int | None = None) -> int:
    value = step.get(key, default)
    if value is None or isinstance(value, bool):
        raise SessionError(f"step needs integer {key!r}", code="bad_args")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise SessionError(f"{key!r} must be an integer, got {value!r}", code="bad_args") from None


def _str(step: dict[str, Any], key: str) -> str:
    value = step.get(key)
    if not isinstance(value, str) or value == "":
        raise SessionError(f"step needs text {key!r}", code="bad_args")
    return value


def _opt_int(step: dict[str, Any], key: str) -> int | None:
    return None if step.get(key) is None else _int(step, key)


def _click(name: str, s: dict[str, Any]) -> dict[str, Any]:
    actions.click(
        get_running(name), _int(s, "x"), _int(s, "y"),
        button=str(s.get("button", "left")), clicks=_int(s, "clicks", 1),
    )
    return {}


def _move(name: str, s: dict[str, Any]) -> dict[str, Any]:
    actions.move(get_running(name), _int(s, "x"), _int(s, "y"))
    return {}


def _drag(name: str, s: dict[str, Any]) -> dict[str, Any]:
    actions.drag(get_running(name), _int(s, "x1"), _int(s, "y1"), _int(s, "x2"), _int(s, "y2"))
    return {}


def _scroll(name: str, s: dict[str, Any]) -> dict[str, Any]:
    actions.scroll(
        get_running(name), dy=_int(s, "dy", 0), dx=_int(s, "dx", 0),
        x=_opt_int(s, "x"), y=_opt_int(s, "y"),
    )
    return {}


def _type(name: str, s: dict[str, Any]) -> dict[str, Any]:
    actions.type_text(get_running(name), _str(s, "text"))
    return {}


def _key(name: str, s: dict[str, Any]) -> dict[str, Any]:
    actions.press_key(get_running(name), _str(s, "key"))
    return {}


def _wait(name: str, s: dict[str, Any]) -> dict[str, Any]:
    return agent_tools.wait(name, float(s.get("seconds", 1.0)))


def _wait_stable(name: str, s: dict[str, Any]) -> dict[str, Any]:
    return agent_tools.wait_stable(
        name, timeout=float(s.get("timeout", 10.0)), settle=float(s.get("settle", 0.6))
    )


def _wait_window(name: str, s: dict[str, Any]) -> dict[str, Any]:
    result = agent_tools.wait_window(
        name, title=s.get("title"), cls=s.get("class"),
        timeout=float(s.get("timeout", 10.0)), gone=bool(s.get("gone", False)),
    )
    if result.get("timeout"):
        # Inside a batch a missing window means the following steps would act blind.
        raise SessionError("wait_window timed out", code="timeout")
    return result


def _focus(name: str, s: dict[str, Any]) -> dict[str, Any]:
    return agent_tools.focus_window(
        name, window_id=s.get("window_id"), title=s.get("title"), cls=s.get("class")
    )


def _open(name: str, s: dict[str, Any]) -> dict[str, Any]:
    import shlex

    return {"pid": open_app(name, shlex.split(_str(s, "command")))}


STEP_HANDLERS: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]] = {
    "click": _click,
    "move": _move,
    "drag": _drag,
    "scroll": _scroll,
    "type": _type,
    "key": _key,
    "wait": _wait,
    "wait_stable": _wait_stable,
    "wait_window": _wait_window,
    "focus": _focus,
    "open": _open,
    "open_url": lambda name, s: agent_tools.open_url(name, _str(s, "url")),
    "run_in_terminal": lambda name, s: agent_tools.run_in_terminal(name, _str(s, "command")),
    "clipboard_set": lambda name, s: agent_tools.clipboard_set(name, str(s.get("text", ""))),
    "clipboard_get": lambda name, s: agent_tools.clipboard_get(name),
}


def run_batch(
    name: str,
    steps: Any,
    *,
    handlers: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run ``steps`` in order; stop at the first failure.

    Each step is ``{"action": "<name>", ...args}`` using the same names and
    arguments as the single tools (``-`` and ``_`` are interchangeable).
    Returns ``ok`` (all steps ran), ``completed`` and one result per step tried.
    """
    handlers = handlers or STEP_HANDLERS
    if not isinstance(steps, list) or not steps:
        raise SessionError("steps must be a non-empty list of objects", code="bad_args")
    if len(steps) > MAX_STEPS:
        raise SessionError(f"too many steps ({len(steps)}); the limit is {MAX_STEPS}", code="bad_args")
    for i, step in enumerate(steps):
        action = step.get("action") if isinstance(step, dict) else None
        if not isinstance(action, str) or action.replace("-", "_") not in handlers:
            known = ", ".join(sorted(handlers))
            raise SessionError(
                f"step {i}: unknown or missing action {action!r}; use one of: {known}",
                code="bad_args",
            )

    results: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        action = step["action"].replace("-", "_")
        try:
            out = handlers[action](name, step) or {}
        except SessionError as exc:
            results.append({"step": i, "action": action, "ok": False, "error": str(exc), "code": exc.code})
            return {
                "ok": False,
                "completed": i,
                "total": len(steps),
                "failed_step": i,
                "error": f"step {i} ({action}): {exc}",
                "code": exc.code,
                "results": results,
            }
        results.append({"step": i, "action": action, **{k: v for k, v in out.items() if k != "ok"}, "ok": True})
    return {"ok": True, "completed": len(steps), "total": len(steps), "results": results}
