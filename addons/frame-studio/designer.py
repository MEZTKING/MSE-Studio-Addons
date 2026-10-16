"""Frame designer: whole Magic frames drawn from a few dozen settings – a
frame for every colour, P/T boxes and mana symbols, with the text boxes
exactly where MSE puts the text. Materials (stone, metal, parchment…), torn
or rounded bars, bevels, shadows, glows, wear and grain are drawn here with
NumPy and OpenCV (both come with MSE Studio); a texture picture (your own or
one an AI made) can be the material too."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import framegen as fg

U_W, U_H = fg.CARD_W, fg.CARD_H            # MSE's card units: everything is placed in these
SLOTS = [k for k, _ in fg.SLOTS]          # w u b r g m a c l

# ------------------------------------------------------------------ the choices
LAYOUTS = {"modern": "Modern (art window, bars, text box)",
           "classic": "Classic (thick border, bevelled frame)",
           "borderless": "Borderless (art to the border, floating bars)",
           "fullart": "Full art (art fills the card, see-through text box)",
           "minimal": "Minimal (flat, thin lines)"}
MATERIALS = {"solid": "Solid colour", "gradient": "Gradient", "metal": "Brushed metal",
             "stone": "Stone", "parchment": "Parchment", "grunge": "Grunge",
             "marble": "Marble", "leather": "Leather", "wood": "Wood", "carbon": "Carbon fibre",
             "picture": "A texture picture"}
PALETTES = {"classic": "Classic Magic colours", "dark": "Dark", "vivid": "Vivid / neon",
            "pastel": "Pastel", "mono": "Black and white", "gothic": "Gothic (black, colour "
            "trim)", "gold": "Gilded (gold trim)", "custom": "My own colours"}
BORDERS = {"black": "Black", "white": "White", "silver": "Silver", "gold": "Gold",
           "colour": "The card's colour", "none": "None"}
BAR_SHAPES = {"rounded": "Rounded", "square": "Square", "angled": "Cut corners",
              "torn": "Torn / brushed", "none": "No bars (text straight on the frame)"}
TEXTBOXES = {"light": "Light", "parchment": "Parchment", "tinted": "Tinted with the colour",
             "dark": "Dark", "glass": "See-through dark glass"}
BOX_SHAPES = {"square": "Square", "rounded": "Rounded", "torn": "Torn / brushed"}
WINDOWS = {"square": "Square", "rounded": "Rounded", "arched": "Arched top"}
PINLINE_COLOURS = {"light": "Lighter than the frame", "dark": "Darker than the frame",
                   "gold": "Gold", "silver": "Silver", "colour": "The card's colour",
                   "white": "White", "black": "Black"}
MANA_STYLES = {"none": "MSE's usual symbols", "circles": "Circles", "tiles": "Square tiles",
               "diamonds": "Diamonds", "brush": "Brushed tiles"}

# body colour of each card colour, per palette ("" = the classic one changed)
_CLASSIC = {"w": "#e6dcc0", "u": "#2a6cb0", "b": "#3a3431", "r": "#c33b2c", "g": "#2f7a46",
            "m": "#c8a048", "a": "#9aa3ab", "c": "#b8b2aa", "l": "#8a6a4a"}
_MANA_FILL = {"w": "#f8f3d6", "u": "#aed3ef", "b": "#bdb2ad", "r": "#ef9a7c", "g": "#9ccf9a",
              "c": "#d6d2cc", "n": "#cac5c0"}


@dataclass
class Design:
    layout: str = "modern"
    material: str = "stone"
    texture: float = 0.45            # how strong the material shows (0..1)
    texture_size: float = 1.0        # bigger = coarser
    picture: str = ""                # a texture picture (material "picture")
    palette: str = "classic"
    colours: dict = field(default_factory=dict)   # palette "custom" (or overrides): slot → #rrggbb
    border: str = "black"
    border_width: float = 0.03       # part of the card's width
    bars: str = "rounded"
    bar_opacity: float = 1.0
    textbox: str = "parchment"
    textbox_opacity: float = 0.94
    textbox_shape: str = "square"
    window: str = "square"
    pinlines: float = 0.006          # part of the card's width (0: none)
    pinline_colour: str = "light"
    bevel: float = 0.55
    shadow: float = 0.5
    glow: float = 0.0
    wear: float = 0.0
    grain: float = 0.12
    vignette: float = 0.25
    pt_box: bool = True
    mana: str = "circles"
    mana_column: bool = False
    title_font: str = ""
    text_font: str = ""
    seed: int = 7

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "Design":
        """A design from saved (or AI-written) settings: unknown keys and values
        are left out, numbers kept in range."""
        out = cls()
        if not isinstance(d, dict):
            return out
        choices = {"layout": LAYOUTS, "material": MATERIALS, "palette": PALETTES,
                   "border": BORDERS, "bars": BAR_SHAPES, "textbox": TEXTBOXES,
                   "textbox_shape": BOX_SHAPES, "window": WINDOWS,
                   "pinline_colour": PINLINE_COLOURS, "mana": MANA_STYLES}
        ranges = {"texture": (0, 1), "texture_size": (0.3, 3), "border_width": (0, 0.08),
                  "bar_opacity": (0.2, 1), "textbox_opacity": (0.2, 1),
                  "pinlines": (0, 0.02), "bevel": (0, 1), "shadow": (0, 1), "glow": (0, 1),
                  "wear": (0, 1), "grain": (0, 1), "vignette": (0, 1)}
        for f in fields(cls):
            if f.name not in d:
                continue
            v = d[f.name]
            if f.name in choices:
                if v in choices[f.name]:
                    setattr(out, f.name, v)
            elif f.name in ranges:
                try:
                    lo, hi = ranges[f.name]
                    setattr(out, f.name, max(lo, min(hi, float(v))))
                except (TypeError, ValueError):
                    pass
            elif f.name == "colours" and isinstance(v, dict):
                out.colours = {k: str(c) for k, c in v.items()
                               if k in SLOTS and isinstance(c, str) and _ok_hex(c)}
            elif f.name in ("pt_box", "mana_column"):
                setattr(out, f.name, bool(v))
            elif f.name == "seed":
                try:
                    out.seed = int(v) % 100000
                except (TypeError, ValueError):
                    pass
            elif isinstance(v, str):
                setattr(out, f.name, v)
        return out

    def to_dict(self) -> dict:
        return asdict(self)


PRESETS = {
    "Modern stone": {},
    "Gothic": dict(layout="modern", material="grunge", palette="gothic", border="black",
                   bars="torn", textbox="parchment", textbox_shape="torn",
                   pinline_colour="colour", pinlines=0.004, bevel=0.2, wear=0.55, grain=0.25,
                   vignette=0.45, mana="brush", mana_column=True),
    "Neon": dict(layout="modern", material="carbon", palette="vivid", border="black",
                 bars="angled", textbox="glass", pinline_colour="colour", pinlines=0.005,
                 glow=0.8, bevel=0.3, grain=0.05, mana="diamonds"),
    "Old parchment": dict(layout="classic", material="parchment", palette="classic",
                          border="black", bars="square", textbox="parchment",
                          window="arched", bevel=0.7, wear=0.25, vignette=0.35),
    "Gilded marble": dict(layout="modern", material="marble", palette="gold", border="gold",
                          bars="rounded", textbox="light", pinline_colour="gold",
                          pinlines=0.007, bevel=0.75),
    "Borderless": dict(layout="borderless", material="metal", palette="dark",
                       border="black", bars="rounded", bar_opacity=0.9, textbox="glass",
                       textbox_opacity=0.8, pinline_colour="colour", vignette=0.0),
    "Full art glass": dict(layout="fullart", material="solid", palette="dark",
                           border="black", bars="rounded", bar_opacity=0.75,
                           textbox="glass", textbox_opacity=0.7, pinlines=0.003,
                           vignette=0.0, grain=0.0),
    "Minimal": dict(layout="minimal", material="solid", palette="mono", border="white",
                    bars="square", textbox="light", pinlines=0.002, bevel=0.0,
                    shadow=0.15, grain=0.0, vignette=0.0, mana="circles"),
}


def _ok_hex(c: str) -> bool:
    c = c.lstrip("#")
    return len(c) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in c)


def _rgb(c: str) -> np.ndarray:
    c = c.lstrip("#")
    return np.array([int(c[k:k + 2], 16) / 255 for k in (0, 2, 4)], dtype=np.float32)


def _hex(v) -> str:
    return "#%02x%02x%02x" % tuple(int(max(0, min(1, x)) * 255 + 0.5) for x in v)


def _mix(a, b, t):
    return np.asarray(a, dtype=np.float32) * (1 - t) + np.asarray(b, dtype=np.float32) * t


def _lum(c) -> float:
    c = np.asarray(c, dtype=np.float32)
    return float(0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2])


def palette(d: Design, slot: str) -> tuple[np.ndarray, np.ndarray]:
    """(the frame's colour, its trim colour) for a card colour."""
    base = _rgb(d.colours.get(slot) or _CLASSIC[slot])
    if d.palette == "custom" or slot in d.colours:
        body = base
    elif d.palette == "dark":
        body = base * 0.55
    elif d.palette == "vivid":
        hsv = np.array(Image.new("RGB", (1, 1), tuple(int(x * 255) for x in base))
                       .convert("HSV").getpixel((0, 0)), dtype=np.float32)
        hsv[1] = min(255, hsv[1] * 1.5 + 40)
        hsv[2] = min(255, hsv[2] * 1.15 + 20)
        body = np.array(Image.new("HSV", (1, 1), tuple(int(x) for x in hsv)).convert("RGB")
                        .getpixel((0, 0)), dtype=np.float32) / 255
    elif d.palette == "pastel":
        body = _mix(base, (1, 1, 1), 0.45)
    elif d.palette == "mono":
        v = _lum(base)
        body = np.array([v, v, v], dtype=np.float32)
    elif d.palette == "gothic":
        body = _mix(base, (0.07, 0.06, 0.07), 0.85)
    else:
        body = base
    trim = {"gothic": base * 1.1, "gold": _rgb("#d4af37")}.get(d.palette)
    if trim is None:
        trim = _mix(body, (1, 1, 1), 0.35) if _lum(body) < 0.6 else body * 0.7
    return np.clip(body, 0, 1), np.clip(trim, 0, 1)


# ------------------------------------------------------------------ where things are
def geometry(d: Design) -> dict:
    """The design's parts in MSE's card units: {part: (left, top, right, bottom)}."""
    bw = d.border_width * U_W if d.border != "none" else 0
    inner = (bw, bw, U_W - bw, U_H - bw)
    g = {"card": (0, 0, U_W, U_H), "inner": inner}
    m = max(bw + 4, 13)
    if d.layout == "classic":
        m = max(bw + 9, 20)
    g["name"] = (m, 24, U_W - m, 56)
    g["window"] = (m + 4, 60, U_W - m - 4, 290)
    g["type"] = (m, 293, U_W - m, 321)
    g["text"] = (m + 4, 325, U_W - m - 4, 480)
    g["pt"] = (U_W - m - 78, 466, U_W - m + 2, 506)
    if d.layout in ("borderless", "fullart"):
        g["window"] = inner
    if d.layout == "fullart":
        g["type"] = (m, 318, U_W - m, 346)
        g["text"] = (m + 4, 350, U_W - m - 4, 482)
    if d.mana_column:                            # the cost down the right side
        g["name"] = (m, 24, U_W - m - 34, 56)
        g["cost"] = (U_W - m - 30, 24, U_W - m - 2, 190)
    return g


def boxes(d: Design) -> dict:
    """Frame studio's boxes (parts of the card) for the design."""
    g = geometry(d)

    def frac(x0, y0, x1, y1):
        return [round(x0 / U_W, 5), round(y0 / U_H, 5), round((x1 - x0) / U_W, 5),
                round((y1 - y0) / U_H, 5)]
    nx0, ny0, nx1, ny1 = g["name"]
    tx0, ty0, tx1, ty1 = g["type"]
    out = {"art": frac(*g["window"]), "text": frac(*g["text"]), "ptbox": frac(*g["pt"])}
    px0, py0, px1, py1 = g["pt"]
    out["pt"] = frac(px0 + 8, py0 + 7, px1 - 8, py1 - 7)
    if "cost" in g:
        out["name"] = frac(nx0 + 8, ny0 + 4, nx1 - 6, ny1 - 3)
        cx0, cy0, cx1, cy1 = g["cost"]
        out["cost"] = frac(cx0 + 2, cy0 + 6, cx1 - 2, cy1)
    else:
        out["name"] = frac(nx0 + 8, ny0 + 4, nx1 - 110, ny1 - 3)
        out["cost"] = frac(nx1 - 112, ny0 + 4, nx1 - 7, ny1 - 3)
    out["type"] = frac(tx0 + 8, ty0 + 4, tx1 - 34, ty1 - 3)
    out["rarity"] = frac(tx1 - 32, ty0 + 4, tx1 - 7, ty1 - 3)
    bottom = g["text"][3]
    out["artist"] = frac(g["text"][0] + 4, bottom + 4, g["pt"][0] - 6, bottom + 14)
    out["credit"] = frac(g["text"][0] + 4, bottom + 15, g["pt"][0] - 6, bottom + 24)
    return out


# ------------------------------------------------------------------ drawing helpers
def _cv2():
    try:
        import cv2
        return cv2
    except Exception:  # noqa: BLE001 - OpenCV comes with MSE Studio
        return None


def _resize(a: np.ndarray, w: int, h: int) -> np.ndarray:
    cv2 = _cv2()
    if cv2 is not None:
        return cv2.resize(a, (w, h), interpolation=cv2.INTER_CUBIC)
    im = Image.fromarray(a.astype(np.float32), "F").resize((w, h), Image.BICUBIC)
    return np.asarray(im, dtype=np.float32)


def _blur(a: np.ndarray, r: float) -> np.ndarray:
    if r <= 0.3:
        return a
    cv2 = _cv2()
    if cv2 is not None:
        return cv2.GaussianBlur(a, (0, 0), r)
    im = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8), "L")
    return np.asarray(im.filter(ImageFilter.GaussianBlur(r)), dtype=np.float32) / 255


