"""Colours for Paint studio.

* ``ColourDisc`` – a hue ring round a square for how strong (saturation) and
  how bright the colour is, like Procreate's colour disc.
* ``harmony`` / ``HARMONIES`` – colours that go with a colour.
* ``palette_from_image`` – the main colours of a picture.
* ``BUILT_IN_PALETTES``, ``load_palettes`` / ``save_palettes`` – palettes.
* ``ColourPanel`` – all of it together: the main and second colour, the disc,
  number sliders, harmony, recent colours and palettes.

Only files in the ``data_dir`` handed in are read or written
(``palettes.json`` and ``colour-panel.json``)."""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QRegularExpression, QSize, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPalette, QPen, QPixmap, QRegularExpressionValidator)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLayout,
                               QLineEdit, QMenu, QMessageBox, QPushButton, QSizePolicy, QSlider,
                               QSpinBox, QToolButton, QVBoxLayout, QWidget)

PALETTES_FILE = "palettes.json"
STATE_FILE = "colour-panel.json"      # recent colours, the chosen palette, Values open or not
RECENT_MAX = 12
SWATCH = 28                           # swatch size in pixels (touch friendly)

# ------------------------------------------------------------------ harmonies
HARMONIES: dict[str, str] = {
    "complementary": "Opposite",
    "split": "Split opposite",
    "analogous": "Neighbours",
    "triadic": "Triangle",
    "tetradic": "Rectangle",
}
HARMONY_TIPS = {
    "complementary": "Complementary: the colour opposite on the colour wheel – strong contrast",
    "split": "Split complementary: the two colours either side of the opposite one – "
             "contrast that's easier on the eye",
    "analogous": "Analogous: the colours next to it on the wheel – calm and natural",
    "triadic": "Triadic: three colours evenly spaced round the wheel – lively but balanced",
    "tetradic": "Tetradic: two pairs of opposite colours – rich; best with one colour in charge",
}
# turns round the colour wheel, in degrees; the colour itself is always first
_HARMONY_TURNS = {
    "complementary": (0, 180),
    "split": (0, 150, 210),
    "analogous": (0, -30, 30),
    "triadic": (0, 120, 240),
    "tetradic": (0, 60, 180, 240),
}


def harmony(c: QColor, mode: str) -> list[QColor]:
    """The colours that go with ``c`` in a harmony (a key of HARMONIES): ``c``
    itself first, then the others turned round the colour wheel with the same
    strength and brightness. A grey has no hue, so its harmony is greys. An
    unknown mode gives just ``c``."""
    c = QColor(c)
    turns = _HARMONY_TURNS.get(mode, (0,))
    h, s, v, a = c.getHsvF()
    if h < 0:
        h = 0.0
    out = [QColor(c)]
    for deg in turns[1:]:
        out.append(QColor.fromHsvF((h + deg / 360.0) % 1.0, s, v, a))
    return out


# ------------------------------------------------------------------ palettes
BUILT_IN_PALETTES: dict[str, list[str]] = {
    "Basics": ["#000000", "#3C3C3C", "#7F7F7F", "#BFBFBF", "#FFFFFF", "#E53935", "#FB8C00",
               "#FDD835", "#43A047", "#00ACC1", "#1E88E5", "#5E35B1", "#D81B60", "#6D4C41"],
    "Skin tones": ["#FCE6DA", "#F5D3C0", "#EFC29F", "#E3B08A", "#D19C74", "#C2996E",
                   "#B07A55", "#9A6440", "#7E4E31", "#643B25", "#4A2A1A", "#33201A"],
    "White mana": ["#FFFDF7", "#FBF5E6", "#F6EBCF", "#F1DEA9", "#EACD7E", "#DDB85C",
                   "#C9A045", "#A88232", "#F3EEE6", "#E3DBCB", "#DCEBF7", "#BFD9EF",
                   "#9FC4E6", "#7FA9D3"],
    "Blue mana": ["#EAF4FC", "#CFE6F8", "#A9D1F2", "#7DB8EA", "#4F9BDE", "#2A7CC9",
                  "#1B5FA6", "#164A82", "#11375F", "#0B2440", "#5BC0DE", "#2E8FA6",
                  "#A8DCE8", "#6E7FB8"],
    "Black mana": ["#0C0B0E", "#17141B", "#221D28", "#2F2836", "#3E3447", "#50435A",
                   "#66566F", "#827489", "#A79CAB", "#CFC7D1", "#3A1E2A", "#5A2738",
                   "#2C3528", "#4B5A3F", "#8D8167", "#D8CFBC"],
    "Red mana": ["#FFE8DD", "#FFC6AE", "#FF9E7D", "#FF7552", "#F04A2F", "#D6301F",
                 "#B0221A", "#861A16", "#5C1210", "#3A0C0B", "#FFB347", "#F28C28",
                 "#C25B1E", "#7A3A1C", "#4B2A22"],
    "Green mana": ["#EEF5E3", "#D3E8BC", "#B2D48D", "#8FBF63", "#6BA544", "#4F8A33",
                   "#3A6E28", "#2A541F", "#1C3A16", "#10240E", "#C9B77A", "#9C7F4F",
                   "#6B5134", "#7FA88E", "#3F6E5B"],
    "Colourless & artifacts": ["#F5F6F8", "#E1E4E8", "#C8CDD3", "#ABB2BA", "#8C949E",
                               "#6E7681", "#525962", "#383E45", "#22262B", "#EAD7AE",
                               "#D1B279", "#B08A4F", "#8A6536", "#63452A", "#B87333",
                               "#7FA39C"],
    "Fantasy night": ["#070A1C", "#0E1430", "#182148", "#243063", "#344283", "#4A4F9E",
                      "#6A5BB0", "#8F7AC4", "#B9A6DD", "#E4DAF4", "#F3E6B8", "#FFD27A",
                      "#2F6F8F", "#6FC7CF", "#3E2A5C"],
    "Fire & embers": ["#120705", "#2B0D07", "#4D1308", "#7A1D0A", "#A8290C", "#D23B0F",
                      "#F05A15", "#FF8020", "#FFA63A", "#FFC85E", "#FFE59A", "#FFF7D6",
                      "#4E4744", "#8A827D"],
    "Forest": ["#0E1810", "#1A2B1C", "#283F2A", "#375538", "#4A6D43", "#62874F", "#80A260",
               "#A6BD7C", "#CCD7A3", "#EBEACB", "#3E3022", "#5E4730", "#846544", "#A98C64",
               "#5C7468", "#94ACA0"],
    "Ocean": ["#021722", "#052B42", "#0A4363", "#0F5C84", "#1676A3", "#2593BF", "#45AFD3",
              "#7CCBE2", "#B4E3EE", "#E6F7FA", "#0B6E6A", "#2E9B8F", "#7CCBB4", "#E8DDBF",
              "#C7B48A"],
    "Sunset": ["#1C1838", "#2F2452", "#4A2C66", "#6E3473", "#93407A", "#B84E7B", "#D9607A",
               "#EE7A73", "#F7976B", "#FBB46B", "#FDD27E", "#FFEBB0", "#FFF7E3"],
    "Ink & paper": ["#0A0A0A", "#1C1C1C", "#2E2E2E", "#424242", "#575757", "#6E6E6E",
                    "#868686", "#9E9E9E", "#B6B6B6", "#CDCDCD", "#E2E2E2", "#F2F2F2",
                    "#FFFFFF", "#F4ECD8", "#262431", "#3E3023"],
    "Gold & jewels": ["#FFF6CC", "#F9E08A", "#EDC24A", "#D4A22A", "#B07F1A", "#7E5A12",
                      "#BDEFFF", "#2F7FC1", "#173F78", "#C62A3A", "#7A1528", "#1E9157",
                      "#0D5A36", "#8A3FB0", "#E8894A", "#F2B8C6"],
}

