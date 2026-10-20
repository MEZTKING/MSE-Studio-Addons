"""The canvas: shows the painting (zoomed, turned, mirrored) and turns the
pen, mouse and fingers into strokes, selections, fills, gradients,
liquify, shapes and moving things.

Pen pressure comes from a drawing tablet; the pen's eraser end erases.
Two fingers move, zoom and turn the canvas; a two-finger tap undoes and a
three-finger tap redoes. The mouse wheel zooms (Shift turns), the middle
button or Space + drag moves the canvas, Alt + click picks a colour."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QImage, QPainter, QPainterPath, QPen,
                           QPixmap, QPolygonF, QTransform)
from PySide6.QtWidgets import QMenu, QWidget

from . import tools as tl
from .doc import Document, as_alpha, blank
from .engine import Stroke, Symmetry, stroke_along

TOOLS = {"brush": "Paint", "smudge": "Smudge", "erase": "Erase", "fill": "Fill",
         "gradient": "Gradient", "picker": "Pick a colour", "select": "Select",
         "move": "Move and resize", "liquify": "Liquify", "shape": "Shapes"}
SELECT_SHAPES = {"rect": "Rectangle", "ellipse": "Ellipse", "lasso": "Freehand",
                 "wand": "Magic wand (same colour)"}
SHAPES = {"rect": "Rectangle", "ellipse": "Ellipse", "line": "Line"}
ZOOM_MIN, ZOOM_MAX = 0.02, 32.0
QUICKSHAPE_MS = 650


@dataclass
class Options:
    tool: str = "brush"
    select_shape: str = "rect"
    select_mode: str = "replace"           # replace, add, subtract, intersect
    fill_tolerance: int = 30
    fill_contiguous: bool = True
    fill_all_layers: bool = True
    gradient_radial: bool = False
    liquify_mode: str = "push"
    liquify_size: float = 160.0
    liquify_strength: float = 0.6
    shape: str = "rect"
    shape_fill: bool = True
    quickshape: bool = True
    speed_pressure: bool = False           # the mouse: faster = thinner
    symmetry: Symmetry = field(default_factory=Symmetry)
    show_frame: bool = True
    frame_opacity: float = 1.0
    grid: bool = False


def _checker() -> QPixmap:
    pm = QPixmap(16, 16)
    pm.fill(QColor("#ffffff"))
    p = QPainter(pm)
    p.fillRect(0, 0, 8, 8, QColor("#d9dce3"))
    p.fillRect(8, 8, 8, 8, QColor("#d9dce3"))
    p.end()
    return pm


class CanvasView(QWidget):
    changed = Signal()              # the painting changed (a stroke, a fill…)
    picked = Signal(QColor)         # the colour picker found a colour
    message = Signal(str)           # a hint for the status line
    view_changed = Signal()         # zoom / turn / mirror
    undo_requested = Signal()
    redo_requested = Signal()

    def __init__(self, studio, parent=None):
        super().__init__(parent)
        self.studio = studio
        self.opts: Options = studio.opts
        self.doc: Optional[Document] = None
        self.selection: Optional[tl.Selection] = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_AcceptTouchEvents)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setMinimumSize(320, 240)
        self.zoom = 1.0
        self.rotation = 0.0
        self.mirrored = False
        self.pan = QPointF(0, 0)
        self._fitted = True
        self._image: Optional[QImage] = None      # everything, put together
        self._checker = QBrush(_checker())
        self.overlay: Optional[QImage] = None      # the card's frame, art window see-through
        self.overlay_box = QRectF()
        # what's happening now
        self._stroke: Optional[Stroke] = None
        self._drag: Optional[dict] = None
        self._space = False
        self._cursor_at: Optional[QPointF] = None
        self._tablet_down = False
        self._eraser_end = False
        self._touch: Optional[dict] = None
        self._tf: Optional[dict] = None             # moving / resizing
        self._preview_path = QPainterPath()         # a selection or shape being drawn
        self._still_at: Optional[QPointF] = None
        self._quick = QTimer(self)
        self._quick.setSingleShot(True)
        self._quick.setInterval(QUICKSHAPE_MS)
        self._quick.timeout.connect(self._quickshape)
        self._hold = QTimer(self)                   # liquify keeps going while held
        self._hold.setInterval(40)
        self._hold.timeout.connect(self._liquify_hold)

    # ------------------------------------------------------------ the painting
    def set_document(self, doc: Document, selection: tl.Selection) -> None:
        self.cancel()
        self.doc, self.selection = doc, selection
        self.refresh_all()
        self.fit()

    def refresh_all(self) -> None:
        if self.doc is None:
            return
        self._image = self.doc.composite()
        self.update()

    def _refresh(self, rect: QRect, replace: Optional[dict] = None) -> None:
        """Put ``rect`` together again (with a stroke in progress) and show it."""
        if self.doc is None or self._image is None:
            return
        r = rect.intersected(self.doc.rect())
        if r.isEmpty():
            return
        part = self.doc.composite(r, replace=replace)
        p = QPainter(self._image)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(r.topLeft(), part)
        p.end()
        self.update(self.transform().mapRect(QRectF(r)).toAlignedRect().adjusted(-3, -3, 3, 3))

    def picture(self) -> Optional[QImage]:
        return self._image

    def set_overlay(self, image: Optional[QImage], box: QRectF = QRectF()) -> None:
        """The card's frame on top of the painting: ``box`` is where the art
        window is in ``image`` (the painting fills it)."""
        self.overlay, self.overlay_box = image, QRectF(box)
        self.update()

    # ------------------------------------------------------------ the view
    def transform(self) -> QTransform:
        t = QTransform()
        if self.doc is None:
            return t
        t.translate(self.width() / 2 + self.pan.x(), self.height() / 2 + self.pan.y())
        t.rotate(self.rotation)
        t.scale(-self.zoom if self.mirrored else self.zoom, self.zoom)
        t.translate(-self.doc.width / 2, -self.doc.height / 2)
        return t

    def to_doc(self, pos: QPointF) -> QPointF:
        inv, ok = self.transform().inverted()
        return inv.map(QPointF(pos)) if ok else QPointF(pos)

    def fit(self) -> None:
        if self.doc is None:
            return
        self.rotation, self.pan = 0.0, QPointF(0, 0)
        w, h = max(1, self.width() - 40), max(1, self.height() - 40)
        self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, min(w / self.doc.width, h / self.doc.height)))
        self._fitted = True
        self._view_changed()

    def actual_size(self) -> None:
        self._fitted = False
        self.zoom = 1.0
        self._view_changed()

    def zoom_by(self, factor: float, around: Optional[QPointF] = None) -> None:
        if self.doc is None:
            return
        around = QPointF(around) if around is not None else QPointF(self.width() / 2,
                                                                   self.height() / 2)
        before = self.to_doc(around)
        self._fitted = False
        self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, self.zoom * factor))
        after = self.transform().map(before)
        self.pan += around - after
        self._view_changed()

    def rotate_by(self, degrees: float, around: Optional[QPointF] = None) -> None:
        if self.doc is None:
            return
        around = QPointF(around) if around is not None else QPointF(self.width() / 2,
                                                                   self.height() / 2)
        before = self.to_doc(around)
        self._fitted = False
        self.rotation = (self.rotation + degrees) % 360
        if self.rotation > 180:
            self.rotation -= 360
        self.pan += around - self.transform().map(before)
        self._view_changed()

    def reset_rotation(self) -> None:
        self.rotation = 0.0
        self._view_changed()

    def flip_view(self) -> None:
        self.mirrored = not self.mirrored
        self._view_changed()

    def _view_changed(self) -> None:
        self.update()
        self.view_changed.emit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fitted:                  # until you zoom or move it, it fits the window
            self.fit()
        self.update()

    # ------------------------------------------------------------ drawing it
    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().color(self.backgroundRole()).darker(115))
        if self.doc is None or self._image is None:
            p.end()
            return
        t = self.transform()
        doc_rect = QRectF(0, 0, self.doc.width, self.doc.height)
        p.save()
        p.setTransform(t)
        shadow = QColor(0, 0, 0, 60)
        p.fillRect(doc_rect.translated(6 / max(self.zoom, 0.01), 6 / max(self.zoom, 0.01)),
                   shadow)
        p.setTransform(QTransform())
        p.setClipRegion(self._doc_region(t))
        p.fillRect(self.rect(), self._checker)
        p.setTransform(t)
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.zoom < 2.0)
        p.drawImage(QPointF(0, 0), self._image)
        p.setClipping(False)
        if self.overlay is not None and self.opts.show_frame and not self.overlay_box.isEmpty():
            b = self.overlay_box
            sx, sy = self.doc.width / b.width(), self.doc.height / b.height()
            p.setOpacity(self.opts.frame_opacity)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawImage(QRectF(-b.x() * sx, -b.y() * sy, self.overlay.width() * sx,
                               self.overlay.height() * sy), self.overlay)
            p.setOpacity(1.0)
        if self.opts.grid:
            pen = QPen(QColor(255, 255, 255, 150), 0)
            p.setPen(pen)
            for i in (1, 2):
                x, y = self.doc.width * i / 3, self.doc.height * i / 3
                p.drawLine(QPointF(x, 0), QPointF(x, self.doc.height))
                p.drawLine(QPointF(0, y), QPointF(self.doc.width, y))
        self._draw_symmetry(p)
        p.restore()
        self._draw_selection(p, t)
        self._draw_preview(p, t)
        self._draw_transform(p, t)
        self._draw_cursor(p)
        p.end()

    def _doc_region(self, t: QTransform):
        from PySide6.QtGui import QRegion
        poly = t.map(QPolygonF(QRectF(0, 0, self.doc.width, self.doc.height))).toPolygon()
        return QRegion(poly)

    def _draw_symmetry(self, p: QPainter) -> None:
        s = self.opts.symmetry
        if not s.kind or self.opts.tool not in ("brush", "smudge", "erase"):
            return
        w, h = self.doc.width, self.doc.height
        cx, cy = s.cx * w, s.cy * h
        p.setPen(QPen(QColor(80, 160, 255, 200), 0, Qt.DashLine))
        if s.kind in ("vertical", "quadrant"):
            p.drawLine(QPointF(cx, 0), QPointF(cx, h))
        if s.kind in ("horizontal", "quadrant"):
            p.drawLine(QPointF(0, cy), QPointF(w, cy))
        if s.kind == "radial":
            r = math.hypot(w, h)
            for i in range(max(2, s.spokes)):
                a = 2 * math.pi * i / max(2, s.spokes) - math.pi / 2
                p.drawLine(QPointF(cx, cy), QPointF(cx + math.cos(a) * r, cy + math.sin(a) * r))

    def _ants(self, p: QPainter, path: QPainterPath) -> None:
        p.setPen(QPen(QColor(255, 255, 255), 1.4))
        p.drawPath(path)
        pen = QPen(QColor(20, 20, 20), 1.4, Qt.CustomDashLine)
        pen.setDashPattern([4, 4])
        p.setPen(pen)
        p.drawPath(path)

    def _draw_selection(self, p: QPainter, t: QTransform) -> None:
        if self.selection is None or not self.selection.active() or self._tf is not None:
            return
        p.setRenderHint(QPainter.Antialiasing)
        self._ants(p, t.map(self.selection.outline))

    def _draw_preview(self, p: QPainter, t: QTransform) -> None:
        if self._preview_path.isEmpty():
            return
        p.setRenderHint(QPainter.Antialiasing)
        self._ants(p, t.map(self._preview_path))
        d = self._drag or {}
        if d.get("kind") == "gradient":
            a, b = t.map(d["a"]), t.map(d["b"])
            for pt in (a, b):
                p.setBrush(QColor(255, 255, 255))
                p.setPen(QPen(QColor(20, 20, 20), 1.5))
                p.drawEllipse(pt, 6, 6)

    def _handles(self, t: QTransform) -> dict:
        """The moving frame's handles in widget coordinates."""
        tf = self._tf
        w, h = tf["float"].width(), tf["float"].height()
        m = tf["matrix"] * t
        pts = {"tl": QPointF(0, 0), "tr": QPointF(w, 0), "br": QPointF(w, h),
               "bl": QPointF(0, h), "t": QPointF(w / 2, 0), "r": QPointF(w, h / 2),
               "b": QPointF(w / 2, h), "l": QPointF(0, h / 2)}
        out = {k: m.map(v) for k, v in pts.items()}
        top, centre = out["t"], m.map(QPointF(w / 2, h / 2))
        d = top - centre
        n = math.hypot(d.x(), d.y()) or 1.0
        out["rot"] = top + QPointF(d.x() / n * 28, d.y() / n * 28)
        out["centre"] = centre
        return out

    def _draw_transform(self, p: QPainter, t: QTransform) -> None:
        if self._tf is None:
            return
        h = self._handles(t)
        p.setRenderHint(QPainter.Antialiasing)
        poly = QPolygonF([h["tl"], h["tr"], h["br"], h["bl"], h["tl"]])
        path = QPainterPath()
        path.addPolygon(poly)
        self._ants(p, path)
        p.setPen(QPen(QColor(20, 20, 20), 1.2))
        p.drawLine(h["t"], h["rot"])
        for k in ("tl", "tr", "br", "bl", "t", "r", "b", "l"):
            p.setBrush(QColor(255, 255, 255))
            p.drawRect(QRectF(h[k].x() - 5, h[k].y() - 5, 10, 10))
        p.setBrush(QColor(80, 160, 255))
        p.drawEllipse(h["rot"], 7, 7)

    def _draw_cursor(self, p: QPainter) -> None:
        at = self._cursor_at
        if at is None or self.doc is None or self._space or self._touch is not None:
            return
        tool = self.opts.tool
        if tool in ("brush", "smudge", "erase"):
            _, size, _ = self.studio.brush_now(tool)
            r = max(1.0, size * self.zoom / 2)
        elif tool == "liquify":
            r = max(1.0, self.opts.liquify_size * self.zoom / 2)
        else:
            return
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
        p.drawEllipse(at, r + 0.75, r + 0.75)
        p.setPen(QPen(QColor(0, 0, 0, 200), 1.0))
        p.drawEllipse(at, r, r)
        if r < 4:
            p.drawLine(at - QPointF(8, 0), at - QPointF(4, 0))
            p.drawLine(at + QPointF(4, 0), at + QPointF(8, 0))
            p.drawLine(at - QPointF(0, 8), at - QPointF(0, 4))
            p.drawLine(at + QPointF(0, 4), at + QPointF(0, 8))

    def _update_cursor(self) -> None:
        if self._space or (self._drag or {}).get("kind") == "pan":
            self.setCursor(Qt.ClosedHandCursor if self._drag else Qt.OpenHandCursor)
        elif self.opts.tool in ("brush", "smudge", "erase", "liquify"):
            self.setCursor(Qt.BlankCursor if self.underMouse() else Qt.ArrowCursor)
        elif self.opts.tool in ("fill", "picker", "gradient", "shape", "select"):
            self.setCursor(Qt.CrossCursor)
        elif self.opts.tool == "move":
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def tool_changed(self) -> None:
        if self.opts.tool != "move" and self._tf is not None:
            self.apply_transform()
        self._update_cursor()
        self.update()

    # ------------------------------------------------------------ input: mouse, pen, touch
    def mousePressEvent(self, e):
        if self._tablet_down:
            return
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and self._space):
            self._drag = {"kind": "pan", "last": e.position()}
            self._update_cursor()
            return
        if e.button() == Qt.RightButton:
            self._context_menu(e.position())
            return
        if e.button() == Qt.LeftButton:
            if e.modifiers() & Qt.AltModifier and self.opts.tool in (
                    "brush", "smudge", "erase", "fill", "gradient", "shape"):
                self._pick(e.position())
                self._drag = {"kind": "pick"}
                return
            self._down(e.position(), 1.0, e.modifiers(), mouse=True)

    def mouseMoveEvent(self, e):
        self._cursor_at = e.position()
        if self._tablet_down:
            return
        d = self._drag
        if d is not None and d.get("kind") == "pan":
            self.pan += e.position() - d["last"]
            d["last"] = e.position()
            self._fitted = False
            self._view_changed()
            return
        if d is not None and d.get("kind") == "pick":
            self._pick(e.position())
            return
        if e.buttons() & Qt.LeftButton:
            self._move(e.position(), 1.0, e.modifiers())
        else:
            self.update()

    def mouseReleaseEvent(self, e):
        if self._tablet_down:
            return
        if self._drag is not None and self._drag.get("kind") in ("pan", "pick"):
            self._drag = None
            self._update_cursor()
            return
        if e.button() == Qt.LeftButton:
            self._up(e.position(), e.modifiers())

    def tabletEvent(self, e):
        e.accept()
        pos, pressure = e.position(), max(0.02, e.pressure())
        self._cursor_at = pos
        t = e.type()
        if t == QEvent.TabletPress:
            self._tablet_down = True
            try:
                from PySide6.QtGui import QPointingDevice
                self._eraser_end = e.pointerType() == QPointingDevice.PointerType.Eraser
            except (ImportError, AttributeError):
                self._eraser_end = False
            if self._space or e.buttons() & Qt.MiddleButton:
                self._drag = {"kind": "pan", "last": pos}
                return
            self._down(pos, pressure, e.modifiers(), mouse=False)
        elif t == QEvent.TabletMove:
            if self._drag is not None and self._drag.get("kind") == "pan":
                self.pan += pos - self._drag["last"]
                self._drag["last"] = pos
                self._view_changed()
            elif self._tablet_down:
                self._move(pos, pressure, e.modifiers())
            else:
                self.update()
        elif t == QEvent.TabletRelease:
            self._tablet_down = False
            if self._drag is not None and self._drag.get("kind") == "pan":
                self._drag = None
            else:
                self._up(pos, e.modifiers())
            self._eraser_end = False

    def wheelEvent(self, e):
        dy = e.angleDelta().y() or e.angleDelta().x()
        if not dy:
            return
        steps = dy / 120.0
        if e.modifiers() & Qt.ShiftModifier:
            self.rotate_by(15 * steps, e.position())
        elif e.modifiers() & Qt.ControlModifier and self.opts.tool in ("brush", "smudge",
                                                                          "erase"):
            self.studio.change_size(1.1 ** steps)
            self.update()
        else:
            self.zoom_by(1.15 ** steps, e.position())
        e.accept()

    def event(self, e):
        t = e.type()
        if t in (QEvent.TouchBegin, QEvent.TouchUpdate, QEvent.TouchEnd, QEvent.TouchCancel):
            self._touch_event(e)
            return True
        if t == QEvent.Leave:
            self._cursor_at = None
            self.update()
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = True
            self._update_cursor()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and self._tf is not None:
            self.apply_transform()
            return
        if e.key() == Qt.Key_Escape and (self._tf is not None or self._drag is not None or
                                         self._stroke is not None):
            self.cancel()
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = False
            self._update_cursor()
            return
        super().keyReleaseEvent(e)

    def enterEvent(self, e):
        self._update_cursor()
        super().enterEvent(e)

    def focusOutEvent(self, e):
        self._space = False
        super().focusOutEvent(e)

    def _touch_event(self, e) -> None:
        pts = e.points()
        t = e.type()
        if t == QEvent.TouchBegin:
            self._touch = {"start": time.monotonic(), "most": len(pts), "moved": 0.0,
                           "painting": False, "last": None}
        tc = self._touch
        if tc is None:
            return
        tc["most"] = max(tc["most"], len(pts))
        if len(pts) == 1 and tc["most"] == 1:              # one finger paints
            pos = pts[0].position()
            if not tc["painting"]:
                tc["painting"] = True
                self._down(pos, 1.0, Qt.NoModifier, mouse=True)
            elif t in (QEvent.TouchEnd, QEvent.TouchCancel):
                self._up(pos, Qt.NoModifier)
            else:
                self._move(pos, 1.0, Qt.NoModifier)
        elif len(pts) >= 2:
            if tc["painting"]:                          # a second finger: it was a gesture
                self.cancel()
                tc["painting"] = False
            a, b = pts[0].position(), pts[1].position()
            centre = (a + b) / 2
            dist = math.hypot(b.x() - a.x(), b.y() - a.y())
            ang = math.degrees(math.atan2(b.y() - a.y(), b.x() - a.x()))
            last = tc["last"]
            if last is not None and len(pts) == 2:
                lc, ld, la = last
                self.pan += centre - lc
                if ld > 4 and dist > 4:
                    self.zoom_by(dist / ld, centre)
                turn = ang - la
                if turn > 180:
                    turn -= 360
                if turn < -180:
                    turn += 360
                if abs(turn) < 45:
                    self.rotate_by(turn, centre)
                tc["moved"] += math.hypot(centre.x() - lc.x(), centre.y() - lc.y()) + \
                    abs(dist - ld)
                self._view_changed()
            tc["last"] = (centre, dist, ang)
        if t in (QEvent.TouchEnd, QEvent.TouchCancel):
            quick = time.monotonic() - tc["start"] < 0.3 and tc["moved"] < 20
            if quick and tc["most"] == 2:
                self.undo_requested.emit()
            elif quick and tc["most"] == 3:
                self.redo_requested.emit()
            self._touch = None

    def _context_menu(self, pos: QPointF) -> None:
        m = QMenu(self)
        m.addAction("Pick this colour", lambda: self._pick(pos))
        m.addSeparator()
        m.addAction("Undo", self.undo_requested.emit)
        m.addAction("Redo", self.redo_requested.emit)
        m.addSeparator()
        m.addAction("Fit to the window", self.fit)
        m.addAction("Actual size (100%)", self.actual_size)
        m.addAction("Turn the canvas back upright", self.reset_rotation)
        m.addAction("Mirror the view", self.flip_view)
        m.exec(self.mapToGlobal(pos.toPoint()))

    # ------------------------------------------------------------ what the tools do
    def _layer_ok(self, quiet: bool = False) -> bool:
        lay = self.doc.layer
        if lay.locked:
            if not quiet:
                self.message.emit("This layer is locked – unlock it in Layers to change it.")
            return False
        if not lay.visible:
            if not quiet:
                self.message.emit("This layer is hidden – show it in Layers to paint on it.")
            return False
        return True

    def _down(self, pos: QPointF, pressure: float, mods, mouse: bool) -> None:
        if self.doc is None:
            return
        self.setFocus()
        tool = "erase" if self._eraser_end else self.opts.tool
        at = self.to_doc(pos)
        if tool in ("brush", "smudge", "erase"):
            if not self._layer_ok():
                return
            brush, size, opacity = self.studio.brush_now(tool)
            sel = self.selection.mask if self.selection is not None and \
                self.selection.active() else None
            self._stroke = Stroke(self.doc, brush, self.studio.colour(), size=size,
                                  opacity=opacity, selection=sel, symmetry=self.opts.symmetry,
                                  pressure_from_speed=mouse and self.opts.speed_pressure)
            self._stroke.add(at.x(), at.y(), pressure)
            self._stroke_refresh()
            self._still_at = pos
            if self.opts.quickshape:
                self._quick.start()
        elif tool == "picker":
            self._pick(pos)
            self._drag = {"kind": "pick"}
        elif tool == "fill":
            self._fill(at)
        elif tool == "gradient":
            if self._layer_ok():
                self._drag = {"kind": "gradient", "a": at, "b": at,
                              "before": self.doc.layer.image}
        elif tool == "select":
            self._select_down(at, mods)
        elif tool == "shape":
            if self._layer_ok():
                self._drag = {"kind": "shape", "a": at, "b": at}
        elif tool == "liquify":
            if self._layer_ok():
                lay = self.doc.layer
                self._drag = {"kind": "liquify", "at": at, "last": at,
                              "original": lay.image, "work": lay.image.copy(),
                              "dirty": QRect()}
                if self.opts.liquify_mode != "push":
                    self._hold.start()
        elif tool == "move":
            self._transform_down(pos, mods)

    def _move(self, pos: QPointF, pressure: float, mods) -> None:
        if self.doc is None:
            return
        at = self.to_doc(pos)
        if self._stroke is not None:
            self._stroke.add(at.x(), at.y(), pressure)
            self._stroke_refresh()
            if self.opts.quickshape and self._still_at is not None:
                d = pos - self._still_at
                if math.hypot(d.x(), d.y()) > 3:
                    self._still_at = pos
                    self._quick.start()
            self.update()
            return
        d = self._drag
        if d is None:
            return
        kind = d.get("kind")
        if kind == "pick":
            self._pick(pos)
        elif kind == "gradient":
            d["b"] = at
            self._gradient_preview()
        elif kind == "select":
            self._select_move(at, mods)
        elif kind == "shape":
            d["b"] = self._constrained(d["a"], at, mods)
            self._preview_path = self._shape_path(d["a"], d["b"])
            self.update()
        elif kind == "liquify":
            delta = at - d["last"]
            d["at"] = at
            if self.opts.liquify_mode == "push":
                self._liquify_step(delta)
            d["last"] = at
        elif kind in ("tf-move", "tf-scale", "tf-rotate"):
            self._transform_move(pos, mods)
        self.update()

    def _up(self, pos: QPointF, mods) -> None:
        if self.doc is None:
            return
        self._quick.stop()
        self._hold.stop()
        if self._stroke is not None:
            s, self._stroke = self._stroke, None
            s.end()
            s.commit()
            self._image = self.doc.composite() if s.dirty.isEmpty() else self._image
            self._refresh(s.dirty)
            self.changed.emit()
            return
        d, self._drag = self._drag, None
        if d is None:
            return
        kind = d.get("kind")
        if kind == "gradient":
            self._preview_path = QPainterPath()
            lay = self.doc.layer
            work = d.get("work")
            if work is not None and d["a"] != d["b"]:
                self.doc.push_region(self.doc.active, self.doc.rect(), d["before"].copy(),
                                     "Gradient")
                lay.image = work
                self.doc.dirty = True
                self.changed.emit()
            self.refresh_all()
        elif kind == "select":
            self._select_up(d, mods)
        elif kind == "shape":
            self._preview_path = QPainterPath()
            self._shape_done(d)
        elif kind == "liquify":
            r = d["dirty"].intersected(self.doc.rect())
            if not r.isEmpty():
                self.doc.push_region(self.doc.active, r, d["original"].copy(r), "Liquify")
                self.doc.layer.image = d["work"]
                self.doc.dirty = True
                self.changed.emit()
            self.refresh_all()
        elif kind in ("tf-move", "tf-scale", "tf-rotate"):
            self._tf["drag"] = None
        self.update()

    def cancel(self) -> None:
        """Stop what's being done without changing the painting."""
        self._quick.stop()
        self._hold.stop()
        self._stroke = None
        self._drag = None
        self._preview_path = QPainterPath()
        if self._tf is not None:
            self.cancel_transform()
        self.refresh_all()

    # ---- strokes
    def _stroke_refresh(self) -> None:
        s = self._stroke
        r = s.take_dirty()
        if not r.isEmpty():
            self._refresh(r, {s.index: s.preview()})

    def _quickshape(self) -> None:
        s = self._stroke
        if s is None:
            return
        shape = s.quickshape()
        if shape:
            self._stroke_refresh()
            self.message.emit("A straight line." if shape == "line" else "An ellipse.")

    # ---- colours
    def _pick(self, pos: QPointF) -> None:
        if self._image is None:
            return
        at = self.to_doc(pos)
        c = tl.pick(self._image, int(at.x()), int(at.y()), radius=1)
        if c.isValid():
            self.picked.emit(c)

    # ---- fill
    def _fill(self, at: QPointF) -> None:
        if not self._layer_ok():
            return
        src = self._image if self.opts.fill_all_layers else self.doc.layer.image
        x, y = int(at.x()), int(at.y())
        if not self.doc.rect().contains(x, y):
            return
        mask = tl.flood_mask(src, x, y, self.opts.fill_tolerance, self.opts.fill_contiguous)
        r = tl.fill_mask(self.doc, mask, self.studio.colour(), self.selection)
        if not r.isEmpty():
            self._refresh(r)
            self.changed.emit()

    # ---- gradient
    def _gradient_preview(self) -> None:
        d = self._drag
        a, b = d["a"], d["b"]
        line = QPainterPath()
        line.moveTo(a)
        line.lineTo(b)
        self._preview_path = line
        if a == b:
            return
        work = d["before"].copy()
        tl.paint_gradient(work, a, b, self.studio.colour(), self.studio.secondary(),
                          self.opts.gradient_radial, self.selection,
                          self.doc.layer.alpha_lock)
        d["work"] = work
        self._refresh(self.doc.rect(), {self.doc.active: work})

    # ---- selections
    def _select_down(self, at: QPointF, mods) -> None:
        mode = self.opts.select_mode
        if mods & Qt.ShiftModifier:
            mode = "add"
        elif mods & Qt.AltModifier:
            mode = "subtract"
        shape = self.opts.select_shape
        if shape == "wand":
            mask = tl.flood_mask(self._image, int(at.x()), int(at.y()),
                                 self.opts.fill_tolerance, self.opts.fill_contiguous, grow=0)
            self.selection.set_mask(mask, mode)
            self.message.emit(self._selection_note())
            self.update()
            return
        path = QPainterPath()
        path.moveTo(at)
        self._drag = {"kind": "select", "a": at, "b": at, "mode": mode, "path": path,
                      "shape": shape}

    def _select_move(self, at: QPointF, mods) -> None:
        d = self._drag
        if d["shape"] == "lasso":
            d["path"].lineTo(at)
            self._preview_path = QPainterPath(d["path"])
            self._preview_path.closeSubpath()
        else:
            d["b"] = self._constrained(d["a"], at, mods)
            r = QRectF(d["a"], d["b"]).normalized()
            self._preview_path = QPainterPath()
            if d["shape"] == "ellipse":
                self._preview_path.addEllipse(r)
            else:
                self._preview_path.addRect(r)

    def _select_up(self, d: dict, mods) -> None:
        path = QPainterPath(self._preview_path)
        self._preview_path = QPainterPath()
        if path.isEmpty() or path.boundingRect().width() < 2 or \
                path.boundingRect().height() < 2:
            if d["mode"] == "replace":           # a click: select nothing
                self.selection.clear()
                self.message.emit("Nothing selected – painting goes everywhere.")
            self.update()
            return
        self.selection.set_path(path, d["mode"])
        self.message.emit(self._selection_note())
        self.update()

    def _selection_note(self) -> str:
        if not self.selection.active():
            return "Nothing selected – painting goes everywhere."
        return ("Painting, filling and changes now stay inside the selection. "
                "Shift adds to it, Alt takes away; Ctrl+D selects nothing.")

    # ---- shapes
    @staticmethod
    def _constrained(a: QPointF, b: QPointF, mods) -> QPointF:
        """Shift: a square / circle, or a line at 45° steps."""
        if not mods & Qt.ShiftModifier:
            return b
        dx, dy = b.x() - a.x(), b.y() - a.y()
        s = max(abs(dx), abs(dy))
        return QPointF(a.x() + math.copysign(s, dx or 1), a.y() + math.copysign(s, dy or 1))

    def _shape_path(self, a: QPointF, b: QPointF) -> QPainterPath:
        path = QPainterPath()
        if self.opts.shape == "line":
            path.moveTo(a)
            path.lineTo(b)
        elif self.opts.shape == "ellipse":
            path.addEllipse(QRectF(a, b).normalized())
        else:
            path.addRect(QRectF(a, b).normalized())
        return path

    def _shape_done(self, d: dict) -> None:
        a, b = d["a"], d["b"]
        if math.hypot(b.x() - a.x(), b.y() - a.y()) < 2:
            return
        path = self._shape_path(a, b)
        if self.opts.shape_fill and self.opts.shape != "line":
            sel = tl.Selection(self.doc.width, self.doc.height)
            sel.set_path(path)
            if sel.mask is None:
                return
            mask = tl.grey_array(sel.mask).copy()
            r = tl.fill_mask(self.doc, mask, self.studio.colour(), self.selection, "Shape")
            self._refresh(r)
        else:
            brush, size, opacity = self.studio.brush_now("brush")
            pts = []
            for poly in path.toSubpathPolygons():
                pts.extend((pt.x(), pt.y()) for pt in poly)
            if self.opts.shape != "line" and pts:
                pts.append(pts[0])
            dense = _densify(pts, max(1.0, size * 0.25))
            sel = self.selection.mask if self.selection.active() else None
            s = stroke_along(self.doc, brush, self.studio.colour(), dense, 1.0, size=size,
                             opacity=opacity, selection=sel)
            s.commit("Shape")
            self._refresh(s.dirty)
        self.changed.emit()

    # ---- liquify
    def _liquify_step(self, delta: QPointF) -> None:
        d = self._drag
        if d is None:
            return
        r = tl.liquify(d["work"], d["original"], self.opts.liquify_mode, d["at"], delta,
                       self.opts.liquify_size / 2, self.opts.liquify_strength)
        if not r.isEmpty():
            d["dirty"] = d["dirty"].united(r)
            self._refresh(r, {self.doc.active: d["work"]})

    def _liquify_hold(self) -> None:
        if self._drag is None or self._drag.get("kind") != "liquify":
            self._hold.stop()
            return
        self._liquify_step(QPointF(0, 0))

    # ------------------------------------------------------------ moving and resizing
    def transform_active(self) -> bool:
        return self._tf is not None

    def begin_transform(self) -> bool:
        """Lift what's selected on the layer (or the whole layer) to move,
        resize and turn it."""
        if self.doc is None or self._tf is not None:
            return self._tf is not None
        if not self._layer_ok():
            return False
        lay = self.doc.layer
        bounds = tl.paint_bounds(lay.image)
        if self.selection is not None and self.selection.active():
            bounds = bounds.intersected(self.selection.bounds())
        if bounds.isEmpty():
            self.message.emit("There's nothing to move on this layer.")
            return False
        before = lay.image
        content = before.copy(bounds)
        base = before.copy()
        if self.selection is not None and self.selection.active():
            mask = as_alpha(self.selection.mask)
            p = QPainter(content)
            p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            p.drawImage(0, 0, mask, bounds.x(), bounds.y(), bounds.width(), bounds.height())
            p.end()
            p = QPainter(base)
            p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
            p.drawImage(0, 0, mask)
            p.end()
        else:
            base.fill(Qt.transparent)
        self._tf = {"layer": self.doc.active, "before": before, "base": base,
                    "float": content, "matrix": QTransform.fromTranslate(bounds.x(), bounds.y()),
                    "drag": None, "work": None}
        self._transform_render()
        self.message.emit("Drag to move, the squares to resize (Shift: free), the blue dot to "
                          "turn. Enter puts it down, Esc puts it back.")
        return True

    def _transform_render(self) -> None:
        tf = self._tf
        work = tf["base"].copy()
        p = QPainter(work)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        p.setTransform(tf["matrix"])
        p.drawImage(0, 0, tf["float"])
        p.end()
        tf["work"] = work
        self._refresh(self.doc.rect(), {tf["layer"]: work})

    def _transform_down(self, pos: QPointF, mods) -> None:
        if self._tf is None and not self.begin_transform():
            return
        tf = self._tf
        h = self._handles(self.transform())
        hit = None
        for k in ("rot", "tl", "tr", "br", "bl", "t", "r", "b", "l"):
            d = h[k] - pos
            if math.hypot(d.x(), d.y()) <= 12:
                hit = k
                break
        start = {"pos": pos, "matrix": QTransform(tf["matrix"]), "handle": hit}
        if hit == "rot":
            self._drag = {"kind": "tf-rotate"}
        elif hit is not None:
            self._drag = {"kind": "tf-scale"}
        else:
            self._drag = {"kind": "tf-move"}
        tf["drag"] = start

    def _transform_move(self, pos: QPointF, mods) -> None:
        tf = self._tf
        st = tf.get("drag")
        if tf is None or st is None:
            return
        m0: QTransform = st["matrix"]
        kind = self._drag["kind"]
        a, b = self.to_doc(st["pos"]), self.to_doc(pos)
        if kind == "tf-move":
            tf["matrix"] = m0 * QTransform.fromTranslate(b.x() - a.x(), b.y() - a.y())
        elif kind == "tf-rotate":
            w, h = tf["float"].width(), tf["float"].height()
            c = m0.map(QPointF(w / 2, h / 2))
            ang = math.degrees(math.atan2(b.y() - c.y(), b.x() - c.x()) -
                               math.atan2(a.y() - c.y(), a.x() - c.x()))
            if mods & Qt.ShiftModifier:
                ang = round(ang / 15) * 15
            r = QTransform()
            r.translate(c.x(), c.y())
            r.rotate(ang)
            r.translate(-c.x(), -c.y())
            tf["matrix"] = m0 * r
        else:
            inv, ok = m0.inverted()
            if not ok:
                return
            la, lb = inv.map(a), inv.map(b)
            w, h = tf["float"].width(), tf["float"].height()
            k = st["handle"]
            ax = w if "l" in k else 0.0 if "r" in k else w / 2
            ay = h if "t" in k else 0.0 if "b" in k else h / 2
            if k in ("tl", "tr", "br", "bl"):
                sa = QPointF(la.x() - ax, la.y() - ay)
                sb = QPointF(lb.x() - ax, lb.y() - ay)
                if mods & Qt.ShiftModifier:          # free
                    kx = sb.x() / sa.x() if abs(sa.x()) > 1e-3 else 1.0
                    ky = sb.y() / sa.y() if abs(sa.y()) > 1e-3 else 1.0
                else:                                 # keeps its shape
                    n = sa.x() ** 2 + sa.y() ** 2
                    kx = ky = (sa.x() * sb.x() + sa.y() * sb.y()) / n if n > 1e-3 else 1.0
            elif k in ("l", "r"):
                kx = (lb.x() - ax) / (la.x() - ax) if abs(la.x() - ax) > 1e-3 else 1.0
                ky = 1.0
            else:
                kx = 1.0
                ky = (lb.y() - ay) / (la.y() - ay) if abs(la.y() - ay) > 1e-3 else 1.0
            if abs(kx) < 0.01:
                kx = math.copysign(0.01, kx or 1)
            if abs(ky) < 0.01:
                ky = math.copysign(0.01, ky or 1)
            s = QTransform()
            s.translate(ax, ay)
            s.scale(kx, ky)
            s.translate(-ax, -ay)
            tf["matrix"] = s * m0
        self._transform_render()

    def transform_flip(self, horizontal: bool = True) -> None:
        if self._tf is None and not self.begin_transform():
            return
        tf = self._tf
        w, h = tf["float"].width(), tf["float"].height()
        s = QTransform()
        s.translate(w / 2, h / 2)
        s.scale(-1 if horizontal else 1, 1 if horizontal else -1)
        s.translate(-w / 2, -h / 2)
        tf["matrix"] = s * tf["matrix"]
        self._transform_render()
        self.update()

    def transform_rotate(self, degrees: float) -> None:
        if self._tf is None and not self.begin_transform():
            return
        tf = self._tf
        w, h = tf["float"].width(), tf["float"].height()
        s = QTransform()
        s.translate(w / 2, h / 2)
        s.rotate(degrees)
        s.translate(-w / 2, -h / 2)
        tf["matrix"] = s * tf["matrix"]
        self._transform_render()
        self.update()

    def transform_fit(self) -> None:
        """Make it fill the painting (covering it)."""
        if self._tf is None and not self.begin_transform():
            return
        tf = self._tf
        w, h = tf["float"].width(), tf["float"].height()
        k = max(self.doc.width / w, self.doc.height / h)
        m = QTransform()
        m.translate((self.doc.width - w * k) / 2, (self.doc.height - h * k) / 2)
        m.scale(k, k)
        tf["matrix"] = m
        self._transform_render()
        self.update()

    def apply_transform(self) -> None:
        tf, self._tf = self._tf, None
        if tf is None:
            return
        self._drag = None
        if tf["work"] is not None:
            lay = self.doc.layers[tf["layer"]]
            self.doc.push_region(tf["layer"], self.doc.rect(), tf["before"].copy(), "Move")
            lay.image = tf["work"]
            self.doc.dirty = True
            if self.selection is not None and self.selection.active():
                self.selection.clear()
            self.changed.emit()
        self.refresh_all()
        self.message.emit("")

    def cancel_transform(self) -> None:
        self._tf = None
        self._drag = None
        self.refresh_all()
        self.message.emit("")

    def sizeHint(self):
        return QSize(900, 700)


def _densify(pts: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    """Points along a path at most ``step`` apart (so a brush follows corners)."""
    out: list[tuple[float, float]] = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        out.extend((x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n))
    if pts:
        out.append(pts[-1])
    return out


def _unused() -> None:            # names some readers look for
    return np, blank, QCursor
