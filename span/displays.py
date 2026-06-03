"""Detect connected displays on macOS via ``NSScreen`` (read-only, no extra deps).

Uses JavaScript-for-Automation (``osascript -l JavaScript``) to read each screen's
frame in global points-space and its backing scale factor. This is a *read-only* system
query — it never writes OS state.
"""

from __future__ import annotations

import json
import subprocess
from typing import List

from .geometry import Display


class DisplayDetectionError(RuntimeError):
    """Raised when the macOS display query fails or returns nothing usable."""


# Reads NSScreen geometry in global points-space (bottom-left origin, y-up).
_JXA = r"""
ObjC.import('AppKit');
var screens = $.NSScreen.screens;
var out = [];
for (var i = 0; i < screens.count; i++) {
  var s = screens.objectAtIndex(i);
  var f = s.frame;
  out.push({
    index: i,
    name: ObjC.unwrap(s.localizedName),
    x: f.origin.x, y: f.origin.y,
    w: f.size.width, h: f.size.height,
    scale: s.backingScaleFactor
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
        displays = [
            Display(
                index=int(d["index"]),
                name=str(d["name"]),
                x=float(d["x"]),
                y=float(d["y"]),
                w=float(d["w"]),
                h=float(d["h"]),
                scale=float(d["scale"]),
            )
            for d in raw
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise DisplayDetectionError(
            f"Malformed display entry from osascript: {exc}"
        ) from exc

    if not displays:
        raise DisplayDetectionError("No displays detected.")

    displays.sort(key=lambda d: d.x)
    return displays
