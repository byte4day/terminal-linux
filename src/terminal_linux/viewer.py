from __future__ import annotations

import select
import shutil
import sys
import termios
import time
import tty
from pathlib import Path

from . import actions
from .graphics import (
    clear_screen,
    disable_mouse,
    display_png,
    enable_mouse,
    hide_cursor,
    show_cursor,
    supports_iterm_graphics,
    supports_kitty_graphics,
    terminal_size,
)
from .session import SessionError, get_running
from .state import SessionState


HELP = (
    "terminal-linux viewer — Ctrl+] quit · Ctrl+G shortcuts · mouse/keyboard drive the guest"
)


SHORTCUTS = {
    "1": ("Super+space", "launcher / search (if configured)"),
    "2": ("alt+F4", "close window"),
    "3": ("ctrl+c", "copy (or interrupt)"),
    "4": ("ctrl+v", "paste"),
    "5": ("alt+Tab", "switch window"),
    "6": ("ctrl+l", "clear / focus location"),
    "7": ("ctrl+t", "new tab"),
    "8": ("ctrl+w", "close tab"),
    "9": ("ctrl+Return", "open / confirm"),
}


def _read_available(fd: int, timeout: float = 0.05) -> bytes:
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return b""
    return os_read_all(fd)


def os_read_all(fd: int) -> bytes:
    import os

    chunks = []
    while True:
        ready, _, _ = select.select([fd], [], [], 0)
        if not ready:
            break
        data = os.read(fd, 4096)
        if not data:
            break
        chunks.append(data)
        if len(data) < 4096:
            break
    return b"".join(chunks)


def _parse_sgr_mouse(seq: bytes) -> tuple[int, int, int, bool] | None:
    """Parse \033[<b;x;yM/m → (button, col, row, pressed)."""
    if not seq.startswith(b"\033[<"):
        return None
    body = seq[3:]
    if not body or body[-1] not in (ord("M"), ord("m")):
        return None
    pressed = body[-1] == ord("M")
    try:
        b_str, x_str, y_str = body[:-1].decode("ascii").split(";")
        return int(b_str), int(x_str), int(y_str), pressed
    except ValueError:
        return None


def _cell_to_pixel(col: int, row: int, state: SessionState) -> tuple[int, int]:
    cols, rows = terminal_size()
    # Leave one status row
    rows = max(1, rows - 1)
    x = int((col - 1) / max(cols, 1) * state.width)
    y = int((row - 1) / max(rows, 1) * state.height)
    x = max(0, min(state.width - 1, x))
    y = max(0, min(state.height - 1, y))
    return x, y


def _status_line(msg: str) -> None:
    cols, rows = terminal_size()
    sys.stdout.write(f"\033[{rows};1H\033[2K{msg[: cols - 1]}")
    sys.stdout.flush()


