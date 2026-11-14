from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import __version__, activity
from .errors import SessionError
from .session import get_running
from .state import SessionState, pid_alive

# Names agents commonly send → X keysym names. Lookup is case-insensitive.
KEY_ALIASES = {
    "return": "Return",
    "enter": "Return",
    "esc": "Escape",
    "escape": "Escape",
    "tab": "Tab",
    "space": "space",
    "spacebar": "space",
    "backspace": "BackSpace",
    "delete": "Delete",
    "del": "Delete",
    "insert": "Insert",
    "ins": "Insert",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "arrowup": "Up",
    "arrowdown": "Down",
    "arrowleft": "Left",
    "arrowright": "Right",
    "home": "Home",
    "end": "End",
    "pageup": "Page_Up",
    "pagedown": "Page_Down",
    "page_up": "Page_Up",
    "page_down": "Page_Down",
    "pgup": "Page_Up",
    "pgdn": "Page_Down",
    "capslock": "Caps_Lock",
    "printscreen": "Print",
    "menu": "Menu",
    # Punctuation cannot be passed raw inside an xdotool chord.
    "+": "plus",
    "plus": "plus",
    "-": "minus",
    "minus": "minus",
    "=": "equal",
    ",": "comma",
    ".": "period",
    "/": "slash",
    "\\": "backslash",
    ";": "semicolon",
    "'": "apostrophe",
    "`": "grave",
    "[": "bracketleft",
    "]": "bracketright",
}

# Modifier spellings (including Mac-style ones) → xdotool modifier names.
MODIFIERS = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "cmd": "ctrl",
    "command": "ctrl",
    "alt": "alt",
    "option": "alt",
    "opt": "alt",
    "shift": "shift",
    "super": "super",
    "win": "super",
    "meta": "super",
}

# A chord that is only a modifier ("super", "ctrl+shift") presses the key itself.
MODIFIER_KEYSYMS = {"ctrl": "Control_L", "alt": "Alt_L", "shift": "Shift_L", "super": "Super_L"}


def _normalize_key(token: str) -> str:
    t = token.strip()
    low = t.lower()
    if low in MODIFIERS:
        return MODIFIERS[low]
    if low in KEY_ALIASES:
        return KEY_ALIASES[low]
    if len(low) >= 2 and low[0] == "f" and low[1:].isdigit():
        return "F" + low[1:]  # f5 → F5
    return t


def parse_chord(spec: str) -> str:
    """'cmd+shift+t' → 'ctrl+shift+t'; 'ctrl++' → 'ctrl+plus'; 'super' → 'Super_L'."""
    spec = spec.strip()
    if not spec:
        raise SessionError("empty key specification", code="bad_args")
    if spec == "+":
        parts = ["+"]
    elif spec.endswith("++"):
        parts = [p for p in spec[:-2].split("+") if p.strip()] + ["+"]
    else:
        parts = [p for p in spec.split("+") if p.strip()]
    if not parts:
        raise SessionError(f"no key in specification {spec!r}", code="bad_args")

    *head, last = parts
    mods: list[str] = []
    for part in head:
        mod = MODIFIERS.get(part.strip().lower())
        if mod is None:
            raise SessionError(
                f"{part.strip()!r} in {spec!r} is not a modifier; one key per chord "
                "(separate chords with spaces, e.g. 'ctrl+a ctrl+c')",
                code="bad_args",
            )
        if mod not in mods:
            mods.append(mod)
    last_mod = MODIFIERS.get(last.strip().lower())
    key = MODIFIER_KEYSYMS[last_mod] if last_mod else _normalize_key(last)
    return "+".join([*mods, key])


def parse_keys(spec: str) -> list[str]:
    """Split a space-separated sequence of chords: 'ctrl+a ctrl+c' → two chords."""
    chords = [parse_chord(part) for part in spec.split()]
    if not chords:
        raise SessionError("empty key specification", code="bad_args")
    return chords


def check_point(state: SessionState, x: int, y: int) -> None:
    """Refuse coordinates off the screen instead of letting X clamp them silently."""
    if not (0 <= x < state.width and 0 <= y < state.height):
        raise SessionError(
            f"point ({x},{y}) is outside the {state.width}x{state.height} screen; "
            "coordinates are pixels of the full screenshot",
            code="out_of_bounds",
        )


def _run_xdotool(state: SessionState, args: list[str]) -> None:
    try:
        subprocess.run(
            ["xdotool", *args],
            check=True,
            env=state.env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise SessionError("xdotool not found on PATH", code="not_found") from exc
    except subprocess.TimeoutExpired as exc:
        raise SessionError(f"xdotool timed out: {' '.join(args[:2])}", code="timeout") from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or "").strip()
        raise SessionError(err or f"xdotool failed: {' '.join(args)}") from exc


