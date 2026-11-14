from __future__ import annotations

import os
import shutil
from typing import Any

from .graphics import supports_iterm_graphics, supports_kitty_graphics
from .paths import VENDOR_OPENBOX
from .session import find_openbox


REQUIRED = ("Xvfb", "xdotool", "import")
RECOMMENDED = {
    "wmctrl": "window titles and geometry (falls back to xdotool)",
    "xclip": "clipboard_get / clipboard_set",
    "xdpyinfo": "display readiness probe (falls back to xdotool)",
    "display": "wallpaper (falls back to a solid colour)",
    "ffmpeg": "smooth live preview (falls back to one screenshot per frame)",
}


def run_doctor() -> dict[str, Any]:
    """Check host dependencies.

    ``ok`` depends only on what a session cannot start without. Everything else
    is reported with ``required: false`` so a missing extra is not read as a failure.
    """
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str, *, required: bool = False) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail, "required": required})

    for binary in REQUIRED:
        path = shutil.which(binary)
        check(binary, bool(path), path or "not found on PATH", required=True)

    try:
        ob, env = find_openbox()
        vendored = VENDOR_OPENBOX in ob.parents
        check("openbox", True, f"{ob}" + (" (vendored)" if vendored else " (system)"), required=True)
        if env.get("LD_LIBRARY_PATH"):
            check("openbox-libs", True, env["LD_LIBRARY_PATH"].split(os.pathsep)[0])
    except Exception as exc:  # noqa: BLE001
        check("openbox", False, str(exc), required=True)

    for binary, why in RECOMMENDED.items():
        path = shutil.which(binary)
        check(binary, bool(path), path or f"not found; used for {why}")

    terminals = [t for t in ("alacritty", "kitty", "xterm", "xfce4-terminal") if shutil.which(t)]
    check(
        "guest-terminal",
        bool(terminals),
        ", ".join(terminals) if terminals else "none of alacritty, kitty, xterm; run_in_terminal needs one",
    )
    firefox = shutil.which("firefox")
    check("firefox", bool(firefox), firefox or "not found; open_url needs a browser")

    kitty = supports_kitty_graphics()
    iterm = supports_iterm_graphics()
    check(
        "inline-graphics",
        kitty or iterm,
        "kitty/ghostty/wezterm"
        if kitty
        else ("iTerm2" if iterm else "this terminal has no inline images; the live view uses text blocks"),
    )

    missing = [c["name"] for c in checks if c["required"] and not c["ok"]]
    report: dict[str, Any] = {"ok": not missing, "checks": checks}
    if missing:
        report["missing"] = missing
    return report
