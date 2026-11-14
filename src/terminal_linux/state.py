from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .paths import machine_dir


@dataclass
class SessionState:
    name: str
    display: int
    width: int
    height: int
    xvfb_pid: int
    wm_pid: int
    created_at: float
    apps: list[list[str]]
    app_pids: list[int] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return f":{self.display}"

    def env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["DISPLAY"] = self.display_name
        # Keep the guest session off the host Wayland/X socket.
        env.pop("WAYLAND_DISPLAY", None)
        return env

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        return cls(
            name=str(data["name"]),
            display=int(data["display"]),
            width=int(data["width"]),
            height=int(data["height"]),
            xvfb_pid=int(data["xvfb_pid"]),
            wm_pid=int(data["wm_pid"]),
            created_at=float(data["created_at"]),
            apps=[list(map(str, cmd)) for cmd in data.get("apps", [])],
            app_pids=[int(p) for p in data.get("app_pids", [])],
        )


def atomic_write_text(path: Path, text: str) -> None:
    """Replace ``path`` in one step so a concurrent reader never sees half a file."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def state_path(name: str, *, create: bool = False) -> Path:
    return machine_dir(name, create=create) / "session.json"


def save_state(state: SessionState) -> None:
    path = state_path(state.name, create=True)
    atomic_write_text(path, json.dumps(state.to_dict(), indent=2) + "\n")


def load_state(name: str) -> SessionState | None:
    path = state_path(name)
    if not path.exists():
        return None
    try:
        return SessionState.from_dict(json.loads(path.read_text()))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def clear_state(name: str) -> None:
    path = state_path(name)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def pid_alive(pid: int) -> bool:
    """True for a live process. A zombie (exited, not yet reaped) counts as dead."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        # Field 3, after the parenthesised command name, is the state letter.
        if stat.rsplit(")", 1)[-1].split()[:1] == ["Z"]:
            return False
    except (OSError, IndexError):
        pass
    return True


def pid_cmdline(pid: int) -> list[str] | None:
    """argv of ``pid``, or None when /proc cannot tell us."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    return [part.decode(errors="replace") for part in raw.split(b"\0") if part]


def is_xvfb_for(pid: int, display: int) -> bool:
    """True when ``pid`` is the Xvfb serving ``:display``.

    Guards against a recycled pid: after a reboot or a crash the saved pid can
    belong to an unrelated process, which must not make a dead session look alive.
    """
    if not pid_alive(pid):
        return False
    argv = pid_cmdline(pid)
    if argv is None:  # no /proc: fall back to liveness only
        return True
    if not argv:
        return False
    return Path(argv[0]).name == "Xvfb" and f":{display}" in argv[1:]


def is_running(state: SessionState) -> bool:
    return is_xvfb_for(state.xvfb_pid, state.display)


def terminate_pid(pid: int, *, force: bool = False, group: bool = False) -> None:
    """Signal ``pid`` (or its process group). Never signals this process's own group."""
    if pid <= 0 or pid == os.getpid() or not pid_alive(pid):
        return
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        if group:
            pgid = os.getpgid(pid)
            if pgid == pid and pgid != os.getpgid(0):
                os.killpg(pgid, sig)
                return
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        return


def wait_gone(pids: list[int], timeout: float = 3.0) -> list[int]:
    """Wait for ``pids`` to exit; return the ones still alive after ``timeout``."""
    deadline = time.time() + max(0.0, timeout)
    remaining = [p for p in pids if p > 0]
    while remaining:
        for pid in list(remaining):
            try:  # reap if it is our own child, so it does not linger as a zombie
                os.waitpid(pid, os.WNOHANG)
            except (ChildProcessError, OSError):
                pass
        remaining = [p for p in remaining if pid_alive(p)]
        if not remaining or time.time() >= deadline:
            break
        time.sleep(0.05)
    return remaining
