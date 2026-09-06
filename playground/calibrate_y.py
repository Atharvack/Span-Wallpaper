"""Solve each panel's vertical position on the wall, by eye.

macOS cannot tell you where your monitors physically sit — its arrangement is a point
count in a space that assumes uniform pixel density. So we ask the only sensor that can
answer: your eyes.

One fullscreen window per display, each drawing a horizontal line. Drag them until they
read as ONE continuous line across the bezels. Judging collinearity is the sharpest thing
human vision does (vernier acuity), so this is a more precise measurement than a ruler —
and it captures perceptual truth from where you actually sit, which is what you want.

The maths, once the lines match:

    d_i = row_i / px_per_mm_i          depth of the line below panel i's top edge, mm
    y_offset_i = d_0 - d_i             panel i's top edge relative to panel 0's

Feed the result straight into span.algorithm:

    panels_from_displays(displays, y_offsets_mm=[...])

    python3 playground/calibrate_y.py

Controls:  drag the line  ·  up/down nudge 1 px  ·  shift 10 px  ·  Enter saves  ·  Esc quits
"""

from __future__ import annotations

import sys
from typing import Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from span.algorithm import detect_displays
from span.algorithm import Display

MM_PER_INCH = 25.4

BG = QColor(10, 10, 16)
LINE = QColor(255, 230, 80)
LINE_HALO = QColor(90, 130, 230)
TEXT = QColor(190, 196, 214)
DIM = QColor(110, 116, 136)


class LineWindow(QWidget):
    """Fullscreen window on one display, drawing a draggable horizontal line."""

    def __init__(self, display: Display, dpr: float, on_commit):
        super().__init__()
        self.display = display
        self.dpr = dpr
        self.on_commit = on_commit
        self.px_per_mm_device = display.ppi / MM_PER_INCH
        self.px_per_mm = self.px_per_mm_device / dpr   # logical px per mm
        self._dragging = False

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.row = 0  # logical px from the top of this window; set once shown

    # -- the measurement --------------------------------------------------------------
    def row_device(self) -> int:
        """The line's position in this panel's REAL pixels, from its top edge."""
        return round(self.row * self.dpr)

    def depth_mm(self) -> float:
        """How far below this panel's top edge the line physically sits."""
        return self.row_device() / self.px_per_mm_device

    # -- painting ---------------------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), BG)
        w = self.width()

        # A soft wide band under a thin bright line: the band makes the line easy to find,
        # the thin core is what your eye actually judges collinearity on.
        halo = QColor(LINE_HALO)
        halo.setAlpha(70)
        p.fillRect(0, self.row - 6, w, 13, halo)
        p.setPen(QPen(LINE, 1))
        p.drawLine(0, self.row, w, self.row)

        f = QFont()
        f.setPointSizeF(13.0)
        p.setFont(f)
        p.setPen(QPen(TEXT))
        p.drawText(
            30, self.row - 22,
            f"{self.display.name}   row {self.row_device()} px   "
            f"{self.depth_mm():.1f} mm below this panel's top edge",
        )
        f.setPointSizeF(11.0)
        p.setFont(f)
        p.setPen(QPen(DIM))
        p.drawText(
            30, self.height() - 30,
            "drag the line  ·  up/down 1 px  ·  shift+up/down 10 px  ·  "
            "Enter saves  ·  Esc quits",
        )

    # -- interaction ------------------------------------------------------------------
    def mousePressEvent(self, event):
        self._dragging = True
        self.row = int(event.position().y())
        self.update()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.row = max(0, min(int(event.position().y()), self.height() - 1))
            self.update()

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            QApplication.quit()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_S):
            self.on_commit()
            return
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        if key == Qt.Key.Key_Up:
            self.row = max(0, self.row - step)
        elif key == Qt.Key.Key_Down:
            self.row = min(self.height() - 1, self.row + step)
        else:
            return
        self.update()


def main() -> int:
    app = QApplication(sys.argv[:1])

    displays = [d for d in detect_displays() if d.ppi]
    if not displays:
        print("error: no display reports a physical size (EDID missing).", file=sys.stderr)
        return 2

    screens = sorted(QGuiApplication.screens(), key=lambda s: s.geometry().x())
    windows: List[LineWindow] = []

    def commit():
        """Convert the placed lines into wall offsets and print them."""
        depths: Dict[int, float] = {w.display.index: w.depth_mm() for w in windows}
        datum = windows[0].depth_mm()

        print("\nLINE POSITIONS")
        for w in windows:
            print(f"  {w.display.name:<14} row {w.row_device():>5} px   "
                  f"{w.depth_mm():7.2f} mm below its top edge   "
                  f"({w.px_per_mm_device:.4f} px/mm)")

        offsets = [round(datum - depths[w.display.index], 2) for w in windows]
        print(f"\nWALL OFFSETS  (datum = {windows[0].display.name}, + means lower)")
        for w, o in zip(windows, offsets):
            print(f"  {w.display.name:<14} y_mm = {o:+8.2f}")

        print("\nUse it:")
        print(f"  panels_from_displays(detect_displays(), y_offsets_mm={offsets})")
        QApplication.quit()

    for i, d in enumerate(displays):
        screen = screens[i] if i < len(screens) else QGuiApplication.primaryScreen()
        w = LineWindow(d, screen.devicePixelRatio(), commit)
        geo = screen.geometry()
        w.setGeometry(geo)
        w.show()
        w.raise_()
        w.row = geo.height() // 2   # start mid-screen; needs the real height first
        windows.append(w)

    windows[0].activateWindow()
    windows[0].setFocus()

    print("Drag each line until they read as ONE continuous line across the bezels.")
    print("Then press Enter on any window.\n")
    for w in windows:
        print(f"  {w.display.name:<14} {w.display.ppi:6.1f} ppi   "
              f"{w.px_per_mm_device:.4f} px/mm   {w.display.native_w}x{w.display.native_h}")

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
