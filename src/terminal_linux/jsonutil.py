from __future__ import annotations

import json
import sys
from typing import Any


def emit(data: Any, *, exit_code: int = 0) -> None:
    sys.stdout.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
    sys.stdout.flush()
    raise SystemExit(exit_code)


def fail(message: str, *, code: str = "error", exit_code: int = 1, **extra: Any) -> None:
    payload: dict[str, Any] = {"ok": False, "error": message, "code": code}
    payload.update(extra)
    emit(payload, exit_code=exit_code)
