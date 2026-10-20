"""The painting tools' work (no widgets): selections, filling an area,
gradients, liquify and finding where a layer has paint.

A selection is a mask (Grayscale8: 255 inside, soft edges in between) and
the outline drawn around it."""
from __future__ import annotations

import math
from typing import Optional

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter, QPainterPath,
                           QRadialGradient)

from .doc import FORMAT, Document, as_alpha, blank
from .engine import qimage_array

GREY = QImage.Format_Grayscale8


def grey_array(img: QImage) -> np.ndarray:
    ptr = img.bits()
    return np.ndarray((img.height(), img.bytesPerLine()), np.uint8, buffer=ptr)[:, :img.width()]


def grey_image(a: np.ndarray) -> QImage:
    a = np.ascontiguousarray(a.astype(np.uint8))
    h, w = a.shape
    return QImage(a.data, w, h, w, GREY).copy()


def path_outline(mask: np.ndarray) -> QPainterPath:
    """The outline of a mask (where it's at least half on)."""
    path = QPainterPath()
    contours, _ = cv2.findContours((mask >= 128).astype(np.uint8), cv2.RETR_LIST,
                                   cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        if len(c) < 2:
            continue
        pts = c[:, 0, :]
        path.moveTo(float(pts[0][0]), float(pts[0][1]))
        for x, y in pts[1:]:
            path.lineTo(float(x), float(y))
        path.closeSubpath()
    return path


class Selection:
    """What's selected: painting, filling and adjusting stay inside it."""

    def __init__(self, width: int, height: int):
        self.width, self.height = width, height
        self.mask: Optional[QImage] = None
        self.outline = QPainterPath()

    def active(self) -> bool:
        return self.mask is not None

    def clear(self) -> None:
        self.mask = None
        self.outline = QPainterPath()

    def _set(self, a: np.ndarray, mode: str = "replace") -> None:
        if mode != "replace" and self.mask is not None:
            old = grey_array(self.mask).astype(np.int16)
            if mode == "add":
                a = np.maximum(old, a)
            elif mode == "subtract":
                a = np.clip(old - a.astype(np.int16), 0, 255)
            elif mode == "intersect":
                a = np.minimum(old, a)
        a = a.astype(np.uint8)
        if not a.any():
            self.clear()
            return
        self.mask = grey_image(a)
        self.outline = path_outline(a)

    def set_path(self, path: QPainterPath, mode: str = "replace") -> None:
        img = QImage(self.width, self.height, GREY)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillPath(path, QColor(255, 255, 255))
        p.end()
        self._set(grey_array(img).copy(), mode)

    def set_rect(self, rect: QRectF, ellipse: bool = False, mode: str = "replace") -> None:
        path = QPainterPath()
        if ellipse:
            path.addEllipse(rect)
        else:
            path.addRect(rect)
        self.set_path(path, mode)

    def set_mask(self, a: np.ndarray, mode: str = "replace") -> None:
        self._set(a, mode)

    def select_all(self) -> None:
        self._set(np.full((self.height, self.width), 255, np.uint8))

    def invert(self) -> None:
        if self.mask is None:
            self.select_all()
            return
        self._set(255 - grey_array(self.mask))

    def feather(self, radius: float) -> None:
        if self.mask is None or radius <= 0:
            return
        k = int(radius * 2) | 1
        self._set(cv2.GaussianBlur(grey_array(self.mask).copy(), (k, k), radius / 2))

    def grow(self, px: int) -> None:
        if self.mask is None or px == 0:
            return
        a = grey_array(self.mask).copy()
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (abs(px) * 2 + 1,) * 2)
        self._set(cv2.dilate(a, kernel) if px > 0 else cv2.erode(a, kernel))

    def from_alpha(self, img: QImage) -> None:
        self._set(qimage_array(img)[..., 3].copy())

    def bounds(self) -> QRect:
        if self.mask is None:
            return QRect(0, 0, self.width, self.height)
        a = grey_array(self.mask)
        ys, xs = np.nonzero(a)
        if not len(xs):
            return QRect()
        return QRect(int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1),
                     int(ys.max() - ys.min() + 1))


def paint_bounds(img: QImage) -> QRect:
    """Where a layer has paint (an empty rect when it has none)."""
    a = qimage_array(img)[..., 3]
    ys, xs = np.nonzero(a)
    if not len(xs):
        return QRect()
    return QRect(int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1),
                 int(ys.max() - ys.min() + 1))


