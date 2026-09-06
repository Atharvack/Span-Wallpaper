"""The wall, rendered live across every display.

One fullscreen window per panel. Each draws the SAME pattern, defined once in wall
millimetres, mapped through that panel's own pixel density:

    window_px = (wall_mm - panel.origin_mm) * panel.px_per_mm

Nothing is cropped or resampled — each panel rasterises the shared wall at its own native
resolution. If the model is right, the pattern is continuous across the bezel: circles
close, diagonals carry on, and the same mm rule meets itself.

The vertical offset is adjustable while you watch, so calibration and verification are the
same act. Nudge until the circles close, press Enter, paste the numbers into
``panels_from_displays(..., y_offsets_mm=[...])``.

    python3 playground/wall_live.py
    python3 playground/wall_live.py --y-offsets 0,67.18

Controls
    up / down        nudge this panel 1 mm (shift: 0.2 mm)
    left / right     nudge the bezel gap 1 mm (shift: 0.2 mm)
    g                cycle: full pattern / rules only / circles only
    Enter            print the offsets
    Esc              quit
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from span.algorithm import MM_PER_INCH, estate, panels_from_displays
from span.algorithm import detect_displays

BG = QColor(10, 10, 16)
COLUMN = QColor(22, 26, 44)
RULE = QColor(255, 230, 80)
RULE_SOFT = QColor(120, 96, 20)
DIAG = QColor(120, 255, 180)
CIRCLE = QColor(90, 130, 230)
SEAM = QColor(255, 93, 93)
LABEL = QColor(235, 238, 248)
DIM = QColor(120, 126, 148)

MODES = ("full", "rules", "circles")


class Wall:
    """Shared, mutable wall geometry. Every window reads from this one object."""

    def __init__(self, displays, y_offsets: List[float], gaps: List[float]):
        self.displays = displays
        self.y_offsets = y_offsets
        self.gaps = gaps
        self.mode = 0

    @property
    def panels(self):
        return panels_from_displays(self.displays, gaps_mm=self.gaps,
                                    y_offsets_mm=self.y_offsets)

    @property
    def estate(self):
        return estate(self.panels)

    @property
    def seam_mm(self) -> float:
        """Middle of the physical bezel between the first two panels."""
        ps = self.panels
        if len(ps) < 2:
            return ps[0].right_mm / 2
        return ps[0].right_mm + (self.gaps[0] if self.gaps else 0.0) / 2


class WallWindow(QWidget):
    """Fullscreen view of the wall from one panel's point of view."""

    def __init__(self, wall: Wall, slot: int, dpr: float, repaint_all, commit):
        super().__init__()
        self.wall = wall
        self.slot = slot            # index into wall.panels, left-to-right
        self.dpr = dpr
        self.repaint_all = repaint_all
        self.commit = commit
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setCursor(Qt.CursorShape.CrossCursor)

    @property
    def panel(self):
        return self.wall.panels[self.slot]

    def k(self) -> float:
        """Logical pixels per millimetre on this panel."""
        return (self.panel.ppi / MM_PER_INCH) / self.dpr

    def to_px(self, x_mm: float, y_mm: float) -> QPointF:
        """Wall millimetres -> this window's pixels."""
        p = self.panel
        return QPointF((x_mm - p.x_mm) * self.k(), (y_mm - p.y_mm) * self.k())

    # -- painting ---------------------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), BG)

        est = self.wall.estate
        seam = self.wall.seam_mm
        mode = MODES[self.wall.mode]
        k = self.k()

        def pt(x_mm, y_mm):
            return self.to_px(x_mm, y_mm)

        if mode == "full":
            # Columns: 40 mm on, 40 mm off — same physical width on every panel.
            x_mm = est.x_mm
            while x_mm < est.x_mm + est.w_mm:
                a, b = pt(x_mm, est.y_mm), pt(x_mm + 40, est.y_mm + est.h_mm)
                p.fillRect(int(a.x()), 0, int(b.x() - a.x()), self.height(), COLUMN)
                x_mm += 80

        if mode in ("full", "rules"):
            # Horizontal rules — these are what a wrong y_mm breaks.
            f = QFont()
            f.setPointSizeF(11.0)
            p.setFont(f)
            y_mm = est.y_mm
            while y_mm <= est.y_mm + est.h_mm + 1e-6:
                major = abs(y_mm % 100) < 1e-6
                p.setPen(QPen(RULE if major else RULE_SOFT, 3 if major else 1))
                y = pt(0, y_mm).y()
                p.drawLine(QPointF(0, y), QPointF(self.width(), y))
                if major:
                    p.setPen(QPen(LABEL))
                    p.drawText(QPointF(14, y - 8), f"{int(y_mm)} mm")
                    p.drawText(QPointF(self.width() - 90, y - 8), f"{int(y_mm)} mm")
                y_mm += 25

        if mode == "full":
            # Diagonals react to an error on either axis.
            p.setPen(QPen(DIAG, 3))
            p.drawLine(pt(est.x_mm, est.y_mm), pt(est.x_mm + est.w_mm, est.y_mm + est.h_mm))
            p.drawLine(pt(est.x_mm, est.y_mm + est.h_mm), pt(est.x_mm + est.w_mm, est.y_mm))

        # Circles straddling the seam — the harshest continuity test.
        p.setPen(QPen(CIRCLE, 5))
        for cy_mm, r_mm in ((95, 62), (188, 62), (281, 62)):
            c = pt(seam, est.y_mm + cy_mm)
            p.drawEllipse(c, r_mm * k, r_mm * k)
            p.drawEllipse(c, r_mm * k / 3, r_mm * k / 3)

        p.setPen(QPen(SEAM, 2))
        sx = pt(seam, 0).x()
        p.drawLine(QPointF(sx, 0), QPointF(sx, self.height()))

        # Readout
        f = QFont()
        f.setPointSizeF(15.0)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QPen(LABEL))
        pan = self.panel
        p.drawText(
            QPointF(30, 46),
            f"{pan.name}   y_mm {pan.y_mm:+.2f}   gap {self.wall.gaps[0] if self.wall.gaps else 0:.2f} mm"
            f"   {pan.ppi:.1f} ppi   [{mode}]",
        )
        f.setBold(False)
        f.setPointSizeF(12.0)
        p.setFont(f)
        p.setPen(QPen(DIM))
        p.drawText(
            QPointF(30, self.height() - 32),
            "up/down: this panel 1 mm  ·  left/right: bezel gap  ·  shift: 0.2 mm  ·  "
            "g: pattern  ·  Enter: print  ·  Esc: quit",
        )

    # -- interaction ------------------------------------------------------------------
    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            QApplication.quit()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.commit()
            return
        if key == Qt.Key.Key_G:
            self.wall.mode = (self.wall.mode + 1) % len(MODES)
            self.repaint_all()
            return

        step = 0.2 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        if key == Qt.Key.Key_Up:
            self.wall.y_offsets[self.slot] -= step
        elif key == Qt.Key.Key_Down:
            self.wall.y_offsets[self.slot] += step
        elif key == Qt.Key.Key_Left and self.wall.gaps:
            self.wall.gaps[0] = max(0.0, self.wall.gaps[0] - step)
        elif key == Qt.Key.Key_Right and self.wall.gaps:
            self.wall.gaps[0] += step
        else:
            return
        self.repaint_all()

    def mousePressEvent(self, event):
        self.activateWindow()
        self.setFocus()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--y-offsets", default="0,67.18", help="wall offsets in mm, comma separated")
    ap.add_argument("--gaps", default="0", help="bezel gaps in mm, comma separated")
    args = ap.parse_args(argv)

    app = QApplication(sys.argv[:1])
    displays = [d for d in detect_displays() if d.ppi]
    if not displays:
        print("error: no display reports a physical size (EDID missing).", file=sys.stderr)
        return 2

    y_offsets = [float(v) for v in args.y_offsets.split(",")]
    gaps = [float(v) for v in args.gaps.split(",")] if args.gaps else []
    y_offsets = (y_offsets + [0.0] * len(displays))[:len(displays)]
    gaps = (gaps + [0.0] * len(displays))[:max(len(displays) - 1, 0)]

    wall = Wall(displays, y_offsets, gaps)
    screens = sorted(QGuiApplication.screens(), key=lambda s: s.geometry().x())
    windows: List[WallWindow] = []

    def repaint_all():
        for w in windows:
            w.update()

    def commit():
        base = wall.y_offsets[0]
        norm = [round(v - base, 2) for v in wall.y_offsets]
        est = wall.estate
        print("\nWALL (mm)")
        for p in wall.panels:
            print(f"  {p.name:<14} {p.width_mm:7.1f} x {p.height_mm:6.1f}   "
                  f"top {p.y_mm:7.2f}  bottom {p.bottom_mm:7.2f}")
        print(f"  estate        {est.w_mm:7.1f} x {est.h_mm:6.1f}   seam {wall.seam_mm:.1f} mm")
        print(f"\n  y_offsets_mm={norm}")
        print(f"  gaps_mm={[round(g, 2) for g in wall.gaps]}")

    for i, d in enumerate(displays):
        screen = screens[i] if i < len(screens) else QGuiApplication.primaryScreen()
        w = WallWindow(wall, i, screen.devicePixelRatio(), repaint_all, commit)
        w.setGeometry(screen.geometry())
        w.show()
        w.raise_()
        windows.append(w)

    windows[0].activateWindow()
    windows[0].setFocus()

    print("The wall is live on every display.")
    print("Click a screen to control it, then nudge until the circles close.\n")
    for p in wall.panels:
        print(f"  {p.name:<14} {p.width_mm:7.1f} x {p.height_mm:6.1f} mm  "
              f"@ ({p.x_mm:7.1f}, {p.y_mm:6.2f})   {p.ppi:.1f} ppi")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
