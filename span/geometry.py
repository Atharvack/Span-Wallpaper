"""Pure geometry for span — no Qt, no Pillow, fully unit-testable.

Coordinate systems
-------------------
* **Display global space** (from macOS ``NSScreen``, see :mod:`span.displays`):
  origin **bottom-left**, ``y`` increases **UP**, units are **points**.
* **Source-image space**: origin **top-left**, ``y`` increases **DOWN**, units are
  **pixels**. The GUI scene and every crop box live here.

A display's *native* pixel size is ``round(w * scale) x round(h * scale)`` and is both
the export resolution and the rectangle's locked aspect ratio. Because the scale factor
is uniform for a display, ``native_w / native_h == w / h`` (up to rounding), so seeding
rectangles from the points-space arrangement already matches the locked aspect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class Display:
    """One connected display, as reported by macOS in points-space."""

    index: int
    name: str
    x: float       # points, global space, bottom-left origin
    y: float
    w: float       # points
    h: float
    scale: float   # backing scale factor (1 or 2)

    @property
    def native_w(self) -> int:
        return round(self.w * self.scale)

    @property
    def native_h(self) -> int:
        return round(self.h * self.scale)

    @property
    def aspect(self) -> float:
        """Locked width:height ratio, driven from native pixels."""
        return self.native_w / self.native_h

    @property
    def native_label(self) -> str:
        return f"{self.native_w}×{self.native_h}"


@dataclass
class Box:
    """An axis-aligned rectangle in source-image pixel space (top-left origin)."""

    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    def as_crop(self) -> Tuple[int, int, int, int]:
        """Integer ``(left, top, right, bottom)`` suitable for ``PIL.Image.crop``."""
        return (round(self.x), round(self.y), round(self.x + self.w), round(self.y + self.h))


def seed_layout(displays: List[Display], img_w: float, img_h: float) -> Dict[int, Box]:
    """Pre-arrange one rectangle per display over the image.

    The displays' *physical* arrangement (their frames in points-space, including
    horizontal gaps, vertical offsets, and differing sizes) is mapped onto the image so
    that adjacent crops line up across the seam out of the box. The whole arrangement is
    uniformly scaled to *fit* inside the image (so no seeded rectangle can start outside
    it) and centered.

    Returns a mapping of ``display.index -> Box`` in source-image pixels.
    """
    if not displays:
        return {}

    min_x = min(d.x for d in displays)
    max_x = max(d.x + d.w for d in displays)
    min_y = min(d.y for d in displays)
    max_y = max(d.y + d.h for d in displays)

    canvas_w = max_x - min_x
    canvas_h = max_y - min_y
    if canvas_w <= 0:
        canvas_w = 1.0
    if canvas_h <= 0:
        canvas_h = 1.0

    # Uniform fit so the arrangement never overflows the image, then center it.
    k = min(img_w / canvas_w, img_h / canvas_h)
    off_x = (img_w - canvas_w * k) / 2.0
    off_y = (img_h - canvas_h * k) / 2.0

    boxes: Dict[int, Box] = {}
    for d in displays:
        left = d.x - min_x
        # Convert the display's TOP edge (y-up) into a top-down offset from the canvas top.
        top_down = max_y - (d.y + d.h)
        boxes[d.index] = Box(
            x=off_x + left * k,
            y=off_y + top_down * k,
            w=d.w * k,
            h=d.h * k,
        )
    return boxes


def clamp_pos(
    x: float, y: float, w: float, h: float, img_w: float, img_h: float
) -> Tuple[float, float]:
    """Clamp a rectangle's top-left so it stays fully inside ``[0,img_w] x [0,img_h]``."""
    max_x = max(img_w - w, 0.0)
    max_y = max(img_h - h, 0.0)
    return (min(max(x, 0.0), max_x), min(max(y, 0.0), max_y))


def aspect_resize(
    px: float,
    py: float,
    corner_x: float,
    corner_y: float,
    aspect: float,
    img_w: float,
    img_h: float,
    min_w: float = 24.0,
) -> Tuple[float, float]:
    """Size a top-left-anchored rectangle from a dragged bottom-right ``corner``.

    Width:height is locked to ``aspect``. The result is clamped so the rectangle stays
    within the image given the fixed top-left ``(px, py)``. Returns ``(w, h)``.
    """
    desired_w = corner_x - px
    desired_h = corner_y - py
    # Drive from whichever axis the user pulled further, so dragging either direction
    # grows the (aspect-locked) rectangle intuitively.
    w = max(desired_w, desired_h * aspect)

    w = max(w, min_w)
    max_w_from_right = img_w - px
    max_w_from_bottom = (img_h - py) * aspect
    w = min(w, max_w_from_right, max_w_from_bottom)
    w = max(w, 0.0)

    return (w, w / aspect)
