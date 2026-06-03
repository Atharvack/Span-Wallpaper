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
from typing import Dict, List, Optional, Tuple

_MM_PER_INCH = 25.4


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
    display_id: int = 0               # CGDirectDisplayID
    width_mm: Optional[float] = None  # physical size (EDID), if available
    height_mm: Optional[float] = None

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

    @property
    def ppi(self) -> Optional[float]:
        """Pixels per inch from physical size, or None if unknown."""
        if self.width_mm and self.width_mm > 0:
            return self.native_w / (self.width_mm / _MM_PER_INCH)
        return None

    def unit_size(self, native_mode: bool, ppi_aware: bool) -> Tuple[float, float]:
        """The size used to lay this display out.

        * native: exact native pixels.
        * ppi: physical inches derived from PPI as ``(native_w/ppi, native_h/ppi)`` — this
          is proportional to real-world size yet keeps the *native* aspect ratio exactly
          (EDID mm can report a slightly different aspect, which would distort the crop).
        * else: points.
        """
        if native_mode:
            return (float(self.native_w), float(self.native_h))
        if ppi_aware and self.ppi:
            return (self.native_w / self.ppi, self.native_h / self.ppi)
        return (float(self.w), float(self.h))


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


def seed_layout(
    displays: List[Display],
    img_w: float,
    img_h: float,
    native_mode: bool = False,
    ppi_aware: bool = False,
) -> Dict[int, Box]:
    """Pre-arrange one rectangle per display over the image.

    Lays the displays out edge-to-edge (honoring points-space gaps) with their real
    vertical offsets, sized by :meth:`Display.unit_size` — points by default, physical
    inches under ``ppi_aware`` (so both monitors land at the *same physical scale* across
    the seam), or native px under ``native_mode``. The whole arrangement is uniformly
    scaled to fit inside the image and centered.

    Returns a mapping of ``display.index -> Box`` in source-image pixels.
    """
    if not displays:
        return {}

    ds = sorted(displays, key=lambda d: d.x)
    sizes = {d.index: d.unit_size(native_mode, ppi_aware) for d in ds}

    ref = ds[0]
    upp_x = sizes[ref.index][0] / ref.w   # unit width per point (for gaps)
    upp_y = sizes[ref.index][1] / ref.h   # unit height per point (for vertical offsets)

    xpos = {ref.index: 0.0}
    for i in range(1, len(ds)):
        prev, cur = ds[i - 1], ds[i]
        gap = cur.x - (prev.x + prev.w)
        xpos[cur.index] = xpos[prev.index] + sizes[prev.index][0] + gap * upp_x

    ref_top = ref.y + ref.h  # y-up top edge
    ypos = {d.index: (ref_top - (d.y + d.h)) * upp_y for d in ds}

    min_x = min(xpos.values())
    max_x = max(xpos[d.index] + sizes[d.index][0] for d in ds)
    min_y = min(ypos.values())
    max_y = max(ypos[d.index] + sizes[d.index][1] for d in ds)
    canvas_w = (max_x - min_x) or 1.0
    canvas_h = (max_y - min_y) or 1.0

    # Uniform fit so the arrangement never overflows the image, then center it.
    k = min(img_w / canvas_w, img_h / canvas_h)
    off_x = (img_w - canvas_w * k) / 2.0
    off_y = (img_h - canvas_h * k) / 2.0

    return {
        d.index: Box(
            x=off_x + (xpos[d.index] - min_x) * k,
            y=off_y + (ypos[d.index] - min_y) * k,
            w=sizes[d.index][0] * k,
            h=sizes[d.index][1] * k,
        )
        for d in ds
    }


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


def target_sizes(
    displays: List[Display],
    current: Dict[int, Box],
    native_mode: bool = False,
    ppi_aware: bool = False,
) -> Dict[int, Tuple[float, float]]:
    """Per-display crop sizes (image px) for an aligned layout.

    * native: exact native pixels.
    * ppi: scaled so the *densest* display lands at native size (1:1, sharpest) and the
      others get proportionally larger crops (downsampled, never upscaled), all keeping
      native aspect.
    * else: keep each box's current size.
    """
    if native_mode:
        return {d.index: (float(d.native_w), float(d.native_h)) for d in displays}
    if ppi_aware and any(d.ppi for d in displays):
        densest = max((d for d in displays if d.ppi), key=lambda d: d.ppi)
        s = densest.ppi  # image px per inch → densest display maps to its native size
        out: Dict[int, Tuple[float, float]] = {}
        for d in displays:
            uw, uh = d.unit_size(native_mode=False, ppi_aware=True)
            out[d.index] = (uw * s, uh * s)
        return out
    return {d.index: (current[d.index].w, current[d.index].h) for d in displays}