def _dist(inside: np.ndarray) -> np.ndarray:
    """Distance (pixels) from each pixel in ``inside`` to the outside."""
    cv2 = _cv2()
    if cv2 is not None:
        return cv2.distanceTransform(inside.astype(np.uint8), cv2.DIST_L2, 5)
    out = np.zeros(inside.shape, dtype=np.float32)
    cur = Image.fromarray(inside.astype(np.uint8) * 255, "L")
    for k in range(1, 40):
        cur = cur.filter(ImageFilter.MinFilter(3))
        a = np.asarray(cur) > 127
        out[a] = k
        if not a.any():
            break
    return out


def _noise(h: int, w: int, cell: float, rng: np.random.Generator) -> np.ndarray:
    gh, gw = max(2, int(h / cell) + 2), max(2, int(w / cell) + 2)
    return _resize(rng.random((gh, gw)).astype(np.float32), w, h)


def _fbm(h: int, w: int, cell: float, octaves: int, rng, gain: float = 0.5) -> np.ndarray:
    out = np.zeros((h, w), dtype=np.float32)
    amp, total = 1.0, 0.0
    for _ in range(octaves):
        out += _noise(h, w, max(1.5, cell), rng) * amp
        total += amp
        amp *= gain
        cell /= 2
    out /= total
    lo, hi = np.percentile(out, (1, 99))
    return np.clip((out - lo) / max(1e-6, hi - lo), 0, 1)


