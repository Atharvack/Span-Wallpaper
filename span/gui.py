"""PySide6 dialog: place one aspect-locked rectangle per display over the image.

The ``QGraphicsScene`` holds the source image at full resolution, so scene coordinates
*are* source-image pixels and every rectangle's geometry is an exact crop box. The view
``fitInView``s the whole scene into the window (re-fit on resize). Labels and resize
grips use ``ItemIgnoresTransformations`` so they stay a constant on-screen size no matter
how far the image is zoomed to fit.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from . import diaglog
from .calibrate import DEFAULT_CELL, calibration_shift, make_crop_grid, make_grid
from .export import export_all, safe_name, unique_path
from .geometry import (
    Box,
    Display,
    align_boxes,
    aspect_resize,
    clamp_pos,
    fit_into_image,
    seed_layout,
    to_native_boxes,
)


def _fmt_box(b: Box) -> str:
    return f"({b.x:.2f},{b.y:.2f} {b.w:.2f}x{b.h:.2f})"


def _fmt_pt(p: QPointF) -> str:
    return f"({p.x():.2f},{p.y():.2f})"

# Distinct, high-contrast colors cycled per display.
_PALETTE = [
    QColor("#ff5d5d"),
    QColor("#4da3ff"),
    QColor("#3ecf8e"),
    QColor("#ffb74d"),
    QColor("#b388ff"),
    QColor("#4dd0e1"),
]

_GRIP = 16  # on-screen px for the corner resize handle (constant via ignored transform)


def pil_to_pixmap(img: Image.Image) -> QPixmap:
    """Convert a PIL image to a QPixmap using identical pixel data (no EXIF surprises)."""
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    # copy() so the pixmap owns its memory (data buffer would otherwise be freed).
    return QPixmap.fromImage(qimg.copy())


class _GripItem(QGraphicsRectItem):
    """Bottom-right corner handle that drives an aspect-locked resize of its parent."""

    def __init__(self, parent: "DisplayRectItem", color: QColor):
        super().__init__(-_GRIP / 2, -_GRIP / 2, _GRIP, _GRIP, parent)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor("white"), 1.5))
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setZValue(3)
        self._active = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._active = True
            parent = self.parentItem()
            diaglog.log("grip.grab", name=repr(parent.display.name),
                        scene_pt=_fmt_pt(event.scenePos()), box=_fmt_box(parent.current_box()))
            event.accept()  # capture so the parent does not start a move
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self._active:
            self.parentItem().resize_from_scene(event.scenePos())
            event.accept()

    def mouseReleaseEvent(self, event):
        self._active = False
        parent = self.parentItem()
        box = parent.current_box()
        diaglog.log("grip.resize_end", name=repr(parent.display.name),
                    box=_fmt_box(box), as_crop=box.as_crop())
        event.accept()


class DisplayRectItem(QGraphicsItem):
    """A movable, aspect-locked, image-clamped rectangle representing one display."""

    def __init__(
        self,
        display: Display,
        color: QColor,
        img_w: float,
        img_h: float,
        on_change: Callable[[], None],
    ):
        super().__init__()
        self.display = display
        self.color = color
        self.img_w = img_w
        self.img_h = img_h
        self.aspect = display.aspect
        self._on_change = on_change
        self._w = 1.0
        self._h = 1.0
        self._locked = False
        self._frozen = False        # calibration mode: no move/resize at all
        self._programmatic = False  # bypass the move-clamp during set_box()

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setZValue(2)

        self._label = QGraphicsSimpleTextItem(self)
        self._label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self._label.setText(f"{display.name}\n{display.native_label}")
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        self._label.setFont(font)
        self._label.setBrush(QBrush(QColor("white")))
        self._label.setPen(QPen(QColor(0, 0, 0, 200), 1.5))  # dark outline → readable anywhere
        self._label.setZValue(3)
        self._label.setPos(6, 6)

        self._grip = _GripItem(self, color)

    # -- geometry -----------------------------------------------------------------
    def boundingRect(self) -> QRectF:
        pad = 2.0
        return QRectF(-pad, -pad, self._w + 2 * pad, self._h + 2 * pad)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0, 0, self._w, self._h)
        fill = QColor(self.color)
        fill.setAlpha(60)
        painter.fillRect(rect, fill)
        pen = QPen(self.color, 3 if self.isSelected() else 2)
        pen.setCosmetic(True)  # constant border width regardless of view zoom
        painter.setPen(pen)
        painter.drawRect(rect)

    def set_box(self, box: Box):
        self.prepareGeometryChange()
        self._w = max(box.w, 1.0)
        self._h = max(box.h, 1.0)
        self._programmatic = True   # place exactly; caller has already fitted the group
        self.setPos(box.x, box.y)
        self._programmatic = False
        self._reposition_children()
        self.update()

    def current_box(self) -> Box:
        p = self.pos()
        return Box(p.x(), p.y(), self._w, self._h)

    def resize_from_scene(self, scene_pt: QPointF):
        if self._locked:
            return
        p = self.pos()
        w, h = aspect_resize(
            p.x(), p.y(), scene_pt.x(), scene_pt.y(), self.aspect, self.img_w, self.img_h
        )
        self.prepareGeometryChange()
        self._w, self._h = w, h
        self._reposition_children()
        self.update()
        self._on_change()
        self._resize_log_n = getattr(self, "_resize_log_n", 0) + 1
        if self._resize_log_n % 6 == 0:
            diaglog.log("item.resize", name=repr(self.display.name),
                        corner=_fmt_pt(scene_pt), box=_fmt_box(self.current_box()))

    def mousePressEvent(self, event):
        diaglog.log("item.grab", name=repr(self.display.name),
                    scene_pt=_fmt_pt(event.scenePos()), box=_fmt_box(self.current_box()))
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        box = self.current_box()
        diaglog.log("item.move_end", name=repr(self.display.name),
                    box=_fmt_box(box), as_crop=box.as_crop())

    def set_locked(self, locked: bool):
        """Lock to native size (1:1 mode): hide the grip and refuse resizes."""
        self._locked = locked
        self._grip.setVisible(not locked and not getattr(self, "_frozen", False))

    def set_frozen(self, frozen: bool):
        """Calibration mode: no move, no resize (the crop is the recommendation)."""
        self._frozen = frozen
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not frozen)
        self._grip.setVisible(not frozen and not self._locked)

    def _reposition_children(self):
        self._grip.setPos(self._w, self._h)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            if self._programmatic:
                return value  # exact placement (align/seed); no per-rect clamp
            x, y = clamp_pos(value.x(), value.y(), self._w, self._h, self.img_w, self.img_h)
            if abs(x - value.x()) > 0.01 or abs(y - value.y()) > 0.01:
                # Throttle: a full-image-height rect clamps on every drag pixel.
                self._clamp_log_n = getattr(self, "_clamp_log_n", 0) + 1
                if self._clamp_log_n % 20 == 1:
                    diaglog.log("item.clamp_move", name=repr(self.display.name),
                                proposed=_fmt_pt(value), clamped=f"({x:.2f},{y:.2f})")
            return QPointF(x, y)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._on_change()
        return super().itemChange(change, value)


class _ImageView(QGraphicsView):
    """A view that keeps the whole scene fit-to-window on show and resize."""

    def __init__(self, scene: QGraphicsScene):
        super().__init__(scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setBackgroundBrush(QBrush(QColor("#202225")))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def _fit(self):
        scene = self.scene()
        if scene is not None:
            self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            t = self.transform()
            vp = self.viewport()
            diaglog.log(
                "view.fit",
                viewport=f"{vp.width()}x{vp.height()}",
                scale_x=round(t.m11(), 6),
                scale_y=round(t.m22(), 6),
                dpr=round(self.devicePixelRatioF(), 3),
                scene=f"{scene.sceneRect().width():.0f}x{scene.sceneRect().height():.0f}",
            )

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


class SpanDialog(QDialog):
    """The placement dialog. On Apply, ``result_boxes`` holds one crop Box per display."""

    def __init__(self, pil_image: Image.Image, displays: List[Display],
                 out_dir: Optional["Path"] = None, image_stem: str = "wallpaper"):
        super().__init__()
        self.setWindowTitle("span — place displays over the wallpaper")
        self.resize(1100, 780)

        self._displays = displays
        self.result_boxes: Optional[Dict[int, Box]] = None
        self._img_w = float(pil_image.width)
        self._img_h = float(pil_image.height)
        self._out_dir = out_dir
        self._image_stem = image_stem
        self._cell = DEFAULT_CELL

        # Photo and calibration-grid backgrounds (same source-pixel space as the scene).
        self._photo_pil = pil_image
        self._grid_pil = make_grid(int(self._img_w), int(self._img_h), self._cell)
        self._photo_pix = pil_to_pixmap(pil_image)
        self._grid_pix = pil_to_pixmap(self._grid_pil)

        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(0, 0, self._img_w, self._img_h)
        self._bg = self._scene.addPixmap(self._photo_pix)
        self._bg.setZValue(0)
        self._bg.setTransformationMode(Qt.TransformationMode.SmoothTransformation)

        self._view = _ImageView(self._scene)

        # Create items first (no seeding yet) so the readout callback — which set_box()
        # fires via itemChange — always sees a fully-populated item map.
        self._items: Dict[int, DisplayRectItem] = {}
        for i, d in enumerate(displays):
            item = DisplayRectItem(
                d, _PALETTE[i % len(_PALETTE)], self._img_w, self._img_h, self._update_readout
            )
            self._scene.addItem(item)
            self._items[d.index] = item

        self._readout = QLabel()
        self._readout.setWordWrap(True)
        mono = QFont("Menlo")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(11)
        self._readout.setFont(mono)
        self._readout.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        hint = QLabel("Drag to move · drag the corner handle to resize (locked to the "
                      "display's aspect) · rectangles stay inside the image.")
        hint.setStyleSheet("color: #888;")

        self._ppi_available = any(d.width_mm for d in displays)

        reset_btn = self._reset_btn = QPushButton("Reset layout")
        align_h_btn = self._align_h_btn = QPushButton("Align ⇆ H")
        align_h_btn.setToolTip("Snap rectangles edge-to-edge horizontally at a consistent scale")
        align_v_btn = self._align_v_btn = QPushButton("Align ⇅ V")
        align_v_btn.setToolTip("Snap rectangles to the displays' true vertical offset")
        self._native_cb = QCheckBox("1:1 native")
        self._native_cb.setToolTip("Lock each rectangle to its display's exact native pixels "
                                   "(no resampling — sharpest). Disables resize.")
        self._ppi_cb = QCheckBox("Match size (PPI)")
        self._ppi_cb.setChecked(self._ppi_available)
        self._ppi_cb.setEnabled(self._ppi_available)
        self._ppi_cb.setToolTip(
            "On Align, size crops by each monitor's physical size so the image is the same "
            "real-world scale across displays."
            + ("" if self._ppi_available else "  (No physical-size data for these displays.)")
        )

        cancel_btn = QPushButton("Cancel")
        apply_btn = QPushButton("Apply")
        apply_btn.setDefault(True)

        reset_btn.clicked.connect(self._reset)
        align_h_btn.clicked.connect(lambda: self._align("h"))
        align_v_btn.clicked.connect(lambda: self._align("v"))
        self._native_cb.toggled.connect(self._toggle_native)
        cancel_btn.clicked.connect(self.reject)
        apply_btn.clicked.connect(self._apply)

        buttons = QHBoxLayout()
        buttons.addWidget(reset_btn)
        buttons.addWidget(align_h_btn)
        buttons.addWidget(align_v_btn)
        buttons.addSpacing(16)
        buttons.addWidget(self._native_cb)
        buttons.addWidget(self._ppi_cb)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(apply_btn)

        # Calibration row: grid background, export, and seam-offset correction.
        self._cal_cb = QCheckBox("Calibration grid")
        self._cal_cb.setToolTip("Swap the background to a numbered grid; export it, set the "
                                "crops as wallpapers, read the seam, then correct the offset.")
        self._cal_cb.toggled.connect(self._toggle_calibration)
        self._export_grid_btn = QPushButton("Export grid")
        self._export_grid_btn.setEnabled(False)
        self._export_grid_btn.clicked.connect(self._export_grid)

        def _spin():
            sb = QSpinBox()
            sb.setRange(0, 9999)
            sb.setFixedWidth(62)
            return sb

        self._row_l, self._row_r = _spin(), _spin()
        self._col_l, self._col_r = _spin(), _spin()
        self._suggest_btn = QPushButton("Suggest")
        self._suggest_btn.setToolTip("Shift the right display so its grid numbers match the left")
        self._suggest_btn.clicked.connect(self._suggest)

        cal_row = QHBoxLayout()
        cal_row.addWidget(self._cal_cb)
        cal_row.addWidget(self._export_grid_btn)
        cal_row.addSpacing(18)
        cal_row.addWidget(QLabel("rows  L"))
        cal_row.addWidget(self._row_l)
        cal_row.addWidget(QLabel("= R"))
        cal_row.addWidget(self._row_r)
        cal_row.addSpacing(10)
        cal_row.addWidget(QLabel("cols  L"))
        cal_row.addWidget(self._col_l)
        cal_row.addWidget(QLabel("= R"))
        cal_row.addWidget(self._col_r)
        cal_row.addWidget(self._suggest_btn)
        cal_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self._view, 1)
        layout.addWidget(hint)
        layout.addWidget(self._readout)
        layout.addLayout(cal_row)
        layout.addLayout(buttons)

        # Seed positions now that every item AND widget exists.
        diaglog.log("dialog.init", image=f"{self._img_w:.0f}x{self._img_h:.0f}",
                    scene=f"{self._scene.sceneRect().width():.0f}x{self._scene.sceneRect().height():.0f}",
                    displays=len(displays))
        seeds = seed_layout(self._displays, self._img_w, self._img_h,
                            native_mode=self._native_cb.isChecked(), ppi_aware=self._ppi_aware())
        for d in self._displays:
            self._items[d.index].set_box(seeds[d.index])
            b = seeds[d.index]
            diaglog.log("dialog.seed", name=repr(d.name), box=_fmt_box(b),
                        as_crop=b.as_crop(), native=f"{d.native_w}x{d.native_h}",
                        aspect=round(d.aspect, 6))
        self._update_readout()

    # -- actions ------------------------------------------------------------------
    def collect_boxes(self) -> Dict[int, Box]:
        return {d.index: self._items[d.index].current_box() for d in self._displays}

    def _apply(self):
        if self._cal_cb.isChecked():
            # WYSIWYG: in calibration mode Apply exports the grid you see, and stays open.
            self._export_grid()
            return
        self.result_boxes = self.collect_boxes()
        diaglog.log("apply", "collecting final boxes")
        for d in self._displays:
            item = self._items[d.index]
            box = item.current_box()
            # The painted rect mapped into scene space — this is what the user SEES.
            painted = item.mapRectToScene(QRectF(0, 0, item._w, item._h))
            scene_bound = item.sceneBoundingRect()
            diaglog.log(
                "apply.geom",
                name=repr(d.name),
                pos_box=_fmt_box(box),
                as_crop=box.as_crop(),
                painted_scene=f"({painted.x():.2f},{painted.y():.2f} "
                              f"{painted.width():.2f}x{painted.height():.2f})",
                scene_bound=f"({scene_bound.x():.2f},{scene_bound.y():.2f} "
                            f"{scene_bound.width():.2f}x{scene_bound.height():.2f})",
            )
        self.accept()

    def _reset(self):
        # Back to the clean default seed — PPI/native-aware, always fit to the image.
        seeds = seed_layout(self._displays, self._img_w, self._img_h,
                            native_mode=self._native_cb.isChecked(), ppi_aware=self._ppi_aware())
        self._apply_boxes(seeds)

    def _apply_boxes(self, boxes: Dict[int, Box]):
        # Keep the whole group inside the image as a unit (shift, or scale-to-fit if the
        # arrangement is larger than the source). Preserves the seam.
        boxes = fit_into_image(boxes, self._img_w, self._img_h)
        for d in self._displays:
            self._items[d.index].set_box(boxes[d.index])
        for d in self._displays:
            b = self._items[d.index].current_box()
            diaglog.log("layout", name=repr(d.name), box=_fmt_box(b), as_crop=b.as_crop())
        self._update_readout()

    def _ppi_aware(self) -> bool:
        return self._ppi_cb.isChecked() and self._ppi_available

    def _align(self, axis: str):
        native = self._native_cb.isChecked()
        diaglog.log("align", axis=axis, native=native, ppi=self._ppi_aware())
        boxes = align_boxes(
            self._displays, self.collect_boxes(), axis,
            native_mode=native, ppi_aware=self._ppi_aware(),
        )
        self._apply_boxes(boxes)

    def _toggle_native(self, checked: bool):
        diaglog.log("toggle_native", on=checked)
        for d in self._displays:
            self._items[d.index].set_locked(checked)
        self._ppi_cb.setEnabled(self._ppi_available and not checked)
        if checked:
            self._apply_boxes(to_native_boxes(self._displays, self.collect_boxes()))
        else:
            self._update_readout()

    def _toggle_calibration(self, on: bool):
        diaglog.log("calibrate.mode", on=on)
        self._bg.setPixmap(self._grid_pix if on else self._photo_pix)
        self._export_grid_btn.setEnabled(on)
        # In calibration mode the crops ARE the recommendation — no move/align/resize.
        for d in self._displays:
            self._items[d.index].set_frozen(on)
        for w in (self._reset_btn, self._align_h_btn, self._align_v_btn, self._native_cb):
            w.setEnabled(not on)

    def _suggest(self):
        dx, dy = calibration_shift(self._row_l.value(), self._row_r.value(),
                                   self._col_l.value(), self._col_r.value(), self._cell)
        diaglog.log("calibrate.suggest",
                    rows=f"L{self._row_l.value()}=R{self._row_r.value()}",
                    cols=f"L{self._col_l.value()}=R{self._col_r.value()}", dx=dx, dy=dy)
        ds = sorted(self._displays, key=lambda d: d.x)
        cur = self.collect_boxes()
        for d in ds[1:]:  # nudge the right-hand display(s) to match the leftmost
            b = cur[d.index]
            cur[d.index] = Box(b.x + dx, b.y + dy, b.w, b.h)
        self._apply_boxes(cur)
        for sb in (self._row_l, self._row_r, self._col_l, self._col_r):
            sb.setValue(0)

    def _export_grid(self):
        if self._out_dir is None:
            return
        self._out_dir.mkdir(parents=True, exist_ok=True)
        boxes = self.collect_boxes()
        paths = []
        for d in self._displays:
            b = boxes[d.index]
            # Render the grid at the display's NATIVE resolution → crisp, high precision.
            grid = make_crop_grid(b.x, b.y, b.w, b.h, d.native_w, d.native_h, self._cell)
            fname = f"{self._image_stem}_GRID_{safe_name(d.name)}_{d.native_w}x{d.native_h}.png"
            path = unique_path(self._out_dir / fname)
            grid.save(path)
            paths.append(path)
        diaglog.log("calibrate.export", files=len(paths))
        self._readout.setText(
            "Calibration grids written (native-res):\n"
            + "\n".join(f"  {p}" for p in paths)
            + "\n→ set as wallpapers; at the seam read which left row meets which right row"
            "\n  (numbers down the edges), type rows L = R, then Suggest. Aligned when L:n = R:n."
        )

    def _update_readout(self):
        # Defensive: set_box() can fire this via itemChange before init finishes wiring up.
        if not getattr(self, "_readout", None) or not getattr(self, "_items", None):
            return
        lines = []
        for d in self._displays:
            left, top, right, bottom = self._items[d.index].current_box().as_crop()
            cw, ch = right - left, bottom - top
            if cw == d.native_w and ch == d.native_h:
                tag = "  · 1:1 (no resample)"
            elif cw < d.native_w or ch < d.native_h:
                tag = "  ⚠ upscaled"
            else:
                tag = ""
            ppi = f"  {d.ppi:.0f}ppi" if d.ppi else ""
            lines.append(
                f"{d.name:<18} crop {cw:>5}×{ch:<5} @ ({left:>5},{top:>5})  →  "
                f"{d.native_label}{ppi}{tag}"
            )
        self._readout.setText("\n".join(lines))


def run_dialog(pil_image: Image.Image, displays: List[Display],
               out_dir=None, image_stem: str = "wallpaper") -> Optional[Dict[int, Box]]:
    """Open the placement dialog modally. Returns crop boxes, or None if cancelled."""
    app = QApplication.instance() or QApplication([])
    dialog = SpanDialog(pil_image, displays, out_dir=out_dir, image_stem=image_stem)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.result_boxes
    return None
