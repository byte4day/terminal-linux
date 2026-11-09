from __future__ import annotations

import os
import shutil
from typing import Any

from .graphics import supports_iterm_graphics, supports_kitty_graphics
from .paths import VENDOR_OPENBOX
from .session import find_openbox


def run_doctor() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    for binary in ("Xvfb", "xdotool", "import", "convert", "xsetroot", "xdpyinfo"):
        path = shutil.which(binary)
        check(binary, bool(path), path or "not found on PATH")

    try:
        ob, env = find_openbox()
        check("openbox", True, f"{ob}" + (" (vendored)" if "vendor" in str(ob) else " (system)"))
        if env.get("LD_LIBRARY_PATH"):
            check("openbox-libs", True, env["LD_LIBRARY_PATH"].split(os.pathsep)[0])
    except Exception as exc:  # noqa: BLE001
        check("openbox", False, str(exc))
        check(
            "vendor-openbox",
            VENDOR_OPENBOX.exists(),
            str(VENDOR_OPENBOX) if VENDOR_OPENBOX.exists() else "missing vendor/openbox",
        )

    kitty = supports_kitty_graphics()
    iterm = supports_iterm_graphics()
    check(
        "inline-graphics",
        kitty or iterm,
        "kitty/ghostty/wezterm" if kitty else ("iTerm2" if iterm else "unsupported terminal"),
    )

    for app in ("firefox", "thunar", "xterm", "xfce4-terminal", "kitty", "alacritty"):
        path = shutil.which(app)
        if path:
            check(f"app:{app}", True, path)

    ok = all(c["ok"] for c in checks if c["name"] in {"Xvfb", "xdotool", "import", "openbox"})
    return {"ok": ok, "checks": checks}
