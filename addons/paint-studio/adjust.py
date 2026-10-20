"""Adjustments and filters for a layer: colour (hue, levels, contrast…),
blurs, sharpen, noise, glow and more, each with the settings its window
shows.

Pictures go in and come out as QImage ARGB32_Premultiplied (``FORMAT``);
the work is done on NumPy arrays (RGBA, straight alpha, 0..1) with OpenCV.
``apply`` uses no widgets, so it can run in a ``Job`` on a worker thread;
``AdjustDialog`` shows the settings and a live preview."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import partial
from typing import Callable, NamedTuple, Optional

import cv2
import numpy as np
from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QColorDialog, QComboBox, QDialog, QDoubleSpinBox,
                               QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout)

from .doc import FORMAT


# ------------------------------------------------------------------ settings
@dataclass
class Param:
    """One setting of an adjustment: a slider (``lo``..``hi`` in ``step``s),
    a colour (``default`` is "#rrggbb") or a choice (``choices`` are
    (key, label) pairs, ``default`` a key)."""
    key: str
    label: str
    lo: float
    hi: float
    default: float | str
    step: float = 1
    suffix: str = ""
    kind: str = "slider"            # "slider" | "colour" | "choice"
    choices: list = field(default_factory=list)
    tip: str = ""


@dataclass
class Adjustment:
    key: str
    label: str
    tip: str
    params: list[Param]


def _slider(key, label, lo, hi, default, step=1, suffix="", tip="") -> Param:
    return Param(key, label, lo, hi, default, step, suffix, "slider", [], tip)


def _colour(key, label, default, tip="") -> Param:
    return Param(key, label, 0, 0, default, 1, "", "colour", [], tip)


def _choice(key, label, choices, default, tip="") -> Param:
    return Param(key, label, 0, 0, default, 1, "", "choice", list(choices), tip)


_ADJUSTMENTS = [
    Adjustment("hsb", "Hue, saturation and brightness",
               "Turn the colours round the colour wheel, make them stronger or greyer, "
               "and lighter or darker.", [
                   _slider("hue", "Hue", -180, 180, 0, 1, "°",
                           "Turns every colour round the colour wheel: red towards yellow "
                           "one way, towards purple the other."),
                   _slider("saturation", "Saturation", -100, 100, 0, 1, "",
                           "Right: stronger colours. Left: greyer – all the way left is "
                           "black and white."),
                   _slider("brightness", "Brightness", -100, 100, 0, 1, "",
                           "Right: lighter (all the way is white). Left: darker (all the way "
                           "is black)."),
               ]),
    Adjustment("colour_balance", "Colour balance",
               "Warm up or cool down the picture: push its colours towards red, green or "
               "blue in its dark parts, its middle tones or its light parts. The picture "
               "keeps its brightness.", [
                   _choice("tones", "Tones", [("shadows", "Shadows (dark parts)"),
                                              ("midtones", "Midtones"),
                                              ("highlights", "Highlights (light parts)"),
                                              ("all", "All of the picture")], "midtones",
                           "Which parts of the picture change."),
                   _slider("cyan_red", "Cyan – Red", -100, 100, 0, 1, "",
                           "Left adds cyan, right adds red."),
                   _slider("magenta_green", "Magenta – Green", -100, 100, 0, 1, "",
                           "Left adds magenta, right adds green."),
                   _slider("yellow_blue", "Yellow – Blue", -100, 100, 0, 1, "",
                           "Left adds yellow, right adds blue."),
               ]),
    Adjustment("levels", "Levels",
               "Set the darkest and the lightest points and how bright the middle tones "
               "are – good for a faded or flat picture.", [
                   _choice("channel", "Channel", [("all", "All colours"), ("red", "Red"),
                                                  ("green", "Green"), ("blue", "Blue")], "all",
                           "Change all the colours together, or just one of them."),
                   _slider("black", "Black point", 0, 254, 0, 1, "",
                           "Everything this dark or darker becomes black."),
                   _slider("white", "White point", 1, 255, 255, 1, "",
                           "Everything this light or lighter becomes white."),
                   _slider("gamma", "Midtones", 0.1, 3.0, 1.0, 0.05, "",
                           "Above 1 lightens the middle tones, below 1 darkens them; black "
                           "and white stay as they are."),
               ]),
    Adjustment("curves_contrast", "Contrast and exposure",
               "More or less contrast with a gentle S-shaped curve, and exposure as if the "
               "picture had been taken with more or less light.", [
                   _slider("contrast", "Contrast", -100, 100, 0, 1, "",
                           "Right: darks darker and lights lighter. Left: flatter and greyer."),
                   _slider("exposure", "Exposure", -2, 2, 0, 0.1, " stops",
                           "Each stop doubles (right) or halves (left) the light."),
               ]),
    Adjustment("blur", "Gaussian blur", "Soften the whole picture evenly.", [
        _slider("radius", "Radius", 0, 100, 10, 1, " px", "How far the blur spreads."),
    ]),
    Adjustment("motion_blur", "Motion blur",
               "Smear the picture in one direction, as if it moved fast.", [
                   _slider("distance", "Distance", 0, 200, 30, 1, " px",
                           "How long the smear is."),
                   _slider("angle", "Angle", 0, 360, 0, 1, "°",
                           "The direction of the smear: 0° is side to side, 90° is up and "
                           "down."),
               ]),
    Adjustment("sharpen", "Sharpen", "Make edges and fine details crisper.", [
        _slider("amount", "Amount", 0, 300, 100, 1, " %", "How much crisper."),
        _slider("radius", "Radius", 0.5, 10, 1.5, 0.5, " px",
                "Small for fine detail such as hair, larger for bigger shapes."),
    ]),
    Adjustment("noise", "Noise", "Add grain, like film or rough paper.", [
        _slider("amount", "Amount", 0, 100, 20, 1, "", "How strong the grain is."),
        _choice("monochrome", "Monochrome", [("yes", "Yes – grey grain"),
                                             ("no", "No – coloured grain")], "yes",
                "Grey grain looks like film; coloured grain like a noisy photo."),
    ]),
    Adjustment("glow", "Bloom / glow",
               "Make the bright parts glow softly, as if light were spilling out of them.", [
                   _slider("threshold", "Threshold", 0, 255, 170, 1, "",
                           "Only parts brighter than this glow. Lower it to make more of "
                           "the picture glow."),
                   _slider("radius", "Radius", 1, 100, 25, 1, " px", "How far the glow spreads."),
                   _slider("strength", "Strength", 0, 200, 80, 1, " %", "How bright the glow is."),
               ]),
    Adjustment("gradient_map", "Gradient map",
               "Recolour the picture by brightness: its dark parts take the first colour, its "
               "light parts the second and the rest a blend of the two.", [
                   _colour("shadows", "Shadows colour", "#1b1036",
                           "The colour the dark parts become."),
                   _colour("highlights", "Highlights colour", "#ffe4a8",
                           "The colour the light parts become."),
                   _slider("strength", "Strength", 0, 100, 100, 1, " %",
                           "Lower it to let some of the picture's own colours through."),
               ]),
    Adjustment("posterize", "Posterise",
               "Cut the colours down to a few flat steps, like a screen print.", [
                   _slider("levels", "Levels", 2, 32, 6, 1, "",
                           "How many steps each colour has. Fewer steps look bolder."),
               ]),
    Adjustment("vignette", "Vignette", "Darken the edges to draw the eye to the middle.", [
        _slider("amount", "Amount", 0, 100, 50, 1, " %", "How dark the edges get."),
        _slider("size", "Size", 10, 100, 60, 1, " %", "How much of the middle stays clear."),
    ]),
    Adjustment("chromatic", "Chromatic aberration",
               "Split the red and the blue apart towards the edges, like an old or cheap "
               "camera lens.", [
                   _slider("distance", "Distance", 0, 30, 6, 1, " px",
                           "How far apart the colours are at the corners."),
               ]),
    Adjustment("invert", "Invert colours",
               "Turn every colour into its opposite, like a photo negative.", []),
]

ADJUSTMENTS: dict[str, Adjustment] = {a.key: a for a in _ADJUSTMENTS}

# These spread paint (and so its transparency) to their neighbours.
SPREADS = frozenset({"blur", "motion_blur", "glow", "chromatic"})


def defaults(key: str) -> dict:
    """The settings an adjustment starts with."""
    return {p.key: p.default for p in ADJUSTMENTS[key].params}


def _settings(adj: Adjustment, params: Optional[dict]) -> dict:
    """``params`` with anything missing or out of range set right."""
    params = params or {}
    out = {}
    for prm in adj.params:
        v = params.get(prm.key, prm.default)
        if prm.kind == "slider":
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = float(prm.default)
            if not math.isfinite(v):
                v = float(prm.default)
            v = min(max(v, float(prm.lo)), float(prm.hi))
        elif prm.kind == "colour":
            c = v if isinstance(v, QColor) else QColor(str(v))
            v = c.name() if c.isValid() else prm.default
        else:
            if v not in [k for k, _ in prm.choices]:
                v = prm.default
        out[prm.key] = v
    return out


# ------------------------------------------------------------------ arrays
# Inside, a picture is four planes [red, green, blue, alpha], each an HxW
# float32 array (straight alpha, 0..1): NumPy is many times faster on whole
# planes than on the colours of an HxWx4 array. Effects never change the
# planes they're given.

_FROM_U8 = (np.arange(256, dtype=np.float32) / 255).astype(np.float32)


def _planes_of(img: QImage) -> list[np.ndarray]:
    rgba = img.convertToFormat(QImage.Format_RGBA8888)
    w, h, bpl = rgba.width(), rgba.height(), rgba.bytesPerLine()
    raw = np.frombuffer(rgba.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)
    return [cv2.LUT(c, _FROM_U8) for c in cv2.split(raw[:, :w * 4].reshape(h, w, 4))]


def _image_of(planes: list[np.ndarray]) -> QImage:
    h, w = planes[0].shape
    if not h or not w:
        return QImage()
    u8 = cv2.merge([cv2.convertScaleAbs(np.maximum(c, 0.0), alpha=255.0) for c in planes])
    img = QImage(u8.data, w, h, w * 4, QImage.Format_RGBA8888)
    return img.convertToFormat(FORMAT)          # a copy with its own pixels


def to_array(img: QImage) -> np.ndarray:
    """HxWx4 float32 RGBA, straight (not premultiplied) alpha, 0..1."""
    if img.isNull() or not img.width() or not img.height():
        return np.zeros((max(0, img.height()), max(0, img.width()), 4), np.float32)
    return cv2.merge(_planes_of(img))


def from_array(a: np.ndarray) -> QImage:
    """An HxWx4 straight-alpha array (clipped to 0..1) as a QImage in FORMAT."""
    a = np.asarray(a, dtype=np.float32)
    if a.ndim != 3 or a.shape[2] != 4:
        raise ValueError("from_array needs an array shaped height × width × 4")
    if not a.shape[0] or not a.shape[1]:
        return QImage()
    return _image_of(list(cv2.split(np.ascontiguousarray(a))))


class _Area(NamedTuple):
    """Where the planes sit in the whole picture, and the picture's size
    (for effects measured from the middle: vignette, chromatic aberration)."""
    x: int
    y: int
    width: int
    height: int


def _gray(c: list[np.ndarray]) -> np.ndarray:
    """Brightness (HxW) of the colour planes."""
    y = cv2.addWeighted(c[0], 0.299, c[1], 0.587, 0.0)
    return cv2.addWeighted(y, 1.0, c[2], 0.114, 0.0)


def _premultiply(c: list[np.ndarray]) -> list[np.ndarray]:
    a = c[3]
    return [c[0] * a, c[1] * a, c[2] * a, a.copy()]


def _unpremultiply(c: list[np.ndarray]) -> list[np.ndarray]:
    """Straight colours again (in place) – blurring premultiplied colour
    keeps dark fringes away from the edges of the paint."""
    a = c[3]
    inv = np.zeros_like(a)
    np.divide(1.0, a, out=inv, where=a > 1e-6)
    for x in c[:3]:
        x *= inv
        np.clip(x, 0.0, 1.0, out=x)
    np.clip(a, 0.0, 1.0, out=a)
    return c


def _gauss1(x: np.ndarray, sigma: float) -> np.ndarray:
    """A Gaussian blur of one plane (a new array). Big blurs are made on a
    smaller copy and enlarged again: the same look, much faster."""
    if sigma < 0.2:
        return x.copy()
    if sigma <= 3.0:
        return cv2.GaussianBlur(x, (0, 0), sigma, borderType=cv2.BORDER_REPLICATE)
    h, w = x.shape
    f = sigma / 3.0
    sw, sh = max(1, round(w / f)), max(1, round(h / f))
    fx, fy = w / sw, h / sh
    small = cv2.resize(x, (sw, sh), interpolation=cv2.INTER_AREA)
    # shrinking and enlarging blur a little on their own: take that off
    sx = math.sqrt(max(sigma * sigma - fx * fx / 4, 0.25)) / fx
    sy = math.sqrt(max(sigma * sigma - fy * fy / 4, 0.25)) / fy
    small = cv2.GaussianBlur(small, (0, 0), sx, sigmaY=sy, borderType=cv2.BORDER_REPLICATE)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def _gauss(c: list[np.ndarray], sigma: float) -> list[np.ndarray]:
    return [_gauss1(x, sigma) for x in c]


def _shift(x: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """A plane read ``dx``, ``dy`` pixels further on (sub-pixel)."""
    h, w = x.shape
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(x, m, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE)


def _curve(x: np.ndarray, fn: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
    """``fn`` (0..1 → 0..1) on every value of a plane, through a table of
    256 steps – exact, as the pictures have 256 steps a colour."""
    lut = np.asarray(fn(np.arange(256, dtype=np.float64) / 255.0), np.float32)
    return cv2.LUT(cv2.convertScaleAbs(np.maximum(x, 0.0), alpha=255.0), lut)


def _smooth(t: np.ndarray) -> np.ndarray:
    return t * t * (3.0 - 2.0 * t)


def _rgbf(hex_colour: str) -> list[float]:
    c = QColor(hex_colour)
    return [c.redF(), c.greenF(), c.blueF()]


# ------------------------------------------------------------------ effects
# Each takes the planes [r, g, b, a], the settings and its _Area, and
# returns new planes of the same size (unchanged ones may be shared).

def _hsb(c, p, area):
    hue, sat, bri = p["hue"], p["saturation"] / 100, p["brightness"] / 100
    r, g, b, a = c
    if hue or sat > 0 or bri > 0:
        h, s, v = cv2.split(cv2.cvtColor(cv2.merge([r, g, b]), cv2.COLOR_RGB2HSV))  # H 0..360
        if hue:
            h += hue
            np.mod(h, 360.0, out=h)
        if sat > 0:                        # stronger colours; greys stay grey
            s = 1.0 - cv2.pow(1.0 - s, 1.0 + 3.0 * sat)
        if bri > 0:                        # lighter, paling to white at the top
            v *= 1.0 - bri
            v += bri
            s *= 1.0 - bri * bri
        r, g, b = cv2.split(cv2.cvtColor(cv2.merge([h, s, v]), cv2.COLOR_HSV2RGB))
    elif sat < 0 or bri < 0:
        r, g, b = r.copy(), g.copy(), b.copy()
    if sat < 0:                            # towards grey of the same brightness
        y = _gray([r, g, b])
        y *= -sat
        for x in (r, g, b):
            x *= 1.0 + sat
            x += y
    if bri < 0:
        for x in (r, g, b):
            x *= 1.0 + bri
    return [r, g, b, a]


def _colour_balance(c, p, area):
    shift = np.array([p["cyan_red"], p["magenta_green"], p["yellow_blue"]], np.float64) * 0.003
    if not shift.any():
        return list(c)
    shift -= shift @ np.array([0.299, 0.587, 0.114])      # a tint that keeps the brightness
    tones = p["tones"]
    if tones == "all":
        return [c[i] + float(shift[i]) for i in range(3)] + [c[3]]
    lum = _gray(c)
    if tones == "shadows":
        w = 1.0 - _smooth(np.clip(lum * (1 / 0.6), 0.0, 1.0))
    elif tones == "highlights":
        w = _smooth(np.clip((lum - 0.4) * (1 / 0.6), 0.0, 1.0))
    else:
        w = 4.0 * lum * (1.0 - lum)
    return [cv2.scaleAdd(w, float(shift[i]), c[i]) for i in range(3)] + [c[3]]


def _levels(c, p, area):
    lo, hi, gamma = p["black"] / 255, p["white"] / 255, p["gamma"]
    if lo <= 0 and hi >= 1 and abs(gamma - 1) < 1e-6:
        return list(c)
    hi = max(hi, lo + 1 / 255)

    def fn(x):
        return np.clip((x - lo) / (hi - lo), 0.0, 1.0) ** (1.0 / gamma)

    which = {"red": (0,), "green": (1,), "blue": (2,)}.get(p["channel"], (0, 1, 2))
    return [_curve(x, fn) if i in which else x for i, x in enumerate(c[:3])] + [c[3]]


def _contrast(c, p, area):
    k, e = p["contrast"] / 100, p["exposure"]
    if not k and not e:
        return list(c)
    gain = 2.0 ** (e / 2.2)                 # a stop of light, on gamma-encoded colour
    power = 4.0 ** k                        # > 1: an S-curve, < 1: flatter

    def fn(x):
        x = np.clip(x * gain, 0.0, 1.0)
        if k:
            xk = x ** power
            x = xk / np.maximum(xk + (1.0 - x) ** power, 1e-12)
        return x

    return [_curve(x, fn) for x in c[:3]] + [c[3]]


def _blur(c, p, area):
    sigma = p["radius"] / 2
    if sigma < 0.2:
        return list(c)
    return _unpremultiply(_gauss(_premultiply(c), sigma))


def _motion_blur(c, p, area):
    dist = p["distance"]
    if dist < 1:
        return list(c)
    t = math.radians(p["angle"])
    ux, uy = math.cos(t), -math.sin(t)            # 90° is straight up
    h, w = c[0].shape
    # the edges carried outwards, so nothing below reads past them
    px = math.ceil(abs(ux) * dist / 2) + 2
    py = math.ceil(abs(uy) * dist / 2) + 2
    size = (w + 2 * px, h + 2 * py)
    flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
    # the average of 2^n copies spread evenly along the line, made by
    # doubling: each round adds a copy of itself moved twice as far; then
    # moved back by half the line, so the smear is centred
    n = max(1, math.ceil(math.log2(dist + 1)))
    gap = dist / (2 ** n - 1)
    moves = [np.float32([[1, 0, ux * gap * 2 ** k], [0, 1, uy * gap * 2 ** k]]) for k in range(n)]
    back = np.float32([[1, 0, -ux * dist / 2], [0, 1, -uy * dist / 2]])
    out = []
    for x in _premultiply(c):
        acc = cv2.copyMakeBorder(x, py, py, px, px, cv2.BORDER_REPLICATE)
        tmp = np.empty_like(acc)                  # two buffers, used over and over
        for m in moves:
            cv2.warpAffine(acc, m, size, dst=tmp, flags=flags, borderMode=cv2.BORDER_REPLICATE)
            cv2.addWeighted(acc, 0.5, tmp, 0.5, 0.0, dst=acc)
        cv2.warpAffine(acc, back, size, dst=tmp, flags=flags, borderMode=cv2.BORDER_REPLICATE)
        out.append(np.ascontiguousarray(tmp[py:py + h, px:px + w]))
    return _unpremultiply(out)


def _sharpen(c, p, area):
    amount = p["amount"] / 100
    if amount <= 0:
        return list(c)
    soft = _unpremultiply(_gauss(_premultiply(c), p["radius"]))
    # c + amount·(c − soft)
    return [cv2.addWeighted(c[i], 1.0 + amount, soft[i], -amount, 0.0) for i in range(3)] + [c[3]]


def _noise(c, p, area):
    amount = p["amount"] / 100 * 0.25
    if amount <= 0:
        return list(c)
    h, w = c[0].shape
    rng = np.random.default_rng(1729)             # the same grain every time
    if p["monochrome"] == "yes":
        n = rng.standard_normal((h, w), dtype=np.float32)
        return [cv2.scaleAdd(n, amount, x) for x in c[:3]] + [c[3]]
    return [cv2.scaleAdd(rng.standard_normal((h, w), dtype=np.float32), amount, x)
            for x in c[:3]] + [c[3]]


def _glow(c, p, area):
    strength = p["strength"] / 100
    if strength <= 0:
        return list(c)
    thr = p["threshold"] / 255
    pm = _premultiply(c)
    w = _gray(c)
    w -= thr
    w *= 1.0 / max(1.0 - thr, 1 / 255)
    np.clip(w, 0.0, 1.0, out=w)
    glow = _gauss([x * w for x in pm], max(p["radius"] / 2, 0.5))
    out = []
    for x, gl in zip(pm, glow, strict=True):
        gl *= strength
        np.clip(gl, 0.0, 1.0, out=gl)
        t = 1.0 - x                               # screen: a + b − a·b = a + b·(1 − a)
        t *= gl
        t += x
        out.append(t)
    return _unpremultiply(out)


def _gradient_map(c, p, area):
    s = p["strength"] / 100
    if s <= 0:
        return list(c)
    c0, c1 = _rgbf(p["shadows"]), _rgbf(p["highlights"])
    lum = _gray(c)
    out = []
    for i in range(3):
        mapped = lum * (s * (c1[i] - c0[i]))
        mapped += s * c0[i]
        out.append(cv2.scaleAdd(c[i], 1.0 - s, mapped))   # c·(1−s) + mapped·s
    return out + [c[3]]


def _posterize(c, p, area):
    n = int(round(p["levels"]))

    def fn(x):
        return np.minimum(np.floor(x * n), n - 1) / (n - 1)

    return [_curve(x, fn) for x in c[:3]] + [c[3]]


def _vignette(c, p, area):
    amount = p["amount"] / 100
    if amount <= 0:
        return list(c)
    h, w = c[0].shape
    cx, cy = area.width / 2, area.height / 2
    xs = ((np.arange(area.x, area.x + w, dtype=np.float32) + 0.5 - cx) / cx) ** 2
    ys = ((np.arange(area.y, area.y + h, dtype=np.float32) + 0.5 - cy) / cy) ** 2
    r = np.sqrt(ys[:, None] + xs[None, :])          # 1 at the middle of each edge
    inner = p["size"] / 100 * 1.2
    f = _smooth(np.clip((r - inner) * (1 / 0.6), 0.0, 1.0))
    f *= -amount
    f += 1.0
    return [x * f for x in c[:3]] + [c[3]]


def _chromatic(c, p, area):
    d = p["distance"]
    if d < 0.05:
        return list(c)
    h, w = c[0].shape
    cx, cy = (area.width - 1) / 2, (area.height - 1) / 2
    k = d / max(math.hypot(cx, cy), 1.0)            # d pixels apart at the corners
    xs = np.arange(area.x, area.x + w, dtype=np.float32) - np.float32(cx)
    ys = np.arange(area.y, area.y + h, dtype=np.float32) - np.float32(cy)
    pm = _premultiply(c)

    def sample(planes, scale):
        mx = np.empty((h, w), np.float32)
        mx[:] = xs * scale + (cx - area.x)
        my = np.empty((h, w), np.float32)
        my[:] = (ys * scale + (cy - area.y))[:, None]
        return [cv2.remap(x, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                for x in planes]

    red, red_a = sample([pm[0], pm[3]], 1 - k)       # red grows outwards
    blue, blue_a = sample([pm[2], pm[3]], 1 + k)     # blue shrinks inwards
    alpha = np.maximum(np.maximum(red_a, pm[3]), blue_a)
    return _unpremultiply([red, pm[1], blue, alpha])


def _invert(c, p, area):
    return [1.0 - x for x in c[:3]] + [c[3]]


def _no_pad(p) -> int:
    return 0


# key: (effect, how far it reads round each pixel, in pixels)
_EFFECTS = {
    "hsb": (_hsb, _no_pad),
    "colour_balance": (_colour_balance, _no_pad),
    "levels": (_levels, _no_pad),
    "curves_contrast": (_contrast, _no_pad),
    "blur": (_blur, lambda p: math.ceil(1.5 * p["radius"]) + 4),
    "motion_blur": (_motion_blur, lambda p: math.ceil(p["distance"] / 2) + 4),
    "sharpen": (_sharpen, lambda p: math.ceil(3 * p["radius"]) + 4),
    "noise": (_noise, _no_pad),
    "glow": (_glow, lambda p: math.ceil(1.5 * p["radius"]) + 4),
    "gradient_map": (_gradient_map, _no_pad),
    "posterize": (_posterize, _no_pad),
    "vignette": (_vignette, _no_pad),
    "chromatic": (_chromatic, lambda p: math.ceil(p["distance"]) + 3),
    "invert": (_invert, _no_pad),
}


# ------------------------------------------------------------------ apply
def _mask_array(mask: QImage, w: int, h: int) -> np.ndarray:
    m = mask if mask.format() == QImage.Format_Grayscale8 else \
        mask.convertToFormat(QImage.Format_Grayscale8)
    if m.width() != w or m.height() != h:
        m = m.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    bpl = m.bytesPerLine()
    raw = np.frombuffer(m.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)
    return np.array(raw[:, :w])


def _bounds(m: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    rows = np.flatnonzero(m.any(axis=1))
    if not rows.size:
        return None
    cols = np.flatnonzero(m.any(axis=0))
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def _mix(orig: list, adj: list, m8: np.ndarray, spreads: bool) -> list:
    """``orig`` where the mask is 0, ``adj`` where it's 255, a blend between."""
    if (m8 == 255).all():
        return adj
    m = np.take(_FROM_U8, m8)
    if not spreads:                        # the same transparency: mix the colours
        return [o + (j - o) * m for o, j in zip(orig[:3], adj[:3], strict=True)] + [orig[3]]
    # the transparency changed too: mix premultiplied, so paint spreading
    # into an empty part doesn't take on the empty part's (black) colour
    wo = orig[3] * (1.0 - m)
    wj = adj[3] * m
    out = [o * wo + j * wj for o, j in zip(orig[:3], adj[:3], strict=True)] + [wo + wj]
    return _unpremultiply(out)


