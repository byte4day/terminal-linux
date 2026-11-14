from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

from .errors import SessionError
from .paths import VENDOR_OPENBOX, machine_dir, machines_dir, validate_name
from .state import (
    SessionState,
    clear_state,
    is_running,
    load_state,
    pid_alive,
    save_state,
    terminate_pid,
    wait_gone,
)

__all__ = ["SessionError"]

MIN_SIZE = (320, 240)
MAX_SIZE = (7680, 4320)


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
        "openbox not found. Install openbox, or run scripts/fetch-openbox.sh from the repo.",
        code="not_found",
    )


def require_bin(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SessionError(f"required binary not found on PATH: {name}", code="not_found")
    return path


def _lock_owner_alive(lock: Path) -> bool:
    """An X lock file holds the server pid. A dead owner means a stale lock."""
    try:
        pid = int(lock.read_text().strip())
    except (OSError, ValueError):
        return True  # unreadable: assume in use
    return pid_alive(pid)


def display_free(display: int, *, tmp: Path = Path("/tmp")) -> bool:
    lock = tmp / f".X{display}-lock"
    if lock.exists():
        # A killed Xvfb leaves its lock behind; the next server replaces a stale one.
        return not _lock_owner_alive(lock)
    return not (tmp / ".X11-unix" / f"X{display}").exists()


def pick_display(start: int = 90) -> int:
    for display in range(start, start + 100):
        if display_free(display):
            return display
    raise SessionError("no free X display in :90–:189")


def _display_answers(display: int) -> bool:
    probe = (
        ["xdpyinfo", "-display", f":{display}"]
        if shutil.which("xdpyinfo")
        else ["xdotool", "getdisplaygeometry"]
    )
    env = os.environ.copy()
    env["DISPLAY"] = f":{display}"
    env.pop("WAYLAND_DISPLAY", None)
    try:
        subprocess.run(
            probe,
            check=True,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1,
        )
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def wait_for_display(
    display: int, timeout: float = 5.0, *, proc: subprocess.Popen | None = None
) -> None:
    """Block until ``:display`` answers. ``proc`` is the Xvfb we started for it."""

    def exited() -> bool:
        return proc is not None and proc.poll() is not None

    deadline = time.time() + timeout
    sock = Path(f"/tmp/.X11-unix/X{display}")
    while time.time() < deadline:
        if not exited() and sock.exists() and _display_answers(display):
            # Another server may own this number and have answered for ours:
            # give a losing Xvfb a moment to exit before trusting the display.
            time.sleep(0.05)
            if not exited():
                return
        if exited():
            raise SessionError(
                f"Xvfb exited with status {proc.returncode} on :{display}",  # type: ignore[union-attr]
                code="display_taken",
            )
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
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    # Solid colour first: instant, and it stays if the image step is unavailable.
    try:
        subprocess.run(["xsetroot", "-solid", "#1a1d23"], check=False, env=env, timeout=5, **quiet)
    except (OSError, subprocess.TimeoutExpired):
        pass

    magick = shutil.which("magick") or shutil.which("convert")
    display_bin = shutil.which("display")
    if not magick or not display_bin:
        return
    wallpaper = machine_dir(name) / "wallpaper.png"
    try:
        subprocess.run(
            [
                magick,
                "-size",
                f"{width}x{height}",
                "gradient:#12151c-#1e2633",
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
            timeout=10,
            **quiet,
        )
        # `display -window root` sets the root pixmap and exits. (`magick FILE x:root`
        # opens an interactive viewer and never returns, which cost 5 s per start.)
        subprocess.run(
            [display_bin, "-window", "root", str(wallpaper)],
            check=False,
            env=env,
            timeout=5,
            **quiet,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass


def check_size(width: int, height: int) -> None:
    if not (MIN_SIZE[0] <= width <= MAX_SIZE[0] and MIN_SIZE[1] <= height <= MAX_SIZE[1]):
        raise SessionError(
            f"size {width}x{height} out of range "
            f"({MIN_SIZE[0]}x{MIN_SIZE[1]} to {MAX_SIZE[0]}x{MAX_SIZE[1]})",
            code="bad_args",
        )


def parse_size(text: str) -> tuple[int, int]:
    """'1920x1080' → (1920, 1080)."""
    try:
        w, h = text.lower().replace("×", "x").split("x")
        size = int(w), int(h)
    except ValueError:
        raise SessionError(f"bad size {text!r}; use WIDTHxHEIGHT, e.g. 1920x1080", code="bad_args") from None
    check_size(*size)
    return size


def _guest_env(name: str, display: int) -> dict[str, str]:
    env = os.environ.copy()
    env["DISPLAY"] = f":{display}"
    env.pop("WAYLAND_DISPLAY", None)
    # Vendored openbox needs its theme directory on XDG_DATA_DIRS.
    vendor_share = VENDOR_OPENBOX / "usr" / "share"
    if vendor_share.exists():
        dirs = env.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
        env["XDG_DATA_DIRS"] = f"{vendor_share}:{dirs}"
    # openbox reads $XDG_CONFIG_HOME/openbox/{rc,menu}.xml
    env["XDG_CONFIG_HOME"] = str(machine_dir(name))
    return env


def _spawn_wm(name: str, display: int) -> tuple[subprocess.Popen, dict[str, str]]:
    openbox, openbox_env = find_openbox()
    env = _guest_env(name, display)
    env.update(openbox_env)
    cfg = write_openbox_config(name)
    log_path = machine_dir(name) / "wm.log"
    with open(log_path, "ab", buffering=0) as wm_log:
        wm = subprocess.Popen(
            [str(openbox), "--config-file", str(cfg / "rc.xml")],
            stdin=subprocess.DEVNULL,
            stdout=wm_log,
            stderr=wm_log,
            env=env,
            start_new_session=True,
        )
    time.sleep(0.3)
    if wm.poll() is not None:
        raise SessionError(f"openbox exited early; see {log_path}")
    return wm, env


def _spawn_xvfb(name: str, width: int, height: int, dpi: int) -> tuple[subprocess.Popen, int]:
    """Start Xvfb on a free display, moving to the next number if one is taken."""
    log_path = machine_dir(name) / "xvfb.log"
    display = 89
    last_error: SessionError | None = None
    for _attempt in range(8):
        display = pick_display(display + 1)
        with open(log_path, "ab", buffering=0) as xvfb_log:
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
                stdin=subprocess.DEVNULL,
                stdout=xvfb_log,
                stderr=xvfb_log,
                start_new_session=True,
            )
        try:
            wait_for_display(display, proc=xvfb)
            return xvfb, display
        except SessionError as exc:
            last_error = exc
            terminate_pid(xvfb.pid, force=True)
            wait_gone([xvfb.pid], 1.0)
            if exc.code != "display_taken":
                break
    raise SessionError(f"could not start Xvfb: {last_error}; see {log_path}")


def start_session(
    name: str = "default",
    *,
    width: int = 1280,
    height: int = 800,
    dpi: int = 96,
    apps: list[list[str]] | None = None,
) -> SessionState:
    validate_name(name)
    existing = load_state(name)
    if existing and is_running(existing):
        if not pid_alive(existing.wm_pid):
            # Desktop is up but the window manager died: bring it back.
            wm, _env = _spawn_wm(name, existing.display)
            existing.wm_pid = wm.pid
            save_state(existing)
        return existing
    if existing:
        clear_state(name)

    check_size(width, height)
    require_bin("Xvfb")
    require_bin("xdotool")
    require_bin("import")
    find_openbox()

    xvfb, display = _spawn_xvfb(name, width, height, dpi)
    try:
        wm, env = _spawn_wm(name, display)
    except SessionError:
        terminate_pid(xvfb.pid, force=True)
        raise

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


def _pids_on_display(display: int) -> list[int]:
    """Processes of this user whose environment has exactly DISPLAY=:<display>."""
    needle = f"DISPLAY=:{display}".encode()
    me = os.getpid()
    found: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        try:
            environ = (entry / "environ").read_bytes()
        except OSError:
            continue
        if needle in environ.split(b"\0"):
            found.append(int(entry.name))
    return found


def stop_session(name: str = "default", *, force: bool = False) -> bool:
    """Stop a session. Returns False when there was nothing to stop."""
    state = load_state(name)
    if not state:
        return False
    live = is_running(state)
    # Only signal pids we can still tie to this session: after a crash or reboot
    # the saved numbers may belong to unrelated processes.
    core = [state.wm_pid, state.xvfb_pid] if live else []
    apps = [p for p in state.app_pids if pid_alive(p)] if live else []
    strays = _pids_on_display(state.display) if (live and force) else []

    for pid in apps + strays:
        terminate_pid(pid, force=force, group=pid in apps)
    for pid in core:
        terminate_pid(pid, force=force)
    # A stop that leaves Xvfb running would orphan the display once state is
    # cleared, so escalate anything that ignores SIGTERM.
    left = wait_gone(core + apps + strays, 0.5 if force else 3.0)
    for pid in left:
        terminate_pid(pid, force=True)
    wait_gone(left, 1.0)
    clear_state(name)
    return True


def get_running(name: str = "default") -> SessionState:
    state = load_state(name)
    if not state or not is_running(state):
        raise SessionError(
            f"session {name!r} is not running; start it with `up` "
            f"(CLI: terminal-linux up {name} --no-view)",
            code="not_running",
        )
    return state


def list_sessions() -> list[dict]:
    rows: list[dict] = []
    root = machines_dir(create=False)
    if not root.exists():
        return rows
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        try:
            state = load_state(path.name)
        except SessionError:
            continue  # not a session directory
        if not state:
            # Logs and profiles of a session that was stopped earlier.
            rows.append({"name": path.name, "status": "stopped"})
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
        raise SessionError("no command given", code="bad_args")

    app = Path(cmd[0]).name
    if app in {"firefox", "firefox-bin"}:
        # Snap Firefox often fails with custom profiles under ~/.local/share
        # ("Close Firefox" dialog). Prefer ~/snap/firefox/common when present.
        snap_common = Path.home() / "snap" / "firefox" / "common"
        if snap_common.is_dir() or "snap" in Path(shutil.which(cmd[0]) or cmd[0]).resolve().parts:
            profile = snap_common / f"terminal-linux-{name}"
        else:
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
    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        raise SessionError(f"command not found: {cmd[0]}", code="not_found") from None
    except OSError as exc:
        raise SessionError(f"could not start {cmd[0]}: {exc}", code="not_found") from None
    state = get_running(name)
    state.apps.append(list(cmd))
    state.apps = state.apps[-50:]
    state.app_pids = [p for p in state.app_pids if pid_alive(p)] + [proc.pid]
    save_state(state)
    return proc.pid


def local_hostname() -> str:
    return socket.gethostname()
