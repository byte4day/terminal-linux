from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
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


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes via a same-directory temp file + os.replace (atomic on POSIX)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def extract_png_frames(buf: bytes) -> tuple[list[bytes], bytes]:
    """Split concatenated PNG bytes into complete frames + remainder."""
    frames: list[bytes] = []
    while True:
        start = buf.find(PNG_SIG)
        if start < 0:
            return frames, b""
        if start > 0:
            buf = buf[start:]
        iend = buf.find(b"\x00\x00\x00\x00IEND")
        if iend < 0:
            return frames, buf
        end = iend + 12  # length(0) + IEND + CRC
        if len(buf) < end:
            return frames, buf
        frame = buf[:end]
        if png_complete(frame):
            frames.append(frame)
        buf = buf[end:]


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
            src.load()  # force decode now
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
    except Exception:
        # Torn/partial frame or Pillow quirk — skip overlay this tick.
        return frame


class CaptureStream:
    """
    Persistent ffmpeg x11grab writer.

    Frames are emitted on stdout as concatenated PNGs; a reader thread publishes
    each complete frame with an atomic replace so the viewer never opens a torn file.
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
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        if self.alive:
            return
        if not shutil.which("ffmpeg"):
            return
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
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
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "pipe:1",
        ]
        self.proc = subprocess.Popen(
            cmd,
            env=self.state.env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._reader = threading.Thread(
            target=self._pump_frames,
            name="terminal-linux-capture",
            daemon=True,
        )
        self._reader.start()

    def _pump_frames(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        buf = b""
        try:
            while not self._stop.is_set():
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk
                frames, buf = extract_png_frames(buf)
                for frame in frames:
                    try:
                        atomic_write_bytes(self.dest, frame)
                    except OSError:
                        pass
                # Cap buffer if ffmpeg ever emits garbage without IEND.
                if len(buf) > 8_000_000:
                    buf = buf[-1_000_000:]
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()
        if not self.proc:
            self._reader = None
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                self.proc.terminate()
            except Exception:
                pass
        try:
            if self.proc.stdout:
                self.proc.stdout.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=2)
        except Exception:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except Exception:
                pass
        if self._reader and self._reader.is_alive():
            self._reader.join(timeout=1.0)
        self.proc = None
        self._reader = None

    def latest(self) -> Path | None:
        if self.dest.exists() and self.dest.stat().st_size > 0:
            return self.dest
        return None

    def snapshot(self, *, retries: int = 10, delay: float = 0.005) -> Path | None:
        """
        Copy a complete live PNG to a sidecar path.

        Dest is atomically replaced, but we still verify PNG integrity before use.
        """
        stable = self.dest.with_name(self.dest.stem + ".stable.png")
        for _ in range(max(1, retries)):
            try:
                data = self.dest.read_bytes()
            except OSError:
                data = b""
            if png_complete(data):
                try:
                    atomic_write_bytes(stable, data)
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
