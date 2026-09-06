"""Persist the wall geometry, keyed by which monitors are plugged in.

Calibration measures physical constants: where the glass is. Those do not change when you
switch wallpapers or reboot — only when you physically move a monitor. So it is measured
once and stored, not repeated per image.

Saved to ``~/.span/wall.json`` (override with ``$SPAN_HOME``), keyed by a signature built
from display names and native sizes. Unplug a monitor and plug it back in and the same
entry is found; add a different monitor and you get a fresh, uncalibrated setup rather
than silently wrong numbers.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .. import diaglog, paths


@dataclass
class WallConfig:
    """The measured geometry for one physical setup.

    ``y_offsets_mm`` is per display, positive meaning lower; ``gaps_mm`` is the bezel gap
    between consecutive displays, so it has one fewer entry.
    """

    y_offsets_mm: List[float] = field(default_factory=list)
    gaps_mm: List[float] = field(default_factory=list)
    note: str = ""

    def sized_for(self, n_displays: int) -> "WallConfig":
        """Pad or trim to match a display count, so a stale entry can never crash a run."""
        y = (list(self.y_offsets_mm) + [0.0] * n_displays)[:n_displays]
        g = (list(self.gaps_mm) + [0.0] * max(n_displays - 1, 0))[:max(n_displays - 1, 0)]
        return WallConfig(y_offsets_mm=y, gaps_mm=g, note=self.note)

    @property
    def is_measured(self) -> bool:
        """False when every number is still zero — the uncalibrated default."""
        return any(abs(v) > 1e-9 for v in list(self.y_offsets_mm) + list(self.gaps_mm))


def config_dir() -> Path:
    return paths.home()


def config_path() -> Path:
    return paths.config_file()


def _read_all() -> Dict[str, dict]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # A corrupt config must not stop the app — fall back to uncalibrated.
        diaglog.log("calibration.read_failed", path=str(path), error=repr(str(exc)))
        return {}
    return data if isinstance(data, dict) else {}


def load(signature: str, n_displays: Optional[int] = None) -> WallConfig:
    """The saved config for this setup, or an all-zero one if it has never been measured."""
    entry = _read_all().get(signature)
    if not isinstance(entry, dict):
        cfg = WallConfig()
        diaglog.log("calibration.miss", signature=repr(signature))
    else:
        cfg = WallConfig(
            y_offsets_mm=[float(v) for v in entry.get("y_offsets_mm", [])],
            gaps_mm=[float(v) for v in entry.get("gaps_mm", [])],
            note=str(entry.get("note", "")),
        )
        diaglog.log("calibration.loaded", signature=repr(signature),
                    y=cfg.y_offsets_mm, gaps=cfg.gaps_mm)
    return cfg.sized_for(n_displays) if n_displays is not None else cfg


def save(signature: str, config: WallConfig) -> Path:
    """Write this setup's config, leaving every other setup's entry untouched."""
    data = _read_all()
    data[signature] = asdict(config)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    diaglog.log("calibration.saved", path=str(path), signature=repr(signature),
                y=config.y_offsets_mm, gaps=config.gaps_mm)
    return path