def align_boxes(
    displays: List[Display],
    current: Dict[int, Box],
    axis: str,
    native_mode: bool = False,
    ppi_aware: bool = False,
) -> Dict[int, Box]:
    """Snap ``current`` boxes onto the detected layout along ``axis``.

    Positions are anchored on the **leftmost** display's current box (so the group stays
    where you put it); sizes come from :func:`target_sizes`.

    * ``"h"`` — edge-to-edge X + consistent size, keeping each box's Y.
    * ``"v"`` — physically-correct vertical offset, keeping each box's X and size.
    * ``"both"`` — full snap (position + size).

    The result may extend outside the image; the caller is expected to shift the whole
    group back in as a unit (so the seam is preserved).
    """
    ds = sorted(displays, key=lambda d: d.x)
    left = ds[0]
    left_cur = current[left.index]
    sizes = target_sizes(displays, current, native_mode, ppi_aware)

    sp = left_cur.w / left.w    # image px per point, for horizontal gaps
    spv = left_cur.h / left.h   # image px per point, for vertical offsets

    xpos = {left.index: left_cur.x}
    for i in range(1, len(ds)):
        prev, cur = ds[i - 1], ds[i]
        gap = cur.x - (prev.x + prev.w)
        xpos[cur.index] = xpos[prev.index] + sizes[prev.index][0] + gap * sp

    left_top = left.y + left.h  # y-up top edge
    ypos = {d.index: left_cur.y + (left_top - (d.y + d.h)) * spv for d in ds}

    out: Dict[int, Box] = {}
    for d in ds:
        cur = current[d.index]
        sw, sh = sizes[d.index]
        if axis == "h":
            out[d.index] = Box(xpos[d.index], cur.y, sw, sh)
        elif axis == "v":
            out[d.index] = Box(cur.x, ypos[d.index], cur.w, cur.h)
        else:
            out[d.index] = Box(xpos[d.index], ypos[d.index], sw, sh)
    return out


def fit_into_image(
    boxes: Dict[int, Box], img_w: float, img_h: float
) -> Dict[int, Box]:
    """Keep a group of boxes on-screen as a rigid unit (seam and sizes preserved).

    Shift only — never scale. If the group fits, it's shifted the minimum amount to bring
    it fully inside. If the group is larger than the image, its **top-left** is anchored
    on-screen and the far edge is allowed to overflow (the user can nudge/resize), rather
    than shrinking the whole arrangement.
    """
    if not boxes:
        return boxes
    min_x = min(b.x for b in boxes.values())
    max_x = max(b.right for b in boxes.values())
    min_y = min(b.y for b in boxes.values())
    max_y = max(b.bottom for b in boxes.values())
    gw = max_x - min_x
    gh = max_y - min_y

    if min_x < 0:
        dx = -min_x                                   # bring the left edge on-screen
    elif max_x > img_w and gw <= img_w:
        dx = img_w - max_x                            # pull the right edge in (only if it fits)
    else:
        dx = 0.0

    if min_y < 0:
        dy = -min_y                                   # bring the top edge on-screen
    elif max_y > img_h and gh <= img_h:
        dy = img_h - max_y                            # pull the bottom in (only if it fits)
    else:
        dy = 0.0

    if dx == 0.0 and dy == 0.0:
        return boxes
    return {i: Box(b.x + dx, b.y + dy, b.w, b.h) for i, b in boxes.items()}


def to_native_boxes(displays: List[Display], current: Dict[int, Box]) -> Dict[int, Box]:
    """Resize every box to its display's exact native pixel size, keeping the top-left."""
    return {
        d.index: Box(current[d.index].x, current[d.index].y, float(d.native_w), float(d.native_h))
        for d in displays
    }
