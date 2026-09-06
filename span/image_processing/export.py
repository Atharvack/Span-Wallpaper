"""Crop, resample to native resolution, and save — one PNG per panel.

Deliberately dull, because everything interesting already happened in millimetres. This
module's only jobs are to cut exactly the box it was given, never to upscale silently,
and never to overwrite a file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

from PIL import Image

from .. import diaglog
from ..algorithm.wall import Box, Panel

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(name: str) -> str:
    """Turn a display name into a filesystem-safe token."""
    cleaned = _SAFE.sub("-", name).strip("-")
    return cleaned or "display"


def unique_path(path: Path) -> Path:
    """``path`` if free, else ``stem (1).ext``, ``stem (2).ext``, … — never overwrite.

    Calibration is iterative: export, look at the seam, adjust, export again. Overwriting
    would destroy the previous round before you had finished comparing it.
    """
    if not path.exists():
        return path
    n = 1
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


@dataclass
class ExportResult:
    panel: Panel
    path: Path
    upscaled: bool     # crop was smaller than the panel; quality suffered
    resampled: bool    # False means a true 1:1 cut, untouched pixels


def _base_name(panel: Panel, image_stem: str) -> str:
    return f"{image_stem}_{safe_name(panel.name)}_{panel.px_w}x{panel.px_h}"


def export_crop(
    image: Image.Image, panel: Panel, box: Box, out_dir: Path, filename: str
) -> ExportResult:
    """Cut ``box`` out of ``image`` and resample it to the panel's native resolution."""
    raw_crop = box.as_crop()
    left, top, right, bottom = raw_crop
    # Defensive clamp to a valid in-bounds crop. Callers normally keep boxes inside the
    # image, but this is public: pin left/top strictly inside first so the +1 minimums
    # below cannot overshoot the edge, which Pillow would pad with black.
    left = min(max(left, 0), image.width - 1)
    top = min(max(top, 0), image.height - 1)
    right = min(max(right, left + 1), image.width)
    bottom = min(max(bottom, top + 1), image.height)

    crop = image.crop((left, top, right, bottom))
    if (right - left, bottom - top) == (panel.px_w, panel.px_h):
        out, resampled = crop, False        # exact native pixels, zero resampling
    else:
        out = crop.resize((panel.px_w, panel.px_h), Image.Resampling.LANCZOS)
        resampled = True

    path = unique_path(Path(out_dir) / filename)
    out.save(path)

    upscaled = (right - left) < panel.px_w or (bottom - top) < panel.px_h
    diaglog.log(
        "export.saved", panel=repr(panel.name), path=path.name,
        box=f"({box.x:.2f},{box.y:.2f} {box.w:.2f}x{box.h:.2f})",
        raw_crop=raw_crop, clamped=(left, top, right, bottom),
        out_size=out.size, upscaled=upscaled, resampled=resampled,
    )
    return ExportResult(panel=panel, path=path, upscaled=upscaled, resampled=resampled)


def export_all(
    image: Image.Image,
    panels: Sequence[Panel],
    boxes: Dict[int, Box],
    out_dir: Path,
    image_stem: str,
) -> List[ExportResult]:
    """Export every panel, giving each a unique filename.

    Counted in two passes so the common case — panels with different names or resolutions
    — gets clean filenames, and only a genuinely ambiguous pair pays for an index suffix.
    """
    base_counts: Dict[str, int] = {}
    for p in panels:
        base = _base_name(p, image_stem)
        base_counts[base] = base_counts.get(base, 0) + 1

    results: List[ExportResult] = []
    for p in panels:
        base = _base_name(p, image_stem)
        filename = f"{base}_{p.index}.png" if base_counts[base] > 1 else f"{base}.png"
        results.append(export_crop(image, p, boxes[p.index], out_dir, filename))
    return results
