from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .state import SessionState

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]

PNG_SIG = b"\x89PNG\r\n\x1a\n"
# Pillow raises SyntaxError on torn PNGs (chunk parse), not just OSError.
_PNG_OPEN_ERRORS = (OSError, SyntaxError, ValueError)


def png_complete(data: bytes) -> bool:
    """True when bytes look like a finished PNG (signature + IEND trailer)."""
    return (
        len(data) >= 57
        and data.startswith(PNG_SIG)
        and b"\x00\x00\x00\x00IEND" in data[-16:]
    )


@dataclass
class Pointer:
    x: int
    y: int


def pointer_position(state: SessionState) -> Pointer | None:
    try:
        proc = subprocess.run(
            ["xdotool", "getmouselocation", "--shell"],
            check=True,
            env=state.env(),
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    vals: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if v.lstrip("-").isdigit():
                vals[k.lower()] = int(v)
    if "x" in vals and "y" in vals:
        return Pointer(vals["x"], vals["y"])
    return None


def draw_agent_cursor(frame: Path, pointer: Pointer, *, src_w: int, src_h: int) -> Path:
    """Draw a bright agent pointer onto the frame (scaled to frame pixels)."""
    if Image is None or ImageDraw is None:
        return frame
    try:
        with Image.open(frame) as src:
            src.load()  # force decode now; ffmpeg may still be rewriting the live file
            im = src.convert("RGBA")
        fw, fh = im.size
        x = int(pointer.x / max(src_w, 1) * fw)
        y = int(pointer.y / max(src_h, 1) * fh)
        x = max(0, min(fw - 1, x))
        y = max(0, min(fh - 1, y))

        overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        # Arrow pointer
        pts = [
            (x, y),
            (x, y + 18),
            (x + 5, y + 14),
            (x + 11, y + 24),
            (x + 15, y + 22),
            (x + 8, y + 12),
            (x + 14, y + 12),
        ]
        d.polygon(pts, fill=(255, 64, 64, 230), outline=(255, 255, 255, 255))
        # hotspot ring so it's obvious even on red UIs
        d.ellipse((x - 3, y - 3, x + 3, y + 3), outline=(255, 255, 0, 255), width=2)
        out = im.convert("RGBA")
        out.alpha_composite(overlay)
        dest = frame.with_name(frame.stem + "-cursor.png")
        out.convert("RGB").save(dest, format="PNG", optimize=True)
        return dest
    except _PNG_OPEN_ERRORS:
        # Torn in-place ffmpeg frame — skip overlay this tick.
        return frame


class CaptureStream:
    """
    Persistent ffmpeg x11grab writer.

    Spawning ffmpeg/import per frame is what made the viewer feel slow.
    This keeps one capture process alive and updates a single PNG in place.
    """

    def __init__(
        self,
        state: SessionState,
        dest: Path,
        *,
        fps: float = 20.0,
        max_w: int = 960,
    ) -> None:
        self.state = state
        self.dest = dest
        self.fps = max(5.0, min(fps, 30.0))
        self.max_w = max_w
        self.proc: subprocess.Popen[bytes] | None = None

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        if self.alive:
            return
        if not shutil.which("ffmpeg"):
            return
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        # Seed a first frame quickly with import so the viewer isn't blank.
        try:
            subprocess.run(
                ["import", "-window", "root", str(self.dest)],
                check=False,
                env=self.state.env(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

        vf = f"scale={self.max_w}:-2"
        cmd = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "x11grab",
            "-framerate",
            str(self.fps),
            "-video_size",
            f"{self.state.width}x{self.state.height}",
            "-i",
            f"{self.state.display_name}.0",
            "-vf",
            vf,
            "-update",
            "1",
            "-y",
            str(self.dest),
        ]
        self.proc = subprocess.Popen(
            cmd,
            env=self.state.env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def stop(self) -> None:
        if not self.proc:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                self.proc.terminate()
            except Exception:
                pass
        try:
            self.proc.wait(timeout=2)
        except Exception:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except Exception:
                pass
        self.proc = None

    def latest(self) -> Path | None:
        if self.dest.exists() and self.dest.stat().st_size > 0:
            return self.dest
        return None

    def snapshot(self, *, retries: int = 10, delay: float = 0.005) -> Path | None:
        """
        Copy a complete live PNG to a sidecar path.

        ffmpeg -update 1 rewrites dest in place, so readers can see a torn file.
        We only publish bytes that parse as a finished PNG.
        """
        stable = self.dest.with_name(self.dest.stem + ".stable.png")
        for _ in range(max(1, retries)):
            try:
                data = self.dest.read_bytes()
            except OSError:
                data = b""
            if png_complete(data):
                try:
                    stable.write_bytes(data)
                    return stable
                except OSError:
                    return None
            time.sleep(delay)
        return None

    def wait_frame(self, timeout: float = 1.0) -> Path | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self.snapshot(retries=2, delay=0.01)
            if frame:
                return frame
            time.sleep(0.02)
        return None
