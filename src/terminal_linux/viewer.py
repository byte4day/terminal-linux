from __future__ import annotations

import os
import select
import shutil
import sys
import termios
import time
import tty

from . import actions, activity
from .ansi_frame import display_ansi_frame
from .graphics import (
    clear_screen,
    delete_kitty_image,
    disable_mouse,
    display_png,
    enable_mouse,
    enter_alt_screen,
    file_digest,
    hide_cursor,
    leave_alt_screen,
    scale_png,
    show_cursor,
    supports_inline_graphics,
    terminal_size,
)
from .paths import machine_dir
from .session import SessionError, get_running
from .state import SessionState, is_running, load_state


HELP = "ONE terminal = live computer · agents use MCP on this session · Ctrl+] quit · Ctrl+G shortcuts"


SHORTCUTS = {
    "1": ("ctrl+l", "focus location / clear"),
    "2": ("alt+F4", "close window"),
    "3": ("ctrl+c", "copy / interrupt"),
    "4": ("ctrl+v", "paste"),
    "5": ("alt+Tab", "switch window"),
    "6": ("ctrl+t", "new tab"),
    "7": ("ctrl+w", "close tab"),
    "8": ("ctrl+r", "reload"),
    "9": ("Return", "confirm"),
}


def _read_available(fd: int, timeout: float = 0.05) -> bytes:
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return b""
    return _os_read_all(fd)


def _os_read_all(fd: int) -> bytes:
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
    rows = max(1, rows - 1)
    x = int((col - 1) / max(cols, 1) * state.width)
    y = int((row - 1) / max(rows, 1) * state.height)
    return max(0, min(state.width - 1, x)), max(0, min(state.height - 1, y))


def _status_line(msg: str) -> None:
    cols, rows = terminal_size()
    sys.stdout.write(f"\033[{rows};1H\033[0m\033[48;5;236m\033[38;5;252m\033[2K")
    sys.stdout.write((msg[: max(0, cols - 1)]).ljust(max(0, cols - 1)))
    sys.stdout.write("\033[0m")
    sys.stdout.flush()


def _banner(
    name: str,
    state: SessionState,
    fps: float,
    last_action: str | None,
    *,
    mode: str,
) -> str:
    act = f" · {last_action}" if last_action else " · waiting for agent MCP…"
    return (
        f" terminal-linux/{name} [{mode}] {state.width}x{state.height} "
        f"@{fps:.0f}fps{act}  │  Ctrl+] exit"
    )