def _shape(w: int, h: int, rect, kind: str, s: float, rng, radius: float = 10) -> np.ndarray:
    """A shape's mask (0..1) on a w × h canvas; ``rect`` in card units, ``s`` px a unit."""
    x0, y0, x1, y1 = (v * s for v in rect)
    ss = 3
    im = Image.new("L", (w * ss, h * ss), 0)
    dr = ImageDraw.Draw(im)
    box = [x0 * ss, y0 * ss, x1 * ss - 1, y1 * ss - 1]
    r = radius * s * ss
    if kind in ("rounded", "torn"):
        dr.rounded_rectangle(box, r if kind == "rounded" else r * 0.4, fill=255)
    elif kind == "angled":
        c = min(r * 1.2, (box[3] - box[1]) / 2)
        dr.polygon([(box[0] + c, box[1]), (box[2] - c, box[1]), (box[2], box[1] + c),
                    (box[2], box[3] - c), (box[2] - c, box[3]), (box[0] + c, box[3]),
                    (box[0], box[3] - c), (box[0], box[1] + c)], fill=255)
    elif kind == "arched":
        top = box[1] + (box[3] - box[1]) * 0.18
        dr.rectangle([box[0], top, box[2], box[3]], fill=255)
        dr.pieslice([box[0], box[1], box[2], top + (top - box[1])], 180, 360, fill=255)
    else:
        dr.rectangle(box, fill=255)
    m = np.asarray(im.resize((w, h), Image.BOX), dtype=np.float32) / 255
    if kind == "torn":                                   # rough, brushed edges
        n = _fbm(h, w, 6 * s, 4, rng)
        streak = _resize(rng.random((max(2, h // max(1, int(2 * s))), 6)).astype(np.float32),
                         w, h)
        edge = _blur(m, 1.5 * s)
        m = np.clip((edge - 0.5 + (n - 0.5) * 0.55 + (streak - 0.5) * 0.25) * 6 + 0.5, 0, 1)
        m = np.minimum(m, _blur((edge > 0.02).astype(np.float32), 0.5))
    return m


def _bevel(mask: np.ndarray, width: float, strength: float) -> np.ndarray:
    """Light (+) and shade (−) of a raised shape's edges, light from the top left."""
    if strength <= 0 or width <= 0.5:
        return np.zeros_like(mask)
    height = np.clip(_dist(mask > 0.5) / width, 0, 1)
    height = _blur(height * height * (3 - 2 * height), max(0.6, width / 6))
    gy, gx = np.gradient(height)
    light = -(gx * -0.7 + gy * -0.7) * width
    return np.clip(light, -1, 1) * strength * mask


def _material(d: Design, h: int, w: int, s: float, rng) -> np.ndarray:
    """The material's light and dark (0..1, about 0.5 on average)."""
    k = d.texture_size * s
    m = d.material
    if m == "solid":
        return np.full((h, w), 0.5, dtype=np.float32)
    if m == "gradient":
        y = np.linspace(0.75, 0.3, h, dtype=np.float32)[:, None]
        return np.repeat(y, w, axis=1)
    if m == "metal":
        streak = _resize(rng.random((h, max(4, int(w / (40 * k))))).astype(np.float32), w, h)
        sheen = 0.5 + 0.25 * np.sin(np.linspace(0, 3.2, h, dtype=np.float32))[:, None]
        return np.clip(0.35 * streak + 0.65 * sheen, 0, 1)
    if m == "stone":
        base = _fbm(h, w, 60 * k, 6, rng)
        ridge = 1 - np.abs(_fbm(h, w, 90 * k, 4, rng) * 2 - 1)
        cracks = np.clip((ridge - 0.9) * 10, 0, 1)
        return np.clip(base * 0.9 + 0.05 - cracks * 0.5, 0, 1)
    if m == "parchment":
        blotch = _fbm(h, w, 120 * k, 5, rng)
        fibre = _resize(rng.random((max(2, int(h / (2 * k))), max(2, int(w / (25 * k)))))
                        .astype(np.float32), w, h)
        return np.clip(0.55 + (blotch - 0.5) * 0.7 + (fibre - 0.5) * 0.15, 0, 1)
    if m == "grunge":
        base = _fbm(h, w, 40 * k, 6, rng, gain=0.6)
        specks = (_noise(h, w, 2.5 * k, rng) > 0.86).astype(np.float32)
        scratch = _resize(rng.random((max(2, int(h / (90 * k))), w)).astype(np.float32), w, h)
        return np.clip((base - 0.5) * 1.6 + 0.5 - specks * 0.35 - (scratch > 0.97) * 0.3,
                       0, 1)
    if m == "marble":
        turb = _fbm(h, w, 80 * k, 5, rng)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        v = np.sin((xx + yy * 0.6) / (55 * k) + turb * 9)
        veins = np.clip(1 - np.abs(v) * 7, 0, 1)
        return np.clip(0.62 + (turb - 0.5) * 0.3 - veins * 0.45, 0, 1)
    if m == "leather":
        pts = np.zeros((h, w), dtype=np.uint8)
        n = int(h * w / (90 * k * k)) + 1
        ys, xs = rng.integers(0, h, n), rng.integers(0, w, n)
        pts[ys, xs] = 1
        cells = _dist(pts == 0)
        cells = np.clip(cells / max(1.0, 5 * k), 0, 1)
        return np.clip(0.3 + cells * 0.45 + (_fbm(h, w, 50 * k, 4, rng) - 0.5) * 0.3, 0, 1)
    if m == "wood":
        turb = _fbm(h, w, 70 * k, 4, rng)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        rings = np.sin((xx * 0.15 + yy) / (9 * k) + turb * 6) * 0.5 + 0.5
        grain = _resize(rng.random((h, max(2, int(w / (30 * k))))).astype(np.float32), w, h)
        return np.clip(0.3 + rings * 0.35 + grain * 0.25, 0, 1)
    if m == "carbon":
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        p = 7 * k
        cx, cy = (xx // p) % 2, (yy // p) % 2
        a = ((xx % p) / p) * (cx == cy) + ((yy % p) / p) * (cx != cy)
        return np.clip(0.3 + a * 0.4 + (_noise(h, w, 3, rng) - 0.5) * 0.1, 0, 1)
    if m == "picture" and d.picture and Path(d.picture).is_file():
        try:
            with Image.open(d.picture) as im:
                im = im.convert("L")
                sc = max(w / im.width, h / im.height)
                im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))),
                               Image.LANCZOS)
                l, t = (im.width - w) // 2, (im.height - h) // 2
                a = np.asarray(im.crop((l, t, l + w, t + h)), dtype=np.float32) / 255
            return np.clip((a - a.mean()) + 0.5, 0, 1)
        except OSError:
            pass
    return np.full((h, w), 0.5, dtype=np.float32)


