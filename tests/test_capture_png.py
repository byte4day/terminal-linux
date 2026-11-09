from pathlib import Path

from PIL import Image

from terminal_linux.capture import Pointer, draw_agent_cursor, png_complete


def test_png_complete_accepts_real_png(tmp_path: Path):
    path = tmp_path / "ok.png"
    Image.new("RGB", (8, 8), color=(10, 20, 30)).save(path, format="PNG")
    assert png_complete(path.read_bytes())


def test_png_complete_rejects_torn_png():
    torn = b"\x89PNG\r\n\x1a\n" + b"Q\xaf\xea\xc5" * 20
    assert not png_complete(torn)


def test_draw_agent_cursor_skips_broken_png(tmp_path: Path):
    broken = tmp_path / "live-frame.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\n" + b"Q\xaf\xea\xc5" * 40)
    out = draw_agent_cursor(broken, Pointer(10, 10), src_w=100, src_h=100)
    assert out == broken


def test_draw_agent_cursor_writes_overlay(tmp_path: Path):
    frame = tmp_path / "live-frame.png"
    Image.new("RGB", (64, 48), color=(0, 0, 0)).save(frame, format="PNG")
    out = draw_agent_cursor(frame, Pointer(32, 24), src_w=64, src_h=48)
    assert out != frame
    assert out.exists()
    assert png_complete(out.read_bytes())
