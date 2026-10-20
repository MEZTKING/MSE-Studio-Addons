"""A painting: its size, its layers (each a full-size picture with an
opacity, a blend mode and locks) and the steps you can undo.

Pictures are QImage ARGB32_Premultiplied, the size of the painting. Undo
keeps only the part of a layer a step changed, so a long session stays
light."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter

FORMAT = QImage.Format_ARGB32_Premultiplied

# key: (label, Qt composition mode, OpenRaster composite-op)
BLENDS = {
    "normal": ("Normal", QPainter.CompositionMode_SourceOver, "svg:src-over"),
    "multiply": ("Multiply", QPainter.CompositionMode_Multiply, "svg:multiply"),
    "screen": ("Screen", QPainter.CompositionMode_Screen, "svg:screen"),
    "overlay": ("Overlay", QPainter.CompositionMode_Overlay, "svg:overlay"),
    "soft-light": ("Soft light", QPainter.CompositionMode_SoftLight, "svg:soft-light"),
    "hard-light": ("Hard light", QPainter.CompositionMode_HardLight, "svg:hard-light"),
    "darken": ("Darken", QPainter.CompositionMode_Darken, "svg:darken"),
    "lighten": ("Lighten", QPainter.CompositionMode_Lighten, "svg:lighten"),
    "color-dodge": ("Colour dodge", QPainter.CompositionMode_ColorDodge, "svg:color-dodge"),
    "color-burn": ("Colour burn", QPainter.CompositionMode_ColorBurn, "svg:color-burn"),
    "add": ("Add (glow)", QPainter.CompositionMode_Plus, "svg:plus"),
    "difference": ("Difference", QPainter.CompositionMode_Difference, "svg:difference"),
    "exclusion": ("Exclusion", QPainter.CompositionMode_Exclusion, "svg:exclusion"),
}
UNDO_BYTES = 700 * 1024 * 1024        # undo steps kept up to about this much memory


def as_alpha(mask: QImage) -> QImage:
    """A Grayscale8 mask (255 = fully on) as an Alpha8 picture to paint with.
    Qt's own conversion would make every pixel solid."""
    if mask.format() == QImage.Format_Alpha8:
        return mask
    g = mask if mask.format() == QImage.Format_Grayscale8 else \
        mask.convertToFormat(QImage.Format_Grayscale8)
    return QImage(g.constBits(), g.width(), g.height(), g.bytesPerLine(),
                  QImage.Format_Alpha8).copy()


def blank(w: int, h: int, colour: Optional[QColor] = None) -> QImage:
    img = QImage(max(1, w), max(1, h), FORMAT)
    img.fill(colour if colour is not None else Qt.transparent)
    return img


@dataclass
class Layer:
    name: str
    image: QImage
    opacity: float = 1.0
    blend: str = "normal"
    visible: bool = True
    locked: bool = False            # can't be painted on or changed
    alpha_lock: bool = False        # paint only where there's paint already
    clip: bool = False              # a clipping mask: shows only on the layer below

    def copy(self) -> "Layer":
        return Layer(self.name, self.image.copy(), self.opacity, self.blend, self.visible,
                     self.locked, self.alpha_lock, self.clip)

    def props(self) -> dict:
        return {"name": self.name, "opacity": self.opacity, "blend": self.blend,
                "visible": self.visible, "locked": self.locked,
                "alpha_lock": self.alpha_lock, "clip": self.clip}


@dataclass
class Step:
    """One thing to undo: a part of one layer (``rect`` + its pixels before),
    or the whole layer stack (adding, deleting, moving layers)."""
    label: str
    layer: int = -1
    rect: QRect = field(default_factory=QRect)
    pixels: Optional[QImage] = None
    stack: Optional[list] = None            # [Layer copies] and the active index
    active: int = 0

    def size(self) -> int:
        if self.pixels is not None:
            return self.pixels.sizeInBytes()
        return sum(lay.image.sizeInBytes() for lay in self.stack or [])