def run_viewer(name: str = "default", *, fps: float = 8.0) -> int:
    state = get_running(name)
    if not (supports_kitty_graphics() or supports_iterm_graphics()):
        raise SessionError(
            "inline graphics need Kitty, Ghostty, WezTerm, or iTerm2. "
            "Use agent actions without the viewer, or open DISPLAY="
            f"{state.display_name} with a nested client."
        )

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    interval = 1.0 / max(fps, 0.5)
    last_frame = 0.0
    drag_origin: tuple[int, int] | None = None
    buf = b""

    try:
        tty.setraw(fd)
        hide_cursor()
        enable_mouse()
        clear_screen()
        _status_line(HELP)

        while True:
            now = time.time()
            if now - last_frame >= interval:
                shot = actions.screenshot(state)
                display_png(shot)
                try:
                    shot.unlink(missing_ok=True)
                except OSError:
                    pass
                _status_line(HELP)
                last_frame = now

            chunk = _read_available(fd, timeout=0.02)
            if not chunk:
                continue
            buf += chunk

            # Quit: Ctrl+] (0x1d) or Ctrl+C / Ctrl+D in raw
            if b"\x1d" in buf or b"\x03" in buf:
                break

            # Ctrl+G palette
            if b"\x07" in buf:
                buf = buf.replace(b"\x07", b"")
                _status_line("shortcuts: " + " · ".join(f"{k}={v[0]}" for k, v in SHORTCUTS.items()))
                # wait one key
                key = _read_available(fd, timeout=3.0)
                if key:
                    ch = key[:1].decode("latin1", errors="ignore")
                    if ch in SHORTCUTS:
                        actions.press_key(state, SHORTCUTS[ch][0])
                        last_frame = 0
                continue

            # Mouse SGR
            while True:
                start = buf.find(b"\033[<")
                if start < 0:
                    break
                end_m = buf.find(b"M", start)
                end_m2 = buf.find(b"m", start)
                ends = [e for e in (end_m, end_m2) if e >= 0]
                if not ends:
                    break
                end = min(ends)
                seq = buf[start : end + 1]
                buf = buf[end + 1 :]
                parsed = _parse_sgr_mouse(seq)
                if not parsed:
                    continue
                button, col, row, pressed = parsed
                x, y = _cell_to_pixel(col, row, state)
                btn = button & 0x3F
                # Motion with button
                if button & 32:
                    actions.move(state, x, y)
                    continue
                if btn == 64:  # wheel up
                    if pressed:
                        actions.scroll(state, dy=120, x=x, y=y)
                    continue
                if btn == 65:  # wheel down
                    if pressed:
                        actions.scroll(state, dy=-120, x=x, y=y)
                    continue
                if btn == 0:  # left
                    if pressed:
                        drag_origin = (x, y)
                        actions.move(state, x, y)
                    else:
                        if drag_origin and (abs(drag_origin[0] - x) > 4 or abs(drag_origin[1] - y) > 4):
                            actions.drag(state, drag_origin[0], drag_origin[1], x, y)
                        else:
                            actions.click(state, x, y, button="left")
                        drag_origin = None
                        last_frame = 0
                elif btn == 2 and pressed:  # right
                    actions.click(state, x, y, button="right")
                    last_frame = 0
                elif btn == 1 and pressed:  # middle
                    actions.click(state, x, y, button="middle")
                    last_frame = 0

            # Strip incomplete ESC sequences; process printable / special keys
            if buf.startswith(b"\033") and len(buf) < 3 and b"\033[<" not in buf:
                continue

            # Arrow keys and such
            while buf:
                if buf.startswith(b"\033["):
                    # CSI — if mouse leftover incomplete, wait
                    if buf.startswith(b"\033[<"):
                        break
                    # arrows
                    if len(buf) >= 3 and buf[2] in b"ABCDH~":
                        mapping = {
                            ord("A"): "Up",
                            ord("B"): "Down",
                            ord("C"): "Right",
                            ord("D"): "Left",
                            ord("H"): "Home",
                        }
                        if buf[2] in mapping:
                            actions.press_key(state, mapping[buf[2]])
                            last_frame = 0
                        buf = buf[3:]
                        continue
                    if len(buf) >= 4 and buf[2:4] == b"1~":
                        actions.press_key(state, "Home")
                        buf = buf[4:]
                        continue
                    # unknown CSI — drop ESC
                    buf = buf[1:]
                    continue
                if buf.startswith(b"\033"):
                    # Alt+key
                    if len(buf) >= 2:
                        ch = buf[1:2]
                        buf = buf[2:]
                        if ch == b"\x7f":
                            actions.press_key(state, "alt+BackSpace")
                        elif 32 <= ch[0] < 127:
                            actions.press_key(state, f"alt+{chr(ch[0])}")
                        last_frame = 0
                    break

                ch = buf[0]
                buf = buf[1:]
                if ch == 0x1D:  # Ctrl+]
                    return 0
                if ch in (0x7F, 0x08):
                    actions.press_key(state, "BackSpace")
                    last_frame = 0
                elif ch == 0x09:
                    actions.press_key(state, "Tab")
                    last_frame = 0
                elif ch in (0x0A, 0x0D):
                    actions.press_key(state, "Return")
                    last_frame = 0
                elif ch == 0x1B:
                    actions.press_key(state, "Escape")
                    last_frame = 0
                elif 32 <= ch < 127:
                    actions.type_text(state, chr(ch))
                    last_frame = 0
                elif 1 <= ch <= 26:
                    letter = chr(ord("a") + ch - 1)
                    actions.press_key(state, f"ctrl+{letter}")
                    last_frame = 0

        return 0
    finally:
        disable_mouse()
        show_cursor()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        clear_screen()
        sys.stdout.write("viewer exited; session still running\n")
        sys.stdout.flush()


def fallback_hint(state: SessionState) -> str:
    if shutil.which("Xephyr"):
        return (
            f"No inline graphics. Try: Xephyr {state.display_name} -parent ... "
            f"or point another X client at DISPLAY={state.display_name}"
        )
    return f"Session ready on DISPLAY={state.display_name}"