def _picture_colour(d: Design, h: int, w: int) -> Optional[np.ndarray]:
    """The texture picture's own colours (material "picture")."""
    if d.material != "picture" or not d.picture or not Path(d.picture).is_file():
        return None
    try:
        with Image.open(d.picture) as im:
            im = im.convert("RGB")
            sc = max(w / im.width, h / im.height)
            im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))),
                           Image.LANCZOS)
            l, t = (im.width - w) // 2, (im.height - h) // 2
            return np.asarray(im.crop((l, t, l + w, t + h)), dtype=np.float32) / 255
    except OSError:
        return None


def _over(dst: np.ndarray, rgb, alpha: np.ndarray) -> None:
    """Paint ``rgb`` (colour or picture) with ``alpha`` over ``dst`` (RGBA, in
    place) – only where ``alpha`` reaches."""
    rows = np.flatnonzero(alpha.max(axis=1) > 0.002)
    if not len(rows):
        return
    cols = np.flatnonzero(alpha[rows[0]:rows[-1] + 1].max(axis=0) > 0.002)
    ys, xs = slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1)
    a = alpha[ys, xs, None].astype(np.float32)
    d = dst[ys, xs]
    rgb = np.asarray(rgb, dtype=np.float32)
    if rgb.ndim == 3:
        rgb = rgb[ys, xs]
    keep = d[..., 3:4] * (1 - a)
    oa = a + keep
    col = d[..., :3] * keep
    col += rgb * a
    col /= np.maximum(oa, 1e-6)
    d[..., :3] = col
    d[..., 3:4] = oa