# ------------------------------------------------------------------ filling
def flood_mask(img: QImage, x: int, y: int, tolerance: int = 32, contiguous: bool = True,
               grow: int = 1) -> np.ndarray:
    """The area around (x, y) of colours within ``tolerance`` (0–255) of the
    one clicked – or all such colours when not ``contiguous`` – as a mask,
    grown a little so no thin line stays between it and the outline."""
    a = qimage_array(img)
    h, w = a.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return np.zeros((h, w), np.uint8)
    bgra = np.ascontiguousarray(a)
    if contiguous:
        mask = np.zeros((h + 2, w + 2), np.uint8)
        flags = 4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE
        lo = (tolerance,) * 4
        img3 = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
        alpha = bgra[..., 3]
        # see-through areas count as one colour, whatever's hidden in them
        img3 = np.where(alpha[..., None] < 8, 0, img3).astype(np.uint8)
        cv2.floodFill(img3, mask, (int(x), int(y)), 0, lo[:3], lo[:3], flags)
        out = mask[1:-1, 1:-1]
        if alpha[y, x] < 8:
            out = np.where(alpha < 8 + tolerance, out, 0).astype(np.uint8)
        else:
            out = np.where(np.abs(alpha.astype(np.int16) - int(alpha[y, x])) <= tolerance,
                           out, 0).astype(np.uint8)
    else:
        ref = bgra[y, x].astype(np.int16)
        diff = np.abs(bgra.astype(np.int16) - ref).max(axis=2)
        out = np.where(diff <= tolerance, 255, 0).astype(np.uint8)
    if grow > 0 and out.any():
        out = cv2.dilate(out, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                        (grow * 2 + 1,) * 2))
    return out


def fill_mask(doc: Document, mask: np.ndarray, colour: QColor,
              selection: Optional[Selection] = None, label: str = "Fill") -> QRect:
    """Fill ``mask`` on the active layer with ``colour`` (inside the selection,
    keeping the layer's alpha lock). One undo step."""
    if selection is not None and selection.active():
        mask = np.minimum(mask, grey_array(selection.mask))
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return QRect()
    r = QRect(int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1),
              int(ys.max() - ys.min() + 1))
    lay = doc.layer
    doc.snapshot_region(r, label)
    sub = np.ascontiguousarray(mask[r.y():r.bottom() + 1, r.x():r.right() + 1])
    paint = blank(r.width(), r.height())
    p = QPainter(paint)
    p.fillRect(paint.rect(), colour)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    p.drawImage(0, 0, as_alpha(grey_image(sub)))
    p.end()
    p = QPainter(lay.image)
    if lay.alpha_lock:
        p.setCompositionMode(QPainter.CompositionMode_SourceAtop)
    p.drawImage(r.topLeft(), paint)
    p.end()
    doc.dirty = True
    return r


# ------------------------------------------------------------------ gradients
def paint_gradient(img: QImage, a: QPointF, b: QPointF, c1: QColor, c2: QColor,
                   radial: bool = False, selection: Optional[Selection] = None,
                   alpha_lock: bool = False) -> QRect:
    """Paint a gradient from ``a`` to ``b`` on ``img`` (inside the selection)."""
    sel = selection is not None and selection.active()
    r = selection.bounds() if sel else img.rect()
    if r.isEmpty():
        return r
    if radial:
        g = QRadialGradient(a, max(1.0, math.hypot(b.x() - a.x(), b.y() - a.y())))
    else:
        g = QLinearGradient(a, b)
    g.setColorAt(0, c1)
    g.setColorAt(1, c2)
    paint = blank(img.width(), img.height())
    p = QPainter(paint)
    p.fillRect(r, g)
    if sel:
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawImage(0, 0, as_alpha(selection.mask))
    p.end()
    p = QPainter(img)
    if alpha_lock:
        p.setCompositionMode(QPainter.CompositionMode_SourceAtop)
    p.drawImage(r.topLeft(), paint, r)
    p.end()
    return r


def gradient(doc: Document, a: QPointF, b: QPointF, c1: QColor, c2: QColor,
             radial: bool = False, selection: Optional[Selection] = None) -> QRect:
    """A gradient on the active layer (or the selection). One undo step."""
    r = selection.bounds() if selection is not None and selection.active() else doc.rect()
    if r.isEmpty():
        return r
    doc.snapshot_region(r, "Gradient")
    paint_gradient(doc.layer.image, a, b, c1, c2, radial, selection, doc.layer.alpha_lock)
    doc.dirty = True
    return r


