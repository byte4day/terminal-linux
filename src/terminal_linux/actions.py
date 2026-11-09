from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import activity
from .session import SessionError, get_running
from .state import SessionState

KEY_ALIASES = {
    "return": "Return",
    "enter": "Return",
    "esc": "Escape",
    "escape": "Escape",
    "tab": "Tab",
    "space": "space",
    "backspace": "BackSpace",
    "delete": "Delete",
    "del": "Delete",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "home": "Home",
    "end": "End",
    "pageup": "Page_Up",
    "pagedown": "Page_Down",
    "pgup": "Page_Up",
    "pgdn": "Page_Down",
    # Mac-ish aliases → Linux
    "cmd": "ctrl",
    "command": "ctrl",
    "option": "alt",
    "opt": "alt",
    "super": "super",
    "win": "super",
    "meta": "super",
}

MOD_NAMES = {
    "ctrl",
    "control",
    "alt",
    "shift",
    "super",
    "meta",
    "cmd",
    "command",
    "option",
    "opt",
    "win",
}


def _run_xdotool(state: SessionState, args: list[str]) -> None:
    try:
        subprocess.run(
            ["xdotool", *args],
            check=True,
            env=state.env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise SessionError("xdotool not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or "").strip()
        raise SessionError(err or f"xdotool failed: {' '.join(args)}") from exc


def screenshot(state: SessionState, output: Path | None = None) -> Path:
    if output is None:
        fd, raw = tempfile.mkstemp(prefix="terminal-linux-", suffix=".png")
        os.close(fd)
        output = Path(raw)
    else:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            ["import", "-window", "root", str(output)],
            check=True,
            env=state.env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise SessionError("ImageMagick 'import' not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or "").strip()
        raise SessionError(err or "screenshot failed") from exc

    if not output.exists() or output.stat().st_size == 0:
        raise SessionError("screenshot produced an empty file")
    return output


def click(
    state: SessionState,
    x: int,
    y: int,
    *,
    button: str = "left",
    clicks: int = 1,
) -> None:
    button_map = {"left": "1", "middle": "2", "right": "3"}
    if button not in button_map:
        raise SessionError(f"unknown button {button!r}; use left|middle|right")
    if clicks < 1 or clicks > 3:
        raise SessionError("clicks must be 1, 2, or 3")
    _run_xdotool(state, ["mousemove", "--sync", str(x), str(y)])
    for _ in range(clicks):
        _run_xdotool(state, ["click", button_map[button]])
    label = "double-click" if clicks == 2 else ("triple-click" if clicks == 3 else "click")
    activity.note(state.name, f"agent {label} {button} @ {x},{y}")


def move(state: SessionState, x: int, y: int) -> None:
    _run_xdotool(state, ["mousemove", "--sync", str(x), str(y)])
    activity.note(state.name, f"agent move @ {x},{y}")


def drag(state: SessionState, x1: int, y1: int, x2: int, y2: int) -> None:
    _run_xdotool(state, ["mousemove", "--sync", str(x1), str(y1)])
    _run_xdotool(state, ["mousedown", "1"])
    _run_xdotool(state, ["mousemove", "--sync", str(x2), str(y2)])
    _run_xdotool(state, ["mouseup", "1"])
    activity.note(state.name, f"agent drag {x1},{y1}→{x2},{y2}")


def scroll(
    state: SessionState,
    *,
    dy: int = 0,
    dx: int = 0,
    x: int | None = None,
    y: int | None = None,
) -> None:
    if x is not None and y is not None:
        _run_xdotool(state, ["mousemove", "--sync", str(x), str(y)])
    # negative dy scrolls down (X button 5).
    if dy:
        button = "5" if dy < 0 else "4"
        for _ in range(max(1, abs(dy) // 40)):
            _run_xdotool(state, ["click", button])
    if dx:
        button = "7" if dx > 0 else "6"
        for _ in range(max(1, abs(dx) // 40)):
            _run_xdotool(state, ["click", button])
    activity.note(state.name, f"agent scroll dy={dy} dx={dx}")


def type_text(state: SessionState, text: str) -> None:
    if text == "":
        return
    _run_xdotool(state, ["type", "--clearmodifiers", "--delay", "12", "--", text])
    preview = text if len(text) <= 40 else text[:37] + "..."
    activity.note(state.name, f"agent type {preview!r}")


def _normalize_key(token: str) -> str:
    t = token.strip().lower()
    return KEY_ALIASES.get(t, token.strip())


def press_key(state: SessionState, keyspec: str) -> None:
    """Accept 'ctrl+c', 'alt+tab', 'return', 'cmd+space' (cmd→ctrl)."""
    parts = [p for p in re.split(r"[+|]", keyspec.strip()) if p]
    if not parts:
        raise SessionError("empty key specification")

    mods: list[str] = []
    key: str | None = None
    for part in parts:
        low = part.lower()
        if low in MOD_NAMES:
            mods.append(_normalize_key(low))
        else:
            key = _normalize_key(part)
    if key is None:
        raise SessionError(f"no key in specification {keyspec!r}")

    xmods: list[str] = []
    for m in mods:
        ml = m.lower()
        if ml in ("ctrl", "control"):
            xmods.append("ctrl")
        elif ml == "alt":
            xmods.append("alt")
        elif ml == "shift":
            xmods.append("shift")
        elif ml in ("super", "meta"):
            xmods.append("super")
        else:
            xmods.append(ml)

    chord = "+".join([*xmods, key]) if xmods else key
    _run_xdotool(state, ["key", "--clearmodifiers", chord])
    activity.note(state.name, f"agent key {chord}")


def status_payload(name: str = "default") -> dict[str, Any]:
    try:
        state = get_running(name)
    except SessionError as exc:
        return {
            "ok": True,
            "name": name,
            "running": False,
            "ready": False,
            "message": str(exc),
            "tools": {
                "xdotool": bool(shutil.which("xdotool")),
                "import": bool(shutil.which("import")),
                "Xvfb": bool(shutil.which("Xvfb")),
            },
        }
    return {
        "ok": True,
        "name": state.name,
        "running": True,
        "ready": True,
        "display": state.display_name,
        "width": state.width,
        "height": state.height,
        "xvfb_pid": state.xvfb_pid,
        "wm_pid": state.wm_pid,
        "apps": state.apps,
        "permissions": {"screen": True, "input": True},
        "tools": {
            "xdotool": bool(shutil.which("xdotool")),
            "import": bool(shutil.which("import")),
            "Xvfb": bool(shutil.which("Xvfb")),
        },
    }