# ------------------------------------------------------------------ the renderer
class Renderer:
    """Draws a design at ``width`` pixels wide: ``frame(slot)``, ``pt_box(slot)``,
    ``mana(code)``. Shapes and textures are worked out once, then each colour
    only tints them."""

    def __init__(self, design: Design, width: int = 1500):
        self.d = d = design
        self.s = s = width / U_W
        self.w, self.h = w, h = width, round(U_H * s)
        self.g = g = geometry(d)
        rng = np.random.default_rng(d.seed)
        self.tex = _material(d, h, w, s, rng)
        self.tex_rgb = _picture_colour(d, h, w)
        paper = _fbm(h, w, 70 * s, 6, np.random.default_rng(d.seed + 1), gain=0.45)
        fibre = _noise(h, w, 1.2 * s, np.random.default_rng(d.seed + 4))
        self.paper = np.clip(0.5 + (paper - 0.5) * 0.55 + (fibre - 0.5) * 0.12, 0, 1)
        y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        self.sheen = np.repeat(1.06 - 0.12 * y, w, axis=1)   # bars: lighter at the top
        wr = np.random.default_rng(d.seed + 2)
        bar = d.bars if d.bars != "none" else "square"
        self.m_card = _shape(w, h, g["card"], "rounded", s, wr, radius=8)
        self.m_inner = _shape(w, h, g["inner"], "rounded" if d.border != "none" else "square",
                              s, wr, radius=4)
        self.m_window = _shape(w, h, g["window"], d.window, s, wr, radius=7)
        self.m_name = _shape(w, h, g["name"], bar, s, wr)
        self.m_type = _shape(w, h, g["type"], bar, s, wr)
        self.m_text = _shape(w, h, g["text"], d.textbox_shape, s, wr, radius=6)
        self.m_cost = _shape(w, h, g["cost"], bar, s, wr) if "cost" in g else None
        self.m_bars = np.maximum(self.m_name, self.m_type)
        if self.m_cost is not None:
            self.m_bars = np.maximum(self.m_bars, self.m_cost)
        pw = d.pinlines * w
        self.pin_w = pw
        self.m_pins = np.zeros((h, w), dtype=np.float32)
        if pw >= 0.6:
            for m in (self.m_bars, self.m_text, self.m_window):
                ring = np.clip(pw + 0.5 - _dist(m < 0.5), 0, 1) * (1 - m)
                self.m_pins = np.maximum(self.m_pins, ring)
        bev = d.bevel
        self.bev_body = _bevel(self.m_inner, 6 * s, bev)
        self.bev_bars = _bevel(self.m_bars, 3.5 * s, bev)
        self.bev_pins = _bevel(self.m_pins, max(1.0, pw * 0.6), bev)
        # the art window and the text box sink in: their inner edges darken
        self.sink = np.clip(1 - _dist(self.m_window > 0.5) / (5 * s), 0, 1) * self.m_window
        self.sink_text = np.clip(1 - _dist(self.m_text > 0.5) / (4 * s), 0, 1) * self.m_text
        sh = d.shadow
        off = int(round(2.5 * s))
        drop = np.roll(np.roll(np.maximum(self.m_bars, self.m_text), off, 0), off, 1)
        self.drop = _blur(drop, 3 * s) * sh * 0.75
        n = _fbm(h, w, 25 * s, 4, wr)
        edge = np.clip(1 - _dist(self.m_card > 0.5) / (30 * s), 0, 1)
        self.wear = np.clip((n - 1 + d.wear * 0.9) * 4 * (0.4 + edge), 0, 1) if d.wear else None
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        r = np.sqrt(((xx / w) - 0.5) ** 2 + ((yy / h) - 0.5) ** 2)
        self.vig = np.clip((r - 0.3) * 1.6, 0, 1) * d.vignette
        self.grain = (np.random.default_rng(d.seed + 3).standard_normal((h, w))
                      .astype(np.float32) * d.grain * 0.06) if d.grain else None

    def _bar_sheen(self) -> np.ndarray:
        """Each bar a little lighter at its top than at its bottom."""
        out = np.ones((self.h, self.w), dtype=np.float32)
        for key in ("name", "type") + (("cost",) if "cost" in self.g else ()):
            x0, y0, x1, y1 = (round(v * self.s) for v in self.g[key])
            if y1 > y0:
                out[y0:y1, :] = np.linspace(1.12, 0.9, y1 - y0, dtype=np.float32)[:, None]
        return out

    # ---------------------------------------------------------------- colours
    def _shade(self, colour, tex: np.ndarray, strength: float,
               pic: Optional[np.ndarray] = None) -> np.ndarray:
        if pic is None and self.tex_rgb is not None and self.tex_rgb.shape[:2] == tex.shape:
            pic = self.tex_rgb
        if pic is not None:
            tint = _mix(pic, pic * colour / max(0.05, float(np.mean(pic))) * 0.9, 0.5)
            return np.clip(_mix(np.broadcast_to(colour, pic.shape), tint, strength), 0, 1)
        f = 1 + (tex[..., None] - 0.5) * 2 * strength
        return np.clip(np.asarray(colour, dtype=np.float32) * f, 0, 1)

    def _border_colour(self, body, trim) -> np.ndarray:
        return {"black": _rgb("#0b0b0c"), "white": _rgb("#f2f0ea"), "silver": _rgb("#b8bec4"),
                "gold": _rgb("#c9a646"), "colour": body * 0.6,
                "none": _rgb("#000000")}[self.d.border]

    def _pin_colour(self, body, trim) -> np.ndarray:
        return {"light": _mix(trim, (1, 1, 1), 0.25), "dark": body * 0.45,
                "gold": _rgb("#d8b24a"), "silver": _rgb("#cfd5da"), "colour": trim,
                "white": _rgb("#ffffff"), "black": _rgb("#0a0a0a")}[self.d.pinline_colour]

    def textbox_colour(self, body) -> np.ndarray:
        return {"light": _rgb("#f3eee3"), "parchment": _rgb("#ecdcb8"),
                "tinted": _mix(body, (1, 1, 1), 0.72), "dark": _rgb("#1b1a1c"),
                "glass": _rgb("#0d0d10")}[self.d.textbox]

    def bar_colour(self, body, trim) -> np.ndarray:
        if self.d.palette in ("gothic", "gold"):
            return np.clip(body * 1.25 + 0.03, 0, 1)
        return np.clip(_mix(body, (1, 1, 1), 0.18), 0, 1)

    # ---------------------------------------------------------------- pictures
    def frame(self, slot: str) -> Image.Image:
        d, h, w = self.d, self.h, self.w
        body, trim = palette(d, slot)
        if slot == "l" and d.palette not in ("custom", "mono"):
            body = _mix(body, _rgb(_CLASSIC["l"]), 0.6)
        out = np.zeros((h, w, 4), dtype=np.float32)
        if d.border != "none":
            bc = self._border_colour(body, trim)
            _over(out, self._shade(bc, self.paper, 0.15), self.m_card)
        frame_body = d.layout not in ("borderless", "fullart")
        if frame_body:
            col = self._shade(body, self.tex, d.texture)
            col = np.clip(col + self.bev_body[..., None] * 0.35, 0, 1)
            _over(out, col, self.m_inner)
        # the art window: cut out (the art goes under the frame), its edge in shadow
        out[..., 3] *= 1 - self.m_window
        if frame_body and d.bevel:
            _over(out, (0, 0, 0), self.sink * 0.55 * d.bevel)
        # shadows of the bars and the text box on the frame
        if d.shadow:
            _over(out, (0, 0, 0), self.drop * (1 - self.m_window) * (out[..., 3] > 0.05))
        # pinlines (and their glow)
        if self.pin_w >= 0.6:
            pc = self._pin_colour(body, trim)
            if d.glow:
                halo = _blur(self.m_pins, 6 * self.s) * d.glow * 1.6
                _over(out, np.clip(pc * 1.2 + 0.1, 0, 1), np.clip(halo, 0, 1))
            pcol = np.clip(pc + self.bev_pins[..., None] * 0.5, 0, 1)
            _over(out, pcol, self.m_pins)
        # the bars
        if d.bars != "none":
            bcol = self._shade(self.bar_colour(body, trim), self.tex, d.texture * 0.8)
            bcol = np.clip(bcol * self._bar_sheen()[..., None] +
                           self.bev_bars[..., None] * 0.45, 0, 1)
            _over(out, bcol, self.m_bars * d.bar_opacity)
        # the text box
        tcol = self.textbox_colour(body)
        if d.textbox == "parchment":
            tcol = self._shade(tcol, self.paper, 0.18)
        elif d.textbox in ("light", "tinted"):
            tcol = self._shade(tcol, self.paper, 0.06)
        tcol = np.clip(tcol * (1 - self.sink_text[..., None] * 0.25), 0, 1)
        _over(out, tcol, self.m_text * d.textbox_opacity)
        # wear, grain, vignette
        if self.wear is not None:
            keep = 1 - self.wear * (1 - self.m_text * 0.7)
            out[..., :3] *= (0.75 + 0.25 * keep)[..., None]
            if d.border == "none" or d.layout in ("borderless", "fullart"):
                out[..., 3] *= np.clip(keep + 0.3, 0, 1)
        if self.grain is not None:
            out[..., :3] = np.clip(out[..., :3] + self.grain[..., None], 0, 1)
        if d.vignette:
            out[..., :3] *= (1 - self.vig * (1 - self.m_text * 0.6))[..., None]
        return Image.fromarray(np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8), "RGBA")

    def pt_box(self, slot: str) -> Image.Image:
        """The P/T box for a colour, cut to its box."""
        d, s = self.d, self.s
        body, trim = palette(d, slot)
        x0, y0, x1, y1 = self.g["pt"]
        pad = 3
        rect = (pad, pad, x1 - x0 + pad, y1 - y0 + pad)
        w, h = round((x1 - x0 + 2 * pad) * s), round((y1 - y0 + 2 * pad) * s)
        rng = np.random.default_rng(d.seed + 5)
        bar = d.bars if d.bars != "none" else "rounded"
        m = _shape(w, h, rect, bar, s, rng, radius=8)
        tex = _material(d, h, w, s, np.random.default_rng(d.seed))
        out = np.zeros((h, w, 4), dtype=np.float32)
        if d.shadow:
            sh = _blur(np.roll(np.roll(m, round(2 * s), 0), round(2 * s), 1), 2.5 * s)
            _over(out, (0, 0, 0), sh * d.shadow * 0.7)
        pw = max(1.0, d.pinlines * self.w * 0.8)
        if d.pinlines:
            ring = np.clip(np.clip(_blur(m, pw * 0.6) * 1.8, 0, 1) - m * 0.0, 0, 1)
            _over(out, self._pin_colour(body, trim), ring)
        col = self._shade(self.bar_colour(body, trim), tex, d.texture * 0.8,
                          _picture_colour(d, h, w))
        col = np.clip(col + _bevel(m, 3 * s, d.bevel)[..., None] * 0.45, 0, 1)
        _over(out, col, m * max(0.85, d.bar_opacity))
        img = Image.fromarray(np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8), "RGBA")
        return img.crop((round(pad * s * 0.4), round(pad * s * 0.4), w - round(pad * s * 0.4),
                         h - round(pad * s * 0.4)))

    def pt_colour(self, slot: str) -> str:
        body, trim = palette(self.d, slot)
        return "#000000" if _lum(self.bar_colour(body, trim)) > 0.55 else "#ffffff"

    def text_colours(self, slot: str = "w") -> dict:
        """Readable text colours for the bars, the text box and the border."""
        body, trim = palette(self.d, slot)
        bar = self.bar_colour(body, trim) if self.d.bars != "none" else body
        box = self.textbox_colour(body)
        border = self._border_colour(body, trim) if self.d.border != "none" else body
        dark = "#111111"

        def on(c):
            return dark if _lum(c) > 0.55 else "#ffffff"
        return {"name": on(bar), "type": on(bar), "text": on(box), "pt": on(bar),
                "artist": on(border), "credit": on(border)}

    def mana(self, code: str, size: int = fg.MANA_SIZE) -> Image.Image:
        """A mana symbol: ``code`` w u b r g c, or n (the tile numbers go on)."""
        return mana_symbol(self.d, code, size)


