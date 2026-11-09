from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
VENDOR_OPENBOX = PACKAGE_ROOT / "vendor" / "openbox"


def data_home() -> Path:
    override = os.environ.get("TERMINAL_LINUX_HOME")
    if override:
        return Path(override).expanduser().resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser().resolve() / "terminal-linux"
    return Path.home() / ".local" / "share" / "terminal-linux"


def machines_dir() -> Path:
    path = data_home() / "machines"
    path.mkdir(parents=True, exist_ok=True)
    return path


def machine_dir(name: str) -> Path:
    path = machines_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path
