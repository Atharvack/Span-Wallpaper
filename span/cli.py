"""Command-line entry point for span."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from . import diaglog, paths
from .algorithm import (
    Display,
    DisplayDetectionError,
    detect_displays,
    detect_raw,
    estate,
    panels_from_displays,
    signature,
)
from .calibration import load as load_config
from .image_processing import ImageLoadError, load_image


class OutDirError(ValueError):
    """Raised when the requested output directory violates the SPAN_ROOT boundary."""


def resolve_out_dir(arg_out: Optional[str]) -> Path:
    """Resolve (but do not create) the output directory.

    Order: ``--out`` > ``$SPAN_ROOT`` > cwd. When ``SPAN_ROOT`` is set it is a confinement
    boundary and the resolved directory must live inside it. Creation happens later, only
    when files are actually written, so quitting without exporting leaves nothing behind.
    """
    root = os.environ.get("SPAN_ROOT")
    if arg_out:
        out = Path(arg_out).expanduser().resolve()
    elif root:
        out = Path(root).expanduser().resolve()
    else:
        out = Path.cwd().resolve()

    if root:
        root_p = Path(root).expanduser().resolve()
        if out != root_p and root_p not in out.parents:
            raise OutDirError(f"--out {out} is outside SPAN_ROOT {root_p}")
    return out


def _displays_json(displays: List[Display]) -> str:
    return json.dumps(
        [
            {
                "index": d.index, "name": d.name,
                "frame_pt": {"x": d.x, "y": d.y, "w": d.w, "h": d.h},
                "scale": d.scale,
                "native": [d.native_w, d.native_h],
                "size_mm": [d.width_mm, d.height_mm],
                "ppi": round(d.ppi, 2) if d.ppi else None,
            }
            for d in displays
        ],
        indent=2,
    )


def _print_wall(displays: List[Display]) -> int:
    """Show the physical layout as currently calibrated."""
    cfg = load_config(signature(displays), len(displays))
    panels = panels_from_displays(displays, gaps_mm=cfg.gaps_mm,
                                  y_offsets_mm=cfg.y_offsets_mm)
    est = estate(panels)
    print(f"setup: {signature(displays)}")
    print(f"calibrated: {'yes' if cfg.is_measured else 'NO — run `span --calibrate`'}\n")
    for p in panels:
        print(f"  {p.name:<16} {p.width_mm:7.1f} x {p.height_mm:6.1f} mm   "
              f"top {p.y_mm:+7.2f}   {p.ppi:6.1f} ppi   {p.px_w}x{p.px_h}")
    print(f"\n  estate          {est.w_mm:7.1f} x {est.h_mm:6.1f} mm")
    print(f"  y_offsets_mm    {cfg.y_offsets_mm}")
    print(f"  gaps_mm         {cfg.gaps_mm}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="span",
        description="Slice one wallpaper across every connected macOS display, in millimetres.",
    )
    parser.add_argument("image", nargs="?", help="source image path")
    parser.add_argument("--out", metavar="DIR",
                        help="output directory (default: $SPAN_ROOT or current dir)")
    parser.add_argument("--list", action="store_true",
                        help="print detected displays as JSON and exit")
    parser.add_argument("--raw", action="store_true",
                        help="print every field macOS reports, and exit")
    parser.add_argument("--wall", action="store_true",
                        help="print the calibrated physical layout and exit")
    parser.add_argument("--calibrate", action="store_true",
                        help="open in calibration mode, with or without an image")
    parser.add_argument("--paths", action="store_true",
                        help="print where span keeps its config, tmp files and log")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.paths:
        paths.ensure_dirs()
        print(paths.describe())
        return 0

    paths.ensure_dirs()
    log_path = diaglog.enable()
    diaglog.banner("span session start")
    diaglog.log("cli.args", image=args.image, out=args.out, list=args.list,
                calibrate=args.calibrate)
    print(f"[span] diagnostic log → {log_path}", file=sys.stderr)

    # Everything that can fail without a GUI fails here, before Qt is ever imported.
    try:
        if args.raw:
            print(json.dumps(detect_raw(), indent=2))
            return 0
        if args.list:
            print(_displays_json(detect_displays()))
            return 0
        if args.wall:
            return _print_wall(detect_displays())
    except DisplayDetectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        out_dir = resolve_out_dir(args.out)
    except OutDirError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        displays = detect_displays()
    except DisplayDetectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    image = None
    image_stem = "wallpaper"
    image_path = None
    if args.image:
        image_path = Path(args.image).expanduser()
        if not image_path.exists():
            print(f"error: image not found: {image_path}", file=sys.stderr)
            return 1
        try:
            image = load_image(image_path)
        except ImageLoadError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        image_stem = image_path.stem

    config = load_config(signature(displays), len(displays))
    if not config.is_measured:
        print("[span] this setup has no saved calibration yet — the welcome window will "
              "offer it.", file=sys.stderr)

    diaglog.log("cli.out_dir", path=str(out_dir))

    # Import the GUI lazily: --list, --raw, --wall and every error above stay Qt-free.
    from .gui import MODE_CALIBRATE, run

    # Only an explicit --calibrate takes over the screens on launch. An uncalibrated wall
    # is explained on the welcome window instead of being acted on unasked.
    start_mode = MODE_CALIBRATE if args.calibrate else None
    exported = run(displays, config, image, out_dir=out_dir, image_stem=image_stem,
                   start_mode=start_mode, image_path=image_path)

    if not exported:
        print("No files written.")
        return 0
    print(f"Wrote {len(exported)} file(s) to {out_dir}:")
    for p in exported:
        print(f"  {p}")
    return 0
