"""End-to-end: build the wall in mm, pin an image to it, export one PNG per display.

This is the whole model running for real:

    panels_from_displays(..., y_offsets_mm=[...])   measured wall geometry
    plan_layout(...)                                crop boxes, computed in mm
    export_all(...)                                 native-resolution PNGs

With no image given it generates a continuity test pattern drawn directly in wall
millimetres — columns, horizontal rules, diagonals, and circles straddling the seam.
Every feature is placed in mm, so if the model is right they must join across the bezel.
Circles are the harshest test: a broken one is obvious from across the room.

    python3 playground/wall_export.py                        # test pattern
    python3 playground/wall_export.py --image photo.jpg      # a real photo
    python3 playground/wall_export.py --y-offsets 0,67.18    # measured offsets
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont

from span.algorithm import estate, native_scale, panels_from_displays, plan_layout
from span.algorithm import detect_displays
from span.image_processing import export_all

OUT_DIR = Path(__file__).resolve().parent / "out"

BG = (10, 10, 16)
COLUMN = (22, 26, 44)
RULE = (255, 230, 80)
RULE_SOFT = (120, 96, 20)
DIAG = (120, 255, 180)
CIRCLE = (90, 130, 230)
SEAM = (255, 93, 93)
LABEL = (235, 238, 248)


def _font(px: int) -> ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            continue
    return ImageFont.load_default()


def make_pattern(est_w_mm: float, est_h_mm: float, seam_mm: float, S: float) -> Image.Image:
    """Draw a continuity test pattern in wall millimetres, rasterised at S px/mm.

    The image is exactly the size of the estate, so it maps onto the glass 1:1 and every
    feature's mm position is directly checkable against the physical result.
    """
    W, H = round(est_w_mm * S), round(est_h_mm * S)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    def px(v_mm: float) -> int:
        return round(v_mm * S)

    # Columns: 40 mm on, 40 mm off. Same physical width on both panels if the model holds.
    x_mm = 0.0
    while x_mm < est_w_mm:
        d.rectangle([px(x_mm), 0, px(x_mm + 40), H], fill=COLUMN)
        x_mm += 80

    # Horizontal rules every 25 mm, bold and labelled every 100 mm. These are what prove
    # the vertical offset: a wrong y_mm shows up as a step at the bezel.
    f_small, f_big = _font(max(12, px(4))), _font(max(16, px(7)))
    y_mm = 0.0
    while y_mm <= est_h_mm:
        major = abs(y_mm % 100) < 1e-6
        d.line([(0, px(y_mm)), (W, px(y_mm))],
               fill=RULE if major else RULE_SOFT, width=3 if major else 1)
        if major:
            for lx in (px(8), px(seam_mm - 42), px(seam_mm + 10), W - px(48)):
                d.text((lx, px(y_mm) + px(2)), f"{int(y_mm)}mm", fill=LABEL, font=f_small)
        y_mm += 25

    # Diagonals cross the seam at an angle, so they react to an error on either axis.
    d.line([(0, 0), (W, H)], fill=DIAG, width=4)
    d.line([(0, H), (W, 0)], fill=DIAG, width=4)

    # Circles centred exactly on the seam — the harshest continuity test there is.
    for cy_mm, r_mm in ((95, 62), (188, 62), (281, 62)):
        cx, cy, r = px(seam_mm), px(cy_mm), px(r_mm)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=CIRCLE, width=5)
        d.ellipse([cx - r // 3, cy - r // 3, cx + r // 3, cy + r // 3], outline=CIRCLE, width=3)

    # The seam itself, so you can see where the model thinks the bezel is.
    d.line([(px(seam_mm), 0), (px(seam_mm), H)], fill=SEAM, width=2)
    d.text((px(seam_mm) + px(4), px(4)), f"seam @ {seam_mm:.1f}mm", fill=SEAM, font=f_big)
    d.text((px(6), H - px(12)),
           f"wall {est_w_mm:.0f} x {est_h_mm:.0f} mm   ·   {S:.4f} px/mm   ·   {W}x{H} px",
           fill=LABEL, font=f_big)
    return img


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--image", help="source image (default: generated test pattern)")
    ap.add_argument("--y-offsets", default="0,67.18",
                    help="per-display wall offsets in mm, comma separated")
    ap.add_argument("--gaps", default="", help="bezel gaps in mm, comma separated")
    args = ap.parse_args(argv)

    displays = detect_displays()
    y_offsets = [float(v) for v in args.y_offsets.split(",")] if args.y_offsets else None
    gaps = [float(v) for v in args.gaps.split(",")] if args.gaps else None

    panels = panels_from_displays(displays, gaps_mm=gaps, y_offsets_mm=y_offsets)
    est = estate(panels)
    S = native_scale(panels)
    seam_mm = panels[0].right_mm - est.x_mm

    print("WALL (mm)")
    for p in panels:
        print(f"  {p.name:<14} {p.width_mm:7.1f} x {p.height_mm:6.1f}   "
              f"top {p.y_mm:7.2f}  bottom {p.bottom_mm:7.2f}")
    print(f"  estate        {est.w_mm:7.1f} x {est.h_mm:6.1f}   seam at {seam_mm:.1f} mm\n")

    if args.image:
        image = Image.open(args.image).convert("RGB")
        stem = Path(args.image).stem
        plan = plan_layout(panels, image.width, image.height, policy="fit")
    else:
        image = make_pattern(est.w_mm, est.h_mm, seam_mm, S)
        stem = "WALLTEST"
        # The pattern is exactly estate-sized at S, so it overlays the glass 1:1.
        plan = plan_layout(panels, image.width, image.height, scale=S)

    print(f"IMAGE  {image.width}x{image.height} px   "
          f"S = {plan.scale:.4f} px/mm   {plan.image_w_mm:.0f} x {plan.image_h_mm:.0f} mm\n")

    print("CROPS")
    for p in panels:
        b = plan.boxes[p.index]
        print(f"  {p.name:<14} {b.w:7.1f} x {b.h:6.1f} px @ ({b.x:8.1f}, {b.y:7.1f})"
              f"   -> {p.px_w}x{p.px_h}")
    if plan.upscaled:
        print(f"  upscaled: {', '.join(plan.upscaled)}")
    if plan.out_of_bounds:
        print(f"  OUT OF BOUNDS: {', '.join(plan.out_of_bounds)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = export_all(image, panels, plan.boxes, OUT_DIR, stem)
    print("\nWROTE")
    for r in results:
        print(f"  {r.path}")
    print("\nSet each on its matching display, then check the seam:\n"
          "  circles close  ·  diagonals continue  ·  the same mm rule meets itself")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
