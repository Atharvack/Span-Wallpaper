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
    QDialog,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .geometry import Box, Display, aspect_resize, clamp_pos, seed_layout

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
            event.accept()  # capture so the parent does not start a move
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self._active:
            self.parentItem().resize_from_scene(event.scenePos())
            event.accept()

    def mouseReleaseEvent(self, event):
        self._active = False
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
        self.setPos(box.x, box.y)
        self._reposition_children()
        self.update()

    def current_box(self) -> Box:
        p = self.pos()
        return Box(p.x(), p.y(), self._w, self._h)

    def resize_from_scene(self, scene_pt: QPointF):
        p = self.pos()
        w, h = aspect_resize(
            p.x(), p.y(), scene_pt.x(), scene_pt.y(), self.aspect, self.img_w, self.img_h
        )
        self.prepareGeometryChange()
        self._w, self._h = w, h
        self._reposition_children()
        self.update()
        self._on_change()

    def _reposition_children(self):
        self._grip.setPos(self._w, self._h)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            x, y = clamp_pos(value.x(), value.y(), self._w, self._h, self.img_w, self.img_h)
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

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


class SpanDialog(QDialog):
    """The placement dialog. On Apply, ``result_boxes`` holds one crop Box per display."""

    def __init__(self, pil_image: Image.Image, displays: List[Display]):
        super().__init__()
        self.setWindowTitle("span — place displays over the wallpaper")
        self.resize(1100, 760)

        self._displays = displays
        self.result_boxes: Optional[Dict[int, Box]] = None
        self._img_w = float(pil_image.width)
        self._img_h = float(pil_image.height)

        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(0, 0, self._img_w, self._img_h)
        bg = self._scene.addPixmap(pil_to_pixmap(pil_image))
        bg.setZValue(0)
        bg.setTransformationMode(Qt.TransformationMode.SmoothTransformation)

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

        reset_btn = QPushButton("Reset layout")
        cancel_btn = QPushButton("Cancel")
        apply_btn = QPushButton("Apply")
        apply_btn.setDefault(True)
        reset_btn.clicked.connect(self._reset)
        cancel_btn.clicked.connect(self.reject)
        apply_btn.clicked.connect(self._apply)

        buttons = QHBoxLayout()
        buttons.addWidget(reset_btn)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(apply_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._view, 1)
        layout.addWidget(hint)
        layout.addWidget(self._readout)
        layout.addLayout(buttons)

        # Seed positions now that every item AND widget exists.
        seeds = seed_layout(self._displays, self._img_w, self._img_h)
        for d in self._displays:
            self._items[d.index].set_box(seeds[d.index])
        self._update_readout()

    # -- actions ------------------------------------------------------------------
    def collect_boxes(self) -> Dict[int, Box]:
        return {d.index: self._items[d.index].current_box() for d in self._displays}

    def _apply(self):
        self.result_boxes = self.collect_boxes()
        self.accept()

    def _reset(self):
        seeds = seed_layout(self._displays, self._img_w, self._img_h)
        for d in self._displays:
            self._items[d.index].set_box(seeds[d.index])
        self._update_readout()

    def _update_readout(self):
        # Defensive: set_box() can fire this via itemChange before init finishes wiring up.
        if not getattr(self, "_readout", None) or not getattr(self, "_items", None):
            return
        lines = []
        for d in self._displays:
            left, top, right, bottom = self._items[d.index].current_box().as_crop()
            cw, ch = right - left, bottom - top
            warn = "  ⚠ upscaled" if (cw < d.native_w or ch < d.native_h) else ""
            lines.append(
                f"{d.name:<18} crop {cw:>5}×{ch:<5} @ ({left:>5},{top:>5})  →  "
                f"{d.native_label}{warn}"
            )
        self._readout.setText("\n".join(lines))


def run_dialog(pil_image: Image.Image, displays: List[Display]) -> Optional[Dict[int, Box]]:
    """Open the placement dialog modally. Returns crop boxes, or None if cancelled."""
    app = QApplication.instance() or QApplication([])
    dialog = SpanDialog(pil_image, displays)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.result_boxes
    return None
