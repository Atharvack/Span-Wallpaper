"""Wall-coordinate scale test: one live window per display, each drawing the SAME
physical bar.

The premise under test: millimetres are the only unit that means the same thing on two
panels of different pixel density. Each window draws a bar of identical *mm* height,
rendered at its own display's pixel count:

    ED270U P2   108 ppi  ->  4.252 px/mm  ->  250 mm = 1063 px
    Sceptre F24  92 ppi  ->  3.622 px/mm  ->  250 mm =  906 px

157 pixels apart, and they should look identical on the wall. Drag them to the bezel and
compare in wall coordinates — what your eyes see, not what the pixel counts say.

    python3 playground/scale.py
    python3 playground/scale.py --mm 150

Controls:  drag to move  ·  arrow keys nudge 1 px  ·  shift+arrow nudge 10 px  ·  Esc quits
"""

from __future__ import annotations

import argparse
import sys
from typing import List

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from span.algorithm import detect_displays
from span.algorithm import Display

MM_PER_INCH = 25.4

BAR_MM_W = 30.0     # bar width in mm
MARGIN_MM = 16.0    # padding around the bar, in mm
MINOR_MM = 10.0     # unlabelled tick every N mm
MAJOR_MM = 50.0     # labelled tick every N mm

BG = QColor(10, 10, 16)
BAR = QColor(90, 130, 230)
TICK_MINOR = QColor(255, 255, 255)
TICK_MAJOR = QColor(255, 230, 80)
CAPTION = QColor(150, 156, 180)


class ScaleBar(QWidget):
    """A frameless, draggable window showing one display's mm bar at native scale."""

    def __init__(self, display: Display, bar_mm_h: float, dpr: float):
        super().__init__()
        self.display = display
        self.bar_mm_h = bar_mm_h
        # px_per_mm is in DEVICE pixels; Qt sizes windows in logical pixels, so divide
        # by the device pixel ratio. On a 1x display these are the same number.
        self.k_device = display.ppi / MM_PER_INCH
        self.k = self.k_device / dpr
        self.dpr = dpr
        self._drag_from: QPoint | None = None

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setWindowTitle(f"scale — {display.name}")
        self.resize(self.mm(BAR_MM_W + 2 * MARGIN_MM), self.mm(bar_mm_h + 2 * MARGIN_MM))

    def mm(self, v: float) -> int:
        """Millimetres -> logical pixels on this display."""
        return round(v * self.k)

    # -- painting -------------------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), BG)

        x0, y0 = self.mm(MARGIN_MM), self.mm(MARGIN_MM)
        bw, bh = self.mm(BAR_MM_W), self.mm(self.bar_mm_h)
        p.fillRect(x0, y0, bw, bh, BAR)

        # Ticks run past BOTH edges of the bar, so two bars set against the bezel still
        # present a full tick pair to compare across the seam.
        f = QFont()
        f.setPointSizeF(9.0)
        p.setFont(f)

        n = 0
        while n * MINOR_MM <= self.bar_mm_h:
            y = y0 + self.mm(n * MINOR_MM)
            major = abs((n * MINOR_MM) % MAJOR_MM) < 1e-6
            p.setPen(QPen(TICK_MAJOR if major else TICK_MINOR, 2 if major else 1))
            length = self.mm(7.0) if major else self.mm(3.5)
            p.drawLine(x0 - length, y, x0 + bw + length, y)
            if major:
                p.drawText(x0 + bw + length + self.mm(2.0), y + 4, f"{int(n * MINOR_MM)}")
            n += 1

        p.setPen(QPen(CAPTION))
        p.drawText(
            self.mm(3.0),
            self.height() - self.mm(5.0),
            f"{self.display.name}  ·  {self.bar_mm_h:.0f} mm = "
            f"{round(self.bar_mm_h * self.k_device)} px  ·  {self.display.ppi:.1f} ppi",
        )

    # -- interaction ----------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_from is not None:
            self.move(event.globalPosition().toPoint() - self._drag_from)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_from = None

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            QApplication.quit()
            return
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        delta = {
            Qt.Key.Key_Left:  QPoint(-step, 0),
            Qt.Key.Key_Right: QPoint(step, 0),
            Qt.Key.Key_Up:    QPoint(0, -step),
            Qt.Key.Key_Down:  QPoint(0, step),
        }.get(key)
        if delta is not None:
            self.move(self.pos() + delta)
            event.accept()


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mm", type=float, default=250.0, help="bar height in mm (default 250)")
    args = ap.parse_args(argv)

    app = QApplication(sys.argv[:1])

    displays = [d for d in detect_displays() if d.ppi]
    if not displays:
        print("error: no display reports a physical size (EDID missing).", file=sys.stderr)
        return 2

    # Qt screens and span displays are both ordered left-to-right, so zip them.
    screens = sorted(QGuiApplication.screens(), key=lambda s: s.geometry().x())

    print(f"Bar height: {args.mm:.0f} mm — identical physical size on every display.\n")
    windows = []
    for i, d in enumerate(displays):
        screen = screens[i] if i < len(screens) else QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio()
        w = ScaleBar(d, args.mm, dpr)
        geo = screen.geometry()
        # Drop it near the inner edge of its own screen, vertically centred.
        x = geo.x() + (geo.width() - w.width() - 40 if i == 0 else 40)
        w.move(x, geo.y() + (geo.height() - w.height()) // 2)
        w.show()
        w.raise_()
        windows.append(w)
        print(f"  {d.name:<14} {d.ppi:6.1f} ppi   {d.ppi / MM_PER_INCH:.4f} px/mm   "
              f"{args.mm:.0f} mm = {round(args.mm * d.ppi / MM_PER_INCH):>4} px   "
              f"window {w.width()}x{w.height()} @ dpr {dpr:g}")

    print(
        "\n  drag to move · arrows nudge 1 px · shift+arrows 10 px · Esc quits\n\n"
        "Push both bars against the bezel and read across the seam:\n"
        "  same height, ticks aligned  ->  EDID is truthful, mm is a valid common unit\n"
        "  one bar taller              ->  that panel's reported size is wrong; read the\n"
        "                                  mm label where the shorter bar ends to measure it"
    )
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