# ------------------------------------------------------------------ mana symbols
def _icon(code: str, n: int) -> Image.Image:
    """The symbol's picture (white on clear), n × n pixels."""
    ss = 4
    N = n * ss
    im = Image.new("L", (N, N), 0)
    dr = ImageDraw.Draw(im)
    c = N / 2
    if code == "w":                                   # a sun
        r = N * 0.17
        dr.ellipse([c - r, c - r, c + r, c + r], fill=255)
        for k in range(8):
            a = k * math.pi / 4
            p = [(c + math.cos(a) * N * 0.38, c + math.sin(a) * N * 0.38),
                 (c + math.cos(a + 0.22) * N * 0.22, c + math.sin(a + 0.22) * N * 0.22),
                 (c + math.cos(a - 0.22) * N * 0.22, c + math.sin(a - 0.22) * N * 0.22)]
            dr.polygon(p, fill=255)
    elif code == "u":                                 # a drop
        r = N * 0.22
        dr.ellipse([c - r, c - r + N * 0.1, c + r, c + r + N * 0.1], fill=255)
        dr.polygon([(c, N * 0.1), (c - r * 0.95, c + N * 0.04), (c + r * 0.95, c + N * 0.04)],
                   fill=255)
    elif code == "b":                                 # a skull
        dr.ellipse([N * 0.24, N * 0.15, N * 0.76, N * 0.62], fill=255)
        dr.rounded_rectangle([N * 0.33, N * 0.5, N * 0.67, N * 0.8], N * 0.05, fill=255)
        for ex in (0.38, 0.62):
            dr.ellipse([N * (ex - 0.08), N * 0.36, N * (ex + 0.08), N * 0.5], fill=0)
        dr.polygon([(c, N * 0.53), (c - N * 0.04, N * 0.6), (c + N * 0.04, N * 0.6)], fill=0)
        for tx in (0.42, 0.5, 0.58):
            dr.line([(N * tx, N * 0.68), (N * tx, N * 0.8)], fill=0, width=max(1, N // 60))
    elif code == "r":                                 # a flame
        def drop(cx, cy, r, tall, lean):
            pts = []
            for k in range(73):
                t = k / 72 * 2 * math.pi
                x = math.sin(t) * abs(math.sin(t / 2)) ** 1.3
                y = -math.cos(t)
                pts.append((cx + (x + lean * (1 - y) ** 2 * 0.25) * r,
                            cy + y * r * tall))
            return pts
        dr.polygon(drop(c, c + N * 0.06, N * 0.27, 1.45, -0.6), fill=255)
        dr.polygon(drop(c - N * 0.12, c + N * 0.12, N * 0.11, 1.5, 0.5), fill=255)
        dr.polygon(drop(c + N * 0.02, c + N * 0.2, N * 0.1, 1.3, 0.2), fill=0)
    elif code == "g":                                 # a tree
        dr.rectangle([c - N * 0.05, N * 0.5, c + N * 0.05, N * 0.82], fill=255)
        for (x, y, r) in ((0.5, 0.33, 0.17), (0.35, 0.45, 0.14), (0.65, 0.45, 0.14)):
            dr.ellipse([N * (x - r), N * (y - r), N * (x + r), N * (y + r)], fill=255)
    elif code == "c":                                 # a diamond
        dr.polygon([(c, N * 0.17), (N * 0.8, c), (c, N * 0.83), (N * 0.2, c)], fill=255)
        dr.polygon([(c, N * 0.3), (N * 0.67, c), (c, N * 0.7), (N * 0.33, c)], fill=0)
    return im.resize((n, n), Image.LANCZOS)


def mana_symbol(d: Design, code: str, size: int = fg.MANA_SIZE) -> Image.Image:
    style = d.mana if d.mana != "none" else "circles"
    n = size
    fill = _rgb(_MANA_FILL.get(code, _MANA_FILL["n"]))
    if d.palette in ("gothic", "dark") and style in ("tiles", "brush", "diamonds"):
        tile_col = _rgb("#151315")
        icon_col = {"w": _rgb("#f1e6c4"), "u": _rgb("#3d8ee0"), "b": _rgb("#a774d6"),
                    "r": _rgb("#e2432e"), "g": _rgb("#3fa35f")}.get(code, _rgb("#e8e2d6"))
    elif d.palette == "vivid":
        tile_col = _rgb("#111318")
        icon_col = {"w": _rgb("#fff1a8"), "u": _rgb("#26a8ff"), "b": _rgb("#c45cff"),
                    "r": _rgb("#ff3b30"), "g": _rgb("#2cff7a")}.get(code, _rgb("#e8e8e8"))
    else:
        tile_col = fill
        icon_col = _rgb("#151515")
    ss = 3
    N = n * ss
    m = Image.new("L", (N, N), 0)
    dr = ImageDraw.Draw(m)
    pad = N * 0.06
    if style == "circles":
        dr.ellipse([pad, pad, N - pad, N - pad], fill=255)
    elif style == "diamonds":
        dr.polygon([(N / 2, pad), (N - pad, N / 2), (N / 2, N - pad), (pad, N / 2)], fill=255)
    else:
        dr.rounded_rectangle([pad, pad, N - pad, N - pad], N * (0.08 if style == "tiles"
                                                                 else 0.03), fill=255)
    mask = np.asarray(m.resize((n, n), Image.LANCZOS), dtype=np.float32) / 255
    rng = np.random.default_rng(abs(hash(code)) % 1000 + d.seed)
    if style == "brush":
        nz = _fbm(n, n, 10, 4, rng)
        mask = np.clip((_blur(mask, 3) - 0.5 + (nz - 0.5) * 0.6) * 5 + 0.5, 0, 1)
    arr = np.zeros((n, n, 4), dtype=np.float32)
    # the outline and the tile
    ring = np.clip(_blur(mask, 2.5) * 1.6, 0, 1)
    _over(arr, (0.05, 0.05, 0.05), ring)
    col = np.clip(tile_col * (1 + (_fbm(n, n, 30, 3, rng)[..., None] - 0.5) * 0.25), 0, 1)
    col = np.clip(col + _bevel(mask, n * 0.05, 0.6)[..., None] * 0.35, 0, 1)
    _over(arr, col, mask)
    if code in ("w", "u", "b", "r", "g", "c"):
        ic = np.asarray(_icon(code, int(n * 0.86)), dtype=np.float32) / 255
        full = np.zeros((n, n), dtype=np.float32)
        o = (n - ic.shape[0]) // 2
        full[o:o + ic.shape[0], o:o + ic.shape[1]] = ic
        if d.glow and d.palette == "vivid":
            _over(arr, np.clip(icon_col + 0.2, 0, 1), np.clip(_blur(full, n * 0.04) * d.glow, 0,
                                                              1) * mask)
        _over(arr, icon_col, full * mask)
    return Image.fromarray(np.clip(arr * 255 + 0.5, 0, 255).astype(np.uint8), "RGBA")


def number_colour(d: Design) -> str:
    """The numbers on the mana tile: light on a dark tile."""
    if d.palette in ("gothic", "dark", "vivid") and d.mana in ("tiles", "brush", "diamonds"):
        return "#f2ece0"
    return "#111111"


# ------------------------------------------------------------------ the whole frame
def render_all(d: Design, width: int = 1500, progress=None, cancel=None) -> dict:
    """Every picture of the design: {slot: PIL image} (frames, P/T boxes, mana)."""
    r = Renderer(d, width)
    out: dict = {}
    jobs = [(k, "frame") for k in SLOTS]
    if d.pt_box:
        jobs += [(k, "pt") for k in SLOTS if k != "l"]
    if d.mana != "none":
        jobs += [(k, "mana") for k in ("w", "u", "b", "r", "g", "c", "n")]
    for n, (k, what) in enumerate(jobs):
        if cancel is not None and getattr(cancel, "cancelled", False):
            from .psdread import Stopped
            raise Stopped()
        if progress:
            progress(n, len(jobs), f"Drawing {dict(fg.SLOTS).get(k, k)} – {what}")
        if what == "frame":
            out[k] = r.frame(k)
        elif what == "pt":
            out["pt-" + k] = r.pt_box(k)
        else:
            out["mana-" + k] = r.mana(k)
    return out


def apply_to_frame(frame, d: Design, width: int = 1500) -> None:
    """The design's boxes, text colours, fonts and settings on a Frame studio frame."""
    frame.boxes = boxes(d)
    r = Renderer(d, 120)
    frame.colours.update(r.text_colours("w"))
    frame.art = "under"
    if d.title_font:
        frame.fonts["title"] = d.title_font
    if d.text_font:
        frame.fonts["text"] = d.text_font
    frame.colours["mana"] = number_colour(d)
    frame.mana_flow = "down" if d.mana_column else ""
    frame.design = d.to_dict()


def describe_options() -> str:
    """What the AI may set, for its instructions."""
    def opts(m):
        return ", ".join(f'"{k}"' for k in m)
    return "\n".join([
        f"layout: one of {opts(LAYOUTS)}",
        f"material: one of {opts(MATERIALS)} (use \"picture\" only if told a texture exists)",
        "texture: 0..1 how strongly the material shows; texture_size: 0.3..3 (bigger = coarser)",
        f"palette: one of {opts(PALETTES)}",
        "colours: optional {\"w\"|\"u\"|\"b\"|\"r\"|\"g\"|\"m\"|\"a\"|\"c\"|\"l\": \"#rrggbb\"} – the "
        "frame colour for white, blue, black, red, green, gold, artifact, colourless, land",
        f"border: one of {opts(BORDERS)}; border_width: 0..0.08 (part of the card's width)",
        f"bars: one of {opts(BAR_SHAPES)}; bar_opacity: 0.2..1",
        f"textbox: one of {opts(TEXTBOXES)}; textbox_opacity: 0.2..1; "
        f"textbox_shape: one of {opts(BOX_SHAPES)}",
        f"window: one of {opts(WINDOWS)}",
        f"pinlines: 0..0.02 (thin lines around the bars, boxes and window); "
        f"pinline_colour: one of {opts(PINLINE_COLOURS)}",
        "bevel, shadow, glow, wear, grain, vignette: 0..1",
        "pt_box: true/false",
        f"mana: one of {opts(MANA_STYLES)}; mana_column: true to put the mana cost down the "
        "right side",
        "title_font, text_font: an installed font's name, or \"\" for MSE's usual",
        "seed: a whole number (changes the texture's pattern)",
    ])
