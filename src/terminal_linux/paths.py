from __future__ import annotations

import os
import re
from pathlib import Path

from .errors import SessionError

# Runtime resources live inside the package so a non-editable install
# (`uv tool install .`, a wheel) finds them too.
PACKAGE_DIR = Path(__file__).resolve().parent
VENDOR_OPENBOX = PACKAGE_DIR / "vendor" / "openbox"
ASSETS_DIR = PACKAGE_DIR / "assets"
BUNDLE_DIR = PACKAGE_DIR / "bundle"

_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def validate_name(name: str) -> str:
    """Session names become directory names; refuse anything path-like."""
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise SessionError(
            f"invalid session name {name!r}: use letters, digits, '.', '_' or '-' (max 64)",
            code="bad_args",
        )
    return name


def data_home() -> Path:
    override = os.environ.get("TERMINAL_LINUX_HOME")
    if override:
        return Path(override).expanduser().resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser().resolve() / "terminal-linux"
    return Path.home() / ".local" / "share" / "terminal-linux"


def machines_dir(*, create: bool = True) -> Path:
    path = data_home() / "machines"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def machine_dir(name: str, *, create: bool = True) -> Path:
    """Directory for one session. Read-only callers pass ``create=False``."""
    path = machines_dir(create=create) / validate_name(name)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path
