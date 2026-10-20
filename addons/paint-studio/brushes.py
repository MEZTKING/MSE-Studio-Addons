"""Brushes: what a brush is (size, how pressure changes it, its tip, the
grain of the paper it shows, how wet it is…), the brush library, and the
pictures a stroke is made of (its tips and grain textures).

Tips and textures are made with NumPy once and kept (they're small)."""
from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

from .doc import FORMAT

SHAPES = {"round": "Round", "square": "Square", "bristle": "Bristles", "chalk": "Chalk",
          "splatter": "Splatter", "star": "Sparkle"}
GRAINS = {"": "None", "paper": "Paper", "canvas": "Canvas", "rough": "Rough",
          "sponge": "Sponge", "noise": "Fine noise"}
MODES = {"paint": "Paint", "smudge": "Smudge", "blur": "Blur", "erase": "Erase"}
STROKE_BLENDS = {"normal": "Normal", "multiply": "Multiply (darkens)",
                 "add": "Add (glows)", "screen": "Screen (lightens)"}
CATEGORIES = ["Sketching", "Inking", "Painting", "Airbrushing", "Watercolour", "Textures",
              "Effects", "Smudge & blend", "Erasers"]


@dataclass
class Brush:
    name: str
    category: str = "Painting"
    size: float = 24.0              # width in pixels at full pressure
    min_size: float = 0.3           # size with no pressure (a part of size)
    opacity: float = 1.0            # the most a stroke covers
    flow: float = 1.0               # how much each touch of the tip adds
    min_flow: float = 1.0           # flow with no pressure (a part of flow)
    hardness: float = 0.8           # 0 soft edge … 1 hard edge
    spacing: float = 0.1            # gap between tips, a part of the size
    roundness: float = 1.0          # 1 round … 0.1 flat
    angle: float = 0.0              # degrees
    follow: bool = False            # the tip turns with the stroke
    jitter_size: float = 0.0        # 0 … 1
    jitter_angle: float = 0.0       # 0 … 1 (up to half a turn)
    jitter_opacity: float = 0.0     # 0 … 1
    jitter_hue: float = 0.0         # 0 … 1 (up to a third of the colour wheel)
    scatter: float = 0.0            # tips land up to this many sizes away
    count: int = 1                  # tips each step (sprays)
    shape: str = "round"
    grain: str = ""
    grain_scale: float = 1.0
    grain_depth: float = 0.6
    smoothing: float = 0.25         # 0 … 1: steadier lines (StreamLine)
    taper: float = 0.0              # 0 … 1: the start of a line grows in
    mode: str = "paint"
    wet: float = 0.0                # paint: picks up colour underneath; smudge/blur: strength
    wet_edges: float = 0.0          # watercolour: darker rims
    build_up: bool = False          # airbrush: keeps adding past its opacity
    blend: str = "normal"           # how the stroke mixes with the layer
    pressure_size: bool = True
    pressure_opacity: bool = False
    builtin: bool = False

    def copy(self, **changes) -> "Brush":
        d = asdict(self)
        d.update(changes)
        return Brush(**d)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("builtin", None)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Brush":
        known = {f.name for f in fields(Brush)}
        b = Brush(**{k: v for k, v in d.items() if k in known and k != "builtin"})
        b.size = max(1.0, min(1000.0, float(b.size)))
        b.spacing = max(0.02, min(3.0, float(b.spacing)))
        b.count = max(1, min(40, int(b.count)))
        if b.shape not in SHAPES:
            b.shape = "round"
        if b.grain not in GRAINS:
            b.grain = ""
        if b.mode not in MODES:
            b.mode = "paint"
        if b.blend not in STROKE_BLENDS:
            b.blend = "normal"
        return b


def _b(name, category, **kw) -> Brush:
    return Brush(name, category, builtin=True, **kw)