class Document:
    def __init__(self, width: int, height: int, background: Optional[QColor] = None):
        self.width, self.height = int(width), int(height)
        bg = background if background is not None else QColor("white")
        self.layers: list[Layer] = [Layer("Background", blank(self.width, self.height, bg),
                                          locked=False)]
        self.active = 0
        self._undo: list[Step] = []
        self._redo: list[Step] = []
        self.dirty = False

    # ------------------------------------------------------------ layers
    @property
    def layer(self) -> Layer:
        return self.layers[self.active]

    def rect(self) -> QRect:
        return QRect(0, 0, self.width, self.height)

    def add_layer(self, name: str = "", image: Optional[QImage] = None,
                  fit: bool = True) -> Layer:
        """A new layer above the active one; ``image`` is fitted into the
        painting (covering it) or put at the top left as it is."""
        self.snapshot_stack("New layer")
        img = blank(self.width, self.height)
        if image is not None and not image.isNull():
            p = QPainter(img)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            if fit and (image.width() != self.width or image.height() != self.height):
                src = image.scaled(self.width, self.height, Qt.KeepAspectRatioByExpanding,
                                   Qt.SmoothTransformation)
                p.drawImage(QPoint((self.width - src.width()) // 2,
                                   (self.height - src.height()) // 2), src)
            else:
                p.drawImage(0, 0, image)
            p.end()
        lay = Layer(name or self._new_name(), img)
        self.layers.insert(self.active + 1, lay)
        self.active += 1
        self.dirty = True
        return lay

    def _new_name(self) -> str:
        names = {lay.name for lay in self.layers}
        n = len(self.layers)
        while f"Layer {n}" in names:
            n += 1
        return f"Layer {n}"

    def duplicate_layer(self) -> None:
        self.snapshot_stack("Duplicate layer")
        lay = self.layer.copy()
        lay.name = f"{lay.name} copy"
        self.layers.insert(self.active + 1, lay)
        self.active += 1
        self.dirty = True

    def delete_layer(self) -> None:
        if len(self.layers) <= 1:
            self.clear_layer()
            return
        self.snapshot_stack("Delete layer")
        del self.layers[self.active]
        self.active = max(0, self.active - 1)
        self.dirty = True

    def move_layer(self, step: int) -> None:
        i, j = self.active, self.active + step
        if not 0 <= j < len(self.layers):
            return
        self.snapshot_stack("Move layer")
        self.layers[i], self.layers[j] = self.layers[j], self.layers[i]
        self.active = j
        self.dirty = True

    def move_layer_to(self, src: int, dst: int) -> None:
        if src == dst or not (0 <= src < len(self.layers)) or not 0 <= dst < len(self.layers):
            return
        self.snapshot_stack("Move layer")
        lay = self.layers.pop(src)
        self.layers.insert(dst, lay)
        self.active = dst
        self.dirty = True

    def merge_down(self) -> None:
        if self.active == 0:
            return
        self.snapshot_stack("Merge down")
        top, below = self.layers[self.active], self.layers[self.active - 1]
        merged = below.image.copy()
        p = QPainter(merged)
        if top.clip:
            clipped = self._clipped(top, below.image)
            p.setOpacity(top.opacity)
            p.setCompositionMode(BLENDS.get(top.blend, BLENDS["normal"])[1])
            p.drawImage(0, 0, clipped)
        else:
            p.setOpacity(top.opacity)
            p.setCompositionMode(BLENDS.get(top.blend, BLENDS["normal"])[1])
            p.drawImage(0, 0, top.image)
        p.end()
        below.image = merged
        del self.layers[self.active]
        self.active -= 1
        self.dirty = True

    def flatten(self) -> None:
        self.snapshot_stack("Flatten")
        flat = self.composite()
        self.layers = [Layer("Background", flat)]
        self.active = 0
        self.dirty = True

    def clear_layer(self) -> None:
        self.snapshot_region(self.rect(), "Clear layer")
        self.layer.image.fill(Qt.transparent)
        self.dirty = True

    def set_props(self, label: str = "Layer", **props) -> None:
        """Change the active layer's name, opacity, blend, visible, locks…"""
        self.snapshot_stack(label, pixels=False)
        for k, v in props.items():
            setattr(self.layer, k, v)
        self.dirty = True

    def resize_canvas(self, width: int, height: int, scale: bool) -> None:
        """A new size: every layer scaled to it, or kept and cropped/extended
        around the centre."""
        self.snapshot_stack("Canvas size")
        for lay in self.layers:
            img = blank(width, height)
            p = QPainter(img)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            if scale:
                p.drawImage(img.rect(), lay.image)
            else:
                p.drawImage(QPoint((width - self.width) // 2, (height - self.height) // 2),
                            lay.image)
            p.end()
            lay.image = img
        self.width, self.height = width, height
        self.dirty = True

    def flip_canvas(self, horizontal: bool = True) -> None:
        self.snapshot_stack("Flip canvas")
        for lay in self.layers:
            lay.image = lay.image.mirrored(horizontal, not horizontal)
        self.dirty = True

    # ------------------------------------------------------------ the picture
    def _clipped(self, lay: Layer, base: QImage, rect: Optional[QRect] = None) -> QImage:
        """``lay`` only where ``base`` has paint (a clipping mask)."""
        r = rect or self.rect()
        out = lay.image.copy(r)
        p = QPainter(out)
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawImage(0, 0, base, r.x(), r.y(), r.width(), r.height())
        p.end()
        return out

    def composite(self, rect: Optional[QRect] = None, layers: Optional[list] = None,
                  replace: Optional[dict] = None) -> QImage:
        """The visible picture (of ``rect``): the layers bottom to top with
        their opacity and blend; clipping masks show only on the layer below
        them. ``replace``: {layer index: picture to use instead} (a stroke in
        progress)."""
        r = (rect or self.rect()).intersected(self.rect())
        out = blank(r.width(), r.height())
        if r.isEmpty():
            return out
        stack = self.layers if layers is None else layers
        p = QPainter(out)
        base: Optional[QImage] = None         # the layer clipping masks clip to
        for i, lay in enumerate(stack):
            img = (replace or {}).get(i, lay.image)
            if not lay.clip:
                base = img
            if not lay.visible:
                continue
            p.setOpacity(lay.opacity)
            p.setCompositionMode(BLENDS.get(lay.blend, BLENDS["normal"])[1])
            if lay.clip and base is not None and base is not img:
                clipped = img.copy(r)
                q = QPainter(clipped)
                q.setCompositionMode(QPainter.CompositionMode_DestinationIn)
                q.drawImage(0, 0, base, r.x(), r.y(), r.width(), r.height())
                q.end()
                p.drawImage(0, 0, clipped)
            else:
                p.drawImage(0, 0, img, r.x(), r.y(), r.width(), r.height())
        p.end()
        return out

    def flattened(self, background: Optional[QColor] = None) -> QImage:
        img = self.composite()
        if background is None:
            return img
        out = blank(self.width, self.height, background)
        p = QPainter(out)
        p.drawImage(0, 0, img)
        p.end()
        return out

    # ------------------------------------------------------------ undo
    def snapshot_region(self, rect: QRect, label: str = "Paint", layer: int = -1) -> None:
        """Keep the part of a layer about to change, to undo it."""
        i = self.active if layer < 0 else layer
        r = rect.intersected(self.rect())
        if r.isEmpty():
            return
        self._push(Step(label, i, r, self.layers[i].image.copy(r)))

    def push_region(self, layer: int, rect: QRect, before: QImage, label: str) -> None:
        """An undo step for a change already made (a stroke kept the layer's
        pixels from before it)."""
        if not rect.isEmpty():
            self._push(Step(label, layer, QRect(rect), before))

    def snapshot_stack(self, label: str, pixels: bool = True) -> None:
        stack = [lay.copy() if pixels else Layer(lay.name, lay.image, lay.opacity, lay.blend,
                                                 lay.visible, lay.locked, lay.alpha_lock,
                                                 lay.clip)
                 for lay in self.layers]
        self._push(Step(label, stack=stack, active=self.active))

    def _push(self, step: Step) -> None:
        self._undo.append(step)
        self._redo.clear()
        total = sum(s.size() for s in self._undo)
        while len(self._undo) > 1 and total > UNDO_BYTES:
            total -= self._undo.pop(0).size()

    def _swap(self, step: Step) -> Step:
        """Put ``step`` back and return the step that undoes that."""
        if step.stack is not None:
            back = Step(step.label, stack=self.layers, active=self.active)
            self.layers = step.stack
            self.active = min(step.active, len(self.layers) - 1)
            self.width = self.layers[0].image.width()
            self.height = self.layers[0].image.height()
            return back
        lay = self.layers[min(step.layer, len(self.layers) - 1)]
        back = Step(step.label, step.layer, step.rect, lay.image.copy(step.rect))
        p = QPainter(lay.image)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(step.rect.topLeft(), step.pixels)
        p.end()
        return back

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> Optional[str]:
        if not self._undo:
            return None
        step = self._undo.pop()
        self._redo.append(self._swap(step))
        self.dirty = True
        return step.label

    def redo(self) -> Optional[str]:
        if not self._redo:
            return None
        step = self._redo.pop()
        self._undo.append(self._swap(step))
        self.dirty = True
        return step.label

    def history(self) -> list[str]:
        return [s.label for s in self._undo]
