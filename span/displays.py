"""Detect connected displays on macOS via ``NSScreen`` (read-only, no extra deps).

Uses JavaScript-for-Automation (``osascript -l JavaScript``) to read each screen's
frame in global points-space and its backing scale factor. This is a *read-only* system
query — it never writes OS state.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
from typing import List, Optional, Tuple

from . import diaglog
from .geometry import Display


class DisplayDetectionError(RuntimeError):
    """Raised when the macOS display query fails or returns nothing usable."""


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


def _screen_size_mm(display_id: int) -> Tuple[Optional[float], Optional[float]]:
    """Physical size in millimeters via CGDisplayScreenSize, or (None, None).

    Best-effort: EDID may be missing for some external displays, in which case this
    returns zeros (treated as unknown) and the tool falls back to points-based layout.
    """
    try:
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cg.CGDisplayScreenSize.restype = _CGSize
        cg.CGDisplayScreenSize.argtypes = [ctypes.c_uint32]
        size = cg.CGDisplayScreenSize(ctypes.c_uint32(int(display_id)))
        if size.width > 0 and size.height > 0:
            return (float(size.width), float(size.height))
    except Exception:  # pragma: no cover - platform/EDID dependent
        pass
    return (None, None)


# Reads NSScreen geometry in global points-space (bottom-left origin, y-up).
_JXA = r"""
ObjC.import('AppKit');
var screens = $.NSScreen.screens;
var out = [];
for (var i = 0; i < screens.count; i++) {
  var s = screens.objectAtIndex(i);
  var f = s.frame;
  var num = s.deviceDescription.objectForKey('NSScreenNumber');
  out.push({
    index: i,
    name: ObjC.unwrap(s.localizedName),
    x: f.origin.x, y: f.origin.y,
    w: f.size.width, h: f.size.height,
    scale: s.backingScaleFactor,
    displayID: ObjC.unwrap(num)
  });
}
JSON.stringify(out);
"""


def detect_displays() -> List[Display]:
    """Return connected displays, sorted left-to-right by global ``x``.

    Raises:
        DisplayDetectionError: if ``osascript`` is missing, errors, returns unparseable
            output, or reports no displays.
    """
    try:
        proc = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", _JXA],
            capture_output=True,
            text=True,
            timeout=15,
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
        raise DisplayDetectionError(
            f"Unexpected display data shape from osascript: {raw!r}"
        )

    try:
        displays = []
        for d in raw:
            display_id = int(d.get("displayID") or 0)
            width_mm, height_mm = _screen_size_mm(display_id) if display_id else (None, None)
            displays.append(
                Display(
                    index=int(d["index"]),
                    name=str(d["name"]),
                    x=float(d["x"]),
                    y=float(d["y"]),
                    w=float(d["w"]),
                    h=float(d["h"]),
                    scale=float(d["scale"]),
                    display_id=display_id,
                    width_mm=width_mm,
                    height_mm=height_mm,
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise DisplayDetectionError(
            f"Malformed display entry from osascript: {exc}"
        ) from exc

    if not displays:
        raise DisplayDetectionError("No displays detected.")

    displays.sort(key=lambda d: d.x)
    for d in displays:
        ppi = round(d.ppi, 1) if d.ppi else None
        diaglog.log(
            "detect.display",
            index=d.index,
            name=repr(d.name),
            frame=f"x={d.x} y={d.y} w={d.w} h={d.h}",
            scale=d.scale,
            native=f"{d.native_w}x{d.native_h}",
            aspect=round(d.aspect, 6),
            size_mm=f"{d.width_mm}x{d.height_mm}" if d.width_mm else None,
            ppi=ppi,
        )
    return displays
