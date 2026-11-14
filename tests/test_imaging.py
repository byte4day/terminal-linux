from __future__ import annotations

import pytest
from PIL import Image

from terminal_linux import imaging
from terminal_linux.errors import SessionError


def _screen(w=400, h=300, color=(20, 20, 20)):
    return Image.new("RGB", (w, h), color)


def test_parse_region_forms_and_clamp():
    assert imaging.parse_region("10,20,100,50", 400, 300) == (10, 20, 100, 50)
    assert imaging.parse_region([10, 20, 100, 50], 400, 300) == (10, 20, 100, 50)
    assert imaging.parse_region("350,250,100,100", 400, 300) == (350, 250, 50, 50)
    assert imaging.parse_region(None, 400, 300) is None


@pytest.mark.parametrize("bad", ["1,2,3", "a,b,c,d", "0,0,0,10", "500,0,10,10", [1, 2]])
def test_parse_region_rejects(bad):
    with pytest.raises(SessionError):
        imaging.parse_region(bad, 400, 300)


def test_region_crop_and_zoom_sizes():
    out = imaging.render(_screen(), region=(100, 50, 120, 80), zoom=3)
    assert out.size == (360, 240)
    assert imaging.render(_screen(), zoom=99).size == (1600, 1200)  # zoom is capped at 4


def test_grid_keeps_size_and_draws():
    plain = _screen()
    out = imaging.render(plain, grid=True)
    assert out.size == plain.size
    assert imaging.changed_fraction(plain, out) > 0.01


def test_grid_lines_sit_on_screen_coordinates_in_a_zoomed_crop():
    # Crop starts at screen x=130; with step 100 the first line is screen x=200,
    # which is crop x=70, drawn at 70*2=140 after 2x zoom.
    base = imaging.render(_screen(), region=(130, 0, 200, 100), zoom=2)
    out = imaging.draw_grid(base, 100, origin=(130, 0), scale=2)
    row = 150  # below the labels
    assert out.getpixel((140, row)) != base.getpixel((140, row))
    assert out.getpixel((100, row)) == base.getpixel((100, row))


def test_pick_grid_step():
    assert imaging.pick_grid_step(1280, 800) == 100
    assert imaging.pick_grid_step(200, 100) == 20


def test_changed_fraction():
    a = _screen(100, 100)
    b = a.copy()
    assert imaging.changed_fraction(a, b) == 0.0
    b.putpixel((5, 5), (255, 255, 255))
    assert imaging.changed_fraction(a, b) == pytest.approx(1 / 10000)
    assert imaging.changed_fraction(a, _screen(50, 50)) == 1.0
    # A one-step change in one channel still counts as a change.
    assert imaging.changed_fraction(_screen(10, 10, (0, 0, 0)), _screen(10, 10, (0, 0, 1))) == 1.0