def apply(key: str, img: QImage, params: Optional[dict], mask: Optional[QImage] = None) -> QImage:
    """A new picture (FORMAT, the same size) with the adjustment ``key`` made
    with ``params`` (missing ones take their defaults). ``mask``: a
    Grayscale8 picture the same size – 255 the full effect, 0 none (a
    selection, soft edges allowed); only its part is worked on."""
    adj = ADJUSTMENTS[key]
    effect, pad_of = _EFFECTS[key]
    p = _settings(adj, params)
    src = img if img.format() == FORMAT else img.convertToFormat(FORMAT)
    w, h = src.width(), src.height()
    if src.isNull() or not w or not h:
        return src.copy()
    if mask is None or mask.isNull():
        return _image_of(effect(_planes_of(src), p, _Area(0, 0, w, h)))
    m = _mask_array(mask, w, h)
    box = _bounds(m)
    if box is None:                         # nothing selected
        return src.copy()
    x0, y0, x1, y1 = box
    pad = max(0, int(pad_of(p)))
    cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
    cx1, cy1 = min(w, x1 + pad), min(h, y1 + pad)
    planes = _planes_of(src.copy(QRect(cx0, cy0, cx1 - cx0, cy1 - cy0)))
    done = effect(planes, p, _Area(cx0, cy0, w, h))
    inner = (slice(y0 - cy0, y1 - cy0), slice(x0 - cx0, x1 - cx0))
    piece = _image_of(_mix([x[inner] for x in planes], [x[inner] for x in done],
                           m[y0:y1, x0:x1], key in SPREADS))
    out = src.copy()
    painter = QPainter(out)
    painter.setCompositionMode(QPainter.CompositionMode_Source)
    painter.drawImage(x0, y0, piece)
    painter.end()
    return out


