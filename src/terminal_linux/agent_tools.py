from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
from typing import Any

from pathlib import Path

from . import actions, activity
from .paths import PACKAGE_ROOT
from .session import SessionError, get_running, open_app
from .state import SessionState

_AGENT_SHELL = PACKAGE_ROOT / "assets" / "agent-shell.sh"
_ALACRITTY_CFG = PACKAGE_ROOT / "assets" / "alacritty-agent.toml"


def _run(state: SessionState, cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            check=check,
            env=state.env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise SessionError(f"required binary missing: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or "").strip()
        raise SessionError(err or f"command failed: {' '.join(cmd)}") from exc


def pick_guest_terminal() -> list[str]:
    """Prefer a real terminal emulator for the AI guest (clean config, no host shell RC)."""
    shell = str(_AGENT_SHELL) if _AGENT_SHELL.exists() else "bash"
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
    raise SessionError("no guest terminal found (install alacritty, kitty, or xterm)")


def ensure_agent_workspace(name: str, *, browser: bool = True, terminal: bool = True) -> dict[str, Any]:
    """Make sure the guest has the tools an agent usually needs."""
    state = get_running(name)
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


def list_windows(name: str = "default") -> list[dict[str, Any]]:
    state = get_running(name)
    if not shutil.which("wmctrl"):
        # Fallback: xdotool search
        proc = _run(state, ["xdotool", "search", "--name", ".*"], check=False)
        ids = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        rows = []
        for wid in ids[:40]:
            title_p = _run(state, ["xdotool", "getwindowname", wid], check=False)
            rows.append({"id": wid, "title": title_p.stdout.strip(), "desktop": None})
        return rows

    proc = _run(state, ["wmctrl", "-lx"], check=False)
    rows: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        # id desktop class host title...
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        rows.append(
            {
                "id": parts[0],
                "desktop": parts[1],
                "class": parts[2],
                "host": parts[3],
                "title": parts[4],
            }
        )
    activity.note(name, f"listed {len(rows)} windows")
    return rows


def active_window(name: str = "default") -> dict[str, Any]:
    state = get_running(name)
    wid = _run(state, ["xdotool", "getactivewindow"]).stdout.strip()
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
    return info


def focus_window(name: str, *, window_id: str | None = None, title: str | None = None) -> dict[str, Any]:
    state = get_running(name)
    if window_id:
        _run(state, ["xdotool", "windowactivate", "--sync", window_id])
        activity.note(name, f"focus id {window_id}")
        return {"ok": True, "id": window_id}
    if not title:
        raise SessionError("provide window_id or title")
    # Partial title match
    for win in list_windows(name):
        if title.lower() in str(win.get("title", "")).lower():
            wid = str(win["id"])
            # wmctrl wants 0x ids; xdotool accepts decimal or hex
            if shutil.which("wmctrl") and wid.startswith("0x"):
                _run(state, ["wmctrl", "-ia", wid])
            else:
                _run(state, ["xdotool", "windowactivate", "--sync", wid])
            activity.note(name, f"focus title~{title!r}")
            return {"ok": True, "id": wid, "title": win.get("title")}
    raise SessionError(f"no window matching title {title!r}")


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
        raise SessionError("xclip not found")
    proc = _run(state, ["xclip", "-selection", "clipboard", "-o"], check=False)
    text = proc.stdout
    activity.note(name, f"clipboard get ({len(text)} chars)")
    return {"ok": True, "text": text}


def clipboard_set(name: str, text: str) -> dict[str, Any]:
    state = get_running(name)
    if not shutil.which("xclip"):
        raise SessionError("xclip not found")
    try:
        subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text,
            check=True,
            env=state.env(),
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SessionError("failed to set clipboard") from exc
    activity.note(name, f"clipboard set ({len(text)} chars)")
    return {"ok": True, "chars": len(text)}


def open_url(name: str, url: str) -> dict[str, Any]:
    state = get_running(name)
    if not url.startswith(("http://", "https://", "file://", "about:")):
        url = "https://" + url
    # Prefer firefox profile already prepared by open_app
    if shutil.which("firefox"):
        pid = open_app(name, ["firefox", "--new-tab", url])
    elif shutil.which("xdg-open"):
        pid = open_app(name, ["xdg-open", url])
    else:
        raise SessionError("no browser available to open URL")
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
) -> dict[str, Any]:
    """Wait until consecutive screenshots match (UI settled) or timeout."""
    state = get_running(name)
    deadline = time.time() + max(0.5, timeout)
    last = ""
    stable_since: float | None = None
    checks = 0
    while time.time() < deadline:
        path = actions.screenshot(state)
        digest = hashlib.sha1(path.read_bytes()).hexdigest()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        checks += 1
        now = time.time()
        if digest == last:
            if stable_since is None:
                stable_since = now
            if now - stable_since >= settle:
                activity.note(name, f"wait_stable ok after {checks} checks")
                return {"ok": True, "stable": True, "checks": checks}
        else:
            last = digest
            stable_since = None
        time.sleep(interval)
    activity.note(name, f"wait_stable timeout after {checks} checks")
    return {"ok": True, "stable": False, "checks": checks, "timeout": True}


def run_in_terminal(name: str, command: str) -> dict[str, Any]:
    """Focus agent-terminal (or any terminal) and type a command + Enter."""
    state = get_running(name)
    focused = False
    for needle in ("agent-terminal", "alacritty", "kitty", "xterm", "Terminal"):
        try:
            focus_window(name, title=needle)
            focused = True
            break
        except SessionError:
            continue
    if not focused:
        # Spawn one, then type after a short delay
        open_app(name, pick_guest_terminal())
        time.sleep(0.8)
        try:
            focus_window(name, title="agent-terminal")
        except SessionError:
            pass
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
