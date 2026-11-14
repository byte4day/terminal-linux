"""Pure image helpers for screenshots: region crops, coordinate grids, change detection.

Nothing here needs an X display, so all of it is unit-tested.
"""

from __future__ import annotations

from typing import Sequence

from PIL import Image, ImageChops, ImageDraw

from .errors import SessionError

Region = tuple[int, int, int, int]  # x, y, width, height in screen pixels


def parse_region(value: str | Sequence[int] | None, screen_w: int, screen_h: int) -> Region | None:
    """Accept 'X,Y,W,H' or [x, y, w, h]; clamp to the screen; reject empty areas."""
    if value is None or value == "" or value == []:
        return None
    try:
        parts = [int(p) for p in (value.replace("x", ",").split(",") if isinstance(value, str) else value)]
    except (TypeError, ValueError):
        parts = []
    if len(parts) != 4:
        raise SessionError("region must be X,Y,WIDTH,HEIGHT", code="bad_args")
    x, y, w, h = parts
    x2, y2 = min(x + w, screen_w), min(y + h, screen_h)
    x, y = max(0, x), max(0, y)
    if w <= 0 or h <= 0 or x >= x2 or y >= y2:
        raise SessionError(
            f"region {parts} is empty or outside the {screen_w}x{screen_h} screen", code="out_of_bounds"
        )
    return x, y, x2 - x, y2 - y


def crop_region(im: Image.Image, region: Region) -> Image.Image:
    x, y, w, h = region
    return im.crop((x, y, x + w, y + h))


def pick_grid_step(width: int, height: int) -> int:
    """A step that gives roughly 8 to 16 columns of labels."""
    for step in (10, 20, 25, 50, 100, 200, 250, 500):
        if max(width, height) / step <= 16:
            return step
    return 500


def draw_grid(
    im: Image.Image,
    step: int = 0,
    *,
    origin: tuple[int, int] = (0, 0),
    scale: int = 1,
) -> Image.Image:
    """Overlay grid lines labelled with *screen* coordinates.

    ``origin`` is the screen position of the image's top-left corner (non-zero
    for a region crop) and ``scale`` is how much the image was enlarged, so the
    labels always read in the pixel space that click/move/drag expect.
    """
    scale = max(1, int(scale))
    if step <= 0:
        step = pick_grid_step(im.width // scale, im.height // scale)
    ox, oy = origin
    base = im.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    line = (255, 60, 200, 110)
    label_bg = (0, 0, 0, 190)
    label_fg = (255, 255, 255, 255)

    def labels(text: str, x: int, y: int) -> None:
        box = d.textbbox((x, y), text)
        d.rectangle((box[0] - 1, box[1] - 1, box[2] + 1, box[3] + 1), fill=label_bg)
        d.text((x, y), text, fill=label_fg)

    first_x = (-ox) % step  # screen-x of the first line, relative to the crop
    for sx in range(first_x, im.width // scale + 1, step):
        px = sx * scale
        d.line((px, 0, px, base.height), fill=line, width=1)
        labels(str(ox + sx), min(px + 2, base.width - 30), 2)
    first_y = (-oy) % step
    for sy in range(first_y, im.height // scale + 1, step):
        py = sy * scale
        d.line((0, py, base.width, py), fill=line, width=1)
        labels(str(oy + sy), 2, min(py + 2, base.height - 12))
    base.alpha_composite(overlay)
    return base.convert("RGB")


def render(
    im: Image.Image,
    *,
    region: Region | None = None,
    grid: int | bool = False,
    zoom: int = 1,
) -> Image.Image:
    """Apply crop → zoom → grid. ``grid`` is a step in pixels, or True for automatic."""
    out = im.convert("RGB")
    origin = (0, 0)
    if region is not None:
        out = crop_region(out, region)
        origin = (region[0], region[1])
    zoom = max(1, min(int(zoom), 4))
    if zoom > 1:
        out = out.resize((out.width * zoom, out.height * zoom), Image.Resampling.LANCZOS)
    if grid:
        out = draw_grid(out, 0 if grid is True else int(grid), origin=origin, scale=zoom)
    return out


def changed_fraction(a: Image.Image, b: Image.Image) -> float:
    """Share of pixels that differ between two frames (1.0 when sizes differ)."""
    if a.size != b.size:
        return 1.0
    r, g, b_ = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).split()
    # Brightest channel difference per pixel. (A luma conversion would round a
    # one-step change in a single channel down to "no change".)
    diff = ImageChops.lighter(ImageChops.lighter(r, g), b_)
    total = a.width * a.height
    if total == 0:
        return 0.0
    unchanged = diff.histogram()[0]
    return (total - unchanged) / total
