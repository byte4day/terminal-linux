from __future__ import annotations

import json
import os
import signal
from dataclasses import asdict, dataclass
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
        )


def state_path(name: str) -> Path:
    return machine_dir(name) / "session.json"


def save_state(state: SessionState) -> None:
    path = state_path(state.name)
    path.write_text(json.dumps(state.to_dict(), indent=2) + "\n")


def load_state(name: str) -> SessionState | None:
    path = state_path(name)
    if not path.exists():
        return None
    try:
        return SessionState.from_dict(json.loads(path.read_text()))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def clear_state(name: str) -> None:
    path = state_path(name)
    if path.exists():
        path.unlink()


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def is_running(state: SessionState) -> bool:
    return pid_alive(state.xvfb_pid)


def terminate_pid(pid: int, *, force: bool = False) -> None:
    if not pid_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError:
        return