# ------------------------------------------------------------------ the window
def _decimals(step: float) -> int:
    s = f"{step:g}"
    return len(s.split(".")[1]) if "." in s else 0


def _swatch(colour: str) -> QIcon:
    pm = QPixmap(16, 16)
    pm.fill(QColor(colour))
    return QIcon(pm)


class AdjustDialog(QDialog):
    """The settings of one adjustment, with the picture changing as you
    move them (``preview`` gets the full-size result a moment after each
    change). After ``exec()`` returns Accepted, ``result_image`` is the
    finished picture; on Cancel the caller puts the picture back."""

    DELAY_MS = 120

    def __init__(self, parent, key: str, image: QImage, mask: Optional[QImage],
                 preview: Callable[[QImage], None]):
        super().__init__(parent)
        self.key = key
        self.adjustment = ADJUSTMENTS[key]
        self.result_image: Optional[QImage] = None
        self._image = image if image.format() == FORMAT else image.convertToFormat(FORMAT)
        self._mask = mask
        self._big = image.width() * image.height() > 4_000_000
        self._preview = preview
        self._values = defaults(key)
        self._controls: dict[str, tuple] = {}
        self._cached: Optional[tuple] = None          # (settings, picture)
        self.setWindowTitle(self.adjustment.label)
        self.setMinimumWidth(460)

        lay = QVBoxLayout(self)
        text = self.adjustment.tip
        if mask is not None:
            text += " Only the selected part changes."
        hint = QLabel(text)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        for row, prm in enumerate(self.adjustment.params):
            self._add_row(grid, row, prm)
        lay.addLayout(grid)
        if not self.adjustment.params:
            none = QLabel("There's nothing to set: press Apply to keep the change.")
            none.setWordWrap(True)
            lay.addWidget(none)

        self._status = QLabel()
        self._status.setObjectName("Hint")
        self._status.setWordWrap(True)
        self._status.hide()
        lay.addWidget(self._status)
        lay.addStretch(1)

        buttons = QHBoxLayout()
        reset = QPushButton("Reset")
        reset.setToolTip("Put every setting back to how it started")
        reset.setAutoDefault(False)
        reset.clicked.connect(self.reset)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setToolTip("Close and leave the picture as it was")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        ok = QPushButton("Apply")
        ok.setToolTip("Keep this change")
        ok.setProperty("kind", "primary")
        ok.setDefault(True)
        ok.clicked.connect(self._apply)
        buttons.addWidget(ok)
        lay.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.DELAY_MS)
        self._timer.timeout.connect(self._update_preview)
        self._timer.start()                       # show the starting settings straight away

    # ---------------------------------------------------------- controls
    def _add_row(self, grid: QGridLayout, row: int, prm: Param) -> None:
        label = QLabel(prm.label)
        label.setToolTip(prm.tip)
        grid.addWidget(label, row, 0)
        if prm.kind == "slider":
            slider = QSlider(Qt.Horizontal)
            ticks = max(1, round((prm.hi - prm.lo) / prm.step))
            slider.setRange(0, ticks)
            slider.setPageStep(max(1, ticks // 10))
            slider.setValue(round((float(prm.default) - prm.lo) / prm.step))
            slider.setToolTip(prm.tip)
            spin = QDoubleSpinBox()
            spin.setRange(prm.lo, prm.hi)
            spin.setDecimals(_decimals(prm.step))
            spin.setSingleStep(prm.step)
            spin.setSuffix(prm.suffix)
            spin.setValue(float(prm.default))
            spin.setKeyboardTracking(False)
            spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            spin.setMinimumWidth(96)
            spin.setToolTip(prm.tip)
            slider.valueChanged.connect(partial(self._slider_moved, prm.key))
            spin.valueChanged.connect(partial(self._spin_changed, prm.key))
            grid.addWidget(slider, row, 1)
            grid.addWidget(spin, row, 2)
            self._controls[prm.key] = (prm, slider, spin)
        elif prm.kind == "colour":
            button = QPushButton()
            button.setToolTip(f"{prm.tip} Click to choose it.".strip())
            button.setAutoDefault(False)
            button.clicked.connect(partial(self._pick_colour, prm.key))
            grid.addWidget(button, row, 1, 1, 2)
            self._controls[prm.key] = (prm, button)
            self._show_colour(prm.key)
        else:
            combo = QComboBox()
            for k, text in prm.choices:
                combo.addItem(text, k)
            combo.setCurrentIndex(max(0, combo.findData(prm.default)))
            combo.setToolTip(prm.tip)
            combo.currentIndexChanged.connect(partial(self._choice_changed, prm.key))
            grid.addWidget(combo, row, 1, 1, 2)
            self._controls[prm.key] = (prm, combo)

    def _slider_moved(self, key: str, tick: int) -> None:
        prm, _slider, spin = self._controls[key]
        value = round(prm.lo + tick * prm.step, _decimals(prm.step))
        spin.blockSignals(True)
        spin.setValue(value)
        spin.blockSignals(False)
        self._values[key] = value
        self._changed()

    def _spin_changed(self, key: str, value: float) -> None:
        prm, slider, _spin = self._controls[key]
        slider.blockSignals(True)
        slider.setValue(round((value - prm.lo) / prm.step))
        slider.blockSignals(False)
        self._values[key] = float(value)
        self._changed()

    def _choice_changed(self, key: str, index: int) -> None:
        prm, combo = self._controls[key]
        self._values[key] = combo.itemData(index) or prm.default
        self._changed()

    def _show_colour(self, key: str) -> None:
        _prm, button = self._controls[key]
        colour = str(self._values[key])
        button.setIcon(_swatch(colour))
        button.setText(colour.upper())

    def _pick_colour(self, key: str) -> None:
        prm, _button = self._controls[key]
        before = self._values[key]
        d = QColorDialog(QColor(before), self)
        d.setWindowTitle(prm.label)
        d.setOption(QColorDialog.DontUseNativeDialog, True)
        d.currentColorChanged.connect(partial(self._colour_live, key))
        if d.exec():
            self.set_value(key, d.selectedColor().name())
        else:
            self.set_value(key, before)
        d.deleteLater()

    def _colour_live(self, key: str, colour: QColor) -> None:
        if colour.isValid():
            self.set_value(key, colour.name())

    def _changed(self) -> None:
        self._timer.start()                       # restarts: one preview once you pause

    # ---------------------------------------------------------- public
    @property
    def params(self) -> dict:
        """The settings as they are now."""
        return dict(self._values)

    def set_value(self, key: str, value) -> None:
        """Change one setting (and its control) as if the user had."""
        entry = self._controls.get(key)
        if entry is None:
            return
        prm = entry[0]
        value = _settings(Adjustment("", "", "", [prm]), {key: value})[key]
        self._values[key] = value
        if prm.kind == "slider":
            _prm, slider, spin = entry
            for w in (slider, spin):
                w.blockSignals(True)
            slider.setValue(round((value - prm.lo) / prm.step))
            spin.setValue(value)
            for w in (slider, spin):
                w.blockSignals(False)
        elif prm.kind == "colour":
            self._show_colour(key)
        else:
            combo = entry[1]
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.blockSignals(False)
        self._changed()

    def reset(self) -> None:
        for prm in self.adjustment.params:
            self.set_value(prm.key, prm.default)
        self._changed()

    # ---------------------------------------------------------- the picture
    def _compute(self) -> QImage:
        settings = tuple(sorted((k, str(v)) for k, v in self._values.items()))
        if self._cached is not None and self._cached[0] == settings:
            return self._cached[1]
        img = apply(self.key, self._image, self._values, self._mask)
        self._cached = (settings, img)
        return img

    def _problem(self, text: str, error: Exception) -> None:
        self._status.setText(text)
        self._status.setToolTip(f"{type(error).__name__}: {error}")
        self._status.show()

    def _update_preview(self) -> None:
        try:
            if self._big:
                QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                img = self._compute()
            except Exception as e:  # noqa: BLE001 - shown, not fatal
                self._problem("This can't be shown with these settings – try other ones.", e)
                return
            finally:
                if self._big:
                    QApplication.restoreOverrideCursor()
            self._status.hide()
            try:
                self._preview(img)
            except Exception as e:  # noqa: BLE001
                self._problem("The picture couldn't be updated – press Apply to see the change.",
                              e)
        except RuntimeError:                      # the window is going away
            return

    def _apply(self) -> None:
        self._timer.stop()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            img = self._compute()
        except Exception as e:  # noqa: BLE001
            self._problem("This can't be made with these settings – try other ones.", e)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.result_image = img
        self.accept()

    def done(self, result: int) -> None:
        self._timer.stop()
        super().done(result)
