"""Assign the exported crops to their displays, via ``NSWorkspace``.

This is the one place span writes OS state, and it only runs when you explicitly ask.
Everything else in the project is read-only.

``NSWorkspace.setDesktopImageURL:forScreen:options:error:`` is per-screen, which is
exactly the shape needed here — a different image on each panel. It is reached through the
same ``osascript -l JavaScript`` bridge :mod:`span.algorithm.displays` uses to read
``NSScreen``, so no new dependency, and because it is a direct AppKit call rather than an
Apple Event it does not trip the Automation permission prompt that a ``System Events``
script would.

Two details that matter:

* **Scaling is pinned explicitly.** The crops are already exactly native resolution, so
  any scaling macOS chose on its own could silently undo the millimetre work. The image is
  set to fill proportionally with clipping allowed — an identity transform when the aspect
  already matches, and still correct on a Retina panel where native pixels are twice the
  points.
* **The file must keep existing.** macOS stores a reference, not a copy, so a wallpaper
  written to the system temp directory reverts as soon as the OS cleans up. Callers should
  pass paths under :func:`span.paths.tmp_dir` or a real output directory.

Screens are matched by ``localizedName``, the same field detection reads, so the mapping
stays correct however the displays are ordered.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from .. import diaglog, paths

# NSImageScaling.NSImageScaleProportionallyUpOrDown — fill the screen, keep the aspect.
_SCALE_PROPORTIONALLY_UP_OR_DOWN = 3

SNAPSHOT_NAME = "wallpaper-before.json"


class WallpaperError(RuntimeError):
    """Raised when the desktop image could not be set."""


@dataclass
class Assignment:
    """One display and the file to show on it."""

    display_name: str
    path: Path


@dataclass
class WallpaperResult:
    display_name: str
    path: Path
    ok: bool
    error: str = ""


_JXA = r"""
ObjC.import('AppKit');

var MAP = __MAP__;
var ws = $.NSWorkspace.sharedWorkspace;
var screens = $.NSScreen.screens;
var results = [];

// Pin the scaling rather than inheriting whatever the OS last used: the crops are already
// native-resolution, so an unexpected scale would undo the millimetre geometry.
function options() {
  var o = $.NSMutableDictionary.alloc.init;
  try {
    o.setObjectForKey($.NSNumber.numberWithInt(__SCALE__),
                      $.NSWorkspaceDesktopImageScalingKey);
    o.setObjectForKey($.NSNumber.numberWithBool(true),
                      $.NSWorkspaceDesktopImageAllowClippingKey);
  } catch (e) {
    // Constants unavailable on this OS version — fall back to the system default rather
    // than failing the whole assignment.
    o = $.NSMutableDictionary.alloc.init;
  }
  return o;
}

