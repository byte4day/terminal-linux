from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any, Callable

from . import actions, activity
from .errors import SessionError
from .paths import ASSETS_DIR
from .session import get_running, open_app
from .state import SessionState

_AGENT_SHELL = ASSETS_DIR / "agent-shell.sh"
_ALACRITTY_CFG = ASSETS_DIR / "alacritty-agent.toml"

# WM_CLASS fragments of terminal emulators, for finding a shell to type into.
TERMINAL_CLASSES = ("alacritty", "kitty", "xterm", "xfce4-terminal", "gnome-terminal", "konsole")


def _run(state: SessionState, cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            check=check,
            env=state.env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise SessionError(f"required binary missing: {cmd[0]}", code="not_found") from exc
    except subprocess.TimeoutExpired as exc:
        raise SessionError(f"{cmd[0]} timed out", code="timeout") from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or "").strip()
        raise SessionError(err or f"command failed: {' '.join(cmd)}") from exc


def pick_guest_terminal() -> list[str]:
    """Prefer a real terminal emulator for the AI guest (clean config, no host shell RC)."""
    shell_args = ["bash", str(_AGENT_SHELL)] if _AGENT_SHELL.exists() else ["bash", "--noprofile", "--norc"]

    if shutil.which("alacritty"):
        cmd = ["alacritty", "--title", "agent-terminal"]
        if _ALACRITTY_CFG.exists():
            cmd.extend(["--config-file", str(_ALACRITTY_CFG)])
        cmd.append("-e")
        cmd.extend(shell_args)
        return cmd
    if shutil.which("kitty"):
        return ["kitty", "--title", "agent-terminal", "--config", "NONE", *shell_args]
    if shutil.which("xterm"):
        return ["xterm", "-T", "agent-terminal", "-e", *shell_args]
    if shutil.which("xfce4-terminal"):
        return ["xfce4-terminal", "--title=agent-terminal", "-e", " ".join(shell_args)]
    raise SessionError("no guest terminal found (install alacritty, kitty, or xterm)", code="not_found")


def ensure_agent_workspace(name: str, *, browser: bool = True, terminal: bool = True) -> dict[str, Any]:
    """Make sure the guest has the tools an agent usually needs."""
    get_running(name)
    launched: list[list[str]] = []
    existing = list_windows(name)
    titles = " ".join(w.get("title", "").lower() for w in existing)
    classes = " ".join(w.get("class", "").lower() for w in existing)
    if terminal and "agent-terminal" not in titles:
        try:
            cmd = pick_guest_terminal()
            open_app(name, cmd)
            launched.append(cmd)
            activity.note(name, "opened agent-terminal")
        except SessionError as exc:
            activity.note(name, f"terminal open failed: {exc}")
    if browser and shutil.which("firefox") and "firefox" not in classes and "firefox" not in titles:
        open_app(name, ["firefox"])
        launched.append(["firefox"])
        activity.note(name, "opened firefox")
    time.sleep(0.8)
    return {"ok": True, "launched": launched, "windows": list_windows(name)}


