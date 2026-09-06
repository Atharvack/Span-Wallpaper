"""Read the connected displays out of macOS.

Two sources, because no single API has both halves:

* ``NSScreen`` via JavaScript-for-Automation — name, frame, backing scale, display id.
  Read-only; it never writes OS state.
* ``CGDisplayScreenSize`` via ctypes — physical size in millimetres, from EDID.

The physical size is the important one. Everything downstream lays out in millimetres,
and ``NSScreen`` cannot supply a physical dimension: its ``NSDeviceResolution`` field
reports 72 dpi on every Mac ever made, a legacy PostScript constant rather than a
measurement.

What the frame is and is not
----------------------------
``x/y/w/h`` are points in the macOS global space. They are used for exactly one thing:
ordering displays left-to-right. They are **not** used for layout, because points are a
count in a space that assumes every display has the same density — false for a mixed
setup, and the source of the seam error this project exists to fix. Physical positions
come from :mod:`span.calibration`.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .. import diaglog

MM_PER_INCH = 25.4


class DisplayDetectionError(RuntimeError):
    """Raised when the macOS display query fails or returns nothing usable."""


@dataclass(frozen=True)
class Display:
    """One connected display, exactly as macOS reports it."""

    index: int
    name: str
    x: float       # points, global space, bottom-left origin — ordering only
    y: float
    w: float       # points
    h: float
    scale: float   # backing scale factor (1 or 2)
    display_id: int = 0               # CGDirectDisplayID
    width_mm: Optional[float] = None  # physical size (EDID), if available
    height_mm: Optional[float] = None

    @property
    def native_w(self) -> int:
        """Real pixels across. Points are device-independent; this is the hardware."""
        return round(self.w * self.scale)

    @property
    def native_h(self) -> int:
        return round(self.h * self.scale)

    @property
    def native_label(self) -> str:
        return f"{self.native_w}×{self.native_h}"

    @property
    def aspect(self) -> float:
        return self.native_w / self.native_h

    @property
    def ppi(self) -> Optional[float]:
        """Pixels per inch, or None when EDID gave us nothing to work with."""
        if self.width_mm and self.width_mm > 0:
            return self.native_w / (self.width_mm / MM_PER_INCH)
        return None

    @property
    def px_per_mm(self) -> Optional[float]:
        """The conversion rate everything else is built on."""
        return self.ppi / MM_PER_INCH if self.ppi else None


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


def _screen_size_mm(display_id: int) -> Tuple[Optional[float], Optional[float]]:
    """Physical size in millimetres via CGDisplayScreenSize, or ``(None, None)``.

    Best-effort by design: the framework may be missing, the symbol may change, or the
    panel may have no EDID. Every one of those means the same thing to the caller — no
    physical size — so they collapse into one return.
    """
    try:
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cg.CGDisplayScreenSize.restype = _CGSize          # without this ctypes assumes int
        cg.CGDisplayScreenSize.argtypes = [ctypes.c_uint32]
        size = cg.CGDisplayScreenSize(ctypes.c_uint32(int(display_id)))
        if size.width > 0 and size.height > 0:
            return (float(size.width), float(size.height))
    except Exception:  # pragma: no cover - platform/EDID dependent
        pass
    return (None, None)


# Every NSScreen property, each guarded so a version-specific one cannot abort the probe:
# safeAreaInsets is 10.15+, auxiliaryTop*Area 12.0+, the refresh interval trio 14.0+.
_JXA = r"""
ObjC.import('AppKit');

function attempt(fn) {
  try { var v = fn(); return v === undefined ? null : v; }
  catch (e) { return null; }
}
function rect(r) { return {x: r.origin.x, y: r.origin.y, w: r.size.width, h: r.size.height}; }

var screens = $.NSScreen.screens;
var main    = $.NSScreen.mainScreen;
var out = [];

