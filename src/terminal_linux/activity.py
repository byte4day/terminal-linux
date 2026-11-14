from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .paths import machine_dir
from .state import atomic_write_text


def activity_path(name: str, *, create: bool = False) -> Path:
    return machine_dir(name, create=create) / "activity.json"


def note(name: str, text: str, **extra: Any) -> None:
    """Record the latest agent action for the live viewer. Never fails an action."""
    payload = {"t": time.time(), "text": text, **extra}
    try:
        atomic_write_text(activity_path(name, create=True), json.dumps(payload) + "\n")
    except OSError:
        pass


def read(name: str) -> dict[str, Any] | None:
    path = activity_path(name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def latest_text(name: str, *, max_age: float = 30.0) -> str | None:
    data = read(name)
    if not data:
        return None
    age = time.time() - float(data.get("t", 0))
    if age > max_age:
        return None
    text = str(data.get("text", "")).strip()
    return text or None