_HEX = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def _norm_hex(value) -> Optional[str]:
    """``"#RRGGBB"`` (capitals) for "#rgb", "rrggbb", "#rrggbb"; None otherwise."""
    if not isinstance(value, str):
        return None
    m = _HEX.match(value.strip())
    if not m:
        return None
    digits = m.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return "#" + digits.upper()


def _hex(c: QColor) -> str:
    return QColor(c).name().upper()


def _write_json(path: Path, data) -> None:
    """Write ``data`` to ``path`` safely (a half-written file never replaces a good one)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_palettes(data_dir: Path) -> dict[str, list[str]]:
    """Your own palettes (name -> "#RRGGBB" colours) from ``data_dir/palettes.json``;
    {} when there's no file or it can't be read."""
    try:
        raw = json.loads((Path(data_dir) / PALETTES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if isinstance(raw, dict) and isinstance(raw.get("palettes"), dict):
        raw = raw["palettes"]
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for name, colours in raw.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(colours, list):
            continue
        out[name.strip()] = [h for h in (_norm_hex(x) for x in colours) if h]
    return out


def save_palettes(data_dir: Path, palettes: dict[str, list[str]]) -> None:
    """Keep your own palettes in ``data_dir/palettes.json`` (raises OSError when
    the disk can't be written)."""
    clean = {str(name): [h for h in (_norm_hex(x) for x in cols) if h]
             for name, cols in palettes.items() if str(name).strip()}
    _write_json(Path(data_dir) / PALETTES_FILE, {"version": 1, "palettes": clean})


def _image_rgba(img: QImage) -> np.ndarray:
    """The pixels of ``img`` as an (h, w, 4) RGBA array (not premultiplied)."""
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes())
    return buf.reshape(h, bpl)[:, :w * 4].reshape(h, w, 4).copy()


def palette_from_image(img: QImage, n: int = 8) -> list[QColor]:
    """The ``n`` main colours of a picture, darkest first. Transparent parts are
    left out; a picture with fewer colours than ``n`` gives just those."""
    if img is None or img.isNull() or n <= 0:
        return []
    import cv2  # comes with MSE Studio; only needed here
    w, h = img.width(), img.height()
    small = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    scale = 200.0 / max(w, h)
    if scale < 1.0:
        small = small.scaled(max(1, round(w * scale)), max(1, round(h * scale)),
                             Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    px = _image_rgba(small).reshape(-1, 4)
    px = np.ascontiguousarray(px[px[:, 3] >= 128][:, :3])
    if not len(px):
        return []
    distinct = np.unique(px, axis=0)
    if len(distinct) <= n:
        centres = distinct
    else:
        # cluster in Lab, where distances match how different colours look
        lab = cv2.cvtColor(px.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3)
        cv2.setRNGSeed(1234)  # the same picture always gives the same palette
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
        _compact, labels, centres = cv2.kmeans(lab.astype(np.float32), n, None, criteria, 3,
                                               cv2.KMEANS_PP_CENTERS)
        used = np.bincount(labels.ravel(), minlength=n) > 0
        centres = np.clip(np.round(centres[used]), 0, 255).astype(np.uint8)
        centres = cv2.cvtColor(centres.reshape(-1, 1, 3), cv2.COLOR_LAB2RGB).reshape(-1, 3)
    seen, out = set(), []
    for r, g, b in sorted((tuple(int(x) for x in c) for c in centres),
                          key=lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]):
        if (r, g, b) not in seen:
            seen.add((r, g, b))
            out.append(QColor(r, g, b))
    return out


# ------------------------------------------------------------------ theme
_THEME: list = []          # MSE Studio's theme module once looked up ([None] without it)
_FALLBACK = {"primary": QPalette.Highlight, "surface": QPalette.Window,
             "on_surface": QPalette.WindowText, "on_surface_variant": QPalette.PlaceholderText,
             "outline": QPalette.Mid, "outline_variant": QPalette.Mid,
             "surface_high": QPalette.AlternateBase}


def _ui(role: str) -> QColor:
    """A colour of MSE Studio's theme (``primary``, ``outline_variant``…), or
    the nearest of Qt's own palette without MSE Studio."""
    if not _THEME:
        try:
            from mse_studio.gui import theme
        except Exception:  # noqa: BLE001 - the module works on its own too
            theme = None
        _THEME.append(theme)
    value = None
    if _THEME[0] is not None:
        try:
            value = getattr(_THEME[0].current(), role, None)
        except Exception:  # noqa: BLE001
            value = None
    if value:
        return QColor(value)
    return QApplication.palette().color(_FALLBACK.get(role, QPalette.WindowText))


def _hsv_of(c: QColor, hue: float = 0.0, sat: float = 0.0) -> tuple[float, float, float]:
    """``c``'s hue, saturation and brightness (0–1). A grey has no hue and black
    no saturation: they keep ``hue`` / ``sat`` so the controls don't jump."""
    h, s, v, _a = QColor(c).getHsvF()
    if h < 0:
        h = hue
    if v <= 0:
        s = sat
    return h % 1.0, s, v


def _hue_rgb(h6):
    """Pure colours for hues ×6 (NumPy arrays), red 0 → yellow 1 → … → red 6."""
    r = np.clip(np.abs(h6 - 3.0) - 1.0, 0.0, 1.0)
    g = np.clip(2.0 - np.abs(h6 - 2.0), 0.0, 1.0)
    b = np.clip(2.0 - np.abs(h6 - 4.0), 0.0, 1.0)
    return r, g, b


def _to_qimage(rgba: np.ndarray, dpr: float) -> QImage:
    """A QImage (its own copy) of a premultiplied RGBA uint8 array."""
    rgba = np.ascontiguousarray(rgba, dtype=np.uint8)
    h, w = rgba.shape[:2]
    img = QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888_Premultiplied)
    img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)  # converts = copies
    img.setDevicePixelRatio(dpr)
    return img


def _marker(p: QPainter, centre: QPointF, radius: float, fill: QColor,
            ring: Optional[QColor] = None) -> None:
    """A round handle: the colour inside a white ring with a thin dark edge."""
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(ring if ring is not None else QColor(0, 0, 0, 120),
                  2.0 if ring is not None else 1.0))
    p.drawEllipse(centre, radius + 2.0, radius + 2.0)
    p.setPen(QPen(QColor(255, 255, 255), 3.0))
    fill = QColor(fill)
    fill.setAlpha(255)
    p.setBrush(fill)
    p.drawEllipse(centre, radius, radius)


