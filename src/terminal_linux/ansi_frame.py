from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def _magick() -> str | None:
    return shutil.which("magick") or shutil.which("convert")


def render_halfblocks(path: Path, *, cols: int, rows: int) -> str:
    """
    Render a PNG as ANSI half-block art (works in almost any terminal).
    Each terminal row = 2 image rows (▀ upper fg / lower bg).
    """
    magick = _magick()
    if not magick or cols < 8 or rows < 4:
        return ""

    # rows of text cells; each cell covers 2 vertical pixels
    img_w = max(8, cols)
    img_h = max(4, rows * 2)
    try:
        proc = subprocess.run(
            [
                magick,
                str(path),
                "-resize",
                f"{img_w}x{img_h}!",
                "-depth",
                "8",
                "ppm:-",
            ],
            check=True,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""

    data = proc.stdout
    # PPM P6 header
    if not data.startswith(b"P6"):
        return ""
    # Skip comments / header
    i = 2
    while i < len(data) and data[i] in b" \t\r\n":
        i += 1
    # optional comment lines
    while i < len(data) and data[i] == ord("#"):
        while i < len(data) and data[i] not in b"\n":
            i += 1
        i += 1
        while i < len(data) and data[i] in b" \t\r\n":
            i += 1

    def read_token() -> str:
        nonlocal i
        while i < len(data) and data[i] in b" \t\r\n":
            i += 1
        start = i
        while i < len(data) and data[i] not in b" \t\r\n":
            i += 1
        return data[start:i].decode("ascii", errors="ignore")

    try:
        width = int(read_token())
        height = int(read_token())
        maxval = int(read_token())
    except ValueError:
        return ""
    if maxval != 255:
        return ""
    while i < len(data) and data[i] in b" \t\r":
        i += 1
    if i < len(data) and data[i] == ord("\n"):
        i += 1
    pixels = data[i:]
    need = width * height * 3
    if len(pixels) < need:
        return ""

    def px(x: int, y: int) -> tuple[int, int, int]:
        o = (y * width + x) * 3
        return pixels[o], pixels[o + 1], pixels[o + 2]

    out: list[str] = []
    # Ensure even height
    h = height - (height % 2)
    for y in range(0, h, 2):
        row_chars: list[str] = []
        for x in range(width):
            r1, g1, b1 = px(x, y)
            r2, g2, b2 = px(x, y + 1)
            # ▀ = upper half with fg, lower half with bg
            row_chars.append(
                f"\033[38;2;{r1};{g1};{b1}m\033[48;2;{r2};{g2};{b2}m▀"
            )
        row_chars.append("\033[0m")
        out.append("".join(row_chars))
    return "\n".join(out)


def display_ansi_frame(path: Path, *, cols: int, rows: int) -> bool:
    frame = render_halfblocks(path, cols=cols, rows=max(1, rows - 1))
    if not frame:
        return False
    sys.stdout.write("\033[H")
    sys.stdout.write(frame)
    if not frame.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()
    return True