def screenshot(
    state: SessionState,
    output: Path | None = None,
    *,
    region: str | list[int] | tuple[int, ...] | None = None,
    grid: int | bool = False,
    zoom: int = 1,
) -> Path:
    """Capture the guest screen to a PNG.

    ``region`` crops to X,Y,W,H, ``zoom`` enlarges the result (1-4) and ``grid``
    overlays lines labelled with full-screen coordinates.
    """
    if output is None:
        fd, raw = tempfile.mkstemp(prefix="terminal-linux-", suffix=".png")
        os.close(fd)
        output = Path(raw)
    else:
        output = Path(output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            ["import", "-window", "root", str(output)],
            check=True,
            env=state.env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise SessionError("ImageMagick 'import' not found on PATH", code="not_found") from exc
    except subprocess.TimeoutExpired as exc:
        raise SessionError("screenshot timed out", code="timeout") from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or "").strip()
        raise SessionError(err or "screenshot failed") from exc

    if not output.exists() or output.stat().st_size == 0:
        raise SessionError("screenshot produced an empty file")

    if region or grid or zoom > 1:
        from PIL import Image

        from . import imaging

        with Image.open(output) as src:
            src.load()
            box = imaging.parse_region(region, src.width, src.height)
            out = imaging.render(src, region=box, grid=grid, zoom=zoom)
        out.save(output, format="PNG")
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
        raise SessionError(f"unknown button {button!r}; use left|middle|right", code="bad_args")
    if clicks < 1 or clicks > 3:
        raise SessionError("clicks must be 1, 2, or 3", code="bad_args")
    check_point(state, x, y)
    _run_xdotool(state, ["mousemove", "--sync", str(x), str(y)])
    # One xdotool call keeps a double-click inside the toolkit's double-click window.
    _run_xdotool(state, ["click", "--repeat", str(clicks), "--delay", "80", button_map[button]])
    label = "double-click" if clicks == 2 else ("triple-click" if clicks == 3 else "click")
    activity.note(state.name, f"agent {label} {button} @ {x},{y}")


def move(state: SessionState, x: int, y: int) -> None:
    check_point(state, x, y)
    _run_xdotool(state, ["mousemove", "--sync", str(x), str(y)])
    activity.note(state.name, f"agent move @ {x},{y}")


def drag(state: SessionState, x1: int, y1: int, x2: int, y2: int) -> None:
    check_point(state, x1, y1)
    check_point(state, x2, y2)
    _run_xdotool(state, ["mousemove", "--sync", str(x1), str(y1)])
    _run_xdotool(state, ["mousedown", "1"])
    try:
        # A midpoint step: many toolkits ignore a drag that jumps in one motion.
        _run_xdotool(state, ["mousemove", "--sync", str((x1 + x2) // 2), str((y1 + y2) // 2)])
        _run_xdotool(state, ["mousemove", "--sync", str(x2), str(y2)])
    finally:
        # Never leave the button held down if a move fails.
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
    if (x is None) != (y is None):
        raise SessionError("scroll needs both x and y, or neither", code="bad_args")
    if x is not None and y is not None:
        check_point(state, x, y)
        _run_xdotool(state, ["mousemove", "--sync", str(x), str(y)])
    # negative dy scrolls down (X button 5). One wheel notch per 40 units.
    if dy:
        notches = min(200, max(1, abs(dy) // 40))
        _run_xdotool(state, ["click", "--repeat", str(notches), "--delay", "8", "5" if dy < 0 else "4"])
    if dx:
        notches = min(200, max(1, abs(dx) // 40))
        _run_xdotool(state, ["click", "--repeat", str(notches), "--delay", "8", "7" if dx > 0 else "6"])
    activity.note(state.name, f"agent scroll dy={dy} dx={dx}")


def type_text(state: SessionState, text: str) -> None:
    if text == "":
        return
    _run_xdotool(state, ["type", "--clearmodifiers", "--delay", "12", "--", text])
    preview = text if len(text) <= 40 else text[:37] + "..."
    activity.note(state.name, f"agent type {preview!r}")


def press_key(state: SessionState, keyspec: str) -> None:
    """Press a chord or a space-separated sequence of chords.

    'ctrl+c', 'alt+Tab', 'return', 'cmd+space' (cmd→ctrl), 'super', 'ctrl++',
    'ctrl+a ctrl+c'.
    """
    chords = parse_keys(keyspec)
    _run_xdotool(state, ["key", "--clearmodifiers", "--delay", "40", *chords])
    activity.note(state.name, f"agent key {' '.join(chords)}")


def _tools() -> dict[str, bool]:
    return {name: bool(shutil.which(name)) for name in ("xdotool", "import", "Xvfb", "wmctrl", "xclip")}


def status_payload(name: str = "default") -> dict[str, Any]:
    try:
        state = get_running(name)
    except SessionError as exc:
        if exc.code != "not_running":
            raise
        return {
            "ok": True,
            "name": name,
            "running": False,
            "ready": False,
            "message": str(exc),
            "version": __version__,
            "tools": _tools(),
        }
    wm_running = pid_alive(state.wm_pid)
    payload: dict[str, Any] = {
        "ok": True,
        "name": state.name,
        "running": True,
        "ready": wm_running,
        "display": state.display_name,
        "width": state.width,
        "height": state.height,
        "xvfb_pid": state.xvfb_pid,
        "wm_pid": state.wm_pid,
        "wm_running": wm_running,
        "apps": state.apps,
        "permissions": {"screen": True, "input": True},
        "version": __version__,
        "tools": _tools(),
    }
    if not wm_running:
        payload["message"] = f"window manager is not running; `terminal-linux up {name} --no-view` restarts it"
    return payload
