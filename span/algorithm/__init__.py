"""Where the OS import and the millimetre maths live.

``displays`` reads what macOS knows. ``wall`` turns that into physical geometry and cuts
crops from it. Neither imports Qt or Pillow, so the whole layout model is testable with
hand-built objects and no hardware.
"""

from .displays import (
    MM_PER_INCH,
    Display,
    DisplayDetectionError,
    detect_displays,
    detect_raw,
    signature,
)
from .wall import (
    Box,
    Estate,
    Panel,
    Plan,
    choose_scale,
    clamp_offset,
    estate,
    fit_scale,
    native_scale,
    panels_from_displays,
    plan_layout,
    seam_positions,
)

__all__ = [
    "MM_PER_INCH",
    "Display",
    "DisplayDetectionError",
    "detect_displays",
    "detect_raw",
    "signature",
    "Box",
    "Estate",
    "Panel",
    "Plan",
    "choose_scale",
    "clamp_offset",
    "estate",
    "fit_scale",
    "native_scale",
    "panels_from_displays",
    "plan_layout",
    "seam_positions",
]