# ------------------------------------------------------------------ the disc
class ColourDisc(QWidget):
    """A hue ring round a square: across the square is how strong the colour
    is (saturation), down it how bright. ``changed`` is sent while dragging and
    on release, and for the keys; ``set_colour`` sends nothing."""

    changed = Signal(QColor)
    MARGIN = 6.0                  # room round the ring for its handle and the focus ring

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._h, self._s, self._v, self._a = 0.0, 0.0, 0.1, 1.0
        self._ring: Optional[QImage] = None
        self._ring_key = None
        self._square: Optional[QImage] = None
        self._square_key = None
        self._drag: Optional[str] = None          # "ring" / "square" while dragging
        sp = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self.setMinimumSize(140, 140)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)
        self.setAccessibleName("Colour disc")
        self.setAccessibleDescription(
            "Hue ring and a square for strength and brightness. Arrow keys change "
            "strength and brightness, Page Up and Page Down the hue.")
        self.setToolTip("Drag round the ring to change the colour, and in the square for how "
                        "strong and how bright it is.\nArrow keys and Page Up / Page Down "
                        "work too (hold Shift for bigger steps).")

    # ---- the colour
    def colour(self) -> QColor:
        return QColor.fromHsvF(self._h, self._s, self._v, self._a)

    def set_colour(self, c: QColor) -> None:
        """Show ``c`` (nothing is sent)."""
        c = QColor(c)
        if c.isValid():
            self._set_hsv(*_hsv_of(c, self._h, self._s), c.alphaF())

    def hsv(self) -> tuple[float, float, float]:
        """Hue, saturation and brightness, 0–1 (kept exactly, unlike a QColor)."""
        return self._h, self._s, self._v

    def _set_hsv(self, h: float, s: float, v: float, a: Optional[float] = None) -> bool:
        h = h % 1.0
        s = min(1.0, max(0.0, s))
        v = min(1.0, max(0.0, v))
        if a is not None:
            self._a = min(1.0, max(0.0, a))
        if (h, s, v) == (self._h, self._s, self._v):
            return False
        self._h, self._s, self._v = h, s, v
        self.update()
        return True

    # ---- size
    def sizeHint(self) -> QSize:
        return QSize(260, 260)

    def minimumSizeHint(self) -> QSize:
        return QSize(140, 140)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return w

    def _geometry(self):
        """(side, left, top, centre x, centre y, outer radius, inner radius, square)."""
        side = max(20, min(self.width(), self.height()))
        left = (self.width() - side) // 2
        top = (self.height() - side) // 2
        cx, cy = left + side / 2.0, top + side / 2.0
        outer = side / 2.0 - self.MARGIN
        band = max(12.0, side * 0.085)
        inner = outer - band
        gap = max(5.0, band * 0.4)
        half = max(4.0, (inner - gap) / math.sqrt(2.0) + 2.0)   # its corners are rounded
        return side, left, top, cx, cy, outer, inner, QRectF(cx - half, cy - half,
                                                             2 * half, 2 * half)

    # ---- the pictures, kept until the size (or, for the square, the hue) changes
    def _ring_image(self, side: int, outer: float, inner: float, dpr: float) -> QImage:
        n = max(1, int(round(side * dpr)))
        key = (n, round(outer, 3), round(inner, 3), dpr)
        if self._ring is None or self._ring_key != key:
            yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
            dx = xx + 0.5 - n / 2.0
            dy = yy + 0.5 - n / 2.0
            dist = np.hypot(dx, dy)
            hue = (np.arctan2(dx, -dy) / (2 * np.pi)) % 1.0       # red at the top, clockwise
            r, g, b = _hue_rgb(hue * 6.0)
            alpha = (np.clip(outer * dpr - dist + 0.5, 0, 1)
                     * np.clip(dist - inner * dpr + 0.5, 0, 1))  # smooth edges
            rgba = np.stack([r * alpha, g * alpha, b * alpha, alpha], axis=-1)
            self._ring = _to_qimage(np.round(rgba * 255), dpr)
            self._ring_key = key
        return self._ring

    def _square_image(self, rect: QRectF, dpr: float) -> QImage:
        n = max(2, int(round(rect.width() * dpr)))
        key = (n, round(self._h, 4), dpr)
        if self._square is None or self._square_key != key:
            hr, hg, hb = (float(x) for x in _hue_rgb(np.float64(self._h * 6.0)))
            s = np.linspace(0.0, 1.0, n, dtype=np.float32)[None, :]
            v = np.linspace(1.0, 0.0, n, dtype=np.float32)[:, None]
            # rounded corners, smoothed (a clip path would leave them jagged)
            radius = max(4.0, rect.width() * 0.06) * dpr
            c = np.arange(n, dtype=np.float32) + 0.5 - n / 2.0
            q = np.abs(c) - (n / 2.0 - radius)
            qx, qy = q[None, :], q[:, None]
            dist = (np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))
                    + np.minimum(np.maximum(qx, qy), 0) - radius)
            alpha = np.clip(0.5 - dist, 0.0, 1.0)
            rgba = np.empty((n, n, 4), np.float32)
            for i, comp in enumerate((hr, hg, hb)):
                rgba[..., i] = v * (1.0 - s + s * comp) * alpha
            rgba[..., 3] = alpha
            self._square = _to_qimage(np.round(rgba * 255), dpr)
            self._square_key = key
        return self._square

    def resizeEvent(self, e):
        self._ring = self._square = None
        super().resizeEvent(e)

    def paintEvent(self, _e):
        side, left, top, cx, cy, outer, inner, sq = self._geometry()
        dpr = self.devicePixelRatioF()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(QRectF(left, top, side, side), self._ring_image(side, outer, inner, dpr))
        p.drawImage(sq, self._square_image(sq, dpr))
        edge = _ui("outline_variant")
        edge.setAlpha(150)
        p.setPen(QPen(edge, 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), outer, outer)
        p.drawEllipse(QPointF(cx, cy), inner, inner)
        radius = max(4.0, sq.width() * 0.06)
        p.drawRoundedRect(sq, radius, radius)
        if self.hasFocus():
            p.setPen(QPen(_ui("primary"), 2.0))
            p.drawEllipse(QPointF(cx, cy), outer + 3.5, outer + 3.5)
        # the handles
        mid = (outer + inner) / 2.0
        turn = self._h * 2 * math.pi
        _marker(p, QPointF(cx + mid * math.sin(turn), cy - mid * math.cos(turn)),
                (outer - inner) / 2.0 + 1.0, QColor.fromHsvF(self._h, 1.0, 1.0))
        _marker(p, QPointF(sq.left() + self._s * sq.width(),
                           sq.top() + (1.0 - self._v) * sq.height()),
                8.0, self.colour())
        p.end()

    # ---- mouse, pen and touch (Qt turns pen and touch into mouse events)
    def _zone(self, pos: QPointF) -> Optional[str]:
        _side, _l, _t, cx, cy, outer, inner, sq = self._geometry()
        d = math.hypot(pos.x() - cx, pos.y() - cy)
        if d > outer + 10:
            return None
        corner = sq.width() / 2.0 * math.sqrt(2.0)
        return "ring" if d >= (inner + min(corner, inner)) / 2.0 - 1.0 else "square"

    def _drag_to(self, pos: QPointF) -> None:
        _side, _l, _t, cx, cy, _o, _i, sq = self._geometry()
        if self._drag == "ring":
            hue = (math.atan2(pos.x() - cx, -(pos.y() - cy)) / (2 * math.pi)) % 1.0
            moved = self._set_hsv(hue, self._s, self._v)
        else:
            moved = self._set_hsv(self._h, (pos.x() - sq.left()) / max(1.0, sq.width()),
                                  1.0 - (pos.y() - sq.top()) / max(1.0, sq.height()))
        if moved:
            self.changed.emit(self.colour())

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            super().mousePressEvent(e)
            return
        zone = self._zone(e.position())
        if zone is None:
            e.ignore()
            return
        self._drag = zone
        self._drag_to(e.position())
        e.accept()

    def mouseMoveEvent(self, e):
        if self._drag and e.buttons() & Qt.LeftButton:
            self._drag_to(e.position())
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag and e.button() == Qt.LeftButton:
            self._drag_to(e.position())
            self._drag = None
            self.changed.emit(self.colour())
            e.accept()
        else:
            super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        big = bool(e.modifiers() & Qt.ShiftModifier)
        step = 0.1 if big else 0.01
        turn = (15.0 if big else 2.0) / 360.0
        h, s, v = self._h, self._s, self._v
        key = e.key()
        if key == Qt.Key_Left:
            s -= step
        elif key == Qt.Key_Right:
            s += step
        elif key == Qt.Key_Up:
            v += step
        elif key == Qt.Key_Down:
            v -= step
        elif key == Qt.Key_PageUp:
            h += turn
        elif key == Qt.Key_PageDown:
            h -= turn
        else:
            super().keyPressEvent(e)
            return
        e.accept()
        if self._set_hsv(h, s, v):
            self.changed.emit(self.colour())

    def focusInEvent(self, e):
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.update()
        super().focusOutEvent(e)


