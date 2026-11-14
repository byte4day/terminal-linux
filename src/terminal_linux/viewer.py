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
from .capture import CaptureStream, draw_agent_cursor, pointer_position
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
    show_cursor,
    supports_inline_graphics,
    terminal_size,
)
from .paths import machine_dir
from .errors import SessionError
from .session import get_running, running_session_names
from .state import SessionState, is_running, load_state


HELP = (
    "LIVE · tabs Alt+←/→ or Alt+1-9 · mouse/keys drive guest · Ctrl+G shortcuts · Ctrl+] quit"
)


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


class _GuestInput:
    """`actions.*` for keys and mouse typed into the live view.

    A key the guest cannot take (an unknown keysym, a point off the screen)
    is shown in the status line instead of ending the preview.
    """

    def __getattr__(self, attr: str):
        fn = getattr(actions, attr)

        def call(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except SessionError as exc:
                _status_line(f" input not sent: {exc}")
                return None

        return call


guest = _GuestInput()


def _alt_chord(ch: int) -> str:
    """Alt+<printable byte> as a key chord ('alt+space' for a blank)."""
    return "alt+space" if ch == 32 else f"alt+{chr(ch)}"


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


def _tab_strip(active: str, tabs: list[str]) -> str:
    if not tabs:
        return f"[{active}]"
    parts: list[str] = []
    for i, name in enumerate(tabs[:9], start=1):
        label = f"{i}:{name}"
        parts.append(f"[{label}]" if name == active else label)
    extra = len(tabs) - 9
    if extra > 0:
        parts.append(f"+{extra}")
    return " ".join(parts)


def _banner(
    name: str,
    state: SessionState,
    fps: float,
    last_action: str | None,
    *,
    mode: str,
    cursor: tuple[int, int] | None,
    tabs: list[str],
) -> str:
    act = f" · {last_action}" if last_action else " · waiting for agent…"
    cur = f" · cursor {cursor[0]},{cursor[1]}" if cursor else ""
    strip = _tab_strip(name, tabs)
    return (
        f" {strip}  │  {state.width}x{state.height} @{fps:.0f}fps [{mode}]"
        f"{cur}{act}  │  Alt+←/→ tabs · Ctrl+] exit"
    )


def _open_stream(name: str, state: SessionState, fps: float) -> CaptureStream:
    cols, _rows = terminal_size()
    max_w = max(640, min(state.width, cols * 12))
    frame_path = machine_dir(name) / "live-frame.png"
    stream = CaptureStream(state, frame_path, fps=fps, max_w=max_w)
    stream.start()
    return stream


def _csi_params(seq: bytes) -> tuple[list[int], int] | None:
    """Parse CSI sequences like ESC [ 1 ; 3 D → ([1, 3], ord('D'))."""
    if not seq.startswith(b"\033["):
        return None
    i = 2
    params: list[int] = []
    cur = ""
    while i < len(seq):
        ch = seq[i]
        if 48 <= ch <= 57:  # digit
            cur += chr(ch)
            i += 1
            continue
        if ch == 59:  # ;
            params.append(int(cur) if cur else 0)
            cur = ""
            i += 1
            continue
        if cur:
            params.append(int(cur))
        return params, ch
    return None


def run_viewer(name: str = "default", *, fps: float = 20.0, show_cursor_overlay: bool = True) -> int:
    """Take over THIS terminal as the live computer preview (multi-session tabs)."""
    state = get_running(name)
    hiqi = supports_inline_graphics()
    mode = "kitty" if hiqi else "ansi"
    fps = max(8.0, min(fps, 30.0))

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    interval = 1.0 / fps
    last_frame = 0.0
    last_digest = ""
    last_tab_refresh = 0.0
    drag_origin: tuple[int, int] | None = None
    buf = b""
    frames = 0
    cursor_xy: tuple[int, int] | None = None
    tabs = running_session_names(prefer=name)
    stream = _open_stream(name, state, fps)
    if not stream.alive:
        mode = mode + "+import"

    def switch_to(target: str) -> bool:
        nonlocal name, state, stream, last_digest, cursor_xy, drag_origin, tabs, mode
        if target == name:
            return True
        try:
            nxt = get_running(target)
        except SessionError:
            _status_line(f" session {target!r} is not running")
            return False
        stream.stop()
        name = target
        state = nxt
        last_digest = ""
        cursor_xy = None
        drag_origin = None
        tabs = running_session_names(prefer=name)
        stream = _open_stream(name, state, fps)
        mode = ("kitty" if hiqi else "ansi") + ("" if stream.alive else "+import")
        activity.note(name, f"viewer switched to tab {name}")
        clear_screen()
        return True

    def cycle(delta: int) -> None:
        nonlocal tabs
        tabs = running_session_names(prefer=name)
        if len(tabs) < 2:
            _status_line(" only one running session — start another with: terminal-linux up NAME")
            return
        try:
            idx = tabs.index(name)
        except ValueError:
            idx = 0
        switch_to(tabs[(idx + delta) % len(tabs)])

    try:
        tty.setraw(fd)
        enter_alt_screen()
        hide_cursor()
        enable_mouse()
        clear_screen()
        activity.note(name, f"viewer attached ({mode})")
        _status_line(
            _banner(
                name,
                state,
                fps,
                activity.latest_text(name),
                mode=mode,
                cursor=None,
                tabs=tabs,
            )
        )

        while True:
            now = time.time()
            if now - last_tab_refresh >= 1.0:
                tabs = running_session_names(prefer=name)
                last_tab_refresh = now
                if name not in tabs:
                    # Current session died — jump to another running tab if any.
                    if tabs:
                        switch_to(tabs[0])
                    else:
                        _status_line(" session stopped")
                        time.sleep(0.3)
                        break

            current = load_state(name)
            if not current or not is_running(current):
                tabs = running_session_names()
                if tabs:
                    switch_to(tabs[0])
                    continue
                _status_line(" session stopped")
                time.sleep(0.3)
                break
            state = current

            if now - last_frame >= interval:
                try:
                    ptr = pointer_position(state)
                    if ptr:
                        cursor_xy = (ptr.x, ptr.y)

                    # Prefer a complete PNG snapshot — ffmpeg rewrites live-frame.png in place.
                    shot = stream.snapshot()
                    if shot is None:
                        # One fixed file: a fresh temp file per frame would fill /tmp.
                        shot = actions.screenshot(state, machine_dir(name) / "live-fallback.png")

                    digest = file_digest(shot)
                    cols, rows = terminal_size()
                    if digest != last_digest or (show_cursor_overlay and ptr):
                        display_path = shot
                        if show_cursor_overlay and ptr:
                            display_path = draw_agent_cursor(
                                shot, ptr, src_w=state.width, src_h=state.height
                            )
                        if hiqi:
                            display_png(display_path, cols=cols, rows=max(1, rows - 1))
                        else:
                            display_ansi_frame(display_path, cols=cols, rows=rows)
                        if display_path != shot:
                            try:
                                display_path.unlink(missing_ok=True)
                            except OSError:
                                pass
                        last_digest = digest
                        frames += 1

                    _status_line(
                        _banner(
                            name,
                            state,
                            fps,
                            activity.latest_text(name),
                            mode=mode,
                            cursor=cursor_xy,
                            tabs=tabs,
                        )
                    )
                except Exception:
                    # Never let a torn capture frame kill the live preview.
                    pass
                last_frame = now

            chunk = _read_available(fd, timeout=0.01)
            if not chunk:
                continue
            buf += chunk

            if b"\x1d" in buf:  # Ctrl+]
                break

            if b"\x07" in buf:  # Ctrl+G
                buf = buf.replace(b"\x07", b"")
                _status_line(
                    " shortcuts: "
                    + " · ".join(f"{k}={v[0]}" for k, v in SHORTCUTS.items())
                    + " · Alt+←/→ session tabs"
                )
                key = _read_available(fd, timeout=3.0)
                if key:
                    ch = key[:1].decode("latin1", errors="ignore")
                    if ch in SHORTCUTS:
                        guest.press_key(state, SHORTCUTS[ch][0])
                        activity.note(name, f"key {SHORTCUTS[ch][0]}")
                        last_digest = ""
                continue

            # Mouse -> guest (you use the terminal as the desktop too)
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
                    guest.move(state, x, y)
                    cursor_xy = (x, y)
                    continue
                if btn == 64 and pressed:
                    guest.scroll(state, dy=120, x=x, y=y)
                    activity.note(name, f"scroll up @ {x},{y}")
                    last_digest = ""
                    continue
                if btn == 65 and pressed:
                    guest.scroll(state, dy=-120, x=x, y=y)
                    activity.note(name, f"scroll down @ {x},{y}")
                    last_digest = ""
                    continue
                if btn == 0:
                    if pressed:
                        drag_origin = (x, y)
                        guest.move(state, x, y)
                        cursor_xy = (x, y)
                    else:
                        if drag_origin and (
                            abs(drag_origin[0] - x) > 4 or abs(drag_origin[1] - y) > 4
                        ):
                            guest.drag(state, drag_origin[0], drag_origin[1], x, y)
                            activity.note(name, f"drag {drag_origin}→{x},{y}")
                        else:
                            guest.click(state, x, y, button="left")
                            activity.note(name, f"click {x},{y}")
                        drag_origin = None
                        cursor_xy = (x, y)
                        last_digest = ""
                elif btn == 2 and pressed:
                    guest.click(state, x, y, button="right")
                    activity.note(name, f"right-click {x},{y}")
                    cursor_xy = (x, y)
                    last_digest = ""
                elif btn == 1 and pressed:
                    guest.click(state, x, y, button="middle")
                    activity.note(name, f"middle-click {x},{y}")
                    cursor_xy = (x, y)
                    last_digest = ""

            if buf.startswith(b"\033") and len(buf) < 3 and b"\033[<" not in buf:
                continue

            while buf:
                if buf.startswith(b"\033["):
                    if buf.startswith(b"\033[<"):
                        break
                    # Need enough bytes for CSI + final (e.g. ESC [ 1 ; 3 D)
                    if len(buf) < 3:
                        break
                    # Find final byte (0x40-0x7E)
                    final_i = None
                    for i in range(2, min(len(buf), 24)):
                        if 0x40 <= buf[i] <= 0x7E:
                            final_i = i
                            break
                    if final_i is None:
                        if len(buf) >= 24:
                            buf = buf[1:]
                            continue
                        break
                    seq = buf[: final_i + 1]
                    buf = buf[final_i + 1 :]
                    parsed = _csi_params(seq)
                    if not parsed:
                        continue
                    params, final = parsed
                    # Alt+Left / Alt+Right (and Ctrl+PageUp/Down) → session tabs
                    if final in (ord("D"), ord("C")) and len(params) >= 2 and params[1] in (3, 5):
                        cycle(-1 if final == ord("D") else 1)
                        continue
                    if final == ord("~") and params:
                        code = params[0]
                        mod = params[1] if len(params) > 1 else 0
                        if code == 5 and mod in (3, 5):  # PageUp
                            cycle(-1)
                            continue
                        if code == 6 and mod in (3, 5):  # PageDown
                            cycle(1)
                            continue
                    if final in b"ABCDH" and (not params or params == [1]):
                        mapping = {
                            ord("A"): "Up",
                            ord("B"): "Down",
                            ord("C"): "Right",
                            ord("D"): "Left",
                            ord("H"): "Home",
                        }
                        if final in mapping:
                            guest.press_key(state, mapping[final])
                            activity.note(name, f"key {mapping[final]}")
                            last_digest = ""
                        continue
                    continue

                if buf.startswith(b"\033"):
                    if len(buf) < 2:
                        break
                    ch = buf[1]
                    # Alt+1..9 → jump to Nth tab
                    if ord("1") <= ch <= ord("9"):
                        buf = buf[2:]
                        tabs = running_session_names(prefer=name)
                        idx = ch - ord("1")
                        if idx < len(tabs):
                            switch_to(tabs[idx])
                        else:
                            _status_line(f" no session tab {idx + 1}")
                        continue
                    # Alt+[/] also cycle tabs
                    if ch in (ord("["), ord("]")):
                        buf = buf[2:]
                        cycle(-1 if ch == ord("[") else 1)
                        continue
                    if 32 <= ch < 127:
                        buf = buf[2:]
                        guest.press_key(state, _alt_chord(ch))
                        activity.note(name, f"key {_alt_chord(ch)}")
                        last_digest = ""
                        continue
                    buf = buf[1:]
                    continue

                ch = buf[0]
                buf = buf[1:]
                if ch == 0x1D:
                    return 0
                if ch == 0x03:
                    guest.press_key(state, "ctrl+c")
                    activity.note(name, "key ctrl+c")
                    last_digest = ""
                    continue
                if ch in (0x7F, 0x08):
                    guest.press_key(state, "BackSpace")
                    last_digest = ""
                elif ch == 0x09:
                    guest.press_key(state, "Tab")
                    last_digest = ""
                elif ch in (0x0A, 0x0D):
                    guest.press_key(state, "Return")
                    last_digest = ""
                elif ch == 0x1B:
                    guest.press_key(state, "Escape")
                    last_digest = ""
                elif 32 <= ch < 127:
                    guest.type_text(state, chr(ch))
                    last_digest = ""
                elif 1 <= ch <= 26:
                    letter = chr(ord("a") + ch - 1)
                    guest.press_key(state, f"ctrl+{letter}")
                    last_digest = ""

        return 0
    finally:
        stream.stop()
        disable_mouse()
        delete_kitty_image()
        show_cursor()
        leave_alt_screen()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write(
            f"viewer exited ({frames} frames); session still running. "
            f"Reattach: terminal-linux view {name}\n"
        )
        sys.stdout.flush()


def fallback_hint(state: SessionState) -> str:
    if shutil.which("Xephyr"):
        return f"No inline graphics. Session ready on DISPLAY={state.display_name}"
    return f"Session ready on DISPLAY={state.display_name}"
