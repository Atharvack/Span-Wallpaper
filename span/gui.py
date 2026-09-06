"""The app: the wall, live across every display.

One fullscreen window per panel. Each renders the shared wall through its own pixel
density, so what you see *is* the export — the rectangle drawn on screen is literally the
crop box handed to Pillow.

    window_px = (wall_mm - panel.origin_mm) * panel.px_per_mm

Two modes, because there are two different unknowns:

* **calibrate** — where the glass physically is. A fact about your room, measured once by
  eye and stored. Nudge until the pattern joins across the bezel.
* **place** — where you want the picture. A preference. Drag the image behind the fixed
  panels; the panels never move, because they cannot.

The panels being immovable is the point. Earlier versions let you drag rectangles over an
image, which had it backwards: monitors are fixed, the poster is what slides.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import diaglog, paths
from .algorithm import (
    Display,
    Panel,
    Plan,
    choose_scale,
    clamp_offset,
    estate,
    panels_from_displays,
    plan_layout,
    seam_positions,
    signature,
)
from .calibration import (
    WallConfig,
    WallpaperError,
    assignments_from_exports,
    capture,
    hide_other_applications,
    normalize,
    pattern,
    restore,
    restored_paths,
    set_wallpapers,
    unhide_all_applications,
)
from .calibration import save as save_config

KEEP_SECONDS = 60
from .image_processing import ImageLoadError, export_all, load_image

IMAGE_FILTER = (
    "Images (*.png *.jpg *.jpeg *.heic *.heif *.tif *.tiff *.webp *.bmp *.gif);;"
    "All files (*)"
)

BG = QColor(10, 10, 16)
HUD = QColor(236, 239, 248)
HUD_DIM = QColor(126, 132, 154)
HUD_KEY = QColor(90, 130, 230)
WARN = QColor(255, 176, 76)

ROLE_PENS = {
    pattern.COLUMN: (QColor(22, 26, 44), 0),
    pattern.RULE_MINOR: (QColor(120, 96, 20), 1),
    pattern.RULE_MAJOR: (QColor(255, 230, 80), 3),
    pattern.DIAGONAL: (QColor(120, 255, 180), 3),
    pattern.CIRCLE: (QColor(90, 130, 230), 5),
    pattern.SEAM: (QColor(255, 93, 93), 2),
}

PATTERN_MODES: Tuple[Tuple[str, ...], ...] = (
    ("rules",),
    ("rules", "circles"),
    ("columns", "rules", "diagonals", "circles"),
)
PATTERN_NAMES = ("line", "rules + circles", "full")

MODE_PLACE = "place"
MODE_CALIBRATE = "calibrate"

# Big enough to hit without aiming, on a wall you are looking at from across the desk.
ACTION_BUTTON_CSS = """
QPushButton {
    background: rgba(18, 19, 28, 235);
    color: #ECEFF8;
    border: 2px solid rgba(140, 148, 176, 120);
    border-radius: 12px;
    padding: 20px 40px;
    font-size: 21px;
    font-weight: 600;
}
QPushButton:hover  { background: rgba(90, 130, 230, 235); border-color: #8FB0FF; }
QPushButton:pressed{ background: rgba(60, 96, 190, 245); }
QPushButton#primary {
    background: rgba(90, 130, 230, 235);
    border-color: #8FB0FF;
}
QPushButton#primary:hover { background: rgba(112, 152, 245, 245); }
"""


def pil_to_qimage(img: Image.Image) -> QImage:
    """Convert a PIL image to a QImage over identical pixel data."""
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return qimg.copy()   # own the memory; the buffer above is about to be freed


class WelcomeWindow(QWidget):
    """The app's front door: a normal window, on one screen.

    It exists for two reasons. Practically, a native file chooser parented to a frameless
    fullscreen window does not reliably receive clicks on macOS — so browsing happens
    here, before any fullscreen window is up. And conceptually, opening straight into a
    calibration pattern across every monitor is a startling thing to do to someone who
    just wanted to pick a picture.
    """

    def __init__(self, state: "AppState", app: "WallApp"):
        super().__init__()
        self.state = state
        self.app = app
        self.setWindowTitle("span")
        self.setMinimumWidth(560)

        title = QLabel("span")
        title.setStyleSheet("font-size: 34px; font-weight: 600; color: #ECEFF8;")
        subtitle = QLabel("One wallpaper across every display, measured in millimetres.")
        subtitle.setStyleSheet("font-size: 14px; color: #8B90A6;")

        self._displays = QLabel()
        self._displays.setStyleSheet(
            "font-family: Menlo, monospace; font-size: 12px; color: #C3C7D6;")
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setStyleSheet("font-size: 13.5px; color: #ECEFF8;")

        self._browse = QPushButton("Browse image…")
        self._browse.setDefault(True)
        self._browse.clicked.connect(self.app.browse_and_continue)
        self._calibrate = QPushButton("Calibrate wall")
        self._calibrate.clicked.connect(lambda: self.app.open_wall(MODE_CALIBRATE))
        self._place = QPushButton("Place image")
        self._place.clicked.connect(lambda: self.app.open_wall(MODE_PLACE))

        buttons = QHBoxLayout()
        buttons.addWidget(self._browse)
        buttons.addWidget(self._place)
        buttons.addStretch(1)
        buttons.addWidget(self._calibrate)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 34, 40, 30)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(14)
        layout.addWidget(self._displays)
        layout.addSpacing(6)
        layout.addWidget(self._status)
        layout.addSpacing(14)
        layout.addLayout(buttons)
        self.setStyleSheet(
            "QWidget { background: #12131C; }"
            "QPushButton { padding: 8px 20px; font-size: 13px; }"
        )
        self.refresh()

    def refresh(self) -> None:
        st = self.state
        rows = []
        for p in st.panels:
            rows.append(f"{p.name:<16} {p.px_w}×{p.px_h}   {p.ppi:5.1f} ppi   "
                        f"{p.width_mm:6.1f} × {p.height_mm:5.1f} mm")
        self._displays.setText("\n".join(rows))

        calibrated = st.config.is_measured
        has_image = st.image is not None
        self._place.setEnabled(has_image and calibrated)

        if not calibrated:
            self._status.setText(
                "This wall has not been calibrated yet.\n"
                "Until it is, crops are laid out as though your panels were flush and "
                "touching — which is exactly what makes a spanned image step at the seam. "
                "Calibration is a one-off measurement per desk."
            )
            self._calibrate.setText("Start calibration")
            self._calibrate.setDefault(not has_image)
        elif has_image:
            self._status.setText(
                f"Loaded {st.image_stem}  ({st.image.width}×{st.image.height})  ·  "
                "wall calibrated. Place it across your displays."
            )
            self._calibrate.setText("Re-calibrate")
        else:
            self._status.setText("Wall calibrated. Choose an image to get started.")
            self._calibrate.setText("Re-calibrate")


class KeepDialog(QDialog):
    """"Keep this wallpaper?" with a countdown that reverts if nothing is clicked.

    The same shape as a display-resolution confirmation, and for the same reason: if the
    result is unusable — or you walked away — doing nothing must undo it. So the timeout
    reverts rather than keeps.
    """

    def __init__(self, parent: QWidget, seconds: int = KEEP_SECONDS):
        super().__init__(parent)
        self.setWindowTitle("Keep this wallpaper?")
        self.setModal(True)
        self._remaining = seconds
        self.keep = False

        title = QLabel("Keep this wallpaper?")
        title.setStyleSheet("font-size: 19px; font-weight: 600; color: #ECEFF8;")
        self._count = QLabel()
        self._count.setStyleSheet("font-size: 13px; color: #7E849A;")

        no = QPushButton("Revert")
        yes = QPushButton("Keep")
        yes.setDefault(True)
        no.clicked.connect(self.reject)
        yes.clicked.connect(self._accept_keep)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(no)
        buttons.addWidget(yes)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(self._count)
        layout.addSpacing(8)
        layout.addLayout(buttons)
        self.setStyleSheet("QDialog { background: #12131C; }"
                           "QPushButton { padding: 6px 18px; }")

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(1000)
        self._render()

    def _accept_keep(self):
        self.keep = True
        self.accept()

    def _render(self):
        self._count.setText(
            f"Reverting to your previous wallpaper in {self._remaining}s "
            "if you don't choose."
        )

    def _tick(self):
        self._remaining -= 1
        if self._remaining <= 0:
            self._tick_timer.stop()
            self.reject()          # timeout == revert
            return
        self._render()


@dataclass
class AppState:
    """Everything both windows read from. One object, so they cannot disagree."""

    displays: List[Display]
    config: WallConfig
    image: Optional[Image.Image]
    image_stem: str
    out_dir: Path
    image_path: Optional[Path] = None
    mode: str = MODE_CALIBRATE
    policy: str = "fit"
    offset_mm: Tuple[float, float] = (0.0, 0.0)
    pattern_mode: int = 0
    message: str = ""

    @property
    def panels(self) -> List[Panel]:
        return panels_from_displays(
            self.displays,
            gaps_mm=self.config.gaps_mm,
            y_offsets_mm=self.config.y_offsets_mm,
        )

    @property
    def seams(self) -> List[float]:
        return seam_positions(self.panels, self.config.gaps_mm)

    def plan(self) -> Optional[Plan]:
        if self.image is None:
            return None
        panels = self.panels
        S = choose_scale(self.image.width, self.image.height, panels, self.policy)
        offset = clamp_offset(panels, self.image.width, self.image.height, S, self.offset_mm)
        self.offset_mm = offset
        return plan_layout(panels, self.image.width, self.image.height,
                           scale=S, offset_mm=offset)


class WallWindow(QWidget):
    """Fullscreen view of the wall from one panel's point of view."""

    def __init__(self, state: AppState, slot: int, dpr: float, app: "WallApp"):
        super().__init__()
        self.state = state
        self.slot = slot
        self.dpr = dpr
        self.app = app
        self._qimage: Optional[QImage] = None
        self._drag_from: Optional[QPointF] = None
        self._drag_offset: Tuple[float, float] = (0.0, 0.0)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        # Real widgets rather than painted rectangles: they take the click themselves, so
        # pressing one can never be mistaken for the start of an image drag.
        self._set_btn = QPushButton("Set wallpaper", self)
        self._set_btn.setObjectName("primary")
        self._set_btn.clicked.connect(self.app.apply_wallpaper)
        self._browse_btn = QPushButton("Browse images", self)
        self._browse_btn.clicked.connect(self.app.open_image)
        self._exit_btn = QPushButton("Exit", self)
        self._exit_btn.clicked.connect(QApplication.quit)

        self._buttons = (self._set_btn, self._browse_btn, self._exit_btn)
        for b in self._buttons:
            b.setStyleSheet(ACTION_BUTTON_CSS)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # keep arrow keys driving the image

    def _layout_buttons(self) -> None:
        """Centre the row along the bottom, and show it only where it applies.

        Calibration is a keyboard job — nudging by millimetres — so the buttons would be
        three large distractions sitting on top of the pattern you are trying to read.
        """
        place = self.state.mode == MODE_PLACE
        for b in self._buttons:
            b.setVisible(place)
        if not place:
            return

        gap = 26
        widths = [b.sizeHint().width() for b in self._buttons]
        height = max(b.sizeHint().height() for b in self._buttons)
        total = sum(widths) + gap * (len(self._buttons) - 1)
        x = (self.width() - total) // 2
        y = self.height() - height - 56
        for b, w in zip(self._buttons, widths):
            b.setGeometry(x, y, w, height)
            b.raise_()
            x += w + gap

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_buttons()

    def showEvent(self, event):
        super().showEvent(event)
        self._layout_buttons()

    def set_image(self, qimage: Optional[QImage]) -> None:
        self._qimage = qimage

    @property
    def panel(self) -> Panel:
        return self.state.panels[self.slot]

    def k(self) -> float:
        """Logical pixels per millimetre on this panel."""
        return self.panel.px_per_mm / self.dpr

    def to_px(self, x_mm: float, y_mm: float) -> QPointF:
        p = self.panel
        k = self.k()
        return QPointF((x_mm - p.x_mm) * k, (y_mm - p.y_mm) * k)

    # -- painting ---------------------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), BG)

        if self.state.mode == MODE_PLACE:
            self._paint_image(p)
        else:
            self._paint_pattern(p)
        self._paint_hud(p)

    def _paint_image(self, p: QPainter) -> None:
        plan = self.state.plan()
        if plan is None or self._qimage is None:
            return
        box = plan.boxes[self.panel.index]
        # Source rect IS the export crop box — what you see is what gets written.
        p.drawImage(
            QRectF(0, 0, self.width(), self.height()),
            self._qimage,
            QRectF(box.x, box.y, box.w, box.h),
        )

    def _paint_pattern(self, p: QPainter) -> None:
        est = estate(self.state.panels)
        pat = pattern.build(est, self.state.seams,
                            modes=PATTERN_MODES[self.state.pattern_mode])
        k = self.k()

        for r in pat.rects:
            colour, _ = ROLE_PENS[r.role]
            a, b = self.to_px(r.x_mm, r.y_mm), self.to_px(r.x_mm + r.w_mm, r.y_mm + r.h_mm)
            p.fillRect(QRectF(a, b), colour)
        for ln in pat.lines:
            colour, width = ROLE_PENS[ln.role]
            p.setPen(QPen(colour, width))
            p.drawLine(self.to_px(ln.x1_mm, ln.y1_mm), self.to_px(ln.x2_mm, ln.y2_mm))
        for c in pat.circles:
            colour, width = ROLE_PENS[c.role]
            p.setPen(QPen(colour, width))
            p.drawEllipse(self.to_px(c.cx_mm, c.cy_mm), c.r_mm * k, c.r_mm * k)

        f = QFont()
        f.setPointSizeF(10.0)
        p.setFont(f)
        p.setPen(QPen(HUD))
        for lb in pat.labels:
            p.drawText(self.to_px(lb.x_mm, lb.y_mm), lb.text)

    def _paint_hud(self, p: QPainter) -> None:
        st = self.state
        pan = self.panel
        focused = self.app.focus_slot == self.slot

        f = QFont()
        f.setPointSizeF(16.0)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QPen(HUD_KEY if focused else HUD))
        head = f"{pan.name}   {pan.px_w}x{pan.px_h}   {pan.ppi:.1f} ppi"
        if focused:
            head += "   ← controlling"
        p.drawText(QPointF(34, 52), head)

        f.setBold(False)
        f.setPointSizeF(12.5)
        p.setFont(f)
        p.setPen(QPen(HUD))

        gap = st.config.gaps_mm[0] if st.config.gaps_mm else 0.0
        line2 = (f"[{st.mode}]   y_mm {pan.y_mm:+.2f}   gap {gap:.2f} mm")
        if st.mode == MODE_PLACE and st.image is not None:
            plan = st.plan()
            if plan is not None:
                line2 += (f"   ·   {st.policy}   S {plan.scale:.3f} px/mm"
                          f"   offset ({st.offset_mm[0]:+.1f}, {st.offset_mm[1]:+.1f}) mm")
        p.drawText(QPointF(34, 80), line2)

        if st.mode == MODE_PLACE and st.image is not None:
            plan = st.plan()
            if plan is not None and plan.upscaled:
                p.setPen(QPen(WARN))
                p.drawText(QPointF(34, 106),
                           f"⚠ upscaled: {', '.join(plan.upscaled)} — try 'f' or a larger image")

        if st.message:
            p.setPen(QPen(HUD_KEY))
            p.drawText(QPointF(34, 134), st.message)

        p.setPen(QPen(HUD_DIM))
        f.setPointSizeF(11.5)
        p.setFont(f)
        if st.mode == MODE_CALIBRATE:
            keys = ("tab place  ·  click a screen to control it  ·  ↑↓ this panel 1 mm  ·  "
                    "←→ bezel gap  ·  shift finer  ·  g pattern  ·  o open image  ·  "
                    "⏎ save  ·  esc back")
            y = self.height() - 34
        else:
            # Shortcuts for the same three actions the buttons offer, plus the framing
            # controls. Sits above the button row rather than under it.
            keys = ("drag or ↑↓←→ move  ·  shift finer  ·  f fit / n native  ·  0 recentre"
                    "  ·  ⏎ export files only  ·  tab calibrate  ·  esc back")
            y = self.height() - 160
        p.drawText(QPointF(34, y), keys)

    # -- interaction ------------------------------------------------------------------
    def mousePressEvent(self, event):
        self.app.set_focus(self.slot)
        if self.state.mode == MODE_PLACE:
            self._drag_from = event.position()
            self._drag_offset = self.state.offset_mm
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.app.repaint_all()

    def mouseMoveEvent(self, event):
        if self._drag_from is None or self.state.mode != MODE_PLACE:
            return
        # Drag in this panel's logical px -> wall mm. Moving the mouse right slides the
        # image right, which is an increase in the image's wall origin.
        k = self.k()
        d = event.position() - self._drag_from
        self.state.offset_mm = (self._drag_offset[0] + d.x() / k,
                                self._drag_offset[1] + d.y() / k)
        self.app.repaint_all()

    def mouseReleaseEvent(self, event):
        self._drag_from = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def keyPressEvent(self, event):
        self.app.set_focus(self.slot)
        self.app.handle_key(event, self.slot)


