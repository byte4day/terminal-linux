from pathlib import Path

from PIL import Image

from terminal_linux.capture import (
    Pointer,
    atomic_write_bytes,
    draw_agent_cursor,
    extract_png_frames,
    png_complete,
)


def _png_bytes(size: tuple[int, int] = (8, 8), color=(10, 20, 30)) -> bytes:
    from io import BytesIO

    buf = BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


def test_png_complete_accepts_real_png(tmp_path: Path):
    path = tmp_path / "ok.png"
    path.write_bytes(_png_bytes())
    assert png_complete(path.read_bytes())


def test_png_complete_rejects_torn_png():
    torn = b"\x89PNG\r\n\x1a\n" + b"Q\xaf\xea\xc5" * 20
    assert not png_complete(torn)


def test_extract_png_frames_splits_concatenated():
    a = _png_bytes((4, 4), (1, 2, 3))
    b = _png_bytes((5, 5), (4, 5, 6))
    frames, rest = extract_png_frames(a + b + a[:10])
    assert frames == [a, b]
    assert rest.startswith(b"\x89PNG")


def test_atomic_write_bytes(tmp_path: Path):
    path = tmp_path / "live-frame.png"
    data = _png_bytes()
    atomic_write_bytes(path, data)
    assert path.read_bytes() == data
    assert not any(tmp_path.glob("*.tmp"))


def test_draw_agent_cursor_skips_broken_png(tmp_path: Path):
    broken = tmp_path / "live-frame.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\n" + b"Q\xaf\xea\xc5" * 40)
    out = draw_agent_cursor(broken, Pointer(10, 10), src_w=100, src_h=100)
    assert out == broken


def test_draw_agent_cursor_writes_overlay(tmp_path: Path):
    frame = tmp_path / "live-frame.png"
    frame.write_bytes(_png_bytes((64, 48), (0, 0, 0)))
    out = draw_agent_cursor(frame, Pointer(32, 24), src_w=64, src_h=48)
    assert out != frame
    assert out.exists()
    assert png_complete(out.read_bytes())