def run_viewer(name: str = "default", *, fps: float = 12.0) -> int:
    """Take over THIS terminal as the live computer preview (one-terminal mode)."""
    state = get_running(name)
    # Always show something: Kitty graphics when available, else ANSI half-blocks.
    hiqi = supports_inline_graphics()
    mode = "kitty" if hiqi else "ansi"

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    interval = 1.0 / max(fps, 1.0)
    last_frame = 0.0
    last_digest = ""
    drag_origin: tuple[int, int] | None = None
    buf = b""
    frames = 0
    scaled = machine_dir(name) / "view-frame.png"

    try:
        tty.setraw(fd)
        enter_alt_screen()
        hide_cursor()
        enable_mouse()
        clear_screen()
        activity.note(name, f"viewer attached ({mode})")
        _status_line(_banner(name, state, fps, activity.latest_text(name), mode=mode))

        while True:
            current = load_state(name)
            if not current or not is_running(current):
                _status_line(" session stopped")
                time.sleep(0.4)
                break
            state = current

            now = time.time()
            if now - last_frame >= interval:
                shot = actions.screenshot(state)
                digest = file_digest(shot)
                cols, rows = terminal_size()
                if digest != last_digest:
                    if hiqi:
                        max_w = max(640, min(state.width, cols * 10))
                        max_h = max(400, min(state.height, max(1, rows - 1) * 20))
                        frame = scale_png(shot, scaled, max_w=max_w, max_h=max_h)
                        display_png(frame, cols=cols, rows=max(1, rows - 1))
                    else:
                        display_ansi_frame(shot, cols=cols, rows=rows)
                    last_digest = digest
                    frames += 1
                try:
                    shot.unlink(missing_ok=True)
                except OSError:
                    pass
                last_action = activity.latest_text(name)
                _status_line(_banner(name, state, fps, last_action, mode=mode))
                last_frame = now

            chunk = _read_available(fd, timeout=0.015)
            if not chunk:
                # Still refresh status for agent activity even if frame unchanged.
                if now - last_frame > 0.25:
                    _status_line(_banner(name, state, fps, activity.latest_text(name)))
                continue
            buf += chunk

            if b"\x1d" in buf:  # Ctrl+]
                break

            if b"\x07" in buf:  # Ctrl+G
                buf = buf.replace(b"\x07", b"")
                _status_line(" shortcuts: " + " · ".join(f"{k}={v[0]}" for k, v in SHORTCUTS.items()))
                key = _read_available(fd, timeout=3.0)
                if key:
                    ch = key[:1].decode("latin1", errors="ignore")
                    if ch in SHORTCUTS:
                        actions.press_key(state, SHORTCUTS[ch][0])
                        activity.note(name, f"key {SHORTCUTS[ch][0]}")
                        last_frame = 0
                        last_digest = ""
                continue

            # Mouse
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
                if button & 32:
                    actions.move(state, x, y)
                    continue
                if btn == 64 and pressed:
                    actions.scroll(state, dy=120, x=x, y=y)
                    activity.note(name, f"scroll up @ {x},{y}")
                    last_digest = ""
                    continue
                if btn == 65 and pressed:
                    actions.scroll(state, dy=-120, x=x, y=y)
                    activity.note(name, f"scroll down @ {x},{y}")
                    last_digest = ""
                    continue
                if btn == 0:
                    if pressed:
                        drag_origin = (x, y)
                        actions.move(state, x, y)
                    else:
                        if drag_origin and (
                            abs(drag_origin[0] - x) > 4 or abs(drag_origin[1] - y) > 4
                        ):
                            actions.drag(state, drag_origin[0], drag_origin[1], x, y)
                            activity.note(name, f"drag {drag_origin}→{x},{y}")
                        else:
                            actions.click(state, x, y, button="left")
                            activity.note(name, f"click {x},{y}")
                        drag_origin = None
                        last_frame = 0
                        last_digest = ""
                elif btn == 2 and pressed:
                    actions.click(state, x, y, button="right")
                    activity.note(name, f"right-click {x},{y}")
                    last_frame = 0
                    last_digest = ""
                elif btn == 1 and pressed:
                    actions.click(state, x, y, button="middle")
                    activity.note(name, f"middle-click {x},{y}")
                    last_frame = 0
                    last_digest = ""

            if buf.startswith(b"\033") and len(buf) < 3 and b"\033[<" not in buf:
                continue

            while buf:
                if buf.startswith(b"\033["):
                    if buf.startswith(b"\033[<"):
                        break
                    if len(buf) >= 3 and buf[2] in b"ABCDH":
                        mapping = {
                            ord("A"): "Up",
                            ord("B"): "Down",
                            ord("C"): "Right",
                            ord("D"): "Left",
                            ord("H"): "Home",
                        }
                        if buf[2] in mapping:
                            actions.press_key(state, mapping[buf[2]])
                            activity.note(name, f"key {mapping[buf[2]]}")
                            last_frame = 0
                            last_digest = ""
                        buf = buf[3:]
                        continue
                    buf = buf[1:]
                    continue
                if buf.startswith(b"\033"):
                    if len(buf) >= 2:
                        ch = buf[1:2]
                        buf = buf[2:]
                        if 32 <= ch[0] < 127:
                            actions.press_key(state, f"alt+{chr(ch[0])}")
                            activity.note(name, f"key alt+{chr(ch[0])}")
                            last_frame = 0
                            last_digest = ""
                    break

                ch = buf[0]
                buf = buf[1:]
                if ch == 0x1D:
                    return 0
                if ch == 0x03:  # Ctrl+C → send to guest, don't kill viewer
                    actions.press_key(state, "ctrl+c")
                    activity.note(name, "key ctrl+c")
                    last_digest = ""
                    continue
                if ch in (0x7F, 0x08):
                    actions.press_key(state, "BackSpace")
                    activity.note(name, "key BackSpace")
                    last_digest = ""
                elif ch == 0x09:
                    actions.press_key(state, "Tab")
                    activity.note(name, "key Tab")
                    last_digest = ""
                elif ch in (0x0A, 0x0D):
                    actions.press_key(state, "Return")
                    activity.note(name, "key Return")
                    last_digest = ""
                elif ch == 0x1B:
                    actions.press_key(state, "Escape")
                    activity.note(name, "key Escape")
                    last_digest = ""
                elif 32 <= ch < 127:
                    actions.type_text(state, chr(ch))
                    activity.note(name, f"type {chr(ch)!r}")
                    last_digest = ""
                elif 1 <= ch <= 26:
                    letter = chr(ord("a") + ch - 1)
                    actions.press_key(state, f"ctrl+{letter}")
                    activity.note(name, f"key ctrl+{letter}")
                    last_digest = ""
                last_frame = 0

        return 0
    finally:
        disable_mouse()
        delete_kitty_image()
        show_cursor()
        leave_alt_screen()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write(
            f"viewer exited ({frames} frames); session still running — "
            f"`terminal-linux view {name}` to reattach\n"
        )
        sys.stdout.flush()


def fallback_hint(state: SessionState) -> str:
    if shutil.which("Xephyr"):
        return f"No inline graphics. Session ready on DISPLAY={state.display_name}"
    return f"Session ready on DISPLAY={state.display_name}"