# ------------------------------------------------------------------ small widgets
class _Flow(QLayout):
    """Lays widgets out in rows, starting a new row when one is full."""

    def __init__(self, parent: Optional[QWidget] = None, gap: int = 2):
        super().__init__(parent)
        self._items: list = []
        self._gap = gap
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._place(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _place(self, rect: QRect, test: bool) -> int:
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line = r.x(), r.y(), 0
        for item in self._items:
            size = item.sizeHint()
            if x > r.x() and x + size.width() > r.right() + 1:
                x, y, line = r.x(), y + line + self._gap, 0
            if not test:
                item.setGeometry(QRect(QPoint(x, y), size))
            x += size.width() + self._gap
            line = max(line, size.height())
        return y + line - rect.y() + m.bottom()


class _Swatch(QAbstractButton):
    """One colour to click. Right-click: use it as the second colour, or take
    it out of your palette."""

    picked = Signal(QColor)
    as_second = Signal(QColor)
    remove = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._colour = QColor(0, 0, 0)
        self.index = 0
        self.removable = False
        self.current = False
        self.setFixedSize(SWATCH + 4, SWATCH + 4)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)        # a click doesn't take the keys from the canvas
        self.clicked.connect(self._clicked)

    def colour(self) -> QColor:
        return QColor(self._colour)

    def set_colour(self, c: QColor, removable: bool = False) -> None:
        self._colour = QColor(c)
        self.removable = removable
        hx = _hex(c)
        self.setToolTip(hx + ("\nRight-click to take it out of the palette" if removable else ""))
        self.setAccessibleName(f"Colour {hx}")
        self.update()

    def set_current(self, on: bool) -> None:
        if on != self.current:
            self.current = on
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(SWATCH + 4, SWATCH + 4)

    def _clicked(self, *_):
        self.picked.emit(QColor(self._colour))

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        use = menu.addAction("Use this colour")
        second = menu.addAction("Use as the second colour")
        drop = menu.addAction("Remove from palette") if self.removable else None
        chosen = menu.exec(e.globalPos())
        try:
            menu.deleteLater()
            if chosen is use:
                self.picked.emit(QColor(self._colour))
            elif chosen is second:
                self.as_second.emit(QColor(self._colour))
            elif drop is not None and chosen is drop:
                self.remove.emit(self.index)
        except RuntimeError:  # the swatch went while the menu was open
            return

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(2.0, 2.0, SWATCH, SWATCH)
        if self.isDown():
            r.adjust(1.0, 1.0, -1.0, -1.0)
        if self.current or self.hasFocus():
            p.setPen(QPen(_ui("primary") if self.hasFocus() else _ui("on_surface"), 2.0))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(1.0, 1.0, SWATCH + 2, SWATCH + 2), 8.0, 8.0)
            r.adjust(2.0, 2.0, -2.0, -2.0)
        edge = _ui("on_surface_variant") if self.underMouse() else _ui("outline_variant")
        p.setPen(QPen(edge, 1.0))
        p.setBrush(self._colour)
        p.drawRoundedRect(r, 6.0, 6.0)
        p.end()