LIBRARY: list[Brush] = [
    # sketching
    _b("HB pencil", "Sketching", size=5, min_size=0.55, opacity=0.9, flow=0.75, min_flow=0.35,
       hardness=0.9, spacing=0.08, shape="chalk", grain="paper", grain_depth=0.55,
       smoothing=0.15, pressure_opacity=True),
    _b("6B pencil", "Sketching", size=12, min_size=0.5, opacity=1, flow=0.8, min_flow=0.3,
       hardness=0.75, spacing=0.08, shape="chalk", grain="paper", grain_depth=0.75,
       smoothing=0.1, pressure_opacity=True),
    _b("Technical pen", "Sketching", size=4, min_size=0.85, hardness=1, spacing=0.05,
       smoothing=0.5),
    _b("Fine liner", "Sketching", size=3, min_size=0.7, hardness=0.95, spacing=0.05,
       smoothing=0.6, taper=0.2),
    # inking
    _b("Studio pen", "Inking", size=12, min_size=0.12, hardness=1, spacing=0.04,
       smoothing=0.55, taper=0.35),
    _b("Ink brush", "Inking", size=22, min_size=0.05, hardness=0.95, spacing=0.04,
       roundness=0.75, angle=30, smoothing=0.45, taper=0.5),
    _b("Dry ink", "Inking", size=18, min_size=0.2, hardness=0.9, spacing=0.06,
       grain="rough", grain_depth=0.7, smoothing=0.35, taper=0.3),
    _b("Marker", "Inking", size=28, min_size=0.9, opacity=0.65, hardness=0.85, spacing=0.05,
       roundness=0.35, angle=45, smoothing=0.3, blend="multiply"),
    # painting
    _b("Round brush", "Painting", size=34, min_size=0.4, opacity=1, flow=0.85, min_flow=0.5,
       hardness=0.7, spacing=0.08, smoothing=0.2, pressure_opacity=True),
    _b("Flat brush", "Painting", size=40, min_size=0.5, flow=0.9, hardness=0.85, spacing=0.05,
       roundness=0.22, follow=True, smoothing=0.2),
    _b("Oil paint", "Painting", size=44, min_size=0.5, flow=0.9, hardness=0.8, spacing=0.05,
       shape="bristle", wet=0.35, grain="canvas", grain_depth=0.25, smoothing=0.15,
       follow=True, roundness=0.8),
    _b("Gouache", "Painting", size=36, min_size=0.45, flow=0.95, hardness=0.75, spacing=0.07,
       grain="canvas", grain_depth=0.3, wet=0.12, smoothing=0.2),
    _b("Acrylic", "Painting", size=38, min_size=0.4, flow=0.85, hardness=0.7, spacing=0.06,
       shape="bristle", grain="canvas", grain_depth=0.4, wet=0.18, follow=True),
    _b("Blender brush", "Painting", size=50, min_size=0.5, flow=0.5, hardness=0.4,
       spacing=0.06, wet=0.65, smoothing=0.2, pressure_opacity=True),
    # airbrushing
    _b("Soft airbrush", "Airbrushing", size=140, min_size=0.6, flow=0.07, min_flow=0.2,
       hardness=0.0, spacing=0.06, build_up=True, smoothing=0.1),
    _b("Hard airbrush", "Airbrushing", size=60, min_size=0.6, flow=0.15, min_flow=0.3,
       hardness=0.6, spacing=0.06, build_up=True),
    _b("Noise spray", "Airbrushing", size=6, min_size=0.5, flow=0.6, hardness=0.9,
       spacing=0.5, count=8, scatter=6, jitter_size=0.6, jitter_opacity=0.6,
       build_up=True, pressure_size=False),
    # watercolour
    _b("Wet wash", "Watercolour", size=90, min_size=0.6, opacity=0.65, flow=0.18,
       hardness=0.15, spacing=0.07, wet_edges=0.55, grain="paper", grain_depth=0.35,
       smoothing=0.15),
    _b("Watercolour round", "Watercolour", size=32, min_size=0.3, opacity=0.75, flow=0.3,
       hardness=0.35, spacing=0.06, wet_edges=0.45, grain="paper", grain_depth=0.4, wet=0.2),
    _b("Splatter", "Watercolour", size=8, min_size=0.4, flow=0.9, hardness=0.9, spacing=1.2,
       count=6, scatter=5, jitter_size=0.8, shape="splatter", build_up=True),
    # textures
    _b("Chalk", "Textures", size=30, min_size=0.5, flow=0.85, hardness=0.8, spacing=0.07,
       shape="chalk", grain="rough", grain_depth=0.8, pressure_opacity=True),
    _b("Charcoal", "Textures", size=26, min_size=0.4, flow=0.7, min_flow=0.3, hardness=0.6,
       spacing=0.06, grain="paper", grain_depth=0.85, grain_scale=1.6, pressure_opacity=True),
    _b("Sponge", "Textures", size=70, min_size=0.6, flow=0.5, hardness=0.6, spacing=0.25,
       grain="sponge", grain_depth=0.9, jitter_angle=1, build_up=True),
    _b("Stipple", "Textures", size=5, min_size=0.6, hardness=0.95, spacing=0.9, count=3,
       scatter=3, jitter_size=0.5, pressure_size=False, build_up=True),
    _b("Cloud brush", "Textures", size=160, min_size=0.7, flow=0.12, hardness=0.0,
       spacing=0.15, grain="sponge", grain_depth=0.6, grain_scale=2.5, scatter=0.2,
       jitter_size=0.3, build_up=True),
    # effects
    _b("Glow pen", "Effects", size=26, min_size=0.4, flow=0.35, hardness=0.25, spacing=0.05,
       blend="add", smoothing=0.4),
    _b("Light", "Effects", size=120, min_size=0.6, flow=0.08, hardness=0.0, spacing=0.07,
       blend="add", build_up=True),
    _b("Sparkles", "Effects", size=14, min_size=0.5, flow=1, hardness=0.9, spacing=1.5,
       count=3, scatter=4, jitter_size=0.8, jitter_angle=1, jitter_hue=0.15, shape="star",
       blend="add", build_up=True, pressure_size=False),
    # smudge & blend
    _b("Soft smudge", "Smudge & blend", size=60, min_size=0.5, hardness=0.25, spacing=0.06,
       mode="smudge", wet=0.75, smoothing=0.2),
    _b("Bristle smudge", "Smudge & blend", size=50, min_size=0.5, hardness=0.6, spacing=0.05,
       mode="smudge", wet=0.85, shape="bristle", follow=True),
    _b("Blur", "Smudge & blend", size=70, min_size=0.5, hardness=0.2, spacing=0.25,
       mode="blur", wet=0.6),
    # erasers
    _b("Hard eraser", "Erasers", size=30, min_size=0.6, hardness=0.95, spacing=0.05,
       mode="erase", smoothing=0.15),
    _b("Soft eraser", "Erasers", size=90, min_size=0.6, flow=0.25, hardness=0.0,
       spacing=0.06, mode="erase", build_up=True),
    _b("Texture eraser", "Erasers", size=40, min_size=0.5, hardness=0.7, spacing=0.07,
       mode="erase", grain="rough", grain_depth=0.7),
]