for (var i = 0; i < screens.count; i++) {
  var s  = screens.objectAtIndex(i);
  var dd = s.deviceDescription;
  out.push({
    index: i,
    name:  attempt(function(){ return ObjC.unwrap(s.localizedName); }),
    x: s.frame.origin.x, y: s.frame.origin.y,
    w: s.frame.size.width, h: s.frame.size.height,
    scale: s.backingScaleFactor,
    displayID: attempt(function(){ return ObjC.unwrap(dd.objectForKey('NSScreenNumber')); }),
    visibleFrame: attempt(function(){ return rect(s.visibleFrame); }),
    isMain: attempt(function(){ return s.isEqual(main); }),
    refreshInterval: attempt(function(){ return s.minimumRefreshInterval; }),
    bitsPerSample: attempt(function(){ return ObjC.unwrap(dd.objectForKey('NSDeviceBitsPerSample')); }),
    colorSpaceName: attempt(function(){ return ObjC.unwrap(dd.objectForKey('NSDeviceColorSpaceName')); })
  });
}
JSON.stringify(out);
"""


def _run_jxa() -> List[Dict[str, Any]]:
    """Run the probe, or raise :class:`DisplayDetectionError` with a printable message."""
    try:
        proc = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", _JXA],
            capture_output=True, text=True, timeout=15,
        )
    except FileNotFoundError as exc:  # pragma: no cover - only on non-macOS
        raise DisplayDetectionError(
            "`osascript` not found — span requires macOS for display detection."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DisplayDetectionError("Display detection timed out.") from exc

    if proc.returncode != 0:
        raise DisplayDetectionError(
            proc.stderr.strip() or f"osascript exited with status {proc.returncode}."
        )
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise DisplayDetectionError(
            f"Could not parse display data from osascript: {proc.stdout!r}"
        ) from exc

    if not isinstance(raw, list):
        raise DisplayDetectionError(f"Unexpected display data shape from osascript: {raw!r}")
    if not raw:
        raise DisplayDetectionError("No displays detected.")
    return raw


def detect_raw() -> List[Dict[str, Any]]:
    """Every field the probe collected, plus the ctypes-only ones, as plain dicts.

    Useful for diagnostics — ``refresh_hz`` and ``visibleFrame`` are not needed for
    layout but they answer "what is actually plugged in".
    """
    raw = _run_jxa()
    for d in raw:
        did = d.get("displayID")
        d["displayID"] = int(did) if isinstance(did, (int, float)) else 0
        d["width_mm"], d["height_mm"] = (
            _screen_size_mm(d["displayID"]) if d["displayID"] else (None, None)
        )
        interval = d.get("refreshInterval")
        d["refresh_hz"] = (
            round(1.0 / interval, 2) if isinstance(interval, (int, float)) and interval else None
        )
    raw.sort(key=lambda d: d.get("x", 0.0))
    return raw


def detect_displays() -> List[Display]:
    """Connected displays, sorted left-to-right.

    The ordering matters: the leftmost display is the calibration datum, and the ones to
    its right are what calibration positions relative to it.
    """
    raw = detect_raw()
    try:
        displays = [
            Display(
                index=int(d["index"]),
                name=str(d["name"]),
                x=float(d["x"]), y=float(d["y"]),
                w=float(d["w"]), h=float(d["h"]),
                scale=float(d["scale"]),
                display_id=int(d["displayID"]),
                width_mm=d["width_mm"], height_mm=d["height_mm"],
            )
            for d in raw
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise DisplayDetectionError(f"Malformed display entry from osascript: {exc}") from exc

    for d in displays:
        diaglog.log(
            "detect.display", index=d.index, name=repr(d.name),
            frame=f"x={d.x} y={d.y} w={d.w} h={d.h}", scale=d.scale,
            native=f"{d.native_w}x{d.native_h}",
            size_mm=f"{d.width_mm}x{d.height_mm}" if d.width_mm else None,
            ppi=round(d.ppi, 1) if d.ppi else None,
        )
    return displays


def signature(displays: List[Display]) -> str:
    """A stable key for this physical setup, for looking up saved calibration.

    Built from names and native sizes rather than ``display_id``, which macOS reassigns
    across reconnects.
    """
    return " | ".join(f"{d.name}@{d.native_w}x{d.native_h}" for d in displays)
