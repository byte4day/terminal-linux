from __future__ import annotations

import base64
import os
import sys
from pathlib import Path


def supports_kitty_graphics() -> bool:
    term = os.environ.get("TERM", "")
    prog = os.environ.get("TERM_PROGRAM", "")
    if "kitty" in term or prog.lower() in {"kitty", "ghostty", "wezterm"}:
        return True
    # Kitty sets KITTY_WINDOW_ID; Ghostty often sets TERM=xterm-ghostty
    if os.environ.get("KITTY_WINDOW_ID") or os.environ.get("GHOSTTY_RESOURCES_DIR"):
        return True
    return False


def supports_iterm_graphics() -> bool:
    return os.environ.get("TERM_PROGRAM", "") == "iTerm.app"


def clear_screen() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def hide_cursor() -> None:
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()


def show_cursor() -> None:
    sys.stdout.write("\033[?25h")
    sys.stdout.flush()


def move_home() -> None:
    sys.stdout.write("\033[H")
    sys.stdout.flush()


def display_png_kitty(path: Path, *, cols: int | None = None, rows: int | None = None) -> None:
    data = path.read_bytes()
    b64 = base64.standard_b64encode(data).decode("ascii")
    # a=T transmit+display, f=100 PNG, q=2 quiet
    chunks = [b64[i : i + 4096] for i in range(0, len(b64), 4096)]
    sys.stdout.write("\033[H")
    for i, chunk in enumerate(chunks):
        more = 1 if i < len(chunks) - 1 else 0
        if i == 0:
            extras = ["a=T", "f=100", "q=2", f"m={more}"]
            if cols:
                extras.append(f"c={cols}")
            if rows:
                extras.append(f"r={rows}")
            sys.stdout.write("\033_G" + ",".join(extras) + ";" + chunk + "\033\\")
        else:
            sys.stdout.write(f"\033_Gm={more};{chunk}\033\\")
    sys.stdout.flush()


def display_png_iterm(path: Path) -> None:
    data = path.read_bytes()
    b64 = base64.standard_b64encode(data).decode("ascii")
    sys.stdout.write("\033[H")
    sys.stdout.write(f"\033]1337;File=inline=1;size={len(data)}:{b64}\a")
    sys.stdout.flush()


def display_png(path: Path, *, cols: int | None = None, rows: int | None = None) -> bool:
    if supports_kitty_graphics():
        display_png_kitty(path, cols=cols, rows=rows)
        return True
    if supports_iterm_graphics():
        display_png_iterm(path)
        return True
    return False


def enable_mouse() -> None:
    # Any-event tracking + SGR extended coordinates
    sys.stdout.write("\033[?1003h\033[?1006h")
    sys.stdout.flush()


def disable_mouse() -> None:
    sys.stdout.write("\033[?1003l\033[?1006l")
    sys.stdout.flush()


def terminal_size() -> tuple[int, int]:
    try:
        size = os.get_terminal_size()
        return size.columns, size.lines
    except OSError:
        return 80, 24