class WallApp:
    """Owns the windows and every key binding."""

    def __init__(self, state: AppState):
        self.state = state
        self.windows: List[WallWindow] = []
        self.focus_slot = 0
        self.exported: List[Path] = []
        self.welcome: Optional["WelcomeWindow"] = None
        self._qimage: Optional[QImage] = None

    def set_focus(self, slot: int) -> None:
        self.focus_slot = slot

    def repaint_all(self) -> None:
        for w in self.windows:
            w._layout_buttons()      # the row appears and vanishes with the mode
            w.update()
        if self.welcome is not None:
            self.welcome.refresh()

    # -- the wall ---------------------------------------------------------------------
    def open_wall(self, mode: str) -> None:
        """Put the wall up on every display. The welcome window waits behind it."""
        st = self.state
        if mode == MODE_PLACE and st.image is None:
            st.message = "no image loaded"
            self.repaint_all()
            return
        st.mode = mode
        st.message = ""
        if self.windows:
            for w in self.windows:
                w.show()
                w.raise_()
            self.repaint_all()
            return

        screens = sorted(QGuiApplication.screens(), key=lambda s: s.geometry().x())
        for i, _ in enumerate(st.panels):
            screen = screens[i] if i < len(screens) else QGuiApplication.primaryScreen()
            w = WallWindow(st, i, screen.devicePixelRatio(), self)
            w.set_image(self._qimage)
            w.setGeometry(screen.geometry())
            w.show()
            w.raise_()
            self.windows.append(w)
        if self.welcome is not None:
            self.welcome.hide()
        self.windows[0].activateWindow()
        self.windows[0].setFocus()
        diaglog.log("gui.wall_open", mode=mode, displays=len(self.windows))

    def close_wall(self) -> None:
        """Take the wall down and come back to the welcome window."""
        for w in self.windows:
            w.close()
        self.windows = []
        if self.welcome is not None:
            self.welcome.refresh()
            self.welcome.show()
            self.welcome.raise_()
            self.welcome.activateWindow()
        diaglog.log("gui.wall_closed")

    def browse_and_continue(self) -> None:
        """Pick an image, then go wherever that leaves us: calibrate, or place."""
        if not self.open_image():
            return
        if self.state.config.is_measured:
            self.open_wall(MODE_PLACE)
        elif self.welcome is not None:
            # Not calibrated: stay on the welcome screen, which now explains why and
            # offers the calibration button. No surprise fullscreen takeover.
            self.welcome.refresh()
            self.welcome.raise_()

    # -- keys -------------------------------------------------------------------------
    def handle_key(self, event, slot: int) -> None:
        st = self.state
        key = event.key()
        fine = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if key == Qt.Key.Key_Escape:
            self.close_wall()          # back to the welcome window, not straight out
            return
        if key == Qt.Key.Key_O:
            self.open_image()
            return
        if key == Qt.Key.Key_Tab:
            st.mode = MODE_PLACE if st.mode == MODE_CALIBRATE else MODE_CALIBRATE
            if st.mode == MODE_PLACE and st.image is None:
                st.mode = MODE_CALIBRATE
                st.message = "no image loaded — press o to choose one"
            else:
                st.message = ""
            self.repaint_all()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._commit()
            return

        if st.mode == MODE_CALIBRATE:
            self._calibrate_key(key, fine, slot)
        else:
            self._place_key(key, fine)
        self.repaint_all()

    def _calibrate_key(self, key, fine: bool, slot: int) -> None:
        st = self.state
        step = 0.2 if fine else 1.0
        if key == Qt.Key.Key_G:
            st.pattern_mode = (st.pattern_mode + 1) % len(PATTERN_MODES)
            st.message = f"pattern: {PATTERN_NAMES[st.pattern_mode]}"
            return
        offsets = list(st.config.y_offsets_mm)
        gaps = list(st.config.gaps_mm)
        if key == Qt.Key.Key_Up:
            offsets[slot] -= step
        elif key == Qt.Key.Key_Down:
            offsets[slot] += step
        elif key == Qt.Key.Key_Left and gaps:
            gaps[0] = max(0.0, gaps[0] - step)
        elif key == Qt.Key.Key_Right and gaps:
            gaps[0] += step
        else:
            return
        st.config.y_offsets_mm = normalize(offsets)
        st.config.gaps_mm = gaps
        st.message = ""

    def _place_key(self, key, fine: bool) -> None:
        st = self.state
        step = 1.0 if fine else 5.0
        dx, dy = st.offset_mm
        if key == Qt.Key.Key_Left:
            dx -= step
        elif key == Qt.Key.Key_Right:
            dx += step
        elif key == Qt.Key.Key_Up:
            dy -= step
        elif key == Qt.Key.Key_Down:
            dy += step
        elif key == Qt.Key.Key_F:
            st.policy = "fit"
            st.message = "scale: fit — cover the estate"
            return
        elif key == Qt.Key.Key_N:
            st.policy = "native"
            st.message = "scale: native — densest panel 1:1"
            return
        elif key == Qt.Key.Key_0:
            st.offset_mm = (0.0, 0.0)
            st.message = "recentred"
            return
        elif key == Qt.Key.Key_W:
            self.apply_wallpaper()
            return
        else:
            return
        st.offset_mm = (dx, dy)
        st.message = ""

    # -- actions ----------------------------------------------------------------------
    def _picker_start_dir(self, start_dir: Optional[Path]) -> str:
        """Where the chooser opens: explicit, then last used, then the current image's
        folder, then home.

        Home rather than ~/Pictures — wallpapers are as likely to be in Downloads or on
        the Desktop, and the sidebar reaches all of them from there.
        """
        for candidate in (start_dir, paths.last_image_dir(), self._current_image_dir()):
            if candidate and Path(candidate).is_dir():
                return str(candidate)
        return str(Path.home())

    def _current_image_dir(self) -> Optional[Path]:
        p = self.state.image_path
        return p.parent if p and p.parent.is_dir() else None

    def open_image(self, start_dir: Optional[Path] = None) -> bool:
        """Pick an image and swap it in live. Returns False if the user cancelled.

        The wall is hidden for the duration: a native file chooser sitting over frameless
        fullscreen windows does not reliably receive clicks on macOS.
        """
        st = self.state
        wall_was_up = bool(self.windows) and self.windows[0].isVisible()
        if wall_was_up:
            for w in self.windows:
                w.hide()
        parent = self.welcome if self.welcome is not None else None
        try:
            path, _ = QFileDialog.getOpenFileName(
                parent, "Choose a wallpaper", self._picker_start_dir(start_dir),
                IMAGE_FILTER,
            )
        finally:
            if wall_was_up:
                for w in self.windows:
                    w.show()
                    w.raise_()
        if not path:
            return False
        try:
            image = load_image(Path(path))
        except ImageLoadError as exc:
            st.message = str(exc)
            self.repaint_all()
            return False

        st.image = image
        st.image_stem = Path(path).stem
        st.image_path = Path(path)
        st.offset_mm = (0.0, 0.0)     # a new image has no meaningful old framing
        paths.remember_image_dir(Path(path))
        self._qimage = pil_to_qimage(image)
        for w in self.windows:
            w.set_image(self._qimage)
        st.message = f"loaded {Path(path).name}  ({image.width}×{image.height})"
        diaglog.log("gui.image_opened", path=path, size=f"{image.width}x{image.height}")
        self.repaint_all()
        return True

    def _export(self, out_dir: Path) -> List:
        """Cut and write one PNG per panel. Returns the ExportResults."""
        st = self.state
        plan = st.plan()
        if plan is None:
            return []
        out_dir.mkdir(parents=True, exist_ok=True)
        results = export_all(st.image, st.panels, plan.boxes, out_dir, st.image_stem)
        self.exported = [r.path for r in results]
        diaglog.log("gui.exported", count=len(results), out_dir=str(out_dir))
        return results

    def apply_wallpaper(self) -> None:
        """Export, set each display, then ask whether to keep it.

        Files go to ``~/.span/tmp`` rather than the output directory: macOS keeps only a
        *reference* to a wallpaper file, so it has to stay put, and the output directory is
        the user's to delete.

        Setting requires a calibrated wall. Without one the crops are laid out as though
        the panels were flush and touching, which is exactly the stepped result this tool
        exists to avoid — so it refuses and says what to do instead.
        """
        st = self.state
        if st.image is None:
            st.message = "nothing to set — press o to open an image"
            self.repaint_all()
            return
        if not st.config.is_measured:
            st.mode = MODE_CALIBRATE
            st.message = ("calibrate first — this wall has no measured geometry, so the "
                          "crops would step at the seam. Nudge until the pattern joins, "
                          "press ⏎ to save, then tab back.")
            diaglog.log("gui.wallpaper_blocked", reason="uncalibrated")
            self.repaint_all()
            return

        # Record what is showing now, before anything changes, so Revert has a target.
        before = capture()

        # Into `pending`, never straight into `current`: an unconfirmed set must not share
        # a directory with the wallpaper that is actually on screen.
        paths.clear_pending()
        results = self._export(paths.pending_dir())
        if not results:
            st.message = "nothing to set"
            self.repaint_all()
            return
        try:
            outcome = set_wallpapers(
                assignments_from_exports([(r.panel.name, r.path) for r in results])
            )
        except WallpaperError as exc:
            st.message = f"could not set wallpaper: {exc}"
            self.repaint_all()
            return

        failed = [o for o in outcome if not o.ok]
        if len(failed) == len(outcome):
            st.message = "could not set any display: " + ", ".join(
                f"{o.display_name} ({o.error})" for o in failed)
            self.repaint_all()
            return

        self._confirm_wallpaper(before, results, failed)

    def _clear_the_view(self) -> None:
        """Get everything out of the way so the wallpaper is actually visible.

        Our own fullscreen wall first — it is a full-screen copy of the very thing being
        judged, and leaving it up would mean approving a preview rather than the result.
        Then every other application's windows.
        """
        for w in self.windows:
            w.hide()
        if self.welcome is not None:
            self.welcome.hide()
        hide_other_applications()
        QApplication.processEvents()     # let the hiding actually paint before we ask

    def _restore_the_view(self, show_wall: bool) -> None:
        unhide_all_applications()
        if show_wall:
            for w in self.windows:
                w.show()
                w.raise_()
            if self.windows:
                self.windows[self.focus_slot].activateWindow()
        elif self.welcome is not None:
            self.welcome.show()
            self.welcome.raise_()

    def _revert_failed_dialog(self, missing, recovered: int) -> None:
        """Tell the user plainly that Revert did not do what they asked.

        Silently leaving the new wallpaper up after they pressed Revert is the worst
        outcome: they believe they undid something they did not.
        """
        names = "\n".join(f"   ·  {r.display_name}" for r in missing)
        if recovered:
            body = (f"{recovered} display(s) went back, but these could not:\n\n{names}\n\n"
                    "They are still showing the new wallpaper.")
        else:
            body = (f"These displays could not be put back:\n\n{names}\n\n"
                    "The wallpaper they were showing no longer exists on disk, and no "
                    "backup copy was made — it was already missing when you pressed Set.\n\n"
                    "The new wallpaper has been kept, since removing it would leave you "
                    "with no wallpaper at all.")

        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Revert failed")
        box.setText("Could not restore your previous wallpaper")
        box.setInformativeText(body)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setStyleSheet("QMessageBox { background: #12131C; }"
                          "QLabel { color: #ECEFF8; font-size: 13px; }"
                          "QPushButton { padding: 6px 18px; }")
        diaglog.log("gui.revert_failed_dialog", missing=len(missing), recovered=recovered)
        box.exec()

    def _confirm_wallpaper(self, before, results, failed) -> None:
        """Ask whether to keep it. Doing nothing reverts — that is what the timer is for."""
        st = self.state
        new_paths = [r.path for r in results]
        self._clear_the_view()
        # No parent: the dialog has to outlive the windows we just hid, and float over a
        # bare desktop as the only thing on screen.
        dialog = KeepDialog(None)
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dialog.exec()

        if dialog.keep:
            # Promote out of `pending` into `current`, then re-point macOS at the new
            # location. promote_pending copies before it deletes, and the displays are
            # re-set before the originals go, so the reference is never left dangling.
            promoted = paths.promote_pending([r.path for r in results])
            if promoted:
                moved = [(r.panel.name, p) for r, p in zip(results, promoted)]
                outcome = set_wallpapers(assignments_from_exports(moved))
                failed += [o for o in outcome if not o.ok]
                new_paths = promoted
            paths.prune_tmp()
            self.exported = list(new_paths)
            note = ""
            if failed:
                note = "  (failed: " + ", ".join(o.display_name for o in failed) + ")"
            diaglog.log("gui.wallpaper_kept", count=len(new_paths))
            st.message = f"wallpaper kept{note}"
            # Put everyone else's windows back before leaving — we hid them, so we own
            # undoing it, and quitting mid-hide would strand the desktop.
            unhide_all_applications()
            QApplication.quit()
            return

        restored = restore(before)
        missing = [r for r in restored if not r.ok]
        recovered = len(restored) - len(missing)
        diaglog.log("gui.wallpaper_reverted", restored=recovered, missing=len(missing))

        if missing:
            # Saying "reverted" here would be a lie: those displays are still showing the
            # new wallpaper. Name what could not be put back, and what you are left with.
            names = ", ".join(r.display_name for r in missing)
            if recovered:
                st.message = (f"partly reverted — {names} could not be restored and "
                              "still shows the new wallpaper")
            else:
                st.message = ("could not revert — the previous wallpaper no longer "
                              "exists on disk. Keeping the new one.")
                self.exported = list(new_paths)   # these are the live wallpaper now
            self._revert_failed_dialog(missing, recovered)
        # Reverted, so the images we just wrote are referenced by nothing — but only clear
        # them if the restore actually took, or we would delete what is still on screen.
        if not missing:
            # The rejected set, and only the rejected set. `current` and `revert` are not
            # reachable from here — that separation is what makes the old bug impossible
            # rather than merely guarded against.
            paths.clear_pending()
        # If anything failed to restore, the pending files are still on screen: leave them.
        paths.prune_tmp()
        self._restore_the_view(show_wall=True)
        self.repaint_all()

    def _commit(self) -> None:
        st = self.state
        if st.mode == MODE_CALIBRATE:
            path = save_config(signature(st.displays), st.config)
            st.message = f"saved wall calibration → {path}"
            diaglog.log("gui.calibration_saved", y=st.config.y_offsets_mm,
                        gaps=st.config.gaps_mm)
        else:
            results = self._export(st.out_dir)
            # Exporting files is rarely the actual goal — say what the next step is
            # rather than leaving someone looking at a wall with nothing to do.
            st.message = (
                f"exported {len(results)} file(s) → {st.out_dir}     "
                "press w to set them as your wallpaper now"
                if results else "nothing to export — press o to open an image"
            )
        self.repaint_all()