def library_names() -> list[str]:
    return [b.name for b in LIBRARY]


def load_user_brushes(data_dir: Optional[Path]) -> list[Brush]:
    if data_dir is None:
        return []
    try:
        data = json.loads((Path(data_dir) / "brushes.json").read_text(encoding="utf-8"))
        return [Brush.from_dict(d) for d in data if isinstance(d, dict) and d.get("name")]
    except (OSError, ValueError, TypeError):
        return []


def save_user_brushes(data_dir: Optional[Path], brushes: list[Brush]) -> None:
    if data_dir is None:
        return
    p = Path(data_dir) / "brushes.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps([b.to_dict() for b in brushes], indent=1), encoding="utf-8")
    tmp.replace(p)


# ------------------------------------------------------------------ tips
def _qimage_from_alpha(alpha: np.ndarray) -> QImage:
    """A white picture with this alpha (0…1), premultiplied."""
    h, w = alpha.shape
    a = np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
    buf = np.empty((h, w, 4), np.uint8)
    buf[..., 0] = a           # B, G, R premultiplied: white × alpha = alpha
    buf[..., 1] = a
    buf[..., 2] = a
    buf[..., 3] = a
    img = QImage(buf.data, w, h, w * 4, FORMAT)
    return img.copy()         # own the pixels


