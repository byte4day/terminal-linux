from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

from .paths import VENDOR_OPENBOX, machine_dir
from .state import SessionState, clear_state, is_running, load_state, save_state, terminate_pid


class SessionError(RuntimeError):
    pass


def find_openbox() -> tuple[Path, dict[str, str]]:
    """Return (binary, extra_env) for openbox — system first, then vendored."""
    system = shutil.which("openbox")
    if system:
        return Path(system), {}

    vendored = VENDOR_OPENBOX / "usr" / "bin" / "openbox"
    if vendored.exists():
        lib = str(VENDOR_OPENBOX / "usr" / "lib")
        env = {"LD_LIBRARY_PATH": lib + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")}
        return vendored, env

    raise SessionError(
        "openbox not found. Install openbox, or keep vendor/openbox from this repo."
    )


def require_bin(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SessionError(f"required binary not found on PATH: {name}")
    return path


def display_free(display: int) -> bool:
    sock = Path(f"/tmp/.X{display}-lock")
    if sock.exists():
        return False
    # Also check TCP/unix abstract — Xvfb uses unix socket
    xsock = Path(f"/tmp/.X11-unix/X{display}")
    return not xsock.exists()


def pick_display(start: int = 90) -> int:
    for display in range(start, start + 100):
        if display_free(display):
            return display
    raise SessionError("no free X display in :90–:189")


def wait_for_display(display: int, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    sock_path = f"/tmp/.X11-unix/X{display}"
    while time.time() < deadline:
        if Path(sock_path).exists():
            # Confirm X answers
            try:
                subprocess.run(
                    ["xdpyinfo", "-display", f":{display}"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1,
                )
                return
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass
        time.sleep(0.05)
    raise SessionError(f"Xvfb display :{display} did not become ready")


def write_openbox_config(name: str) -> Path:
    cfg = machine_dir(name) / "openbox"
    cfg.mkdir(parents=True, exist_ok=True)
    rc = cfg / "rc.xml"
    # Minimal RC: no desktop panels, focus follows click, no keybindings that fight agents.
    rc.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <resistance><strength>10</strength><screen_edge_strength>20</screen_edge_strength></resistance>
  <focus><focusNew>yes</focusNew><followMouse>no</followMouse><focusLast>yes</focusLast></focus>
  <theme><name>Clearlooks</name><titleLayout>NLIMC</titleLayout><keepBorder>yes</keepBorder></theme>
  <desktops><number>1</number><firstdesk>1</firstdesk><popupTime>0</popupTime></desktops>
  <keyboard><chainQuitKey>C-g</chainQuitKey></keyboard>
  <mouse>
    <context name="Frame"><mousebind button="A-Left" action="Move"/><mousebind button="A-Right" action="Resize"/></context>
    <context name="Titlebar"><mousebind button="Left" action="Focus"/><mousebind button="Left" action="Raise"/></context>
  </mouse>
</openbox_config>
"""
    )
    menu = cfg / "menu.xml"
    menu.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<openbox_menu xmlns="http://openbox.org/3.4/menu">
  <menu id="root-menu" label="terminal-linux">
    <item label="Terminal"><action name="Execute"><command>xterm || xfce4-terminal || kitty || alacritty</command></action></item>
    <item label="Firefox"><action name="Execute"><command>firefox</command></action></item>
    <item label="Thunar"><action name="Execute"><command>thunar</command></action></item>
    <separator/>
    <item label="Exit"><action name="Exit"/></item>
  </menu>
</openbox_menu>
"""
    )
    return cfg


def paint_desktop(env: dict[str, str], width: int, height: int, name: str) -> None:
    """Paint a labeled wallpaper onto the X root window."""
    wallpaper = machine_dir(name) / "wallpaper.png"
    magick = shutil.which("magick") or shutil.which("convert")
    painted = False
    if magick:
        try:
            subprocess.run(
                [
                    magick,
                    "-size",
                    f"{width}x{height}",
                    f"gradient:#12151c-#1e2633",
                    "-gravity",
                    "center",
                    "-fill",
                    "#c5cee0",
                    "-pointsize",
                    "36",
                    "-annotate",
                    "0",
                    "terminal-linux",
                    "-fill",
                    "#7f8ba3",
                    "-pointsize",
                    "18",
                    "-annotate",
                    "+0+42",
                    f"session · {name}",
                    str(wallpaper),
                ],
                check=True,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Write the PNG onto the X root window (non-interactive).
            subprocess.run(
                [magick, str(wallpaper), "x:root"],
                check=True,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            painted = True
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            painted = False
    if not painted:
        subprocess.run(
            ["xsetroot", "-solid", "#1a1d23"],
            check=False,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def start_session(
    name: str = "default",
    *,
    width: int = 1280,
    height: int = 800,
    dpi: int = 96,
    apps: list[list[str]] | None = None,
) -> SessionState:
    existing = load_state(name)
    if existing and is_running(existing):
        return existing
    if existing:
        clear_state(name)

    require_bin("Xvfb")
    require_bin("xdotool")
    require_bin("import")
    openbox, openbox_env = find_openbox()

    display = pick_display()
    log_dir = machine_dir(name)
    xvfb_log = open(log_dir / "xvfb.log", "ab", buffering=0)
    wm_log = open(log_dir / "wm.log", "ab", buffering=0)

    xvfb = subprocess.Popen(
        [
            "Xvfb",
            f":{display}",
            "-screen",
            "0",
            f"{width}x{height}x24",
            "-dpi",
            str(dpi),
            "-nolisten",
            "tcp",
            "+extension",
            "RANDR",
        ],
        stdout=xvfb_log,
        stderr=xvfb_log,
        start_new_session=True,
    )

    try:
        wait_for_display(display)
    except SessionError:
        terminate_pid(xvfb.pid, force=True)
        raise

    env = os.environ.copy()
    env["DISPLAY"] = f":{display}"
    env.pop("WAYLAND_DISPLAY", None)
    env.update(openbox_env)

    # Vendored openbox needs its theme directory on XDG_DATA_DIRS.
    vendor_share = VENDOR_OPENBOX / "usr" / "share"
    if vendor_share.exists():
        existing = env.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
        env["XDG_DATA_DIRS"] = f"{vendor_share}:{existing}"

    cfg = write_openbox_config(name)
    # openbox reads $XDG_CONFIG_HOME/openbox/{rc,menu}.xml
    env["XDG_CONFIG_HOME"] = str(log_dir)

    wm = subprocess.Popen(
        [str(openbox), "--config-file", str(cfg / "rc.xml")],
        stdout=wm_log,
        stderr=wm_log,
        env=env,
        start_new_session=True,
    )
    time.sleep(0.3)
    if wm.poll() is not None:
        terminate_pid(xvfb.pid, force=True)
        raise SessionError(f"openbox exited early; see {log_dir / 'wm.log'}")

    paint_desktop(env, width, height, name)

    state = SessionState(
        name=name,
        display=display,
        width=width,
        height=height,
        xvfb_pid=xvfb.pid,
        wm_pid=wm.pid,
        created_at=time.time(),
        apps=[],
    )
    save_state(state)

    for cmd in apps or []:
        if not cmd:
            continue
        try:
            open_app(name, cmd)
        except SessionError:
            # Session is up even if an optional autostart app fails.
            pass

    refreshed = load_state(name)
    return refreshed or state


def stop_session(name: str = "default", *, force: bool = False) -> None:
    state = load_state(name)
    if not state:
        return
    terminate_pid(state.wm_pid, force=force)
    terminate_pid(state.xvfb_pid, force=force)
    # Best-effort: kill anything still bound to this display.
    if force:
        subprocess.run(
            ["pkill", "-f", f"DISPLAY=:{state.display}"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    clear_state(name)


def get_running(name: str = "default") -> SessionState:
    state = load_state(name)
    if not state or not is_running(state):
        raise SessionError(f"session {name!r} is not running; start with: terminal-linux up {name}")
    return state


def list_sessions() -> list[dict]:
    from .paths import machines_dir

    rows = []
    root = machines_dir()
    if not root.exists():
        return rows
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        state = load_state(path.name)
        if not state:
            rows.append({"name": path.name, "status": "unknown"})
            continue
        rows.append(
            {
                "name": state.name,
                "status": "running" if is_running(state) else "stopped",
                "display": state.display_name,
                "size": f"{state.width}x{state.height}",
                "xvfb_pid": state.xvfb_pid,
            }
        )
    return rows


def running_session_names(*, prefer: str | None = None) -> list[str]:
    """Running session names for the live tab bar (prefer first if still up)."""
    names = [row["name"] for row in list_sessions() if row.get("status") == "running"]
    if prefer and prefer in names:
        names = [prefer] + [n for n in names if n != prefer]
    return names


def _prepare_command(name: str, command: list[str]) -> tuple[list[str], dict[str, str]]:
    """Tune common apps so they don't attach to the host session."""
    state = get_running(name)
    env = state.env()
    cmd = list(command)
    if not cmd:
        raise SessionError("no command given")

    app = Path(cmd[0]).name
    if app in {"firefox", "firefox-bin"}:
        profile = machine_dir(name) / "mozilla"
        profile.mkdir(parents=True, exist_ok=True)
        if "--no-remote" not in cmd:
            cmd.insert(1, "--no-remote")
        if "-profile" not in cmd and "--profile" not in cmd:
            cmd[1:1] = ["--profile", str(profile)]
        env["MOZ_ENABLE_WAYLAND"] = "0"
        env["GDK_BACKEND"] = "x11"
    elif app in {"chromium", "chromium-browser", "google-chrome", "google-chrome-stable"}:
        profile = machine_dir(name) / "chromium"
        profile.mkdir(parents=True, exist_ok=True)
        if "--user-data-dir" not in " ".join(cmd):
            cmd.insert(1, f"--user-data-dir={profile}")
        for flag in ("--no-first-run", "--disable-features=WaylandWindowDecorations"):
            if flag not in cmd:
                cmd.insert(1, flag)
        env["GDK_BACKEND"] = "x11"
    elif app in {"alacritty", "kitty", "xterm", "xfce4-terminal"}:
        guest_home = machine_dir(name) / "guest-home"
        guest_home.mkdir(parents=True, exist_ok=True)
        (guest_home / "README.txt").write_text(
            "terminal-linux guest home\nAI agents work here.\n"
        )
        env["HOME"] = str(guest_home)
        env["TERMINAL_LINUX_GUEST_HOME"] = str(guest_home)
        env["LANG"] = "C"
        env["LC_ALL"] = "C"

    return cmd, env


def open_app(name: str, command: list[str]) -> int:
    cmd, env = _prepare_command(name, command)
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    state = get_running(name)
    state.apps.append(list(cmd))
    save_state(state)
    return proc.pid


def local_hostname() -> str:
    return socket.gethostname()
