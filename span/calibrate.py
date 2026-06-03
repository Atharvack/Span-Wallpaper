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

from typing import Tuple

from PIL import Image, ImageDraw

# Source-pixel spacing between numbered (major) grid lines.
DEFAULT_CELL = 120


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
