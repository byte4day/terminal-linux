from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .paths import machine_dir


def activity_path(name: str) -> Path:
    return machine_dir(name) / "activity.json"


def note(name: str, text: str, **extra: Any) -> None:
    payload = {"t": time.time(), "text": text, **extra}
    activity_path(name).write_text(json.dumps(payload) + "\n")


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
