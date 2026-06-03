"""Crop + resample + save one PNG per display (Pillow).

Cropping reads from the *same* in-memory image the GUI displays (EXIF orientation
already applied upstream), so the saved region matches exactly where the rectangle sat.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from PIL import Image

from .geometry import Box, Display

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(name: str) -> str:
    """Turn a display name into a filesystem-safe token."""
    cleaned = _SAFE.sub("-", name).strip("-")
    return cleaned or "display"


@dataclass
class ExportResult:
    display: Display
    path: Path
    upscaled: bool  # True if the crop was smaller than native (quality may suffer)


def _base_name(display: Display, image_stem: str) -> str:
    return f"{image_stem}_{safe_name(display.name)}_{display.native_w}x{display.native_h}"


def export_crop(
    image: Image.Image,
    display: Display,
    box: Box,
    out_dir: Path,
    filename: str,
) -> ExportResult:
    """Crop ``image`` to ``box`` then resample to the display's native resolution."""
    left, top, right, bottom = box.as_crop()
    # Defensive clamp to a valid in-bounds crop. The GUI already keeps boxes inside the
    # image, but export_crop is public: keep left/top strictly inside so the +1 fallbacks
    # below can never overshoot the image edge (which would crop past the bounds and
    # produce a black strip).
    left = min(max(left, 0), image.width - 1)
    top = min(max(top, 0), image.height - 1)
    right = min(max(right, left + 1), image.width)
    bottom = min(max(bottom, top + 1), image.height)

    crop = image.crop((left, top, right, bottom))
    out = crop.resize((display.native_w, display.native_h), Image.Resampling.LANCZOS)

    path = Path(out_dir) / filename
    out.save(path)

    upscaled = (right - left) < display.native_w or (bottom - top) < display.native_h
    return ExportResult(display=display, path=path, upscaled=upscaled)


def export_all(
    image: Image.Image,
    displays: List[Display],
    boxes: Dict[int, Box],
    out_dir: Path,
    image_stem: str,
) -> List[ExportResult]:
    """Export every display, giving each a unique filename (dedup on collision)."""
    base_counts: Dict[str, int] = {}
    for d in displays:
        base = _base_name(d, image_stem)
        base_counts[base] = base_counts.get(base, 0) + 1

    results: List[ExportResult] = []
    for d in displays:
        base = _base_name(d, image_stem)
        # Two displays with identical name AND native res → disambiguate by index.
        filename = f"{base}_{d.index}.png" if base_counts[base] > 1 else f"{base}.png"
        results.append(export_crop(image, d, boxes[d.index], out_dir, filename))
    return results
