"""Strokes: turning the pen's path into paint.

A stroke smooths the pen's points (StreamLine), places the brush's tip
along them (spacing), changes each tip with pressure and jitter, and draws:

- paint / erase: the tips build up in a stroke buffer, which goes onto the
  layer with the brush's opacity (so one stroke never covers more than its
  opacity, like real paint – unless the brush builds up);
- smudge: the tip carries the paint under it along the stroke;
- blur: the paint under the tip is softened.

Symmetry repeats every tip in mirror (or radial) positions. QuickShape turns
a finished line into a straight line or an ellipse."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QTransform

from . import brushes as bl
from .brushes import Brush
from .doc import FORMAT, Document, as_alpha, blank

COMPOSE = {"normal": QPainter.CompositionMode_SourceOver,
           "multiply": QPainter.CompositionMode_Multiply,
           "add": QPainter.CompositionMode_Plus,
           "screen": QPainter.CompositionMode_Screen}


@dataclass
class Symmetry:
    """Mirror drawing: "" off, "vertical" (left–right), "horizontal",
    "quadrant", or "radial" with ``spokes`` copies around the centre."""
    kind: str = ""
    spokes: int = 6
    cx: float = 0.5                 # the centre, as a part of the width / height
    cy: float = 0.5

    def points(self, x: float, y: float, angle: float, w: int, h: int
               ) -> list[tuple[float, float, float]]:
        cx, cy = self.cx * w, self.cy * h
        out = [(x, y, angle)]
        if self.kind in ("vertical", "quadrant"):
            out.append((2 * cx - x, y, 180 - angle))
        if self.kind in ("horizontal", "quadrant"):
            out.append((x, 2 * cy - y, -angle))
        if self.kind == "quadrant":
            out.append((2 * cx - x, 2 * cy - y, angle + 180))
        if self.kind == "radial" and self.spokes > 1:
            for i in range(1, self.spokes):
                a = 2 * math.pi * i / self.spokes
                dx, dy = x - cx, y - cy
                out.append((cx + dx * math.cos(a) - dy * math.sin(a),
                            cy + dx * math.sin(a) + dy * math.cos(a),
                            angle + math.degrees(a)))
        return out


def qimage_array(img: QImage) -> np.ndarray:
    """The picture's pixels as an H×W×4 uint8 array (a view: changes write
    through while ``img`` lives)."""
    ptr = img.bits()
    return np.ndarray((img.height(), img.bytesPerLine() // 4, 4), np.uint8,
                      buffer=ptr)[:, :img.width()]


class Stroke:
    """One stroke on one layer. ``add()`` the pen's points, ``preview()`` is
    the layer as it looks now, ``commit()`` puts it on the layer (one undo
    step)."""

    def __init__(self, doc: Document, brush: Brush, colour: QColor,
                 size: Optional[float] = None, opacity: Optional[float] = None,
                 selection: Optional[QImage] = None, symmetry: Optional[Symmetry] = None,
                 alpha_lock: Optional[bool] = None, layer: Optional[int] = None,
                 pressure_from_speed: bool = False, seed: Optional[int] = None):
        self.doc = doc
        self.index = doc.active if layer is None else layer
        self.layer = doc.layers[self.index]
        self.brush = brush
        self.colour = QColor(colour)
        self.size = float(size if size is not None else brush.size)
        self.opacity = float(opacity if opacity is not None else brush.opacity)
        self.selection = selection                # Grayscale8 mask or None
        self.symmetry = symmetry or Symmetry()
        self.alpha_lock = self.layer.alpha_lock if alpha_lock is None else alpha_lock
        self.pressure_from_speed = pressure_from_speed
        self.rnd = random.Random(seed)
        self.original = self.layer.image          # untouched until commit
        self.work = self.original.copy()          # the layer with the stroke so far
        self.buffer = None if brush.mode in ("smudge", "blur") else \
            blank(doc.width, doc.height)
        self.dirty = QRect()                      # everything this stroke changed
        self._new = QRect()                       # changed since the last take_dirty()
        self._raw: list[tuple[float, float, float]] = []     # pen points (x, y, pressure)
        self._smooth: Optional[tuple[float, float, float]] = None
        self._last: Optional[tuple[float, float, float]] = None   # last tip
        self._left = 0.0                          # distance to the next tip
        self._travel = 0.0                        # how far the stroke has gone
        self._angle = 0.0                         # the stroke's direction
        self._carry: dict[int, QImage] = {}       # smudge: paint carried, per mirror
        self._mix = QColor(self.colour)           # wet paint: the colour now
        self.points: list[tuple[float, float, float]] = []   # the tips' path (QuickShape)

    # ------------------------------------------------------------ input
    def add(self, x: float, y: float, pressure: float = 1.0) -> None:
        pressure = max(0.0, min(1.0, pressure))
        if self.pressure_from_speed and self._raw:
            px, py, _ = self._raw[-1]
            speed = math.hypot(x - px, y - py)
            pressure = max(0.25, min(1.0, 1.2 - speed / max(8.0, self.size * 1.5)))
        self._raw.append((x, y, pressure))
        s = self.brush.smoothing
        if self._smooth is None:
            self._smooth = (x, y, pressure)
            self._tip_at(x, y, pressure)
            return
        k = 1.0 - min(0.95, s) ** 0.6 * 0.9        # StreamLine: lag behind the pen
        sx, sy, sp = self._smooth
        n = (sx + (x - sx) * k, sy + (y - sy) * k, sp + (pressure - sp) * k)
        self._segment(self._smooth, n)
        self._smooth = n

    def end(self) -> None:
        """The pen lifts: catch up with where it ended."""
        if self._smooth is not None and self._raw:
            x, y, p = self._raw[-1]
            self._segment(self._smooth, (x, y, self._smooth[2]))
            self._smooth = (x, y, p)

    # ------------------------------------------------------------ placing tips
    def _diameter(self, pressure: float) -> float:
        b = self.brush
        d = self.size
        if b.pressure_size:
            d *= b.min_size + (1.0 - b.min_size) * pressure
        if b.taper > 0:
            d *= min(1.0, 0.15 + self._travel / max(1.0, b.taper * self.size * 8))
        return max(0.6, d)

    def _segment(self, a, b) -> None:
        ax, ay, ap = a
        bx, by, bp = b
        dist = math.hypot(bx - ax, by - ay)
        if dist < 1e-3:
            return
        self._angle = math.degrees(math.atan2(by - ay, bx - ax))
        t = 0.0
        while True:
            pressure = ap + (bp - ap) * t
            step = max(0.5, self.brush.spacing * self._diameter(pressure))
            need = step - self._left
            if t * dist + need > dist:
                self._left += dist - t * dist
                break
            t += need / dist
            self._left = 0.0
            x, y = ax + (bx - ax) * t, ay + (by - ay) * t
            self._travel += step
            self._tip_at(x, y, ap + (bp - ap) * t)

    def _tip_at(self, x: float, y: float, pressure: float) -> None:
        b = self.brush
        self.points.append((x, y, pressure))
        for _ in range(max(1, b.count)):
            d = self._diameter(pressure)
            if b.jitter_size:
                d *= 1.0 - self.rnd.uniform(0, b.jitter_size) * 0.9
            ang = b.angle + (self._angle if b.follow else 0.0)
            if b.jitter_angle:
                ang += self.rnd.uniform(-90, 90) * b.jitter_angle
            px, py = x, y
            if b.scatter:
                r = math.sqrt(self.rnd.uniform(0, 1)) * b.scatter * d
                t = self.rnd.uniform(0, 2 * math.pi)
                px, py = x + math.cos(t) * r, y + math.sin(t) * r
            flow = b.flow
            if b.pressure_opacity:
                flow *= b.min_flow + (1.0 - b.min_flow) * pressure
            if b.jitter_opacity:
                flow *= 1.0 - self.rnd.uniform(0, b.jitter_opacity)
            for i, (mx, my, mang) in enumerate(self.symmetry.points(
                    px, py, ang, self.doc.width, self.doc.height)):
                self._dab(i, mx, my, d, mang, flow, pressure)
        self._last = (x, y, pressure)

    # ------------------------------------------------------------ drawing a tip
    def _dab_rect(self, x: float, y: float, d: float) -> QRect:
        r = d / 2.0 + 2
        return QRect(int(math.floor(x - r)), int(math.floor(y - r)),
                     int(math.ceil(2 * r)) + 1, int(math.ceil(2 * r)) + 1)

    def _dab_image(self, d: float, colour: QColor, flow: float, angle: float,
                   origin: QPointF) -> tuple[QImage, QPoint]:
        """The tip as a picture (rotated, its grain on), and where it goes."""
        b = self.brush
        di = max(1, int(round(d)))
        t = bl.tip(b.shape, di, round(b.hardness, 2), round(b.roundness, 2),
                   round(b.wet_edges, 2), colour.rgba())
        rect = self._dab_rect(origin.x(), origin.y(), d)
        img = blank(rect.width(), rect.height())
        p = QPainter(img)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setOpacity(max(0.0, min(1.0, flow)))
        p.translate(origin.x() - rect.x(), origin.y() - rect.y())
        if angle and (b.roundness < 0.999 or b.shape not in ("round",)):
            p.rotate(angle)
        scale = d / di
        p.scale(scale, scale)
        p.drawImage(QPointF(-di / 2.0, -di / 2.0), t)
        p.resetTransform()
        grain = bl.grain_texture(b.grain, round(b.grain_depth, 2))
        if grain is not None:                   # the grain stays on the canvas
            br = QBrush(grain)
            tr = QTransform()
            tr.translate(-rect.x(), -rect.y())
            tr.scale(b.grain_scale, b.grain_scale)
            br.setTransform(tr)
            p.setOpacity(1.0)
            p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            p.fillRect(img.rect(), br)
        p.end()
        return img, rect.topLeft()

    def _dab(self, mirror: int, x: float, y: float, d: float, angle: float, flow: float,
             pressure: float) -> None:
        b = self.brush
        rect = self._dab_rect(x, y, d).intersected(self.doc.rect())
        if rect.isEmpty():
            return
        if b.mode == "smudge":
            self._smudge(mirror, x, y, d, angle, pressure)
        elif b.mode == "blur":
            self._blur(x, y, d, angle, pressure)
        else:
            colour = self.colour
            if b.mode == "paint" and b.wet > 0:            # wet paint: picks up colour
                under = bl.average(self.work.copy(self._dab_rect(x, y, max(2, d * 0.5))
                                                  .intersected(self.doc.rect())))
                if under.alpha() > 10:
                    self._mix = bl.mix(self._mix, under, b.wet * 0.35)
                self._mix = bl.mix(self._mix, self.colour, (1 - b.wet) * 0.25)
                colour = self._mix
            if b.jitter_hue:
                colour = bl.jitter_colour(colour, b.jitter_hue, self.rnd)
            img, at = self._dab_image(d, colour, flow, angle, QPointF(x, y))
            p = QPainter(self.buffer)
            p.drawImage(at, img)
            p.end()
            self._apply(rect)
        self.dirty = self.dirty.united(rect)
        self._new = self._new.united(rect)

    def _masked(self, img: QImage, at: QPoint) -> QImage:
        """``img`` (placed at ``at``) only inside the selection."""
        if self.selection is None:
            return img
        out = img.copy()
        p = QPainter(out)
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mask = self.selection.copy(QRect(at, img.size()))
        alpha = as_alpha(mask)
        p.drawImage(0, 0, alpha)
        p.end()
        return out

    def _apply(self, rect: QRect) -> None:
        """Redo ``rect`` of the working layer: the original with the stroke
        buffer on it."""
        b = self.brush
        p = QPainter(self.work)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(rect.topLeft(), self.original, rect)
        part = self._masked(self.buffer.copy(rect), rect.topLeft())
        if b.mode == "erase":
            p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
        elif self.alpha_lock:
            p.setCompositionMode(QPainter.CompositionMode_SourceAtop)
        else:
            p.setCompositionMode(COMPOSE.get(b.blend, COMPOSE["normal"]))
        p.setOpacity(1.0 if b.build_up else max(0.0, min(1.0, self.opacity)))
        p.drawImage(rect.topLeft(), part)
        p.end()

    def _smudge(self, mirror: int, x: float, y: float, d: float, angle: float,
                pressure: float) -> None:
        b = self.brush
        rect = self._dab_rect(x, y, d)
        under = self.work.copy(rect)
        carry = self._carry.get(mirror)
        if carry is None or carry.size() != under.size():
            self._carry[mirror] = under
            return
        strength = b.wet * (0.35 + 0.65 * pressure) * self.opacity
        mask_tip, at = self._dab_image(d, QColor(255, 255, 255), 1.0, angle,
                                       QPointF(x, y))
        moved = carry.copy()
        p = QPainter(moved)
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawImage(0, 0, mask_tip)
        p.end()
        moved = self._masked(moved, at)
        p = QPainter(self.work)
        if self.alpha_lock:
            p.setCompositionMode(QPainter.CompositionMode_SourceAtop)
        p.setOpacity(max(0.0, min(1.0, strength)))
        p.drawImage(at, moved)
        p.end()
        # the tip picks up some of what's here for the next step
        p = QPainter(carry)
        p.setOpacity(max(0.0, min(1.0, 1.0 - b.wet * 0.9)))
        p.drawImage(0, 0, self.work, rect.x(), rect.y(), rect.width(), rect.height())
        p.end()

    def _blur(self, x: float, y: float, d: float, angle: float, pressure: float) -> None:
        import cv2
        b = self.brush
        rect = self._dab_rect(x, y, d).intersected(self.doc.rect())
        if rect.width() < 3 or rect.height() < 3:
            return
        part = self.work.copy(rect)
        arr = qimage_array(part).astype(np.float32)
        k = max(3, int(d * 0.12) | 1)
        blurred = cv2.GaussianBlur(arr, (k, k), 0)
        out = QImage(np.ascontiguousarray(np.clip(blurred, 0, 255).astype(np.uint8)).data,
                     rect.width(), rect.height(), rect.width() * 4, FORMAT).copy()
        mask_tip, at = self._dab_image(d, QColor(255, 255, 255), 1.0, angle, QPointF(x, y))
        off = QPoint(at.x() - rect.x(), at.y() - rect.y())
        p = QPainter(out)
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawImage(off, mask_tip)
        p.end()
        out = self._masked(out, rect.topLeft())
        p = QPainter(self.work)
        p.setOpacity(max(0.0, min(1.0, b.wet * (0.4 + 0.6 * pressure) * self.opacity)))
        p.drawImage(rect.topLeft(), out)
        p.end()

    # ------------------------------------------------------------ results
    def take_dirty(self) -> QRect:
        """What changed since the last call (to redraw just that)."""
        r, self._new = self._new, QRect()
        return r

    def preview(self) -> QImage:
        return self.work

    def commit(self, label: str = "") -> QRect:
        """Put the stroke on the layer: one undo step."""
        r = self.dirty.intersected(self.doc.rect())
        if r.isEmpty():
            return r
        self.doc.push_region(self.index, r, self.original.copy(r),
                             label or self.brush.name)
        self.layer.image = self.work
        self.doc.dirty = True
        return r

    # ------------------------------------------------------------ QuickShape
    def quickshape(self) -> Optional[str]:
        """Hold the pen still at the end of a line: it becomes a straight line,
        or an ellipse when it closes. Returns "line", "ellipse" or None."""
        pts = [(x, y) for x, y, _ in self._raw]
        if len(pts) < 4:
            return None
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        length = math.hypot(x1 - x0, y1 - y0)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        pressure = sum(p for _, _, p in self._raw) / len(self._raw)
        if length > 10:
            dev = max(abs((y1 - y0) * px - (x1 - x0) * py + x1 * y0 - y1 * x0) / length
                      for px, py in pts)
            if dev < max(4.0, length * 0.06):
                self._redo_along([(x0, y0), (x1, y1)], pressure)
                return "line"
        if diag > 20 and length < diag * 0.22:
            cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
            rx, ry = (max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2
            if abs(rx - ry) < max(rx, ry) * 0.15:      # nearly round: a circle
                rx = ry = (rx + ry) / 2
            n = max(24, int(2 * math.pi * max(rx, ry) / 4))
            path = [(cx + rx * math.cos(2 * math.pi * i / n),
                     cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
            self._redo_along(path, pressure)
            return "ellipse"
        return None

    def _redo_along(self, path: list[tuple[float, float]], pressure: float) -> None:
        """Start the stroke again along ``path``."""
        self.work = self.original.copy()
        if self.buffer is not None:
            self.buffer.fill(Qt.transparent)
        self._new = self._new.united(self.dirty)
        self._carry.clear()
        self._left = 0.0
        self._travel = 1e9                      # no taper on a shape
        self.points.clear()
        smoothing, self.brush = self.brush.smoothing, self.brush.copy(smoothing=0)
        self._tip_at(path[0][0], path[0][1], pressure)
        for a, b in zip(path, path[1:]):
            self._segment((a[0], a[1], pressure), (b[0], b[1], pressure))
        self.brush = self.brush.copy(smoothing=smoothing)
        self._raw = [(x, y, pressure) for x, y in path]


def stroke_along(doc: Document, brush: Brush, colour: QColor, path: list[tuple[float, float]],
                 pressure: float = 1.0, **kw) -> Stroke:
    """A stroke drawn along ``path`` (shapes, previews)."""
    s = Stroke(doc, brush.copy(smoothing=0), colour, **kw)
    for x, y in path:
        s.add(x, y, pressure)
    s.end()
    return s


def preview_stroke(brush: Brush, colour: QColor, width: int = 220, height: int = 56,
                   background: Optional[QColor] = None) -> QImage:
    """A small picture of the brush: an S-shaped stroke growing in pressure."""
    if background is None and brush.blend in ("add", "screen"):
        background = QColor("#1d1f2b")                  # glows show on dark
    doc = Document(width, height, background or QColor(0, 0, 0, 0))
    size = min(brush.size, height * 0.42)
    pts = []
    for i in range(61):
        t = i / 60
        x = 12 + t * (width - 24)
        y = height / 2 + math.sin(t * math.pi * 2) * height * 0.22
        pts.append((x, y, 0.15 + 0.85 * math.sin(t * math.pi)))
    if brush.mode == "erase":                           # something to rub out
        band = Brush("band", size=height * 0.8, hardness=1, spacing=0.05,
                     pressure_size=False, smoothing=0)
        s = Stroke(doc, band, QColor("#9aa4b8"), seed=1)
        s.add(4, height / 2, 1.0)
        s.add(width - 4, height / 2, 1.0)
        s.end()
        s.commit()
    if brush.mode in ("smudge", "blur"):               # something to smudge first
        under = brush.copy(mode="paint", name="under", shape="round", grain="", wet=0,
                           blend="normal", size=height * 0.35, flow=1, opacity=1,
                           pressure_size=False, jitter_size=0, count=1, scatter=0)
        s = Stroke(doc, under, QColor("#4a7bd0"), seed=1)
        for x, _, _ in pts:
            s.add(x, height * 0.5 + (x % 30 - 15) * 0.5, 1.0)
        s.end()
        s.commit()
        colour = QColor("#e8b04a")
        s = Stroke(doc, under, colour, seed=2)
        for x, _, _ in pts[::2]:
            s.add(x, height * 0.3, 1.0)
        s.end()
        s.commit()
    s = Stroke(doc, brush, colour, size=size, seed=3)
    for x, y, p in pts:
        s.add(x, y, p)
    s.end()
    s.commit()
    return doc.composite()
