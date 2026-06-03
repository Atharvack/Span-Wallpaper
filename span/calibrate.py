"""Calibration grid + offset math.

The calibration grid replaces the photo as the source. Because the per-display crops are
PPI-scaled to the same physical px/mm, a grid drawn at a fixed *source-pixel* spacing
appears at the same physical spacing on every monitor — so grid lines are directly
comparable across the bezel.

Workflow: export grid crops → set as wallpapers → read which left line meets which right
line at the seam (e.g. ``L:3 = R:6``) → :func:`calibration_shift` converts that residual
into a pixel nudge for the right display → re-export until ``L:n = R:n``.
"""

from __future__ import annotations

import math
from typing import Tuple

from PIL import Image, ImageDraw

# Source-pixel spacing between numbered (major) grid lines. Because every display's crop
# is PPI-scaled to the same source-px/mm, one cell is the same *physical* size on each
# monitor — so the numbers are directly comparable across the bezel. Smaller = finer/more
# precise reading at the seam.
DEFAULT_CELL = 60


def make_crop_grid(
    x: float, y: float, w: float, h: float,
    native_w: int, native_h: int, cell: float,
) -> Image.Image:
    """Render a crisp calibration grid for ONE display, drawn at its native resolution.

    The display's crop covers source region ``[x, x+w] x [y, y+h]``; this draws the shared
    *canvas* grid (numbered by source-cell index, so numbering is continuous across
    displays) directly into a ``native_w x native_h`` image — no upscaling, so the lines
    and numbers stay sharp. When the vertical offset is correct, the same number meets the
    same number at the seam.
    """
    img = Image.new("RGB", (native_w, native_h), (10, 10, 16))
    d = ImageDraw.Draw(img)
    kx = native_w / w
    ky = native_h / h
    minor = cell / 5

    c = math.floor(x / minor)
    while c * minor <= x + w:
        nx = round((c * minor - x) * kx)
        d.line([(nx, 0), (nx, native_h)], fill=(32, 32, 46), width=1)
        c += 1
    r = math.floor(y / minor)
    while r * minor <= y + h:
        ny = round((r * minor - y) * ky)
        d.line([(0, ny), (native_w, ny)], fill=(32, 32, 46), width=1)
        r += 1

    c0, c1 = math.floor(x / cell), math.ceil((x + w) / cell)
    r0, r1 = math.floor(y / cell), math.ceil((y + h) / cell)
    for c in range(c0, c1 + 1):
        nx = round((c * cell - x) * kx)
        d.line([(nx, 0), (nx, native_h)], fill=(90, 130, 230), width=2)
    for r in range(r0, r1 + 1):
        ny = round((r * cell - y) * ky)
        d.line([(0, ny), (native_w, ny)], fill=(90, 130, 230), width=2)
    # Row numbers down both side edges (readable at the seam); col numbers top & bottom.
    for r in range(r0, r1 + 1):
        ny = round((r * cell - y) * ky)
        d.text((5, ny + 2), str(r), fill=(255, 230, 80))
        d.text((native_w - 36, ny + 2), str(r), fill=(255, 230, 80))
    for c in range(c0, c1 + 1):
        nx = round((c * cell - x) * kx)
        d.text((nx + 3, 3), str(c), fill=(120, 255, 180))
        d.text((nx + 3, native_h - 18), str(c), fill=(120, 255, 180))
    return img


def make_grid(width: int, height: int, cell: int = DEFAULT_CELL) -> Image.Image:
    """A numbered calibration grid: minor lines every ``cell/4``, bold numbered lines
    every ``cell`` px, each major intersection labelled ``col,row``."""
    img = Image.new("RGB", (width, height), (12, 12, 18))
    d = ImageDraw.Draw(img)

    minor = max(1, cell // 4)
    for x in range(0, width + 1, minor):
        d.line([(x, 0), (x, height)], fill=(38, 38, 52), width=1)
    for y in range(0, height + 1, minor):
        d.line([(0, y), (width, y)], fill=(38, 38, 52), width=1)

    ncols = width // cell
    nrows = height // cell
    for c in range(ncols + 1):
        x = c * cell
        d.line([(x, 0), (x, height)], fill=(90, 120, 210), width=2)
    for r in range(nrows + 1):
        y = r * cell
        d.line([(0, y), (width, y)], fill=(90, 120, 210), width=2)

    # Label every major intersection "col,row" so any point is readable at the bezel.
    for r in range(nrows + 1):
        for c in range(ncols + 1):
            d.text((c * cell + 3, r * cell + 2), f"{c},{r}", fill=(255, 230, 80))
    return img


def calibration_shift(
    row_l: float, row_r: float, col_l: float, col_r: float, cell: float
) -> Tuple[float, float]:
    """Pixel nudge (dx, dy) to apply to the RIGHT display so its grid numbers line up
    with the left's.

    ``row_l``/``row_r`` are the row numbers seen at the seam on the left/right monitors
    (``col_*`` likewise). If the right shows a *higher* number than the left it is cropping
    too far down/right, so it must move up/left — hence the negative sign.
    """
    dx = -(col_r - col_l) * cell
    dy = -(row_r - row_l) * cell
    return (dx, dy)