for (var i = 0; i < screens.count; i++) {
  var s = screens.objectAtIndex(i);
  var name = ObjC.unwrap(s.localizedName);
  for (var j = 0; j < MAP.length; j++) {
    if (MAP[j].name !== name) { continue; }
    var entry = {name: name, path: MAP[j].path, ok: false, error: ''};
    try {
      var url = $.NSURL.fileURLWithPath(MAP[j].path);
      var err = Ref();
      entry.ok = ws.setDesktopImageURLForScreenOptionsError(url, s, options(), err) === true;
      if (!entry.ok) { entry.error = 'setDesktopImageURL returned false'; }
    } catch (e) {
      entry.error = String(e);
    }
    results.push(entry);
  }
}
JSON.stringify(results);
"""


def _script(assignments: Sequence[Assignment]) -> str:
    payload = json.dumps([{"name": a.display_name, "path": str(Path(a.path).resolve())}
                          for a in assignments])
    return (_JXA
            .replace("__MAP__", payload)
            .replace("__SCALE__", str(_SCALE_PROPORTIONALLY_UP_OR_DOWN)))


def current_wallpapers() -> Dict[str, str]:
    """What each display is showing right now. Read-only; useful for undo and for tests."""
    script = r"""
    ObjC.import('AppKit');
    var ws = $.NSWorkspace.sharedWorkspace;
    var screens = $.NSScreen.screens;
    var out = {};
    for (var i = 0; i < screens.count; i++) {
      var s = screens.objectAtIndex(i);
      var url = ws.desktopImageURLForScreen(s);
      out[ObjC.unwrap(s.localizedName)] = url.isNil() ? null : ObjC.unwrap(url.path);
    }
    JSON.stringify(out);
    """
    try:
        proc = subprocess.run(["osascript", "-l", "JavaScript", "-e", script],
                              capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            return {}
        data = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}
    return {k: v for k, v in data.items() if v} if isinstance(data, dict) else {}


def set_wallpapers(assignments: Sequence[Assignment]) -> List[WallpaperResult]:
    """Set each display's desktop image. Raises only if the bridge itself fails.

    A per-display failure comes back as a :class:`WallpaperResult` with ``ok=False``, so
    one bad screen never prevents the others from being set.
    """
    if not assignments:
        return []

    missing = [str(a.path) for a in assignments if not Path(a.path).exists()]
    if missing:
        raise WallpaperError(f"file(s) do not exist: {', '.join(missing)}")

    try:
        proc = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", _script(assignments)],
            capture_output=True, text=True, timeout=20,
        )
    except FileNotFoundError as exc:  # pragma: no cover - only on non-macOS
        raise WallpaperError("`osascript` not found — setting wallpaper needs macOS.") from exc
    except subprocess.TimeoutExpired as exc:
        raise WallpaperError("Setting the wallpaper timed out.") from exc

    if proc.returncode != 0:
        raise WallpaperError(proc.stderr.strip()
                             or f"osascript exited with status {proc.returncode}.")
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise WallpaperError(f"Unreadable response from osascript: {proc.stdout!r}") from exc
    if not isinstance(raw, list):
        raise WallpaperError(f"Unexpected response shape: {raw!r}")

    results = [
        WallpaperResult(display_name=str(e.get("name", "")), path=Path(e.get("path", "")),
                        ok=bool(e.get("ok")), error=str(e.get("error", "")))
        for e in raw
    ]
    named = {a.display_name for a in assignments}
    for name in sorted(named - {r.display_name for r in results}):
        # A display in the request that no screen matched — unplugged mid-run, most likely.
        results.append(WallpaperResult(name, Path(), False, "no matching screen"))

    for r in results:
        diaglog.log("wallpaper.set", display=repr(r.display_name), path=str(r.path),
                    ok=r.ok, error=r.error or None)
    return results


def assignments_from_exports(exports: Sequence[Tuple[str, Path]]) -> List[Assignment]:
    """Convenience: ``[(display_name, path), ...]`` -> assignments."""
    return [Assignment(display_name=name, path=Path(path)) for name, path in exports]


# --------------------------------------------------------------------------------------
# Undo
# --------------------------------------------------------------------------------------
#
# Setting a wallpaper is the one irreversible-looking thing span does, so it is offered
# with a way back: record what was showing, set the new images, and let the user confirm.
# Only the per-screen *paths* are recorded — the originals are the user's own files and
# already exist on disk, so copying megabytes for a one-minute undo window would be waste.
# What the snapshot cannot survive is the original file being deleted in the meantime,
# which :func:`restore` reports rather than silently skipping.

def snapshot_path() -> Path:
    return paths.tmp_dir() / SNAPSHOT_NAME


def capture(path: Optional[Path] = None) -> Dict[str, str]:
    """Record what each display is showing now, so :func:`restore` can put it back."""
    current = current_wallpapers()
    target = Path(path) if path is not None else snapshot_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    except OSError as exc:
        # An unwritable snapshot must not block the set — the in-memory copy is enough
        # for the confirmation dialog, which is the common case.
        diaglog.log("wallpaper.capture_failed", path=str(target), error=repr(str(exc)))
    diaglog.log("wallpaper.captured", displays=len(current), path=str(target))
    return current


def load_snapshot(path: Optional[Path] = None) -> Dict[str, str]:
    """Read back a captured mapping, or ``{}`` if there is not a usable one."""
    target = Path(path) if path is not None else snapshot_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(k): str(v) for k, v in data.items() if v} if isinstance(data, dict) else {}


def restore(
    snapshot: Optional[Dict[str, str]] = None, path: Optional[Path] = None
) -> List[WallpaperResult]:
    """Put back a captured mapping. Missing originals come back as failed results."""
    mapping = snapshot if snapshot is not None else load_snapshot(path)
    if not mapping:
        return []

    assignments, gone = [], []
    for name, p in mapping.items():
        if Path(p).exists():
            assignments.append(Assignment(name, Path(p)))
        else:
            gone.append(WallpaperResult(name, Path(p), False, "original file is gone"))

    results = set_wallpapers(assignments) if assignments else []
    for g in gone:
        diaglog.log("wallpaper.restore_missing", display=repr(g.display_name), path=str(g.path))
    return results + gone
