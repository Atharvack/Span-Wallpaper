"""The calibration pattern, defined once in wall millimetres.

Renderer-agnostic on purpose: this module emits primitives with mm coordinates and a
*role*, and the caller decides how to paint them. The live Qt view and any offline PNG
render therefore draw provably the same geometry — if the pattern joins up on screen, it
is the model that is right, not the renderer.

What each element proves:

* **columns** — equal physical width on panels of different density; the scale is right.
* **rules** — a wrong vertical offset shows up as a step at the bezel. The main event.
* **diagonals** — sensitive to an error on *either* axis, so they catch a bad bezel gap
  that the rules cannot see.
* **circles** straddling the seam — the harshest test. A broken circle is obvious from
  across the room.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

from ..algorithm.wall import Estate

# Roles a renderer must understand. Keeping them as plain strings avoids dragging an enum
# through the Qt layer for no benefit.
COLUMN = "column"
RULE_MAJOR = "rule_major"
RULE_MINOR = "rule_minor"
DIAGONAL = "diagonal"
CIRCLE = "circle"
SEAM = "seam"
LABEL = "label"

COLUMN_MM = 40.0     # column width, and the gap between columns
RULE_MM = 25.0       # a rule every N mm
RULE_MAJOR_MM = 100.0
CIRCLE_R_MM = 62.0


@dataclass
class Rect:
    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float
    role: str


@dataclass
class Line:
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float
    role: str


@dataclass
class Circle:
    cx_mm: float
    cy_mm: float
    r_mm: float
    role: str


@dataclass
class Label:
    x_mm: float
    y_mm: float
    text: str
    role: str = LABEL


@dataclass
class Pattern:
    """Everything to draw, in wall mm. Painted in list order, back to front."""

    rects: List[Rect] = field(default_factory=list)
    lines: List[Line] = field(default_factory=list)
    circles: List[Circle] = field(default_factory=list)
    labels: List[Label] = field(default_factory=list)


def build(
    est: Estate,
    seams_mm: Sequence[float],
    modes: Tuple[str, ...] = ("columns", "rules", "diagonals", "circles"),
) -> Pattern:
    """Assemble the pattern for one estate.

    ``modes`` selects which families are included, so a busy pattern can be thinned down
    to just the element you are currently judging.
    """
    p = Pattern()
    x0, y0, w, h = est.x_mm, est.y_mm, est.w_mm, est.h_mm

    if "columns" in modes:
        x = x0
        while x < x0 + w:
            p.rects.append(Rect(x, y0, min(COLUMN_MM, x0 + w - x), h, COLUMN))
            x += COLUMN_MM * 2

    if "rules" in modes:
        n = 0
        while y0 + n * RULE_MM <= y0 + h + 1e-6:
            y = y0 + n * RULE_MM
            major = abs((n * RULE_MM) % RULE_MAJOR_MM) < 1e-6
            p.lines.append(Line(x0, y, x0 + w, y, RULE_MAJOR if major else RULE_MINOR))
            if major:
                # Labels near both ends and either side of every seam — at the bezel the
                # edge labels are the only ones you can actually read.
                spots = [x0 + 6.0, x0 + w - 26.0]
                for s in seams_mm:
                    spots += [s - 30.0, s + 6.0]
                for sx in spots:
                    p.labels.append(Label(sx, y - 3.0, f"{int(n * RULE_MM)} mm"))
            n += 1

    if "diagonals" in modes:
        p.lines.append(Line(x0, y0, x0 + w, y0 + h, DIAGONAL))
        p.lines.append(Line(x0, y0 + h, x0 + w, y0, DIAGONAL))

    if "circles" in modes:
        for s in seams_mm:
            for frac in (0.26, 0.5, 0.74):
                cy = y0 + h * frac
                p.circles.append(Circle(s, cy, CIRCLE_R_MM, CIRCLE))
                p.circles.append(Circle(s, cy, CIRCLE_R_MM / 3.0, CIRCLE))

    for s in seams_mm:
        p.lines.append(Line(s, y0, s, y0 + h, SEAM))

    return p