def parse_wmctrl(output: str) -> list[dict[str, Any]]:
    """Parse `wmctrl -lGx`: id desktop x y w h class host title."""
    rows: list[dict[str, Any]] = []
    for line in output.splitlines():
        parts = line.split(None, 8)
        if len(parts) < 8:
            continue
        try:
            x, y, w, h = (int(v) for v in parts[2:6])
        except ValueError:
            continue
        rows.append(
            {
                "id": parts[0],
                "desktop": parts[1],
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "center": [x + w // 2, y + h // 2],
                "class": parts[6],
                "host": parts[7],
                "title": parts[8] if len(parts) > 8 else "",
            }
        )
    return rows


def _same_window(a: Any, b: Any) -> bool:
    """Compare window ids given as hex ('0x00400004') or decimal ('4194308')."""
    try:
        return int(str(a), 0) == int(str(b), 0)
    except ValueError:
        return False


def _active_id(state: SessionState) -> str | None:
    wid = _run(state, ["xdotool", "getactivewindow"], check=False).stdout.strip()
    return wid or None


def list_windows(name: str = "default") -> list[dict[str, Any]]:
    """Guest windows with id, class, title, geometry and which one is focused."""
    state = get_running(name)
    active = _active_id(state)
    if shutil.which("wmctrl"):
        rows = parse_wmctrl(_run(state, ["wmctrl", "-lGx"], check=False).stdout)
    else:
        # Fallback without wmctrl: visible windows through xdotool.
        proc = _run(state, ["xdotool", "search", "--onlyvisible", "--name", ".+"], check=False)
        rows = []
        for wid in [line.strip() for line in proc.stdout.splitlines() if line.strip()][:40]:
            row: dict[str, Any] = {
                "id": wid,
                "desktop": None,
                "title": _run(state, ["xdotool", "getwindowname", wid], check=False).stdout.strip(),
            }
            geom = _run(state, ["xdotool", "getwindowgeometry", "--shell", wid], check=False).stdout
            for line in geom.splitlines():
                key, _, value = line.partition("=")
                if key.lower() in {"x", "y", "width", "height"} and value.lstrip("-").isdigit():
                    row[key.lower()] = int(value)
            if {"x", "y", "width", "height"} <= row.keys():
                row["center"] = [row["x"] + row["width"] // 2, row["y"] + row["height"] // 2]
            rows.append(row)
    for row in rows:
        row["active"] = bool(active) and _same_window(row["id"], active)
    return rows


def find_window(
    windows: list[dict[str, Any]], *, title: str | None = None, cls: str | None = None
) -> dict[str, Any] | None:
    """First window whose title and class contain the given text (case-insensitive)."""
    if not title and not cls:
        return None
    for win in windows:
        if title and title.lower() not in str(win.get("title", "")).lower():
            continue
        if cls and cls.lower() not in str(win.get("class", "")).lower():
            continue
        return win
    return None


def active_window(name: str = "default") -> dict[str, Any]:
    state = get_running(name)
    wid = _active_id(state)
    if not wid:
        raise SessionError("no window is focused", code="not_found")
    title = _run(state, ["xdotool", "getwindowname", wid], check=False).stdout.strip()
    geom = _run(
        state,
        ["xdotool", "getwindowgeometry", "--shell", wid],
        check=False,
    ).stdout
    info: dict[str, Any] = {"id": wid, "title": title}
    for line in geom.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.lower()] = int(v) if v.lstrip("-").isdigit() else v
    if wid.isdigit():
        info["hex_id"] = f"0x{int(wid):08x}"
    return info


def focus_window(
    name: str,
    *,
    window_id: str | None = None,
    title: str | None = None,
    cls: str | None = None,
) -> dict[str, Any]:
    state = get_running(name)
    if window_id:
        _run(state, ["xdotool", "windowactivate", "--sync", str(window_id)])
        activity.note(name, f"focus id {window_id}")
        return {"ok": True, "id": window_id}
    if not title and not cls:
        raise SessionError("provide window_id, title or class", code="bad_args")
    win = find_window(list_windows(name), title=title, cls=cls)
    if not win:
        wanted = " ".join(f"{k} {v!r}" for k, v in (("title", title), ("class", cls)) if v)
        raise SessionError(f"no window matching {wanted}", code="not_found")
    _run(state, ["xdotool", "windowactivate", "--sync", str(win["id"])])
    activity.note(name, f"focus {win.get('title')!r}")
    return {"ok": True, "id": win["id"], "title": win.get("title"), "class": win.get("class")}


def cursor_position(name: str = "default") -> dict[str, Any]:
    state = get_running(name)
    out = _run(state, ["xdotool", "getmouselocation", "--shell"]).stdout
    data: dict[str, Any] = {"ok": True}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.lower()] = int(v) if v.lstrip("-").isdigit() else v
    return data


def clipboard_get(name: str = "default") -> dict[str, Any]:
    state = get_running(name)
    if not shutil.which("xclip"):
        raise SessionError("xclip not found", code="not_found")
    proc = _run(state, ["xclip", "-selection", "clipboard", "-o"], check=False)
    text = proc.stdout if proc.returncode == 0 else ""
    activity.note(name, f"clipboard get ({len(text)} chars)")
    return {"ok": True, "text": text}