def run(
    displays: List[Display],
    config: WallConfig,
    image: Optional[Image.Image],
    out_dir: Path,
    image_stem: str = "wallpaper",
    start_mode: Optional[str] = None,
    image_path: Optional[Path] = None,
) -> List[Path]:
    """Start the app on its welcome window. Returns the paths exported, if any.

    The wall only goes fullscreen when there is something to do with it — placing an
    image, or calibrating. Everything before that happens in an ordinary window, which is
    both less startling and the only way a native file chooser behaves properly.
    """
    app = QApplication.instance() or QApplication([])

    state = AppState(
        displays=displays, config=config.sized_for(len(displays)),
        image=image, image_stem=image_stem, out_dir=out_dir, image_path=image_path,
        mode=start_mode or (MODE_PLACE if image is not None else MODE_CALIBRATE),
    )
    if image_path is not None:
        paths.remember_image_dir(image_path)

    wall_app = WallApp(state)
    wall_app._qimage = pil_to_qimage(image) if image is not None else None
    welcome = WelcomeWindow(state, wall_app)
    wall_app.welcome = welcome
    welcome.show()
    welcome.raise_()
    welcome.activateWindow()

    diaglog.log("gui.open", displays=len(displays), calibrated=config.is_measured,
                has_image=image is not None)

    def _start():
        """Skip the welcome screen only when the command line already said what to do.

        With no image given there is nothing to skip to — the welcome window waits for a
        click rather than throwing a file dialog over itself before it has even painted.
        """
        if start_mode == MODE_CALIBRATE:
            wall_app.open_wall(MODE_CALIBRATE)
        elif image is not None and config.is_measured:
            wall_app.open_wall(MODE_PLACE)

    QTimer.singleShot(0, _start)
    app.exec()
    return wall_app.exported
