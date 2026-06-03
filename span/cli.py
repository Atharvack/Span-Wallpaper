"""Command-line entry point for span."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from . import diaglog
from .displays import DisplayDetectionError, detect_displays
from .export import export_all
from .geometry import Display


def _displays_json(displays: List[Display]) -> str:
    return json.dumps(
        [
            {
                "index": d.index,
                "name": d.name,
                "x": d.x,
                "y": d.y,
                "w": d.w,
                "h": d.h,
                "scale": d.scale,
                "native_w": d.native_w,
                "native_h": d.native_h,
            }
            for d in displays
        ],
        indent=2,
    )


class OutDirError(ValueError):
    """Raised when the requested output directory violates the SPAN_ROOT boundary."""


def resolve_out_dir(arg_out: Optional[str]) -> Path:
    """Resolve (but do not create) the output directory.

    Order: ``--out`` arg > ``$SPAN_ROOT`` > current working directory. When
    ``$SPAN_ROOT`` is set it acts as a confinement boundary: the resolved directory must
    live inside it. The directory is created later, only when files are actually written,
    so cancelling the dialog never leaves an empty directory behind.
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


def _prompt_image() -> str:
    try:
        return input("Image path: ").strip()
    except EOFError:
        return ""


def _load_image(path: Path) -> Image.Image:
    try:
        img = Image.open(path)
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise SystemExit(f"error: cannot open image {path}: {exc}")
    original_size = img.size
    orientation = img.getexif().get(274)  # 274 = EXIF Orientation tag
    # Honor EXIF orientation so the preview and the crops match what the user sees.
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    diaglog.log(
        "cli.load_image",
        path=str(path),
        original=f"{original_size[0]}x{original_size[1]}",
        exif_orientation=orientation,
        loaded=f"{img.width}x{img.height}",
        mode=img.mode,
    )
    return img


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="span",
        description="Slice one wallpaper across every connected macOS display.",
    )
    parser.add_argument("image", nargs="?", help="source image path (prompted if omitted)")
    parser.add_argument(
        "--out", metavar="DIR", help="output directory (default: $SPAN_ROOT or current dir)"
    )
    parser.add_argument(
        "--list", action="store_true", help="print detected displays as JSON and exit"
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    log_path = diaglog.enable()
    diaglog.banner("span session start")
    diaglog.log("cli.args", image=args.image, out=args.out, list=args.list)
    print(f"[span] diagnostic log → {log_path}", file=sys.stderr)

    if args.list:
        try:
            print(_displays_json(detect_displays()))
        except DisplayDetectionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        return 0

    # Validate the output location early — fail fast before prompting or opening the GUI.
    try:
        out_dir = resolve_out_dir(args.out)
    except OutDirError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    image_arg = args.image or _prompt_image()
    if not image_arg:
        print("error: no image provided.", file=sys.stderr)
        return 1
    image_path = Path(image_arg).expanduser()
    if not image_path.exists():
        print(f"error: image not found: {image_path}", file=sys.stderr)
        return 1

    try:
        displays = detect_displays()
    except DisplayDetectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    diaglog.log("cli.out_dir", path=str(out_dir))
    image = _load_image(image_path)

    # Import the GUI lazily so --list and early errors never spin up a Qt event loop.
    from .gui import run_dialog

    boxes = run_dialog(image, displays)
    if boxes is None:
        diaglog.log("cli.cancelled")
        print("Cancelled — no files written.")
        return 0

    for d in displays:
        b = boxes[d.index]
        diaglog.log("cli.apply_box", display=repr(d.name),
                    box=f"({b.x:.2f},{b.y:.2f} {b.w:.2f}x{b.h:.2f})", as_crop=b.as_crop())

    # Create the output directory only now that we will actually write to it.
    out_dir.mkdir(parents=True, exist_ok=True)
    results = export_all(image, displays, boxes, out_dir, image_path.stem)
    print(f"Wrote {len(results)} file(s) to {out_dir}:")
    for r in results:
        suffix = "  ⚠ upscaled (source smaller than native)" if r.upscaled else ""
        print(f"  {r.path}{suffix}")
    return 0