def clipboard_set(name: str, text: str) -> dict[str, Any]:
    state = get_running(name)
    if not shutil.which("xclip"):
        raise SessionError("xclip not found", code="not_found")
    try:
        # xclip stays alive in the background to own the selection. It must not
        # inherit our stdout/stderr, or anything reading our output through a
        # pipe (an agent's shell tool, the MCP client) waits on it forever.
        subprocess.run(
            ["xclip", "-selection", "clipboard", "-in"],
            input=text,
            check=True,
            env=state.env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        raise SessionError("setting the clipboard timed out", code="timeout") from exc
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SessionError("failed to set clipboard") from exc
    activity.note(name, f"clipboard set ({len(text)} chars)")
    return {"ok": True, "chars": len(text)}


def open_url(name: str, url: str) -> dict[str, Any]:
    get_running(name)
    url = url.strip()
    if not url:
        raise SessionError("url is empty", code="bad_args")
    if url.startswith("-"):
        raise SessionError("url must not start with '-'", code="bad_args")
    if not url.startswith(("http://", "https://", "file://", "about:")):
        url = "https://" + url
    # Prefer firefox profile already prepared by open_app
    if shutil.which("firefox"):
        pid = open_app(name, ["firefox", "--new-tab", url])
    elif shutil.which("xdg-open"):
        pid = open_app(name, ["xdg-open", url])
    else:
        raise SessionError("no browser available to open URL", code="not_found")
    activity.note(name, f"open_url {url}")
    return {"ok": True, "url": url, "pid": pid}


def wait(name: str, seconds: float = 1.0) -> dict[str, Any]:
    seconds = max(0.0, min(float(seconds), 30.0))
    time.sleep(seconds)
    activity.note(name, f"wait {seconds}s")
    return {"ok": True, "waited": seconds}


def wait_stable(
    name: str,
    *,
    timeout: float = 10.0,
    settle: float = 0.6,
    interval: float = 0.25,
    tolerance: float = 0.0005,
    grab: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Wait until the screen stops changing for ``settle`` seconds, or time out.

    Frames are compared pixel by pixel; ``tolerance`` is the share of pixels
    allowed to differ, so a blinking text cursor does not keep it waiting.
    ``grab`` (a callable returning a PIL image) replaces the real screenshot in tests.
    """
    from PIL import Image

    from . import imaging

    if grab is None:
        state = get_running(name)

        def grab() -> Any:
            path = actions.screenshot(state)
            try:
                with Image.open(path) as im:
                    im.load()
                    return im.convert("RGB")
            finally:
                path.unlink(missing_ok=True)

    timeout = max(0.5, min(float(timeout), 120.0))
    start = time.monotonic()
    deadline = start + timeout
    last = None
    stable_since: float | None = None
    checks = 0
    while True:
        frame = grab()
        checks += 1
        now = time.monotonic()
        if last is not None and imaging.changed_fraction(last, frame) <= tolerance:
            if stable_since is None:
                stable_since = now
            if now - stable_since >= settle:
                activity.note(name, f"wait_stable ok after {checks} checks")
                return {"ok": True, "stable": True, "checks": checks, "waited": round(now - start, 2)}
        else:
            stable_since = None
        last = frame
        if now >= deadline:
            break
        time.sleep(interval)
    activity.note(name, f"wait_stable timeout after {checks} checks")
    return {
        "ok": True,
        "stable": False,
        "timeout": True,
        "checks": checks,
        "waited": round(time.monotonic() - start, 2),
    }


def wait_window(
    name: str,
    *,
    title: str | None = None,
    cls: str | None = None,
    timeout: float = 10.0,
    gone: bool = False,
    interval: float = 0.25,
    lister: Callable[[], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Wait for a window to appear (or, with ``gone``, to close).

    Matches a title and/or class substring, case-insensitive. Returns
    ``found: false, timeout: true`` instead of failing, so the caller can decide.
    """
    if not title and not cls:
        raise SessionError("wait_window needs a title or a class", code="bad_args")
    lister = lister or (lambda: list_windows(name))
    timeout = max(0.0, min(float(timeout), 120.0))
    start = time.monotonic()
    while True:
        win = find_window(lister(), title=title, cls=cls)
        waited = round(time.monotonic() - start, 2)
        if gone and win is None:
            return {"ok": True, "gone": True, "waited": waited}
        if not gone and win is not None:
            activity.note(name, f"window {win.get('title')!r} appeared")
            return {"ok": True, "found": True, "window": win, "waited": waited}
        if time.monotonic() - start >= timeout:
            key = "gone" if gone else "found"
            return {"ok": True, key: False, "timeout": True, "waited": waited}
        time.sleep(interval)


def _focus_terminal(name: str) -> bool:
    """Focus agent-terminal, else any terminal emulator (matched by class, not title:
    a browser tab titled 'kitty docs' is not a shell)."""
    windows = list_windows(name)
    win = find_window(windows, title="agent-terminal")
    if win is None:
        for cls in TERMINAL_CLASSES:
            win = find_window(windows, cls=cls)
            if win is not None:
                break
    if win is None:
        return False
    focus_window(name, window_id=str(win["id"]))
    return True


def run_in_terminal(name: str, command: str) -> dict[str, Any]:
    """Focus agent-terminal (or any terminal) and type a command + Enter."""
    state = get_running(name)
    if not command.strip():
        raise SessionError("command is empty", code="bad_args")
    if not _focus_terminal(name):
        open_app(name, pick_guest_terminal())
        found = wait_window(name, title="agent-terminal", timeout=8.0)
        if not found.get("found") or not _focus_terminal(name):
            raise SessionError("could not open a guest terminal", code="not_found")
    time.sleep(0.2)
    actions.type_text(state, command)
    actions.press_key(state, "Return")
    activity.note(name, f"run_in_terminal {command!r}")
    return {"ok": True, "command": command}


def hotkeys_help() -> dict[str, str]:
    return {
        "focus_location": "ctrl+l",
        "new_tab": "ctrl+t",
        "close_tab": "ctrl+w",
        "reload": "ctrl+r",
        "find": "ctrl+f",
        "copy": "ctrl+c",
        "paste": "ctrl+v",
        "select_all": "ctrl+a",
        "close_window": "alt+F4",
        "switch_window": "alt+Tab",
        "terminal_interrupt": "ctrl+c",
        "clear_terminal": "ctrl+l",
    }