class _SwatchRow(QWidget):
    """A wrapping row of swatches, with a hint when there are none."""

    picked = Signal(QColor)
    as_second = Signal(QColor)
    remove = Signal(int)

    def __init__(self, hint: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.hint = QLabel(hint, self)
        self.hint.setWordWrap(True)
        self.hint.setForegroundRole(QPalette.PlaceholderText)
        self.hint.setVisible(bool(hint))
        lay.addWidget(self.hint)
        self._box = QWidget(self)
        self._flow = _Flow(self._box, 2)
        lay.addWidget(self._box)
        self._swatches: list[_Swatch] = []
        self._current = ""

    def swatches(self) -> list[_Swatch]:
        return list(self._swatches)

    def colours(self) -> list[QColor]:
        return [sw.colour() for sw in self._swatches]

    def set_colours(self, colours, removable: bool = False) -> None:
        """Show these colours (QColors or "#RRGGBB"); swatches are reused, so this
        is cheap enough to call while a colour is dragged."""
        cols = [QColor(c) for c in colours]
        while len(self._swatches) > len(cols):
            sw = self._swatches.pop()
            self._flow.removeWidget(sw)
            sw.hide()
            sw.deleteLater()
        while len(self._swatches) < len(cols):
            sw = _Swatch(self._box)
            sw.picked.connect(self.picked)
            sw.as_second.connect(self.as_second)
            sw.remove.connect(self.remove)
            self._flow.addWidget(sw)
            sw.show()
            self._swatches.append(sw)
        for i, (sw, c) in enumerate(zip(self._swatches, cols)):
            sw.index = i
            if _hex(c) != _hex(sw.colour()) or sw.removable != removable:
                sw.set_colour(c, removable)
            sw.set_current(_hex(c) == self._current)
        self.hint.setVisible(not cols and bool(self.hint.text()))
        self._box.setVisible(bool(cols))
        self._box.updateGeometry()

    def set_hint(self, text: str) -> None:
        self.hint.setText(text)
        self.hint.setVisible(not self._swatches and bool(text))

    def set_current(self, hx: str) -> None:
        """Ring the swatch of this colour ("#RRGGBB")."""
        self._current = hx
        for sw in self._swatches:
            sw.set_current(_hex(sw.colour()) == hx)


class _DualSwatch(QWidget):
    """The main colour in front of the second colour; click the back one to swap."""

    swap = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._front = QColor(0, 0, 0)
        self._back = QColor(255, 255, 255)
        self.setFixedSize(60, 52)
        self.setToolTip("Your main colour (in front) and second colour (behind).\n"
                        "Click the one behind to swap them.")

    def set_colours(self, front: QColor, back: QColor) -> None:
        self._front, self._back = QColor(front), QColor(back)
        self.setAccessibleName(f"Main colour {_hex(front)}, second colour {_hex(back)}")
        self.update()

    def _rects(self) -> tuple[QRectF, QRectF]:
        size = 36.0
        return (QRectF(2.0, 2.0, size, size),
                QRectF(self.width() - size - 2.0, self.height() - size - 2.0, size, size))

    def mousePressEvent(self, e):
        front, back = self._rects()
        pos = e.position()
        if e.button() == Qt.LeftButton and back.contains(pos) and not front.contains(pos):
            self.swap.emit()
            e.accept()
        else:
            super().mousePressEvent(e)

    def paintEvent(self, _e):
        front, back = self._rects()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        edge = _ui("outline_variant")
        p.setPen(QPen(edge, 1.0))
        p.setBrush(self._back)
        p.drawRoundedRect(back, 8.0, 8.0)
        # a gap round the front swatch, in the panel's own colour, so the two stand apart
        p.setPen(Qt.NoPen)
        p.setBrush(self.palette().color(self.backgroundRole()))
        p.drawRoundedRect(front.adjusted(-2.5, -2.5, 2.5, 2.5), 10.0, 10.0)
        p.setPen(QPen(edge, 1.0))
        p.setBrush(self._front)
        p.drawRoundedRect(front, 8.0, 8.0)
        p.end()


class _SwapButton(QToolButton):
    """A small button with two arrows (⇄), drawn in the theme's colours."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAutoRaise(True)
        self.setFixedSize(32, 32)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setToolTip("Swap colours (X)")
        self.setAccessibleName("Swap colours")

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(_ui("on_surface_variant"), 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        # → on top, ← below
        p.drawLine(QPointF(cx - 7, cy - 3.5), QPointF(cx + 7, cy - 3.5))
        p.drawLine(QPointF(cx + 7, cy - 3.5), QPointF(cx + 3.5, cy - 7))
        p.drawLine(QPointF(cx + 7, cy - 3.5), QPointF(cx + 3.5, cy))
        p.drawLine(QPointF(cx + 7, cy + 3.5), QPointF(cx - 7, cy + 3.5))
        p.drawLine(QPointF(cx - 7, cy + 3.5), QPointF(cx - 3.5, cy))
        p.drawLine(QPointF(cx - 7, cy + 3.5), QPointF(cx - 3.5, cy + 7))
        p.end()


class _ChannelSlider(QSlider):
    """A slider whose track shows the colours it goes through: click or drag
    anywhere on it; the keys work as on any slider."""

    HANDLE = 9.0

    def __init__(self, maximum: int, name: str, parent: Optional[QWidget] = None):
        super().__init__(Qt.Horizontal, parent)
        self.setRange(0, maximum)
        self.setPageStep(max(1, maximum // 10))
        self.setMinimumSize(80, 26)
        self.setAccessibleName(name)
        self._stops: list = [(0.0, QColor(0, 0, 0)), (1.0, QColor(255, 255, 255))]

    def sizeHint(self) -> QSize:
        return QSize(140, 26)

    def set_stops(self, stops: list) -> None:
        """The track's colours: [(0–1, QColor), …]."""
        self._stops = stops
        self.update()

    def _track(self) -> QRectF:
        pad = self.HANDLE + 3.0
        return QRectF(pad, self.height() / 2.0 - 6.0, max(1.0, self.width() - 2 * pad), 12.0)

    def _value_at(self, x: float) -> int:
        t = self._track()
        f = min(1.0, max(0.0, (x - t.left()) / t.width()))
        return int(round(self.minimum() + f * (self.maximum() - self.minimum())))

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            super().mousePressEvent(e)
            return
        self.setSliderDown(True)
        self.setValue(self._value_at(e.position().x()))
        e.accept()

    def mouseMoveEvent(self, e):
        if self.isSliderDown():
            self.setValue(self._value_at(e.position().x()))
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.isSliderDown() and e.button() == Qt.LeftButton:
            self.setSliderDown(False)
            e.accept()
        else:
            super().mouseReleaseEvent(e)

    def wheelEvent(self, e):
        if self.hasFocus():              # otherwise the wheel scrolls the panel
            super().wheelEvent(e)
        else:
            e.ignore()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.4)
        t = self._track()
        grad = QLinearGradient(t.left(), 0, t.right(), 0)
        for pos, c in self._stops:
            grad.setColorAt(pos, c)
        path = QPainterPath()
        path.addRoundedRect(t, 6.0, 6.0)
        p.fillPath(path, QBrush(grad))
        p.setPen(QPen(_ui("outline_variant"), 1.0))
        p.drawPath(path)
        span = max(1, self.maximum() - self.minimum())
        f = (self.value() - self.minimum()) / span
        _marker(p, QPointF(t.left() + f * t.width(), t.center().y()), self.HANDLE - 2.0,
                _lerp_stops(self._stops, f), _ui("primary") if self.hasFocus() else None)
        p.end()


def _lerp_stops(stops: list, t: float) -> QColor:
    t = min(1.0, max(0.0, t))
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if t <= p1:
            f = (t - p0) / (p1 - p0) if p1 > p0 else 0.0
            return QColor.fromRgbF(c0.redF() + (c1.redF() - c0.redF()) * f,
                                   c0.greenF() + (c1.greenF() - c0.greenF()) * f,
                                   c0.blueF() + (c1.blueF() - c0.blueF()) * f)
    return QColor(stops[-1][1])


