"""Turn what the eye measured into wall geometry.

macOS cannot tell you where your monitors physically sit — its arrangement is a point
count in a space that assumes uniform pixel density, and the offset it records is a guess
you made with a cursor, correct at exactly one row. So we ask the only sensor that can
answer: your eyes.

The method: draw a horizontal line on every display and move them until they read as ONE
continuous line across the bezels. Judging collinearity is the sharpest thing human
vision does, so this beats a ruler — and it captures perceptual truth from where you
actually sit, which is what you want, since angled panels are never perfectly coplanar.

Once the lines match, they are all at the same height on the wall:

    d_i = row_i / px_per_mm_i        depth of the line below panel i's top edge
    y_offset_i = d_0 - d_i           panel i's top edge relative to the datum panel
"""

from __future__ import annotations

from typing import List, Sequence


def line_depth_mm(row_px: float, px_per_mm: float) -> float:
    """How far below a panel's top edge a line at ``row_px`` physically sits."""
    if px_per_mm <= 0:
        raise ValueError("px_per_mm must be positive")
    return row_px / px_per_mm


def offsets_from_rows(
    rows_px: Sequence[float], px_per_mm: Sequence[float], datum: int = 0
) -> List[float]:
    """Wall offsets from one line position per display.

    Args:
        rows_px: each line's row, in that panel's **real** pixels from its top edge.
        px_per_mm: each panel's pixel density, same order.
        datum: which panel is the zero reference. Only differences are used downstream,
            so the choice does not affect the result — it only shifts every value.

    Returns:
        One offset per panel, mm, positive meaning that panel sits lower.
    """
    if len(rows_px) != len(px_per_mm):
        raise ValueError(
            f"rows_px has {len(rows_px)} entries, px_per_mm has {len(px_per_mm)}"
        )
    if not rows_px:
        return []
    if not 0 <= datum < len(rows_px):
        raise IndexError(f"datum {datum} out of range for {len(rows_px)} panels")

    depths = [line_depth_mm(r, k) for r, k in zip(rows_px, px_per_mm)]
    base = depths[datum]
    return [base - d for d in depths]


def normalize(offsets: Sequence[float], datum: int = 0) -> List[float]:
    """Re-zero a set of offsets on ``datum`` so the datum reads exactly 0.

    Nudging panels around in a live view leaves the datum non-zero; downstream only cares
    about differences, but a stored config is easier to read when the first entry is 0.
    """
    if not offsets:
        return []
    base = offsets[datum]
    return [round(v - base, 4) for v in offsets]
