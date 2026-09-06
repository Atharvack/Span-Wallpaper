"""The wall: lay everything out in millimetres, convert to pixels once.

A pixel is a count, not a length. 60 px is 14.11 mm on a 108 ppi panel and 16.57 mm on a
92 ppi one, so no pixel-space arrangement can be physically correct across displays.
Millimetres are the only unit that means the same thing on every screen.

So every panel becomes a rectangle on an imaginary wall behind the monitors, measured in
mm. The source image is pinned to that same wall at a chosen density ``S`` (image pixels
per mm). Each display's crop is the region of the image that falls behind its glass.
Pixel counts appear once, in a final ``round()``.

    wall (mm)  ->  crop = panel rectangle x S  ->  image pixels

Bezel compensation is not a feature here — it falls out. The gap between two panels is mm
you do not cover, so the picture continues behind the plastic.

Coordinates
-----------
Wall space: origin at the top-left of the leftmost panel, x grows right, **y grows down**
— the same sense as image space, so no axis flip exists anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .displays import MM_PER_INCH, Display


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
        """Integer ``(left, top, right, bottom)`` for ``PIL.Image.crop``."""
        return (round(self.x), round(self.y), round(self.x + self.w), round(self.y + self.h))


@dataclass(frozen=True)
class Panel:
    """One display as a rectangle of glass on the wall.

    ``x_mm`` / ``y_mm`` are the top-left corner in wall coordinates. They come from
    calibration, never from the OS — see :mod:`span.calibration`.
    """

    index: int
    name: str
    px_w: int
    px_h: int
    ppi: float
    x_mm: float
    y_mm: float

    @property
    def px_per_mm(self) -> float:
        return self.ppi / MM_PER_INCH

    @property
    def width_mm(self) -> float:
        return self.px_w / self.px_per_mm

    @property
    def height_mm(self) -> float:
        return self.px_h / self.px_per_mm

    @property
    def right_mm(self) -> float:
        return self.x_mm + self.width_mm

    @property
    def bottom_mm(self) -> float:
        return self.y_mm + self.height_mm


@dataclass(frozen=True)
class Estate:
    """The bounding rectangle of every panel, in wall mm."""

    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float

    @property
    def right_mm(self) -> float:
        return self.x_mm + self.w_mm

    @property
    def bottom_mm(self) -> float:
        return self.y_mm + self.h_mm


def estate(panels: Sequence[Panel]) -> Estate:
    """Bounding extent of the arrangement.

    Widths accumulate when panels sit in a row; heights do not, because they overlap. So
    both axes are a min/max over edges, never a sum.
    """
    if not panels:
        raise ValueError("estate() needs at least one panel")
    left = min(p.x_mm for p in panels)
    right = max(p.right_mm for p in panels)
    top = min(p.y_mm for p in panels)
    bottom = max(p.bottom_mm for p in panels)
    return Estate(x_mm=left, y_mm=top, w_mm=right - left, h_mm=bottom - top)


def seam_positions(panels: Sequence[Panel], gaps_mm: Sequence[float]) -> List[float]:
    """Wall x of the middle of each bezel, for drawing calibration marks."""
    out: List[float] = []
    for i in range(len(panels) - 1):
        gap = gaps_mm[i] if i < len(gaps_mm) else 0.0
        out.append(panels[i].right_mm + gap / 2.0)
    return out


# --------------------------------------------------------------------------------------
# Pinning the image to the wall
# --------------------------------------------------------------------------------------

def native_scale(panels: Sequence[Panel]) -> float:
    """Density at which the sharpest panel is exactly 1:1, in image px per mm.

    Any S at or above this means no display upscales.
    """
    return max(p.px_per_mm for p in panels)


def fit_scale(image_w_px: int, image_h_px: int, est: Estate) -> float:
    """Largest S at which the image still covers the whole estate.

    A *smaller* S spreads the image over more wall, so covering both axes means the
    minimum of the two per-axis limits.
    """
    return min(image_w_px / est.w_mm, image_h_px / est.h_mm)


def choose_scale(
    image_w_px: int, image_h_px: int, panels: Sequence[Panel], policy: str = "fit"
) -> float:
    """Pick the image's wall density.

    * ``"fit"`` — cover the estate exactly, using as much of the image as possible.
    * ``"native"`` — pin the densest panel at 1:1 for maximum sharpness. The image may
      then not reach across the estate, which :func:`plan_layout` reports.

    S is a zoom level, not a correctness parameter: continuity comes from the mm layout,
    and every panel is scaled by the same S, so no value of S can break the seam.
    """
    if policy == "native":
        return native_scale(panels)
    if policy == "fit":
        return fit_scale(image_w_px, image_h_px, estate(panels))
    raise ValueError(f"unknown policy {policy!r} (expected 'fit' or 'native')")


@dataclass
class Plan:
    """One crop box per panel, plus what went wrong."""

    scale: float                  # image px per mm
    est: Estate
    image_w_mm: float
    image_h_mm: float
    image_x_mm: float             # where the image's top-left sits on the wall
    image_y_mm: float
    boxes: Dict[int, Box]         # panel.index -> crop box in image px
    upscaled: List[str]
    out_of_bounds: List[str]

    @property
    def ok(self) -> bool:
        return not self.upscaled and not self.out_of_bounds


def plan_layout(
    panels: Sequence[Panel],
    image_w_px: int,
    image_h_px: int,
    policy: str = "fit",
    scale: Optional[float] = None,
    offset_mm: Tuple[float, float] = (0.0, 0.0),
) -> Plan:
    """Lay the image on the wall and cut one crop per panel.

    The image is centred on the estate, then slid by ``offset_mm`` — that offset is the
    user's drag, in millimetres, and it moves every crop together so it can never disturb
    continuity.
    """
    if not panels:
        raise ValueError("plan_layout() needs at least one panel")

    est = estate(panels)
    S = scale if scale is not None else choose_scale(image_w_px, image_h_px, panels, policy)

    image_w_mm = image_w_px / S
    image_h_mm = image_h_px / S
    img_x_mm = est.x_mm + (est.w_mm - image_w_mm) / 2.0 + offset_mm[0]
    img_y_mm = est.y_mm + (est.h_mm - image_h_mm) / 2.0 + offset_mm[1]

    boxes: Dict[int, Box] = {}
    upscaled: List[str] = []
    out_of_bounds: List[str] = []

    for p in panels:
        # A panel's crop is just its glass, measured from the image's top-left corner.
        box = Box(
            x=(p.x_mm - img_x_mm) * S,
            y=(p.y_mm - img_y_mm) * S,
            w=p.width_mm * S,
            h=p.height_mm * S,
        )
        boxes[p.index] = box

        # The image supplies S px per mm; this panel wants px_per_mm. Below that, stretch.
        if S < p.px_per_mm - 1e-9:
            upscaled.append(p.name)
        if (box.x < -0.5 or box.y < -0.5
                or box.right > image_w_px + 0.5 or box.bottom > image_h_px + 0.5):
            out_of_bounds.append(p.name)

    return Plan(
        scale=S, est=est,
        image_w_mm=image_w_mm, image_h_mm=image_h_mm,
        image_x_mm=img_x_mm, image_y_mm=img_y_mm,
        boxes=boxes, upscaled=upscaled, out_of_bounds=out_of_bounds,
    )


def clamp_offset(
    panels: Sequence[Panel], image_w_px: int, image_h_px: int, S: float,
    offset_mm: Tuple[float, float],
) -> Tuple[float, float]:
    """Limit a drag so no panel ever reads past the edge of the image.

    Only clamps on an axis where the image is actually larger than the estate; when it is
    smaller there is nothing to slide and the offset is pinned to centred.
    """
    est = estate(panels)
    image_w_mm, image_h_mm = image_w_px / S, image_h_px / S
    slack_x = (image_w_mm - est.w_mm) / 2.0
    slack_y = (image_h_mm - est.h_mm) / 2.0
    dx, dy = offset_mm
    dx = min(max(dx, -slack_x), slack_x) if slack_x > 0 else 0.0
    dy = min(max(dy, -slack_y), slack_y) if slack_y > 0 else 0.0
    return (dx, dy)


# --------------------------------------------------------------------------------------
# Displays -> Panels
# --------------------------------------------------------------------------------------

def panels_from_displays(
    displays: Sequence[Display],
    gaps_mm: Optional[Sequence[float]] = None,
    y_offsets_mm: Optional[Sequence[float]] = None,
) -> List[Panel]:
    """Build the wall from detected displays plus **measured** positions.

    Args:
        displays: as returned by :func:`span.algorithm.displays.detect_displays`.
        gaps_mm: bezel + air gap between consecutive panels, mm. One fewer entry than
            there are displays. Defaults to zero — the "panels touch" fiction.
        y_offsets_mm: each panel's top edge relative to the leftmost panel's, mm,
            positive = lower. Defaults to zero, i.e. tops flush.

    Those two sequences are exactly what macOS cannot supply. They come from
    :mod:`span.calibration`, never from ``Display.x/y``, which are point counts in a
    space that assumes uniform pixel density.
    """
    ds = sorted(displays, key=lambda d: d.x)
    gaps = list(gaps_mm) if gaps_mm is not None else [0.0] * max(len(ds) - 1, 0)
    offsets = list(y_offsets_mm) if y_offsets_mm is not None else [0.0] * len(ds)

    if len(gaps) != max(len(ds) - 1, 0):
        raise ValueError(f"gaps_mm needs {max(len(ds) - 1, 0)} entries, got {len(gaps)}")
    if len(offsets) != len(ds):
        raise ValueError(f"y_offsets_mm needs {len(ds)} entries, got {len(offsets)}")

    panels: List[Panel] = []
    x = 0.0
    for i, d in enumerate(ds):
        if not d.ppi:
            raise ValueError(
                f"{d.name} reports no physical size (EDID missing) — wall coordinates "
                "need it."
            )
        p = Panel(index=d.index, name=d.name, px_w=d.native_w, px_h=d.native_h,
                  ppi=d.ppi, x_mm=x, y_mm=offsets[i])
        panels.append(p)
        x = p.right_mm + (gaps[i] if i < len(gaps) else 0.0)
    return panels
