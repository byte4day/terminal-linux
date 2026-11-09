from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


KITTY_IMAGE_ID = 42


def supports_kitty_graphics() -> bool:
    term = os.environ.get("TERM", "")
    prog = os.environ.get("TERM_PROGRAM", "")
    if "kitty" in term or prog.lower() in {"kitty", "ghostty", "wezterm"}:
        return True
    if os.environ.get("KITTY_WINDOW_ID") or os.environ.get("GHOSTTY_RESOURCES_DIR"):
        return True
    # Many modern terminals still speak the Kitty graphics protocol.
    if os.environ.get("TERM_PROGRAM", "").lower() in {"warpterminal", "vscode"}:
        return False
    return "xterm-kitty" in term or term.endswith("-kitty")


def supports_iterm_graphics() -> bool:
    return os.environ.get("TERM_PROGRAM", "") == "iTerm.app"


def supports_inline_graphics() -> bool:
    return supports_kitty_graphics() or supports_iterm_graphics()


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


def terminal_size() -> tuple[int, int]:
    try:
        size = os.get_terminal_size()
        return size.columns, size.lines
    except OSError:
        return 80, 24


def file_digest(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def scale_png(src: Path, dest: Path, *, max_w: int, max_h: int) -> Path:
    """Downscale for faster terminal transfers. Falls back to src on failure."""
    magick = shutil.which("magick") or shutil.which("convert")
    if not magick or max_w < 32 or max_h < 32:
        return src
    try:
        subprocess.run(
            [
                magick,
                str(src),
                "-resize",
                f"{max_w}x{max_h}>",
                str(dest),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if dest.exists() and dest.stat().st_size > 0:
            return dest
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    return src


def display_png_kitty(
    path: Path,
    *,
    cols: int | None = None,
    rows: int | None = None,
    image_id: int = KITTY_IMAGE_ID,
) -> None:
    data = path.read_bytes()
    b64 = base64.standard_b64encode(data).decode("ascii")
    chunks = [b64[i : i + 4096] for i in range(0, len(b64), 4096)] or [""]

    # Place at home, reuse same image id so frames replace in-place (video-like).
    sys.stdout.write("\033[H")
    for i, chunk in enumerate(chunks):
        more = 1 if i < len(chunks) - 1 else 0
        if i == 0:
            extras = [
                "a=T",
                "f=100",
                f"i={image_id}",
                "q=2",
                f"m={more}",
                "C=1",  # don't move cursor after image
            ]
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
    sys.stdout.write(
        f"\033]1337;File=inline=1;preserveAspectRatio=1;size={len(data)}:{b64}\a"
    )
    sys.stdout.flush()


def display_png(path: Path, *, cols: int | None = None, rows: int | None = None) -> bool:
    if supports_kitty_graphics():
        display_png_kitty(path, cols=cols, rows=rows)
        return True
    if supports_iterm_graphics():
        display_png_iterm(path)
        return True
    return False


def delete_kitty_image(image_id: int = KITTY_IMAGE_ID) -> None:
    if not supports_kitty_graphics():
        return
    sys.stdout.write(f"\033_Ga=d,d=i,i={image_id}\033\\")
    sys.stdout.flush()


def enable_mouse() -> None:
    sys.stdout.write("\033[?1003h\033[?1006h")
    sys.stdout.flush()


def disable_mouse() -> None:
    sys.stdout.write("\033[?1003l\033[?1006l")
    sys.stdout.flush()


def enter_alt_screen() -> None:
    sys.stdout.write("\033[?1049h")
    sys.stdout.flush()


def leave_alt_screen() -> None:
    sys.stdout.write("\033[?1049l")
    sys.stdout.flush()