def _round_profile(d: int, hardness: float, roundness: float) -> np.ndarray:
    r = d / 2.0
    ys, xs = np.mgrid[0:d, 0:d].astype(np.float32) + 0.5
    x = (xs - r) / r
    y = (ys - r) / max(1e-3, r * roundness)
    dist = np.sqrt(x * x + y * y)
    h = min(0.98, max(0.0, hardness))
    t = np.clip((1.0 - dist) / max(1e-3, 1.0 - h), 0.0, 1.0)
    a = t * t * (3 - 2 * t)                      # smooth falloff
    edge = np.clip((1.0 - dist) * r, 0, 1)       # antialiased rim on hard tips
    return np.minimum(a, edge) if h > 0.6 else a


@lru_cache(maxsize=256)
def tip_alpha(shape: str, diameter: int, hardness: float, roundness: float,
              wet_edges: float, seed: int = 7) -> QImage:
    """The tip's shape as a white picture with alpha, ``diameter`` across."""
    d = max(1, int(diameter))
    if d <= 2:
        return _qimage_from_alpha(np.ones((d, d), np.float32))
    rnd = np.random.default_rng(seed + d)
    if shape == "square":
        a = np.ones((d, d), np.float32)
        m = max(1, int(d * (1 - hardness) * 0.3))
        ramp = np.clip(np.minimum.reduce(np.meshgrid(np.arange(d), np.arange(d)[::-1],
                                                     indexing="xy")) / m, 0, 1)
        a = np.minimum(a, np.minimum(ramp, ramp[::-1, ::-1]))
        if roundness < 1:
            a[: int(d * (1 - roundness) / 2)] = 0
            a[d - int(d * (1 - roundness) / 2):] = 0
    elif shape == "bristle":
        a = np.zeros((d, d), np.float32)
        r = d / 2.0
        n = max(6, int(d * 0.9))
        ys, xs = np.mgrid[0:d, 0:d].astype(np.float32) + 0.5
        for _ in range(n):
            ang = rnd.uniform(0, 2 * math.pi)
            rad = math.sqrt(rnd.uniform(0, 1)) * r * 0.85
            cx, cy = r + math.cos(ang) * rad, r + math.sin(ang) * rad * roundness
            br = max(0.7, rnd.uniform(0.04, 0.11) * d)
            dd = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
            a = np.maximum(a, np.clip(1 - dd / br, 0, 1) * rnd.uniform(0.5, 1.0))
        a = np.clip(a * 1.6, 0, 1)
    elif shape == "chalk":
        a = _round_profile(d, hardness, roundness)
        noise = rnd.uniform(0, 1, (d, d)).astype(np.float32)
        a = a * np.clip(noise * 1.4 - 0.15, 0, 1)
    elif shape == "splatter":
        a = np.zeros((d, d), np.float32)
        ys, xs = np.mgrid[0:d, 0:d].astype(np.float32) + 0.5
        r = d / 2.0
        for _ in range(max(3, d // 3)):
            ang = rnd.uniform(0, 2 * math.pi)
            rad = rnd.uniform(0, 1) ** 0.7 * r * 0.8
            cx, cy = r + math.cos(ang) * rad, r + math.sin(ang) * rad
            br = max(0.6, rnd.uniform(0.04, 0.16) * d)
            dd = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
            a = np.maximum(a, np.clip((br - dd) + 0.5, 0, 1))
    elif shape == "star":
        ys, xs = np.mgrid[0:d, 0:d].astype(np.float32) + 0.5
        r = d / 2.0
        x, y = (xs - r) / r, (ys - r) / r
        core = np.clip(1 - np.sqrt(x * x + y * y) * 3.0, 0, 1)
        rays = np.clip(1 - np.abs(x) * 9, 0, 1) * np.clip(1 - np.abs(y), 0, 1) + \
            np.clip(1 - np.abs(y) * 9, 0, 1) * np.clip(1 - np.abs(x), 0, 1)
        a = np.clip(core + rays * 0.9, 0, 1)
    else:
        a = _round_profile(d, hardness, roundness)
    if wet_edges > 0:                    # watercolour: more paint at the rim
        ys, xs = np.mgrid[0:d, 0:d].astype(np.float32) + 0.5
        r = d / 2.0
        dist = np.sqrt(((xs - r) / r) ** 2 + ((ys - r) / max(1e-3, r * roundness)) ** 2)
        rim = np.clip(1 - np.abs(dist - 0.82) * 6, 0, 1)
        a = np.clip(a * (1 - wet_edges * 0.45) + rim * wet_edges * 0.6 * (a > 0.02), 0, 1)
    return _qimage_from_alpha(a.astype(np.float32))


@lru_cache(maxsize=512)
def tip(shape: str, diameter: int, hardness: float, roundness: float, wet_edges: float,
        rgba: int) -> QImage:
    """The tip in a colour (``rgba`` = QColor.rgba())."""
    base = tip_alpha(shape, diameter, round(hardness, 2), round(roundness, 2),
                     round(wet_edges, 2))
    out = base.copy()
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(out.rect(), QColor.fromRgba(rgba))
    p.end()
    return out


# ------------------------------------------------------------------ grain
def _tileable_noise(size: int, power: float, seed: int) -> np.ndarray:
    """Noise that repeats seamlessly (filtered in frequency space), 0…1."""
    rnd = np.random.default_rng(seed)
    white = rnd.standard_normal((size, size))
    f = np.fft.fft2(white)
    fy = np.fft.fftfreq(size)[:, None]
    fx = np.fft.fftfreq(size)[None, :]
    k = np.sqrt(fx * fx + fy * fy)
    k[0, 0] = 1
    f = f / (k ** power)
    out = np.real(np.fft.ifft2(f))
    out = (out - out.min()) / max(1e-6, out.max() - out.min())
    return out.astype(np.float32)


@lru_cache(maxsize=16)
def grain_texture(name: str, depth: float) -> Optional[QImage]:
    """A seamless texture: white with alpha – 1 where paint shows fully,
    lower in the grain's dips (``depth`` deeper dips)."""
    if not name:
        return None
    size = 256
    if name == "paper":
        g = 0.65 * _tileable_noise(size, 0.9, 3) + 0.35 * _tileable_noise(size, 0.3, 4)
    elif name == "canvas":
        t = np.arange(size, dtype=np.float32)
        weave = 0.5 + 0.25 * np.sin(t[None, :] * 2 * math.pi / 8) * \
            np.sign(np.sin(t[:, None] * 2 * math.pi / 16)) + \
            0.25 * np.sin(t[:, None] * 2 * math.pi / 8)
        g = 0.7 * (weave - weave.min()) / max(1e-6, np.ptp(weave)) + \
            0.3 * _tileable_noise(size, 0.6, 5)
    elif name == "rough":
        g = _tileable_noise(size, 0.5, 6)
        g = np.clip((g - 0.35) * 2.2, 0, 1)
    elif name == "sponge":
        g = _tileable_noise(size, 1.4, 7)
        g = np.clip((g - 0.45) * 4.0, 0, 1)
    else:                                            # fine noise
        g = np.random.default_rng(8).uniform(0, 1, (size, size)).astype(np.float32)
    a = 1.0 - depth * (1.0 - g)
    return _qimage_from_alpha(np.clip(a, 0, 1).astype(np.float32))


# ------------------------------------------------------------------ a colour nearby
def jitter_colour(c: QColor, amount: float, rnd: random.Random) -> QColor:
    if amount <= 0:
        return c
    h, s, v, a = c.getHsvF()
    h = (max(0.0, h) + rnd.uniform(-amount, amount) / 3.0) % 1.0
    return QColor.fromHsvF(h, s, v, a)


def mix(a: QColor, b: QColor, t: float) -> QColor:
    """``a`` with ``t`` of ``b`` mixed in."""
    t = max(0.0, min(1.0, t))
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * t,
                           a.greenF() + (b.greenF() - a.greenF()) * t,
                           a.blueF() + (b.blueF() - a.blueF()) * t,
                           a.alphaF())


def average(img: QImage) -> QColor:
    """The average colour of a (small) picture, ignoring see-through parts."""
    if img.isNull() or img.width() == 0:
        return QColor(0, 0, 0, 0)
    one = img.scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    c = QColor.fromRgba(one.pixel(0, 0))
    if c.alpha() == 0:
        return c
    a = c.alphaF()
    return QColor.fromRgbF(min(1.0, c.redF() / a) if a else 0, min(1.0, c.greenF() / a) if a
                           else 0, min(1.0, c.blueF() / a) if a else 0, a) \
        if img.format() == FORMAT else c
