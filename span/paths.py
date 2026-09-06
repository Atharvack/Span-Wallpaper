"""Where span keeps its runtime files.

One base directory holding everything:

    tmp/wall.json              measured wall geometry, per setup
    tmp/wallpaper-before.json  what was on screen before the last set
    tmp/*.png                  every generated image — exports, patterns
    tmp/desktop_wallpaper_do_not_remove/
                               the images currently ON your desktop
    logs/span.log              one append-only log, every session, tailable

The `desktop_wallpaper_do_not_remove` folder is named as a warning to a future human with
a cleanup impulse. macOS stores a *reference* to a wallpaper file rather than a copy, so
deleting what is in there blanks the desktop. Nothing else is written to it, it holds
only the current set, and pruning never touches it.

Which base depends on how span is running. From a source checkout it is the **project
root**, so the files sit beside the code where you can see and tail them while working.
Installed as a package there is no checkout to write into, so it falls back to
``~/.span``. ``$SPAN_HOME`` overrides both.

``tmp`` is span's whole working directory, state and images together. Pruning only ever
removes *images*, so the JSON state files living beside them are never at risk.

The log is deliberately a single file rather than one per run: to watch what the tool is
doing you point a terminal at it once and leave it there.

    tail -f ~/.span/logs/span.log

``tmp`` matters more than it looks. macOS stores a *reference* to a wallpaper file, so an
image set as wallpaper must keep existing at that path — writing it to the system temp
directory would make the desktop revert as soon as the OS cleaned up. Files here persist
until :func:`prune_tmp` removes the oldest.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable, List, Optional

DEFAULT_HOME = "~/.span"
LOG_NAME = "span.log"
TMP_KEEP = 60          # generated images retained before the oldest are pruned

# Only these are ever pruned. State files (wall.json, wallpaper-before.json) share the
# directory and must survive.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".gif"}


def project_root() -> Optional[Path]:
    """The repo root when running from a source checkout, else ``None``.

    Detected by ``pyproject.toml`` sitting next to the package — present in a checkout
    (including an editable install), absent once the package is installed for real.
    """
    root = Path(__file__).resolve().parent.parent
    return root if (root / "pyproject.toml").is_file() else None


def home() -> Path:
    """The base directory: ``$SPAN_HOME``, else the checkout, else ``~/.span``."""
    env = os.environ.get("SPAN_HOME")
    if env:
        return Path(env).expanduser()
    return project_root() or Path(DEFAULT_HOME).expanduser()


def tmp_dir() -> Path:
    return home() / "tmp"


def wallpaper_root() -> Path:
    """Everything macOS may be referencing. The long name is the warning label."""
    return tmp_dir() / "desktop_wallpaper_do_not_remove"


def wallpaper_dir() -> Path:
    """The images actually on the desktop right now."""
    return wallpaper_root() / "current"


def pending_dir() -> Path:
    """A newly set wallpaper that has not been confirmed yet.

    Kept apart from ``current`` on purpose. When both sets shared a folder, "clear away
    the rejected files" and "clear the folder" were the same operation, and a Revert
    deleted the wallpaper it had just restored to. Now Revert only ever empties *this*
    directory, so it cannot reach a live file however the code is written.
    """
    return wallpaper_root() / "pending"


def revert_dir() -> Path:
    """Copies of whatever was on the desktop before the last set.

    A path alone is not a safe undo — the original can be moved, renamed, or deleted
    between setting a new wallpaper and deciding to reject it. Holding an actual copy
    means Revert cannot fail for want of a file.
    """
    return wallpaper_root() / "revert"


def log_dir() -> Path:
    return home() / "logs"


def log_file() -> Path:
    """The append-only log. ``$SPAN_DIAG_LOG`` overrides it outright."""
    override = os.environ.get("SPAN_DIAG_LOG")
    return Path(override).expanduser() if override else log_dir() / LOG_NAME


def config_file() -> Path:
    return tmp_dir() / "wall.json"


def ensure_dirs() -> None:
    """Create the base layout. Safe to call repeatedly; ignores a read-only home."""
    for d in (home(), tmp_dir(), wallpaper_root(), wallpaper_dir(), pending_dir(),
              revert_dir(), log_dir()):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


def prune_tmp(keep: int = TMP_KEEP, protect: Optional[Iterable[Path]] = None) -> List[Path]:
    """Delete all but the ``keep`` newest *images* in ``tmp``. Returns what was removed.

    Only image files are considered — the JSON state beside them is never touched. Anything
    in ``protect`` is skipped outright, which is how a file currently serving as someone's
    wallpaper survives regardless of age.

    Called after a set rather than before, so the file just handed to the window server is
    never the one deleted.
    """
    d = tmp_dir()
    if not d.is_dir():
        return []
    keep_paths = {Path(p).resolve() for p in (protect or ())}
    # iterdir does not recurse, so desktop_wallpaper_do_not_remove/ is out of reach here
    # by construction rather than by an exclusion that could be forgotten.
    images = sorted(
        (f for f in d.iterdir()
         if f.is_file() and f.suffix.lower() in IMAGE_SUFFIXES
         and f.resolve() not in keep_paths),
        key=lambda f: f.stat().st_mtime, reverse=True,
    )
    removed: List[Path] = []
    for f in images[keep:]:
        try:
            f.unlink()
            removed.append(f)
        except OSError:
            pass
    return removed


def _empty(d: Path, keep: Optional[Iterable[Path]] = None) -> List[Path]:
    """Delete the files in ``d``, except any in ``keep``. Returns what went."""
    if not d.is_dir():
        return []
    keep_paths = {Path(p).resolve() for p in (keep or ())}
    removed: List[Path] = []
    for f in d.iterdir():
        if not f.is_file() or f.resolve() in keep_paths:
            continue
        try:
            f.unlink()
            removed.append(f)
        except OSError:
            pass
    return removed


def clear_pending() -> List[Path]:
    """Throw away a rejected set.

    The only deletion Revert performs. It cannot reach ``current`` or ``revert`` — not
    because it is careful, but because it is not given their paths.
    """
    return _empty(pending_dir())


def promote_pending(files: Iterable[Path]) -> List[Path]:
    """Move a confirmed set from ``pending`` into ``current``. Returns the new paths.

    Copy first, then remove the source: a half-finished move must not be able to leave a
    file that macOS references in neither place.
    """
    wallpaper_dir().mkdir(parents=True, exist_ok=True)
    promoted: List[Path] = []
    for src in files:
        src = Path(src)
        if not src.is_file():
            continue
        dest = wallpaper_dir() / src.name
        try:
            shutil.copy2(src, dest)
            promoted.append(dest)
        except OSError:
            continue
    # Only now is it safe to drop the originals and the superseded set.
    _empty(pending_dir())
    _empty(wallpaper_dir(), keep=promoted)
    return promoted


LAST_DIR_NAME = "last-image-dir.txt"


def last_image_dir() -> Optional[Path]:
    """The folder the file chooser was last used in, if it still exists."""
    try:
        raw = (tmp_dir() / LAST_DIR_NAME).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    p = Path(raw).expanduser()
    return p if p.is_dir() else None


def remember_image_dir(path: Path) -> None:
    """Remember where an image was picked from, so the next open starts there."""
    directory = Path(path)
    directory = directory if directory.is_dir() else directory.parent
    try:
        tmp_dir().mkdir(parents=True, exist_ok=True)
        (tmp_dir() / LAST_DIR_NAME).write_text(str(directory) + "\n", encoding="utf-8")
    except OSError:
        pass          # a forgotten directory is a small loss; never block the open


def describe() -> str:
    """Human-readable summary of every path, for ``span --paths``."""
    rows = [
        ("home", home()),
        ("tmp", tmp_dir()),
        ("wallpaper", wallpaper_dir()),
        ("calibration", config_file()),
        ("log", log_file()),
    ]
    width = max(len(name) for name, _ in rows)
    lines = [f"  {name:<{width}}  {path}" for name, path in rows]
    lines.append("")
    lines.append(f"  tail -f {log_file()}")
    return "\n".join(lines)
