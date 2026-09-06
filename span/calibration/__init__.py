"""Measuring where the glass physically is, and remembering it.

macOS reports monitor positions as point counts in a space that assumes uniform pixel
density. For a mixed setup that assumption is false, so those numbers cannot be converted
to millimetres — the error is up to tens of millimetres and shows as a step at the seam.

There is no API for this. The information is a fact about your room, and the only
practical sensor is your own vision, which is exceptionally good at judging whether two
line segments are collinear. So: draw a line on each display, move them until they read
as one, and solve. Measured once per desk, stored, reused.
"""

from . import pattern
from .solve import line_depth_mm, normalize, offsets_from_rows
from .store import WallConfig, config_path, load, save
from .wallpaper import (
    Assignment,
    WallpaperError,
    WallpaperResult,
    assignments_from_exports,
    capture,
    current_wallpapers,
    hide_other_applications,
    load_snapshot,
    load_snapshot_entries,
    restore,
    restored_paths,
    set_wallpapers,
    snapshot_path,
    unhide_all_applications,
)

__all__ = [
    "pattern",
    "line_depth_mm",
    "normalize",
    "offsets_from_rows",
    "WallConfig",
    "config_path",
    "load",
    "save",
    "Assignment",
    "WallpaperError",
    "WallpaperResult",
    "assignments_from_exports",
    "capture",
    "current_wallpapers",
    "hide_other_applications",
    "load_snapshot",
    "load_snapshot_entries",
    "restore",
    "restored_paths",
    "set_wallpapers",
    "snapshot_path",
    "unhide_all_applications",
]