def _heading(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    f = label.font()
    f.setBold(True)
    label.setFont(f)
    return label


def _icon(button: QAbstractButton, name: str) -> None:
    """MSE Studio's icon on a button (nothing without MSE Studio)."""
    try:
        from mse_studio.gui.icons import set_icon
        set_icon(button, name)
    except Exception:  # noqa: BLE001 - a button without an icon is fine
        pass


# questions to the user (kept apart so tests can answer them)
def _ask(parent: QWidget, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) == QMessageBox.Yes


def _ask_name(parent: QWidget, title: str, label: str, text: str = "") -> Optional[str]:
    name, ok = QInputDialog.getText(parent, title, label, QLineEdit.Normal, text)
    name = (name or "").strip()[:60]
    return name if ok and name else None


def _tell(parent: QWidget, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


# ------------------------------------------------------------------ the panel
class ColourPanel(QWidget):
    """Everything to choose colours with: the main and second colour, the
    colour disc, number sliders, harmonies, recent colours and palettes.

    ``changed`` is sent when you change the main colour (``set_colour`` sends
    it only with ``emit=True``). ``data_dir`` keeps your palettes and recent
    colours; ``image_source()`` gives the picture for *From the picture*."""

    changed = Signal(QColor)

    def __init__(self, data_dir: Optional[Path] = None,
                 image_source: Optional[Callable[[], Optional[QImage]]] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._dir = Path(data_dir) if data_dir else None
        self._image_source = image_source
        self._primary = QColor("#1B1B1B")
        self._secondary = QColor("#FFFFFF")
        self._h, self._s, self._v = _hsv_of(self._primary)
        self._syncing = False
        self._loading = True
        self._user: dict[str, list[str]] = load_palettes(self._dir) if self._dir else {}
        state = self._load_state()
        recent = state.get("recent") if isinstance(state.get("recent"), list) else []
        self._recent: list[str] = [h for h in (_norm_hex(x) for x in recent) if h][:RECENT_MAX]
        self._saved_state = state
        self._build(state)
        self._loading = False
        self._sync(None)

    # ---- building
    def _build(self, state: dict) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # 1. main and second colour, the hex code
        top = QHBoxLayout()
        top.setSpacing(4)
        self.dual = _DualSwatch(self)
        self.dual.swap.connect(self._swap_clicked)
        self.swap_button = _SwapButton(self)
        self.swap_button.clicked.connect(self._swap_clicked)
        self.hex_edit = QLineEdit(self)
        self.hex_edit.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"#?[0-9A-Fa-f]{0,6}"), self.hex_edit))
        self.hex_edit.setMaxLength(7)
        self.hex_edit.setFixedWidth(96)
        self.hex_edit.setPlaceholderText("#RRGGBB")
        self.hex_edit.setAccessibleName("Colour code")
        self.hex_edit.setToolTip("The colour as a hex code, like #3A7BD5.\n"
                                 "Type or paste one to use it.")
        self.hex_edit.textEdited.connect(self._hex_typed)
        self.hex_edit.editingFinished.connect(self._hex_done)
        top.addWidget(self.dual)
        top.addWidget(self.swap_button, 0, Qt.AlignBottom)
        top.addStretch(1)
        top.addWidget(self.hex_edit, 0, Qt.AlignVCenter)
        lay.addLayout(top)

        # 2. the disc
        self.disc = ColourDisc(self)
        self.disc.changed.connect(self._disc_changed)
        lay.addWidget(self.disc)

        # 3. number sliders, folded away unless opened
        self.values_button = QToolButton(self)
        self.values_button.setText("Values")
        self.values_button.setCheckable(True)
        self.values_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.values_button.setAutoRaise(True)
        self.values_button.setToolTip("Show or hide sliders for the colour's numbers")
        self.values_box = QWidget(self)
        grid = QGridLayout(self.values_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        self.sliders: dict[str, _ChannelSlider] = {}
        self.spins: dict[str, QSpinBox] = {}
        rows = [("h", "H", "Hue", "Hue – which colour it is, round the colour wheel", 360, "°"),
                ("s", "S", "Saturation", "Saturation – how strong the colour is (0 is grey)",
                 100, "%"),
                ("v", "B", "Brightness", "Brightness – how light the colour is (0 is black)",
                 100, "%"),
                None,
                ("r", "R", "Red", "Red – how much red light is in the colour", 255, ""),
                ("g", "G", "Green", "Green – how much green light is in the colour", 255, ""),
                ("b", "B", "Blue", "Blue – how much blue light is in the colour", 255, "")]
        row = 0
        for spec in rows:
            if spec is None:
                grid.setRowMinimumHeight(row, 6)
                row += 1
                continue
            key, letter, name, tip, maximum, suffix = spec
            label = QLabel(letter, self.values_box)
            label.setToolTip(tip)
            label.setFixedWidth(14)
            slider = _ChannelSlider(maximum, name, self.values_box)
            slider.setToolTip(tip)
            spin = QSpinBox(self.values_box)
            spin.setRange(0, maximum)
            spin.setSuffix(suffix)
            spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            spin.setFixedWidth(64)
            spin.setStyleSheet("padding: 2px 4px;")   # (no buttons squeezes the text away)
            spin.setToolTip(tip)
            spin.setAccessibleName(name)
            if key in "hsv":
                slider.valueChanged.connect(self._hsv_slider_moved)
                spin.valueChanged.connect(self._hsv_spin_changed)
            else:
                slider.valueChanged.connect(self._rgb_slider_moved)
                spin.valueChanged.connect(self._rgb_spin_changed)
            grid.addWidget(label, row, 0)
            grid.addWidget(slider, row, 1)
            grid.addWidget(spin, row, 2)
            self.sliders[key], self.spins[key] = slider, spin
            row += 1
        lay.addWidget(self.values_button)
        lay.addWidget(self.values_box)
        opened = bool(state.get("values", False))
        self.values_button.setChecked(opened)
        self._show_values(opened)
        self.values_button.toggled.connect(self._show_values)

        # 4. harmony
        hrow = QHBoxLayout()
        hrow.setSpacing(6)
        hrow.addWidget(_heading("Harmony", self))
        self.harmony_combo = QComboBox(self)
        self.harmony_combo.setToolTip("Colours that go well with the current one.\n"
                                      "Click one below to use it.")
        self.harmony_combo.setAccessibleName("Harmony")
        for key, label in HARMONIES.items():
            self.harmony_combo.addItem(label, key)
            self.harmony_combo.setItemData(self.harmony_combo.count() - 1,
                                           HARMONY_TIPS[key], Qt.ToolTipRole)
        i = self.harmony_combo.findData(state.get("harmony", "complementary"))
        self.harmony_combo.setCurrentIndex(max(0, i))
        self.harmony_combo.currentIndexChanged.connect(self._harmony_changed)
        hrow.addWidget(self.harmony_combo, 1)
        lay.addLayout(hrow)
        self.harmony_row = _SwatchRow("", self)
        self._connect_row(self.harmony_row)
        lay.addWidget(self.harmony_row)

        # 5. recent colours
        lay.addWidget(_heading("Recent", self))
        self.recent_row = _SwatchRow("The colours you paint with show up here.", self)
        self._connect_row(self.recent_row)
        lay.addWidget(self.recent_row)

        # 6. palettes
        lay.addWidget(_heading("Palettes", self))
        self.palette_combo = QComboBox(self)
        self.palette_combo.setAccessibleName("Palette")
        self.palette_combo.setToolTip("Your own palettes come first, then the ones that come "
                                      "with Paint studio")
        lay.addWidget(self.palette_combo)
        self.palette_row = _SwatchRow("", self)
        self._connect_row(self.palette_row)
        self.palette_row.remove.connect(self._remove_swatch)
        lay.addWidget(self.palette_row)
        buttons = QGridLayout()
        buttons.setSpacing(4)
        self.add_button = QPushButton("Add colour", self)
        self.add_button.setToolTip("Put the current colour in this palette")
        self.new_button = QPushButton("New palette…", self)
        self.new_button.setToolTip("Start a new, empty palette of your own")
        self.picture_button = QPushButton("From the picture", self)
        self.picture_button.setToolTip("Make a palette of the main colours in the picture")
        self.picture_button.setEnabled(self._image_source is not None)
        self.delete_button = QPushButton("Delete palette", self)
        self.delete_button.setToolTip("Delete this palette (only your own palettes)")
        for i, (b, icon, slot) in enumerate((
                (self.add_button, "add", self._add_colour),
                (self.new_button, "palette", self._new_palette),
                (self.picture_button, "image", self._from_picture),
                (self.delete_button, "delete", self._delete_palette))):
            b.setStyleSheet("padding: 5px 8px;")
            _icon(b, icon)
            b.clicked.connect(slot)
            buttons.addWidget(b, i // 2, i % 2)
        lay.addLayout(buttons)
        lay.addStretch(1)
        self._fill_palettes(state.get("palette") if isinstance(state.get("palette"), str)
                            else None)

    def _connect_row(self, row: _SwatchRow) -> None:
        row.picked.connect(self._swatch_picked)
        row.as_second.connect(self._swatch_second)

    # ---- the colours
    def colour(self) -> QColor:
        return QColor(self._primary)

    def secondary(self) -> QColor:
        return QColor(self._secondary)

    def set_colour(self, c: QColor, emit: bool = False) -> None:
        """Make ``c`` the main colour; ``changed`` only with ``emit=True``."""
        c = QColor(c)
        if not c.isValid():
            return
        if c.rgba() != self._primary.rgba():
            self._use(c, emit=False)
        if emit:
            self.changed.emit(QColor(c))

    def set_secondary(self, c: QColor) -> None:
        c = QColor(c)
        if c.isValid():
            self._secondary = c
            self.dual.set_colours(self._primary, self._secondary)

    def swap(self) -> None:
        """Swap the main and second colour (sends ``changed``)."""
        self._primary, self._secondary = self._secondary, self._primary
        self._use(self._primary)

    def add_recent(self, c: QColor) -> None:
        """Remember a colour you painted with (the last 12 are kept)."""
        c = QColor(c)
        if not c.isValid():
            return
        hx = _hex(c)
        if self._recent and self._recent[0] == hx:
            return
        self._recent = [hx] + [h for h in self._recent if h != hx][:RECENT_MAX - 1]
        self.recent_row.set_colours(self._recent)
        self.recent_row.set_current(_hex(self._primary))
        self._save_state()

    def recent(self) -> list[QColor]:
        return [QColor(h) for h in self._recent]

    def _use(self, c: QColor, hsv: Optional[tuple] = None, source: Optional[str] = None,
             emit: bool = True) -> None:
        """Make ``c`` the main colour and bring every control up to date, except
        ``source`` – the one being moved."""
        c = QColor(c)
        self._h, self._s, self._v = hsv if hsv is not None else _hsv_of(c, self._h, self._s)
        self._primary = c
        self._sync(source)
        if emit:
            self.changed.emit(QColor(c))

    def _sync(self, source: Optional[str]) -> None:
        self._syncing = True
        try:
            h, s, v, c = self._h, self._s, self._v, self._primary
            if source != "disc":
                self.disc._set_hsv(h, s, v, c.alphaF())
            if source != "hsv":
                for key, value in (("h", round(h * 360)), ("s", round(s * 100)),
                                   ("v", round(v * 100))):
                    self._set_pair(key, value)
            if source != "rgb":
                for key, value in zip("rgb", (c.red(), c.green(), c.blue())):
                    self._set_pair(key, value)
            if source != "hex":
                self.hex_edit.setText(_hex(c))
            self._update_tracks()
            self.dual.set_colours(c, self._secondary)
            self.harmony_row.set_colours(harmony(QColor.fromHsvF(h, s, v),
                                                 self._harmony_mode()))
            hx = _hex(c)
            for row in (self.harmony_row, self.recent_row, self.palette_row):
                row.set_current(hx)
        finally:
            self._syncing = False

    def _set_pair(self, key: str, value: int) -> None:
        for w in (self.sliders[key], self.spins[key]):
            if w.value() != value:
                was = w.blockSignals(True)
                w.setValue(value)
                w.blockSignals(was)

    def _update_tracks(self) -> None:
        h, s, v, c = self._h, self._s, self._v, self._primary
        self.sliders["h"].set_stops([(i / 6.0, QColor.fromHsvF((i / 6.0) % 1.0, 1.0, 1.0))
                                     for i in range(7)])
        self.sliders["s"].set_stops([(0.0, QColor.fromHsvF(h, 0.0, v)),
                                     (1.0, QColor.fromHsvF(h, 1.0, v))])
        self.sliders["v"].set_stops([(0.0, QColor.fromHsvF(h, s, 0.0)),
                                     (1.0, QColor.fromHsvF(h, s, 1.0))])
        r, g, b = c.red(), c.green(), c.blue()
        self.sliders["r"].set_stops([(0.0, QColor(0, g, b)), (1.0, QColor(255, g, b))])
        self.sliders["g"].set_stops([(0.0, QColor(r, 0, b)), (1.0, QColor(r, 255, b))])
        self.sliders["b"].set_stops([(0.0, QColor(r, g, 0)), (1.0, QColor(r, g, 255))])

    # ---- what the controls send
    def _swap_clicked(self, *_):
        self.swap()

    def _disc_changed(self, _c: QColor) -> None:
        if self._syncing:
            return
        h, s, v = self.disc.hsv()
        self._use(QColor.fromHsvF(h, s, v, self._primary.alphaF()), (h, s, v), "disc")

    def _hsv_slider_moved(self, *_):
        self._copy_pairs("hsv", from_sliders=True)
        self._from_hsv()

    def _hsv_spin_changed(self, *_):
        self._copy_pairs("hsv", from_sliders=False)
        self._from_hsv()

    def _rgb_slider_moved(self, *_):
        self._copy_pairs("rgb", from_sliders=True)
        self._from_rgb()

    def _rgb_spin_changed(self, *_):
        self._copy_pairs("rgb", from_sliders=False)
        self._from_rgb()

    def _copy_pairs(self, keys: str, from_sliders: bool) -> None:
        for key in keys:
            src, dst = ((self.sliders[key], self.spins[key]) if from_sliders
                        else (self.spins[key], self.sliders[key]))
            if dst.value() != src.value():
                was = dst.blockSignals(True)
                dst.setValue(src.value())
                dst.blockSignals(was)

    def _from_hsv(self) -> None:
        if self._syncing:
            return
        hv, sv, vv = (self.sliders[k].value() for k in "hsv")
        # keep the exact value when its rounded number hasn't changed (no drift)
        h = self._h if round(self._h * 360) % 360 == hv % 360 else (hv % 360) / 360.0
        s = self._s if round(self._s * 100) == sv else sv / 100.0
        v = self._v if round(self._v * 100) == vv else vv / 100.0
        self._use(QColor.fromHsvF(h, s, v, self._primary.alphaF()), (h, s, v), "hsv")

    def _from_rgb(self) -> None:
        if self._syncing:
            return
        r, g, b = (self.sliders[k].value() for k in "rgb")
        self._use(QColor(r, g, b, self._primary.alpha()), None, "rgb")

    def _hex_typed(self, text: str) -> None:
        digits = text.lstrip("#")
        if len(digits) == 6:
            hx = _norm_hex(digits)
            if hx and hx != _hex(self._primary):
                self._use(QColor(hx), None, "hex")

    def _hex_done(self) -> None:
        hx = _norm_hex(self.hex_edit.text())
        if hx and hx != _hex(self._primary):
            self._use(QColor(hx), None, "hex")
        self.hex_edit.setText(_hex(self._primary))

    def _swatch_picked(self, c: QColor) -> None:
        self._use(QColor(c))

    def _swatch_second(self, c: QColor) -> None:
        self.set_secondary(c)

    def _show_values(self, on: bool) -> None:
        self.values_button.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.values_box.setVisible(on)
        self._save_state()

    def _harmony_mode(self) -> str:
        return self.harmony_combo.currentData() or "complementary"

    def _harmony_changed(self, *_):
        self.harmony_row.set_colours(harmony(QColor.fromHsvF(self._h, self._s, self._v),
                                             self._harmony_mode()))
        self.harmony_row.set_current(_hex(self._primary))
        self._save_state()

    # ---- palettes
    def _fill_palettes(self, select: Optional[str] = None) -> None:
        """Fill the palette list (your own first) and pick ``select`` ("u:name" for
        yours, "b:name" for a built-in one)."""
        combo = self.palette_combo
        was = combo.blockSignals(True)
        combo.clear()
        for name in self._user:
            combo.addItem(name, "u:" + name)
            combo.setItemData(combo.count() - 1, "Your palette", Qt.ToolTipRole)
        if self._user:
            combo.insertSeparator(combo.count())
        for name in BUILT_IN_PALETTES:
            combo.addItem(name, "b:" + name)
            combo.setItemData(combo.count() - 1, "Comes with Paint studio (can't be changed)",
                              Qt.ToolTipRole)
        i = combo.findData(select) if select else -1
        if i < 0:
            i = combo.findData("b:" + next(iter(BUILT_IN_PALETTES)))
        combo.setCurrentIndex(i)
        combo.blockSignals(was)
        if not getattr(self, "_palette_hooked", False):
            combo.currentIndexChanged.connect(self._palette_chosen)
            self._palette_hooked = True
        self._palette_chosen()

    def _current_palette(self) -> tuple[str, str]:
        """("u", name) for your palette, ("b", name) for a built-in one."""
        data = self.palette_combo.currentData() or ""
        kind, _, name = data.partition(":")
        return kind, name

    def _palette_chosen(self, *_):
        kind, name = self._current_palette()
        mine = kind == "u"
        cols = self._user.get(name, []) if mine else BUILT_IN_PALETTES.get(name, [])
        self.palette_row.set_hint("This palette is empty – choose a colour and press "
                                  "Add colour." if mine else "")
        self.palette_row.set_colours(cols, removable=mine)
        self.palette_row.set_current(_hex(self._primary))
        self.delete_button.setEnabled(mine)
        self._save_state()

    def _unique(self, name: str) -> str:
        name = name.strip()[:60] or "My palette"
        out, n = name, 2
        while out in self._user or out in BUILT_IN_PALETTES:
            out, n = f"{name} {n}", n + 1
        return out

    def _palettes_changed(self, select: str) -> None:
        if self._dir is not None:
            try:
                save_palettes(self._dir, self._user)
            except OSError as e:
                _tell(self, "Palettes", f"Your palettes couldn't be saved:\n{e}\n\n"
                                        "Check there's room on the disk, then try again.")
        self._fill_palettes(select)

    def _add_colour(self, *_):
        hx = _hex(self._primary)
        kind, name = self._current_palette()
        if kind != "u":
            if not _ask(self, "Add colour", "The palettes that come with Paint studio can't "
                                            "be changed.\n\nMake a new palette of your own "
                                            "with this colour in it?"):
                return
            name = _ask_name(self, "New palette", "Name of the new palette:", "My colours")
            if name is None:
                return
            name = self._unique(name)
            self._user[name] = [hx]
        else:
            cols = self._user.setdefault(name, [])
            if hx in cols:
                return
            cols.append(hx)
        self._palettes_changed("u:" + name)

    def _new_palette(self, *_):
        name = _ask_name(self, "New palette", "Name of the new palette:", "My palette")
        if name is None:
            return
        name = self._unique(name)
        self._user[name] = []
        self._palettes_changed("u:" + name)

    def _from_picture(self, *_):
        if self._image_source is None:
            return
        try:
            img = self._image_source()
        except Exception:  # noqa: BLE001 - the editor couldn't give the picture
            img = None
        if isinstance(img, QPixmap):
            img = img.toImage()
        if not isinstance(img, QImage) or img.isNull():
            _tell(self, "From the picture", "There's no picture to take colours from yet.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            cols = palette_from_image(img, 12)
        finally:
            QApplication.restoreOverrideCursor()
        if not cols:
            _tell(self, "From the picture", "The picture is see-through all over, so there "
                                            "are no colours to take.")
            return
        name = self._unique("From the picture")
        self._user[name] = [_hex(c) for c in cols]
        self._palettes_changed("u:" + name)

    def _delete_palette(self, *_):
        kind, name = self._current_palette()
        if kind != "u" or name not in self._user:
            return
        if not _ask(self, "Delete palette",
                    f"Delete the palette “{name}”?\nThis can't be undone."):
            return
        names = list(self._user)
        i = names.index(name)
        del self._user[name]
        rest = list(self._user)
        select = ("u:" + rest[min(i, len(rest) - 1)] if rest
                  else "b:" + next(iter(BUILT_IN_PALETTES)))
        self._palettes_changed(select)

    def _remove_swatch(self, index: int) -> None:
        kind, name = self._current_palette()
        cols = self._user.get(name) if kind == "u" else None
        if cols is not None and 0 <= index < len(cols):
            del cols[index]
            self._palettes_changed("u:" + name)

    # ---- what's remembered between sessions
    def _load_state(self) -> dict:
        if self._dir is None:
            return {}
        try:
            data = json.loads((self._dir / STATE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self) -> None:
        if self._dir is None or self._loading:
            return
        data = {"recent": list(self._recent),
                "palette": self.palette_combo.currentData() or "",
                "values": self.values_button.isChecked(),
                "harmony": self._harmony_mode()}
        if data == self._saved_state:
            return
        try:
            _write_json(self._dir / STATE_FILE, data)
        except OSError:
            return  # only a convenience: tried again on the next change
        self._saved_state = data