# ------------------------------------------------------------------ liquify
LIQUIFY = {"push": "Push", "twirl": "Twirl", "pinch": "Pinch", "expand": "Expand",
           "smooth": "Reconstruct (undo it here)"}


def liquify(work: QImage, original: QImage, mode: str, centre: QPointF, delta: QPointF,
            radius: float, strength: float) -> QRect:
    """One step of liquify on ``work`` (the layer being changed) around
    ``centre``: push along ``delta``, twirl, pinch, expand, or bring back
    ``original`` there."""
    r = int(max(4, radius))
    x0, y0 = int(centre.x()) - r, int(centre.y()) - r
    rect = QRect(x0, y0, 2 * r + 1, 2 * r + 1).intersected(work.rect())
    if rect.width() < 3 or rect.height() < 3:
        return QRect()
    src = np.ascontiguousarray(qimage_array(work)[rect.y():rect.bottom() + 1,
                                                 rect.x():rect.right() + 1]).copy()
    h, w = src.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = centre.x() - rect.x(), centre.y() - rect.y()
    dx, dy = xs - cx, ys - cy
    dist = np.sqrt(dx * dx + dy * dy)
    f = np.clip(1 - dist / r, 0, 1) ** 2 * strength
    if mode == "push":
        mx, my = xs - delta.x() * f, ys - delta.y() * f
    elif mode == "twirl":
        ang = f * 0.25
        mx = cx + dx * np.cos(ang) - dy * np.sin(ang)
        my = cy + dx * np.sin(ang) + dy * np.cos(ang)
    elif mode in ("pinch", "expand"):
        k = 1 + (0.12 if mode == "pinch" else -0.12) * f
        mx, my = cx + dx * k, cy + dy * k
    else:                                                    # bring back the original
        orig = qimage_array(original)[rect.y():rect.bottom() + 1, rect.x():rect.right() + 1]
        out = (src.astype(np.float32) * (1 - f[..., None] * 0.5) +
               orig.astype(np.float32) * f[..., None] * 0.5)
        qimage_array(work)[rect.y():rect.bottom() + 1, rect.x():rect.right() + 1] = \
            np.clip(out, 0, 255).astype(np.uint8)
        return rect
    moved = cv2.remap(src, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_REFLECT)
    qimage_array(work)[rect.y():rect.bottom() + 1, rect.x():rect.right() + 1] = moved
    return rect


# ------------------------------------------------------------------ picking a colour
def pick(img: QImage, x: int, y: int, radius: int = 0) -> QColor:
    """The colour at (x, y) – averaged over ``radius`` – without its alpha
    premultiplied in."""
    if not (0 <= x < img.width() and 0 <= y < img.height()):
        return QColor()
    if radius <= 0:
        c = img.pixelColor(x, y)
    else:
        part = img.copy(QRect(x - radius, y - radius, radius * 2 + 1, radius * 2 + 1))
        c = part.scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixelColor(0, 0)
    c.setAlpha(255)
    return c


def stamp_image(doc: Document, image: QImage, at: QPointF, label: str = "Paste") -> None:
    """A picture as a new layer, placed at ``at`` (its top left)."""
    lay = doc.add_layer(label)
    p = QPainter(lay.image)
    p.drawImage(at, image)
    p.end()


def selection_copy(doc: Document, selection: Selection, merged: bool = False) -> QImage:
    """The selected part of the layer (or of the whole picture) as a picture
    the size of the painting, transparent outside the selection."""
    src = doc.composite() if merged else doc.layer.image
    out = src.copy()
    if selection.active():
        p = QPainter(out)
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawImage(0, 0, as_alpha(selection.mask))
        p.end()
    return out


def clear_selection_area(doc: Document, selection: Selection, label: str = "Clear") -> None:
    r = selection.bounds()
    if r.isEmpty():
        return
    doc.snapshot_region(r, label)
    p = QPainter(doc.layer.image)
    p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
    if selection.active():
        p.drawImage(0, 0, as_alpha(selection.mask))
    else:
        p.fillRect(r, QColor(0, 0, 0, 255))
    p.end()
    doc.dirty = True


def _unused(_: FORMAT) -> None:            # keep the import for type readers
    return None
