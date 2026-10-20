"""Trace a picture into layers to paint your own version over: clean ink
lines, flat areas of colour and simple shading, each on a layer of its own,
with the picture kept underneath – faint and locked – as a guide.

``trace`` uses no widgets, so it runs in a ``Job``; ``TraceDialog`` shows the
settings with a preview of the result. Pictures are QImage in ``FORMAT``; the
work is done with NumPy and OpenCV."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout)

from .adjust import from_array, to_array
from .doc import FORMAT, Layer

PREVIEW_SIDE = 560
SAMPLES = 60_000                # pixels the colours are chosen from
SOURCES = [("layer", "The layer you're on"), ("all", "Everything you see"),
           ("file", "A picture file…")]


@dataclass
class TraceOptions:
    detail: int = 5             # 1..10: more finds fainter lines too
    thickness: int = 2          # 1..8 px at full size
    colours: int = 8            # 2..24 flat colours
    smooth: int = 5             # 0..10: how much small detail the colour areas lose
    shading: int = 3            # 0 = none, else 2..5 steps of shadow
    lines: bool = True
    flat: bool = True
    keep_picture: bool = True


try:                            # Stop in MSE Studio is then heard as stopping
    from mse_studio.pipeline.common import Cancelled
except ImportError:             # pragma: no cover - outside MSE Studio
    class Cancelled(Exception):
        pass


# ------------------------------------------------------------------ the work
def fit(img: QImage, w: int, h: int) -> QImage:
    """``img`` covering a ``w`` × ``h`` painting (centred, cut to fit)."""
    img = img.convertToFormat(FORMAT)
    if img.width() == w and img.height() == h:
        return img
    src = img.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QImage(w, h, FORMAT)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.drawImage(QPoint((w - src.width()) // 2, (h - src.height()) // 2), src)
    p.end()
    return out


def _step(progress, cancel, k: int, total: int, text: str) -> None:
    if cancel is not None and getattr(cancel, "cancelled", False):
        raise Cancelled()
    if progress is not None:
        progress(k, total, text)


def _outlines(labels: np.ndarray, centres: np.ndarray, solid: np.ndarray,
              o: TraceOptions) -> np.ndarray:
    """Lines where one flat colour meets another – closed shapes, like a
    colouring book. At low detail only colours far apart get a line."""
    dist = np.sqrt(((centres[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2))
    need = 6.0 + 4.5 * (10 - o.detail)                # Lab distance (0..255 scale)
    ink = np.zeros(labels.shape, np.float32)
    for a, b, sl_a, sl_b in ((labels[:, :-1], labels[:, 1:], np.s_[:, :-1], np.s_[:, 1:]),
                             (labels[:-1, :], labels[1:, :], np.s_[:-1, :], np.s_[1:, :])):
        edge = (a != b) & (dist[a, b] >= need)
        ink[sl_a][edge] = 1.0
        ink[sl_b][edge] = 1.0
    edge_of_paint = solid ^ cv2.erode(solid.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    ink[edge_of_paint] = 1.0                           # around see-through parts too
    ink[~solid] = 0.0
    return ink


def _details(gray: np.ndarray, solid: np.ndarray, o: TraceOptions, scale: float) -> np.ndarray:
    """Finer lines inside the shapes (folds, hair, texture): edges found as a
    difference of two blurs (an XDoG), specks dropped. None at low detail."""
    if o.detail <= 3:
        return np.zeros_like(gray)
    sigma = max(0.6, 1.2 * scale)
    g1 = cv2.GaussianBlur(gray, (0, 0), sigma)
    g2 = cv2.GaussianBlur(gray, (0, 0), sigma * 1.6)
    d = g1 - 0.985 * g2
    eps = -0.004 - 0.003 * (10 - o.detail)
    ink = np.clip((eps - d) * 120.0, 0.0, 1.0)
    ink[~solid] = 0.0
    on = (ink > 0.4).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(on, connectivity=8)
    small = max(6, int(40 * scale * scale * (11 - o.detail) / 6))
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= small
    return np.where(keep[labels], ink, 0.0).astype(np.float32)


def _ink(base: np.ndarray, o: TraceOptions, scale: float) -> np.ndarray:
    """The lines made as thick as asked, with soft edges."""
    ink = base
    t = max(1, round(o.thickness * scale)) - 1
    if t > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * t + 1, 2 * t + 1))
        ink = cv2.dilate(ink, k)
    return cv2.GaussianBlur(ink, (0, 0), 0.6)         # soft, not jagged


def _smoothed(rgb8: np.ndarray, o: TraceOptions, scale: float) -> np.ndarray:
    out = rgb8
    for _ in range(1 + o.smooth // 3):
        out = cv2.bilateralFilter(out, 9, 18 + 6 * o.smooth, max(2.0, (2 + o.smooth) * scale))
    if o.smooth:
        k = 2 * max(1, round(o.smooth * scale / 3)) + 1
        out = cv2.medianBlur(out, min(k, 9))
    return out


def _flat(rgb8: np.ndarray, solid: np.ndarray, o: TraceOptions, scale: float, progress,
          cancel) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(flat colours as RGB 0..1, each pixel's colour number, the colours in
    Lab, how much lighter each pixel is than its flat colour) – the picture's
    own colours, grouped into a few."""
    smooth = _smoothed(rgb8, o, scale)
    _step(progress, cancel, 2, 5, "Finding the colours")
    lab = cv2.cvtColor(smooth, cv2.COLOR_RGB2LAB).astype(np.float32)
    pts = lab[solid] if solid.any() else lab.reshape(-1, 3)
    rng = np.random.default_rng(0)
    if len(pts) > SAMPLES:
        pts = pts[rng.choice(len(pts), SAMPLES, replace=False)]
    k = max(2, min(int(o.colours), len(pts)))
    cv2.setRNGSeed(0)
    _c, _l, centres = cv2.kmeans(np.ascontiguousarray(pts, np.float32), k, None,
                                 (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5),
                                 3, cv2.KMEANS_PP_CENTERS)
    h, w = lab.shape[:2]
    flat_lab = lab.reshape(-1, 3)
    labels = np.empty(h * w, np.uint8)
    for a in range(0, h * w, 400_000):              # nearest colour, a slice at a time
        part = flat_lab[a:a + 400_000]
        dist = ((part[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
        labels[a:a + 400_000] = dist.argmin(axis=1)
    labels = labels.reshape(h, w)
    if o.smooth:                                    # no specks of a stray colour
        labels = cv2.medianBlur(labels, 3 if o.smooth < 5 else 5)
    _step(progress, cancel, 3, 5, "Painting the flat colours")
    centre_lab = np.clip(centres, 0, 255).astype(np.uint8).reshape(1, -1, 3)
    centre_rgb = cv2.cvtColor(centre_lab, cv2.COLOR_LAB2RGB).reshape(-1, 3)
    rgb = centre_rgb[labels].astype(np.float32) / 255.0
    lightness = lab[:, :, 0] * (100.0 / 255.0)
    centre_l = centres[:, 0] * (100.0 / 255.0)
    return rgb, labels, centres, lightness - centre_l[labels]


def _shade(rel: np.ndarray, solid: np.ndarray, o: TraceOptions, scale: float) -> np.ndarray:
    """Shadow as a grey to multiply (1 = none): how much darker each part is
    than its flat colour, in a few clear steps."""
    rel = cv2.GaussianBlur(rel.astype(np.float32), (0, 0), max(1.0, 2.0 * scale))
    depth = np.clip(-rel / 30.0, 0.0, 1.0)            # 30 points darker = the deepest step
    steps = np.ceil(depth * o.shading - 0.35) / o.shading
    grey = 1.0 - 0.55 * np.clip(steps, 0.0, 1.0)
    grey[~solid] = 1.0
    return grey.astype(np.float32)


def trace(image: QImage, o: TraceOptions, progress: Optional[Callable] = None,
          cancel=None) -> dict:
    """The layers made from ``image``: {"lines", "colours", "shading"} as
    QImages (the ones asked for), the same size as ``image``."""
    a = to_array(image.convertToFormat(FORMAT))
    h, w = a.shape[:2]
    if not h or not w:
        return {}
    scale = max(h, w) / 1000.0
    solid = a[:, :, 3] > 0.5
    rgb8 = np.clip(a[:, :, :3] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out: dict = {}
    _step(progress, cancel, 0, 5, "Looking at the picture")
    labels = centres = None
    if o.flat or o.shading or o.lines:
        rgb, labels, centres, rel = _flat(rgb8, solid, o, scale, progress, cancel)
        alpha = solid.astype(np.float32)
        if o.flat:
            out["colours"] = from_array(np.dstack([rgb, alpha]))
        if o.shading:
            _step(progress, cancel, 4, 5, "Finding light and shadow")
            grey = _shade(rel, solid, o, scale)
            shadow = (grey < 0.999).astype(np.float32) * alpha
            out["shading"] = from_array(np.dstack([grey, grey, grey, shadow]))
    if o.lines:
        _step(progress, cancel, 4, 5, "Drawing the lines")
        gray = cv2.cvtColor(_smoothed(rgb8, TraceOptions(smooth=min(o.smooth, 3)), scale),
                            cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
        ink = _ink(np.maximum(_outlines(labels, centres, solid, o),
                              _details(gray, solid, o, scale)), o, scale)
        zero = np.zeros_like(ink)
        out["lines"] = from_array(np.dstack([zero, zero, zero, ink]))
    _step(progress, cancel, 5, 5, "Done")
    return out


def layers(image: QImage, traced: dict, o: TraceOptions, name: str = "picture") -> list[Layer]:
    """The new layers, bottom first: the guide, flat colours, shading, lines."""
    out = []
    if o.keep_picture:
        out.append(Layer(f"Guide: {name}", image.convertToFormat(FORMAT), opacity=0.35,
                         locked=True))
    if "colours" in traced:
        out.append(Layer("Flat colours", traced["colours"]))
    if "shading" in traced:
        out.append(Layer("Shading", traced["shading"], opacity=0.8, blend="multiply"))
    if "lines" in traced:
        out.append(Layer("Lines", traced["lines"]))
    return out


def has_paint(image: QImage) -> bool:
    """Something to trace: not see-through everywhere."""
    return bool((to_array(image.convertToFormat(FORMAT))[:, :, 3] > 0.5).any())


def preview_of(traced: dict, size) -> QImage:
    """What the layers look like together (on white)."""
    img = QImage(size, FORMAT)
    img.fill(Qt.white)
    p = QPainter(img)
    if "colours" in traced:
        p.drawImage(0, 0, traced["colours"])
    if "shading" in traced:
        p.setCompositionMode(QPainter.CompositionMode_Multiply)
        p.setOpacity(0.8)
        p.drawImage(0, 0, traced["shading"])
        p.setOpacity(1.0)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
    if "lines" in traced:
        p.drawImage(0, 0, traced["lines"])
    p.end()
    return img


# ------------------------------------------------------------------ the window
class TraceDialog(QDialog):
    """The tracing settings with a preview. After Accepted: ``source()`` is
    the picture to trace (fitted to the painting) and ``options()`` the
    settings."""

    DELAY_MS = 150

    def __init__(self, parent, layer_image: QImage, everything: QImage, width: int,
                 height: int):
        super().__init__(parent)
        self.setWindowTitle("Trace a picture")
        self.setMinimumWidth(900)
        self._w, self._h = width, height
        self._pictures = {"layer": layer_image, "all": everything}
        self._file_name = ""
        lay = QHBoxLayout(self)
        side = QVBoxLayout()
        hint = QLabel("Splits a picture into layers to paint your own version over: clean "
                      "ink lines, flat areas of colour and simple shading – with the picture "
                      "kept underneath, faint and locked, as a guide. Change, repaint or "
                      "hide any of them; the guide can be deleted when you're done.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        side.addWidget(hint)
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        self.source_box = QComboBox()
        for key, label in SOURCES:
            self.source_box.addItem(label, key)
        self.source_box.setToolTip("What to trace")
        self.source_box.activated.connect(self._source_chosen)
        grid.addWidget(QLabel("Trace"), 0, 0)
        grid.addWidget(self.source_box, 0, 1, 1, 2)
        o = TraceOptions()
        self.sliders: dict[str, QSlider] = {}
        rows = [("detail", "Line detail", 1, 10, o.detail,
                 "More finds the fainter lines too; less keeps only the main outlines"),
                ("thickness", "Line thickness", 1, 8, o.thickness, "How thick the ink lines are"),
                ("colours", "Colours", 2, 24, o.colours, "How many flat colours the picture "
                                                         "is split into"),
                ("smooth", "Simplify", 0, 10, o.smooth, "How much small detail the colour "
                                                        "areas lose"),
                ("shading", "Shadow steps", 0, 5, o.shading, "Steps of shadow on their own "
                                                             "layer (0 = none)")]
        for r, (key, label, lo, hi, value, tip) in enumerate(rows, 1):
            name = QLabel(label)
            name.setToolTip(tip)
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            s.setValue(value)
            s.setToolTip(tip)
            num = QLabel(str(value))
            num.setMinimumWidth(24)
            s.valueChanged.connect(num.setNum)
            s.valueChanged.connect(self._changed)
            grid.addWidget(name, r, 0)
            grid.addWidget(s, r, 1)
            grid.addWidget(num, r, 2)
            self.sliders[key] = s
        side.addLayout(grid)
        self.checks: dict[str, QCheckBox] = {}
        for key, label, tip in (("lines", "Ink lines", "A layer of black lines"),
                                ("flat", "Flat colours", "A layer of flat areas of colour"),
                                ("keep_picture", "Keep the picture as a guide",
                                 "The picture underneath at a third of its strength, locked")):
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.setToolTip(tip)
            cb.toggled.connect(self._changed)
            side.addWidget(cb)
            self.checks[key] = cb
        self.status = QLabel()
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        side.addWidget(self.status)
        side.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.ok = QPushButton("Make the layers")
        self.ok.setProperty("kind", "primary")
        self.ok.setDefault(True)
        self.ok.setToolTip("Trace the whole picture into new layers (takes a moment for a big one)")
        self.ok.clicked.connect(self.accept)
        buttons.addWidget(self.ok)
        side.addLayout(buttons)
        lay.addLayout(side, 1)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setMinimumSize(PREVIEW_SIDE, PREVIEW_SIDE)
        lay.addWidget(self.view, 1)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.DELAY_MS)
        self._timer.timeout.connect(self._update_preview)
        self._timer.start()

    # ---------------------------------------------------------- choices
    def options(self) -> TraceOptions:
        v = {k: s.value() for k, s in self.sliders.items()}
        return TraceOptions(detail=v["detail"], thickness=v["thickness"], colours=v["colours"],
                            smooth=v["smooth"], shading=v["shading"],
                            lines=self.checks["lines"].isChecked(),
                            flat=self.checks["flat"].isChecked(),
                            keep_picture=self.checks["keep_picture"].isChecked())

    def source_key(self) -> str:
        return self.source_box.currentData() or "layer"

    def source_name(self) -> str:
        key = self.source_key()
        return self._file_name if key == "file" else dict(SOURCES).get(key, "").lower()

    def source(self) -> QImage:
        """The picture to trace, the painting's size."""
        img = self._pictures.get(self.source_key())
        return fit(img, self._w, self._h) if img is not None and not img.isNull() else QImage()

    def use_file(self, path: str) -> bool:
        from . import files
        try:
            img = files.import_image(Path(path))
        except (OSError, ValueError) as e:
            self.status.setText(f"That picture can't be opened ({e}).")
            return False
        self._pictures["file"] = img
        self._file_name = Path(path).stem
        self.source_box.setCurrentIndex(self.source_box.findData("file"))
        self._changed()
        return True

    def _source_chosen(self, _i: int) -> None:
        if self.source_key() == "file":
            path, _ = QFileDialog.getOpenFileName(
                self, "Trace a picture", "", "Pictures (*.png *.jpg *.jpeg *.webp *.bmp *.gif "
                "*.tif *.tiff *.psd)")
            if not path or not self.use_file(path):
                if "file" not in self._pictures:
                    self.source_box.setCurrentIndex(0)
        self._changed()

    def _changed(self, *_) -> None:
        self._timer.start()

    # ---------------------------------------------------------- preview
    def _small_source(self) -> QImage:
        img = self.source()
        if img.isNull():
            return img
        return img.scaled(PREVIEW_SIDE, PREVIEW_SIDE, Qt.KeepAspectRatio,
                          Qt.SmoothTransformation)

    def _update_preview(self) -> None:
        try:
            small = self._small_source()
            if small.isNull() or not has_paint(small):
                self.status.setText("There's nothing to trace there – choose something else "
                                    "to trace.")
                self.view.clear()
                return
            o = self.options()
            if not (o.lines or o.flat or o.shading):
                self.status.setText("Tick at least one kind of layer to make.")
                return
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                got = trace(small, o)
            except Exception as e:  # noqa: BLE001 - shown, not fatal
                self.status.setText(f"This can't be traced with these settings – try other "
                                    f"ones ({e}).")
                return
            finally:
                QApplication.restoreOverrideCursor()
            self.status.setText("The preview is smaller than the result; the layers are made "
                                "at the painting's full size.")
            self.view.setPixmap(QPixmap.fromImage(preview_of(got, small.size())))
        except RuntimeError:                      # the window is going away
            return

    def done(self, result: int) -> None:
        self._timer.stop()
        super().done(result)
