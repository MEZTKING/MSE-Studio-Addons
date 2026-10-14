"""Frame studio: a Magic Set Editor frame made from pictures – the blank frames
a proxy maker shares or sells (one picture per colour: white, blue… gold,
artifact, land), or frames you drew yourself.

A frame here is a small description (its name, which picture is which
colour, where the name, mana cost, art, type line, rules text and P/T go,
text colours and fonts) kept in the add-on's data folder. Saving it writes an
MSE frame folder (``magic-fs-<name>.mse-style``: a ``style`` file and the
pictures) and installs it in MSE's data folder through MSE Studio's own
frame-pack installer – the same as Advanced → Frames → Install a frame pack.

Nothing here uses the network."""
from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image

ADDON_ID = "frame-studio"
PREFIX = "fs-"                          # our frames: magic-fs-<slug>.mse-style
CARD_W, CARD_H, CARD_DPI = 375, 523, 150   # MSE's Magic card, in its own units
MAX_W = 1500                            # pictures are kept up to this wide
PICTURES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".psd")

# the colours a frame has a picture for; MSE picks one by the card's colour
SLOTS = [("w", "White"), ("u", "Blue"), ("b", "Black"), ("r", "Red"), ("g", "Green"),
         ("m", "Gold (multicolour)"), ("a", "Artifact"), ("c", "Colourless"), ("l", "Land")]
SLOT_NAMES = dict(SLOTS)
PT_SLOTS = [("pt-" + k, v) for k, v in SLOTS if k != "l"]     # P/T boxes, if separate
BASE = ["w", "u", "b", "r", "g", "m", "a", "c"]

# where things go, as parts of the card (left, top, width, height) – a modern
# (M15) frame; Frame studio's page lets you move every box
BOXES = [("name", "Name"), ("cost", "Mana cost"), ("art", "Art"), ("type", "Type line"),
         ("rarity", "Set symbol"), ("text", "Rules text"), ("pt", "Power / toughness"),
         ("ptbox", "P/T box picture"), ("artist", "Artist line"), ("credit", "Credit line")]
BOX_NAMES = dict(BOXES)


def _f(x, y, w, h):
    return [round(x / CARD_W, 5), round(y / CARD_H, 5), round(w / CARD_W, 5),
            round(h / CARD_H, 5)]


DEFAULT_BOXES = {
    "name": _f(32, 30, 300, 23), "cost": _f(236, 29, 110, 23), "art": _f(29, 59, 316, 231),
    "type": _f(32, 296, 284, 20), "rarity": _f(318, 297, 26, 20), "text": _f(29, 327, 314, 154),
    "pt": _f(286, 469, 60, 28), "ptbox": _f(273, 466, 81, 42),
    "artist": _f(32, 486, 230, 10), "credit": _f(32, 497, 250, 9)}
FULL_ART = {"art": [0.0, 0.0, 1.0, 1.0]}
TEXT_BOXES = ["name", "type", "text", "pt", "artist"]       # each gets a text colour
DEFAULT_FONTS = {"title": "Beleren Bold", "text": "MPlantin", "italic": "MPlantin-Italic",
                 "pt": "Beleren Bold", "info": "MPlantin"}

# text sizes when you haven't set one: (its box, part of the box's height, at most)
SIZE_RULES = {"title": ("name", 0.7, 17), "cost": ("cost", 0.68, 16), "type": ("type", 0.65, 14),
              "text": ("text", 1.0, 14), "pt": ("pt", 0.57, 17), "info": ("artist", 0.75, 7.5)}
SIZE_NAMES = [("title", "Name"), ("cost", "Mana symbols"), ("type", "Type line"),
              ("text", "Rules text"), ("pt", "Power / toughness"),
              ("info", "Artist and credit lines")]

ART_MODES = {"under": "Under the frame – it shows through the frame's clear parts",
             "over": "On top of the frame, in the art box"}


class FrameError(RuntimeError):
    pass


@dataclass
class Frame:
    name: str                                   # "Death Note – Vibrant"
    slug: str = ""                              # death-note-vibrant
    pictures: dict = field(default_factory=dict)   # slot → file in the frame's folder
    boxes: dict = field(default_factory=dict)   # box → [x, y, w, h] parts of the card
    art: str = "under"                          # under | over
    colours: dict = field(default_factory=dict)   # name, type, text, pt, artist → "#rrggbb"
    fonts: dict = field(default_factory=dict)
    made_from: str = ""                         # the folder or file it came from
    proxy_deck: str = ""                        # a Proxy decks deck it's for (its id)
    when: str = ""
    font_files: list = field(default_factory=list)   # fonts that came with it (in fonts/)
    sizes: dict = field(default_factory=dict)   # title, type, text, cost, pt, info → size
    sources: list = field(default_factory=list)  # the files and folders it was made from

    @property
    def style_name(self) -> str:
        """The name cards use for it (MSE's stylesheet, without "magic-")."""
        return PREFIX + self.slug

    @property
    def folder_name(self) -> str:
        return f"magic-{self.style_name}.mse-style"

    def box(self, key: str) -> list:
        return list(self.boxes.get(key) or DEFAULT_BOXES[key])

    def font(self, key: str) -> str:
        return self.fonts.get(key) or DEFAULT_FONTS[key]

    def colour(self, key: str) -> str:
        return self.colours.get(key) or "#000000"

    def size(self, key: str) -> float:
        """A text's size in MSE's points: the one you set, else one that fits
        its box (never bigger than a real frame's)."""
        try:
            v = float(self.sizes.get(key) or 0)
        except (TypeError, ValueError):
            v = 0
        if v > 0:
            return v
        box, share, cap = SIZE_RULES[key]
        h = self.box(box)[3] * CARD_H
        return round(max(4.0, min(h * share, cap)), 1)


# ------------------------------------------------------------------ where frames are kept
def _data() -> Path:
    from mse_studio.core import addons
    return addons.data_dir(ADDON_ID)


def frames_dir() -> Path:
    d = _data() / "frames"
    d.mkdir(parents=True, exist_ok=True)
    return d


def frame_dir(slug: str) -> Path:
    return frames_dir() / slug


def slug_for(name: str, taken: Optional[set] = None) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "frame"
    out, n = s, 2
    while taken and out in taken:
        out, n = f"{s}-{n}", n + 1
    return out


def load_frames() -> list[Frame]:
    out = []
    for f in sorted(frames_dir().glob("*/frame.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append(Frame(**{k: v for k, v in d.items() if k in Frame.__dataclass_fields__}))
        except (OSError, ValueError, TypeError):
            continue
    return sorted(out, key=lambda fr: fr.name.lower())


def save_frame(frame: Frame) -> None:
    d = frame_dir(frame.slug)
    d.mkdir(parents=True, exist_ok=True)
    frame.when = _dt.datetime.now().isoformat(timespec="seconds")
    (d / "frame.json").write_text(json.dumps(asdict(frame), indent=2), encoding="utf-8")


def delete_frame(slug: str) -> None:
    shutil.rmtree(frame_dir(slug), ignore_errors=True)


# ------------------------------------------------------------------ which picture is which
_WORDS = {
    "w": ("w", "white", "plains", "wht"), "u": ("u", "blue", "island", "blu"),
    "b": ("b", "black", "swamp", "blk"), "r": ("r", "red", "mountain"),
    "g": ("g", "green", "forest", "grn"),
    "m": ("m", "gold", "multi", "multicolor", "multicolour", "multicolored", "multicoloured"),
    "a": ("a", "artifact", "artefact", "artifacts", "vehicle"),
    "c": ("c", "colorless", "colourless", "eldrazi", "devoid", "grey", "gray"),
    "l": ("l", "land", "lands", "nonbasic"),
}
_PT_WORDS = ("pt", "ptbox", "power", "toughness")


def _tokens(stem: str) -> list[str]:
    stem = re.sub(r"([a-z])([A-Z])", r"\1 \2", stem)          # WhiteFrame → White Frame
    return [t for t in re.split(r"[^a-z0-9]+", stem.lower()) if t]


def guess_slot(file_name: str) -> Optional[str]:
    """Which colour a picture is for, from its name ("White.png", "wcard.png",
    "Frame_U.png", "Gold PT.png" → pt-m…); None when it can't tell."""
    stem = Path(file_name).stem
    low = stem.lower().strip()
    m = re.fullmatch(r"([wubrgmac])(l?)(card|pt|frame)?", low)
    if m:                                            # MSE's own names: wcard, gl…
        if m.group(3) == "pt":
            return "pt-" + m.group(1)
        return "l" if m.group(2) else m.group(1)
    toks = _tokens(stem)
    is_pt = any(t in _PT_WORDS for t in toks) or "p/t" in low
    found = []
    for slot, words in _WORDS.items():
        long_words = [w for w in words if len(w) > 1]
        if any(t in long_words for t in toks):
            found.append(slot)
    if not found:                                    # single letters: W, U, B…
        letters = [t for t in toks if len(t) == 1 and t in "wubrgmacl"]
        if len(letters) == 1:
            found = [letters[0]]
    if not found:
        return None
    colour = [s for s in found if s in BASE]
    if is_pt:
        return "pt-" + (colour[0] if colour else found[0]) if (colour or found[0] != "l") \
            else None
    if "l" in found:
        return "l"
    return colour[0] if len(colour) == 1 else ("m" if len(colour) > 1 else found[0])


def pictures_in(folder: Path) -> list[Path]:
    """Picture files in a folder (and the folders in it)."""
    out = []
    for p in sorted(Path(folder).rglob("*")):
        if p.is_file() and p.suffix.lower() in PICTURES and not p.name.startswith("."):
            out.append(p)
    return out


def sort_pictures(files: list[Path]) -> tuple[dict, list[Path]]:
    """{slot: file} for the pictures whose names say their colour, and the rest."""
    slots: dict = {}
    rest = []
    for f in files:
        s = guess_slot(f.name)
        if s and s not in slots:
            slots[s] = f
        else:
            rest.append(f)
    return slots, rest


# ------------------------------------------------------------------ Photoshop files
PSD_W = 1700                    # Photoshop files are read up to this wide (then cut to MAX_W)
# layers that aren't part of the frame: the art, the set symbol, mana symbols…
_PLACEHOLDER = {"art", "artwork", "illustration", "illus", "image", "picture", "photo",
                "symbol", "symbols", "setsymbol", "rarity", "mana", "watermark", "placeholder",
                "expansion", "insert", "paste"}
_KEEP = {"box", "bar", "frame", "border", "bg", "background", "plate", "pinline", "pinlines",
         "line", "lines", "window", "shadow", "outline", "trim", "crown", "texture", "overlay"}


def _is_placeholder(layer) -> bool:
    if layer.kind == "text":                   # the sample name, type line, rules…
        return True
    toks = set(_tokens(layer.name))
    return bool(toks & _PLACEHOLDER) and not toks & _KEEP


def _is_pt(name: str) -> bool:
    return any(t in _PT_WORDS for t in _tokens(name)) or "p/t" in name.lower()


@dataclass
class PsdPick:
    """A picture a Photoshop file can give: a colour's frame put together from
    its groups, the whole file, a group or a single layer."""
    label: str
    guess: str                                   # the slot it's probably for, or ""
    visible: object = None                       # layer key → drawn? (None: as saved)
    root: Optional[int] = None                   # only this group / layer (its key)
    merged: bool = False                         # Photoshop's own merged picture


def _annotate(nodes: list, info: dict, in_pt: bool = False) -> None:
    """For each layer (by key): which colour it is in a set of colour versions
    ("White", "Blue"… side by side), whether it's the P/T box or a placeholder."""
    colours = {}
    for n in nodes:
        g = guess_slot(n.name)
        if g:
            colours[n.key] = g[3:] if g.startswith("pt-") else g
    options = set(colours.values()) if len(set(colours.values())) >= 2 else set()
    for n in nodes:
        pt = in_pt or _is_pt(n.name)
        i = info[n.key] = {"variant": colours.get(n.key) if options else None,
                           "options": options, "pt": pt, "has_pt": pt,
                           "placeholder": _is_placeholder(n), "slots": set()}
        if n.is_group:
            _annotate(n.children, info, pt)
            for c in n.children:
                ci = info[c.key]
                i["has_pt"] = i["has_pt"] or ci["has_pt"]
                i["slots"] |= ci["slots"] | ({ci["variant"]} if ci["variant"] else set())


def _visible(info: dict, slot: Optional[str], part: str = "frame"):
    """Which layers make the frame (``part`` "frame") or the P/T box ("pt")
    for a colour: in each set of colour versions only that colour's; the art,
    sample text and symbols left out."""
    def vis(n) -> bool:
        i = info.get(n.key)
        if i is None or i["placeholder"]:
            return False
        if part == "frame" and i["pt"]:
            return False
        if part == "pt" and not (i["pt"] or i["has_pt"]):
            return False
        if slot and i["variant"] and slot in i["options"]:
            return i["variant"] == slot
        if slot and n.is_group and slot in i["slots"]:
            return True
        if part == "pt" and not i["pt"]:
            return True                          # a group the P/T box is in
        return not n.hidden
    return vis


def psd_picks(psd) -> list[PsdPick]:
    """What a Photoshop file can give, best first."""
    info: dict = {}
    _annotate(psd.layers, info)
    options = set()
    pt_options = set()
    for i in info.values():
        if i["variant"]:
            (pt_options if i["pt"] else options).update(i["options"])
    picks = []
    names = dict(SLOTS)
    for slot in [k for k, _ in SLOTS if k in options]:
        picks.append(PsdPick(f"{names[slot]} frame (put together from the layers)", slot,
                             _visible(info, slot, "frame")))
    for slot in [k for k, _ in SLOTS if k in pt_options and k != "l"]:
        picks.append(PsdPick(f"P/T box – {names[slot]} (put together)", "pt-" + slot,
                             _visible(info, slot, "pt")))
    picks.append(PsdPick("The whole frame as saved (without sample text and art)", "",
                         _visible(info, None, "frame")))
    if psd.merged is not None:
        picks.append(PsdPick("All layers (Photoshop's own picture, with effects)", "",
                             merged=True))

    def groups(nodes, path=""):
        for n in reversed(nodes):                # top first, as Photoshop lists them
            label = f"{path} › {n.name}" if path else n.name
            if n.is_group and not info[n.key]["placeholder"]:
                picks.append(PsdPick(f"Group: {label}", guess_slot(n.name) or "",
                                     _group_vis(info, n.key), root=n.key))
                groups(n.children, label)
    groups(psd.layers)
    for n in reversed(list(psd.walk())):
        if n.kind == "pixel" and n.image is not None:
            picks.append(PsdPick(f"Layer: {n.name}" + (" (hidden)" if n.hidden else ""),
                                 guess_slot(n.name) or "", lambda _n: True, root=n.key))
    return picks


def _group_vis(info: dict, root: int):
    def vis(n) -> bool:
        i = info.get(n.key)
        if n.key == root:
            return True
        return i is not None and not i["placeholder"] and not n.hidden
    return vis


def psd_picture(psd, pick: PsdPick, cancel=None) -> Image.Image:
    """A pick drawn (at the size ``psd`` was read)."""
    from . import psdread
    if pick.merged:
        return psd.merged.copy()
    nodes = None
    if pick.root is not None:
        nodes = [n for n in psd.walk() if n.key == pick.root]
    return psdread.composite(psd, pick.visible, nodes=nodes, cancel=cancel)


def read_psd(path: Path, progress=None, cancel=None):
    from . import psdread
    return psdread.read(Path(path), max_w=PSD_W, progress=progress, cancel=cancel)


# ------------------------------------------------------------------ fonts
FONT_EXTS = (".ttf", ".otf", ".ttc")


def fonts_in(paths: list) -> list[Path]:
    """Font files among files and folders (and in .zip files there, unpacked
    into the add-on's data folder)."""
    out: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and (f.suffix.lower() in FONT_EXTS or
                                    (f.suffix.lower() == ".zip" and "font" in f.name.lower())):
                    out += fonts_in([f])
        elif p.suffix.lower() in FONT_EXTS and p.is_file():
            out.append(p)
        elif p.suffix.lower() == ".zip" and p.is_file():
            out += _fonts_from_zip(p)
    seen, keep = set(), []
    for f in out:                                # the same font twice ("… copy.ttf")
        key = (f.stat().st_size, font_name(f).lower())
        if key not in seen:
            seen.add(key)
            keep.append(f)
    return keep


def _fonts_from_zip(z: Path) -> list[Path]:
    import hashlib
    out = []
    dest = _data() / "font-inbox" / hashlib.sha1(str(z).encode()).hexdigest()[:10]
    try:
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                base = Path(n).name
                if n.endswith("/") or Path(base).suffix.lower() not in FONT_EXTS or \
                        base.startswith((".", "__MACOSX")) or "__MACOSX" in n:
                    continue
                dest.mkdir(parents=True, exist_ok=True)
                f = dest / base
                f.write_bytes(zf.read(n))
                out.append(f)
    except (OSError, zipfile.BadZipFile):
        return []
    return out


def font_name(path: Path) -> str:
    """The name MSE uses for a font file (its family)."""
    try:
        from PIL import ImageFont
        fam, _sty = ImageFont.truetype(str(path), 12).getname()
        return (fam or Path(path).stem).strip()
    except Exception:  # noqa: BLE001 - not a font Pillow can read
        return Path(path).stem


def guess_fonts(files: list) -> dict:
    """Which of a frame's fonts go where: the most title-like one for the
    name and type line (the rules text keeps MSE's MPlantin unless one says
    it's for text)."""
    names = [font_name(f) for f in files]
    if not names:
        return {}

    def score(n: str) -> int:
        t = set(_tokens(n))
        s = 0
        s += 3 * bool(t & {"title", "name", "header", "heading", "beleren", "display", "logo"})
        s -= 3 * bool(t & {"hand", "handwriting", "handwritten", "script", "note", "notes"})
        s -= 1 * bool(t & {"extra", "copy", "italic", "light"})
        return s
    out = {"title": sorted(names, key=lambda n: -score(n))[0]}
    body = [n for n in names if set(_tokens(n)) & {"text", "body", "rules", "plantin", "book"}]
    if body:
        out["text"] = body[0]
    return out


def keep_fonts(frame: Frame, files: list) -> None:
    """Fonts that came with the frame, kept in its folder."""
    d = frame_dir(frame.slug) / "fonts"
    for f in files:
        f = Path(f)
        if not f.is_file():
            continue
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f.name
        if dest.resolve() != f.resolve():
            shutil.copyfile(f, dest)
        rel = f"fonts/{f.name}"
        if rel not in frame.font_files:
            frame.font_files.append(rel)


def frame_fonts(frame: Frame) -> list[Path]:
    return [frame_dir(frame.slug) / f for f in frame.font_files
            if (frame_dir(frame.slug) / f).is_file()]


# ------------------------------------------------------------------ pictures
def psd_layers(path: Path) -> list[tuple[str, Image.Image]]:
    """The layers of a Photoshop file, each on the whole canvas (with its
    transparency), top layer first – and the whole picture last ("All
    layers"), when the file has one."""
    from . import psdread
    out = list(psdread.layer_pictures(Path(path)))
    try:
        with Image.open(path) as im:               # the merged picture Photoshop saves
            out.append(("All layers", im.convert("RGBA")))
    except Exception:  # noqa: BLE001 - not every file has it
        pass
    return out


def open_picture(path: Path) -> Image.Image:
    from PIL import ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        return im.convert("RGBA")


def card_area(size: tuple[int, int]) -> tuple[int, int, int, int]:
    """The card in a picture (left, top, right, bottom): without MPC's 1/8 in
    margin when the picture has it."""
    w, h = size
    if not w or not h:
        return 0, 0, w, h
    r = w / h
    if abs(r - 2.75 / 3.75) < abs(r - 2.5 / 3.5) and r < 0.8:
        bx, by = round(w * 0.125 / 2.75), round(h * 0.125 / 3.75)
        return bx, by, w - bx, h - by
    return 0, 0, w, h


def card_picture(path: Path) -> Image.Image:
    """A frame picture as the card alone (margin cut off), at most MAX_W wide."""
    im = open_picture(path)
    im = im.crop(card_area(im.size))
    if im.width > MAX_W:
        im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
    return im


def coverage(path: Path) -> float:
    """How much of a picture isn't see-through: 0..1."""
    with Image.open(path) as im:
        if im.mode not in ("RGBA", "LA", "PA"):
            return 1.0
        a = im.getchannel("A").resize((32, 32))
    data = list(a.getdata())
    return sum(1 for v in data if v >= 128) / len(data)


def is_card_shaped(size: tuple[int, int]) -> bool:
    w, h = size
    return h > 0 and 0.62 < w / h < 0.8


def clear_in(img: Image.Image, box: list) -> float:
    """How much of a box (parts of the picture) is see-through: 0..1."""
    w, h = img.size
    x, y, bw, bh = box
    region = img.crop((round(x * w), round(y * h), round((x + bw) * w), round((y + bh) * h)))
    if region.mode != "RGBA" or not region.width or not region.height:
        return 0.0
    a = region.getchannel("A").resize((32, 32))
    data = list(a.getdata())
    return sum(1 for v in data if v < 128) / len(data)


def guess_art(img: Image.Image) -> tuple[str, Optional[list]]:
    """Where the art goes on this frame: (mode, art box or None for the
    default). A frame that's clear in the middle of its text box is a full-art
    one (the art fills the card under it)."""
    win = clear_in(img, DEFAULT_BOXES["art"])
    text = clear_in(img, DEFAULT_BOXES["text"])
    if win > 0.5 and text > 0.3:
        return "under", list(FULL_ART["art"])
    if win > 0.5:
        return "under", None
    return "over", None


def guess_colours(img: Image.Image, boxes: dict) -> dict:
    """Dark text on light parts of the frame, white text on dark parts."""
    w, h = img.size
    rgb = Image.new("RGB", img.size, (128, 128, 128))
    rgb.paste(img, mask=img.getchannel("A") if img.mode == "RGBA" else None)
    out = {}
    for key in TEXT_BOXES:
        x, y, bw, bh = boxes.get(key) or DEFAULT_BOXES[key]
        region = rgb.crop((round(x * w), round(y * h), round((x + bw) * w),
                           round((y + bh) * h))).resize((16, 16))
        px = list(region.getdata())
        if not px:
            continue
        lum = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px) / len(px)
        out[key] = "#000000" if lum > 120 else "#ffffff"
    return out


# ------------------------------------------------------------------ the MSE frame
def _n(v: float) -> str:
    v = round(v, 1)
    return str(int(v)) if v == int(v) else str(v)


def _rect(box: list) -> dict:
    x, y, w, h = box
    return {"left": _n(x * CARD_W), "top": _n(y * CARD_H), "width": _n(w * CARD_W),
            "height": _n(h * CARD_H)}


def _rgb(hexcol: str) -> str:
    c = (hexcol or "#000000").lstrip("#")
    try:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except (ValueError, IndexError):
        r = g = b = 0
    return f"rgb({r},{g},{b})"


def _files_for(frame: Frame) -> tuple[dict, dict]:
    """{code: file name} for every frame code MSE asks for (w… c, wl… cl) and
    for the P/T boxes – missing colours use the nearest one there is."""
    have = {k: v for k, v in frame.pictures.items() if v}
    base = [k for k in BASE if k in have]
    if not base and "l" not in have:
        raise FrameError("Pick at least one frame picture (White, Blue… or any colour).")
    first = base[0] if base else "l"
    names = {}
    for k in BASE:
        names[k] = f"card-{k if k in have else ('c' if 'c' in have else first)}.png"
    for k in BASE:
        names[k + "l"] = "card-l.png" if "l" in have else names[k]
    pts = {}
    pt_have = [k[3:] for k in have if k.startswith("pt-")]
    if pt_have:
        for k in BASE:
            pick = k if k in pt_have else ("c" if "c" in pt_have else pt_have[0])
            pts[k] = f"pt-{pick}.png"
        for k in BASE:
            pts[k + "l"] = pts[k]
    return names, pts


def _map(name: str, values: dict) -> list[str]:
    lines = [f"\t{name} := ["]
    lines += [f'\t\t{k}: "{v}"' for k, v in values.items()]
    lines.append("\t]")
    return lines


def style_text(frame: Frame, version: str = "") -> str:
    """The MSE ``style`` file of a frame."""
    names, pts = _files_for(frame)
    today = version or _dt.date.today().isoformat()
    full = frame.name.replace("\n", " ").strip() or "Frame studio frame"
    short = full[:32]
    under = frame.art != "over"
    L = [
        "mse version: 2.0.2",
        "game: magic",
        f"short name: {short}",
        f"full name: {full}",
        "icon: card-sample.png",
        "position hint: 900",
        f"installer group: magic/Frame studio/{short}",
        f"version: {today}",
        "depends on:",
        "\tpackage: magic.mse-game",
        "\tversion: 2008-08-08",
        "depends on:",
        "\tpackage: magic-default-image.mse-include",
        "\tversion: 2007-09-23",
        "depends on:",
        "\tpackage: magic-mana-large.mse-symbol-font",
        "\tversion: 2007-09-23",
        "depends on:",
        "\tpackage: magic-mana-small.mse-symbol-font",
        "\tversion: 2007-09-23",
        "",
        f"card width: {CARD_W}",
        f"card height: {CARD_H}",
        f"card dpi: {CARD_DPI}",
        "#### Made with Frame studio (an MSE Studio add-on) from pictures.",
        "init script:",
        "\tinclude file: /magic-default-image.mse-include/scripts",
        "\t# which picture: the card's colour (several colours: gold), and land",
        "\tfs_frame_code := {",
        "\t\tcol := card.card_color",
        '\t\tn := count_chosen(col, choices: "white,blue,black,red,green")',
        "\t\tcode :=",
        '\t\tif      n > 1                              then "m"',
        '\t\telse if chosen(col, choice: "white")       then "w"',
        '\t\telse if chosen(col, choice: "blue")        then "u"',
        '\t\telse if chosen(col, choice: "black")       then "b"',
        '\t\telse if chosen(col, choice: "red")         then "r"',
        '\t\telse if chosen(col, choice: "green")       then "g"',
        '\t\telse if chosen(col, choice: "artifact")    then "a"',
        '\t\telse                                            "c"',
        "\t\t",
        '\t\tif chosen(col, choice: "land") then code + "l" else code',
        "\t}",
    ]
    L += _map("fs_frames", names)
    L.append("\tfs_frame := { fs_frames[fs_frame_code()] }")
    if pts:
        L += _map("fs_pt_boxes", pts)
        L.append("\tfs_pt_box := { fs_pt_boxes[fs_frame_code()] }")
    L += [
        "############################################################## Set symbol",
        "set info style:",
        "\tsymbol:",
    ]
    for var, fill, border in (("common", "rgb(0,0,0)", "rgb(255,255,255)"),
                              ("uncommon", "rgb(176,188,198)", "rgb(0,0,0)"),
                              ("rare", "rgb(213,180,90)", "rgb(0,0,0)"),
                              ("mythic rare", "rgb(232,96,32)", "rgb(0,0,0)"),
                              ("special", "rgb(120,70,170)", "rgb(0,0,0)")):
        L += ["\t\tvariation:", f"\t\t\tname: {var}", "\t\t\tborder radius: 0.10",
              "\t\t\tfill type: solid", f"\t\t\tfill color: {fill}",
              f"\t\t\tborder color: {border}"]
    L += [
        "############################################################## The card",
        "card style:",
        "\tcard color:",
        "\t\tleft: 0",
        "\t\ttop: 0",
        f"\t\twidth: {CARD_W}",
        f"\t\theight: {CARD_H}",
        f"\t\tz index: {1 if under else 0}",
        "\t\trender style: image",
        "\t\tpopup style: in place",
        "\t\timage: { fs_frame() }",
    ]
    r = _rect(frame.box("art"))
    L += ["\timage:"] + [f"\t\t{k}: {v}" for k, v in r.items()] + [
        f"\t\tz index: {0 if under else 1}",
        "\t\tdefault: {default_image(card.card_color)}"]
    # name: up to the mana cost
    nr, cr = _rect(frame.box("name")), _rect(frame.box("cost"))
    cost_right = float(cr["left"]) + float(cr["width"])
    name_right = float(nr["left"]) + float(nr["width"])
    L += ["\tname:", f"\t\tleft: {nr['left']}", f"\t\ttop: {nr['top']}",
          f"\t\tright: {{ min({_n(name_right)}, {_n(cost_right)} - "
          "card_style.casting_cost.content_width - 4) }",
          f"\t\theight: {nr['height']}",
          "\t\talignment: bottom shrink-overflow", "\t\tpadding bottom: 0", "\t\tz index: 3",
          "\t\tfont:", f"\t\t\tname: {frame.font('title')}",
          f"\t\t\tsize: {_n(frame.size('title'))}",
          f"\t\t\tcolor: {_rgb(frame.colour('name'))}"]
    L += ["\tcasting cost:", f"\t\tright: {_n(cost_right)}", f"\t\ttop: {cr['top']}",
          "\t\twidth: { max(30, card_style.casting_cost.content_width) + 5 }",
          f"\t\theight: {cr['height']}", "\t\talignment: middle right",
          "\t\tfont:", f"\t\t\tname: {frame.font('text')}",
          f"\t\t\tsize: {_n(frame.size('cost'))}",
          "\t\tsymbol font:", "\t\t\tname: magic-mana-large",
          f"\t\t\tsize: {_n(frame.size('cost'))}",
          "\t\t\talignment: middle right", "\t\talways symbol: true", "\t\tz index: 4",
          "\t\tpadding top: 0"]
    tr = _rect(frame.box("type"))
    L += ["\ttype:"] + [f"\t\t{k}: {v}" for k, v in tr.items()] + [
        "\t\talignment: top shrink-overflow", "\t\tz index: 3", "\t\tpadding top: 2",
        "\t\tfont:", f"\t\t\tname: {frame.font('title')}",
        f"\t\t\tsize: {_n(frame.size('type'))}",
        f"\t\t\tcolor: {_rgb(frame.colour('type'))}",
        "\t\t\tseparator color: rgb(128,128,128)"]
    rr = _rect(frame.box("rarity"))
    L += ["\trarity:"] + [f"\t\t{k}: {v}" for k, v in rr.items()] + [
        "\t\tz index: 4", "\t\talignment: middle right", "\t\trender style: image",
        "\t\tchoice images:"]
    for choice, var in (("basic land", "common"), ("common", "common"),
                        ("uncommon", "uncommon"), ("rare", "rare"),
                        ("mythic rare", "mythic rare"), ("special", "special"),
                        ("masterpiece", "special")):
        L.append(f'\t\t\t{choice}: {{ symbol_variation(symbol: set.symbol, variation: "{var}") }}')
    xr = _rect(frame.box("text"))
    L += ["\ttext:"] + [f"\t\t{k}: {v}" for k, v in xr.items()] + [
        "\t\tfont:", f"\t\t\tname: {frame.font('text')}",
        f"\t\t\titalic name: {frame.font('italic')}", f"\t\t\tsize: {_n(frame.size('text'))}",
        "\t\t\tscale down to: 6", f"\t\t\tcolor: {_rgb(frame.colour('text'))}",
        "\t\tsymbol font:", "\t\t\tname: magic-mana-small",
        f"\t\t\tsize: {_n(frame.size('text'))}",
        "\t\talignment: middle left", "\t\tz index: 3", "\t\tpadding left: 6",
        "\t\tpadding right: 4", "\t\tline height hard: 1.2", "\t\tline height line: 1.5",
        "\t\tline height soft: 0.9", "\t\tline height hard max: 1.3",
        "\t\tline height line max: 1.6"]
    pr = _rect(frame.box("pt"))
    L += ["\tpt:"] + [f"\t\t{k}: {v}" for k, v in pr.items()] + [
        "\t\tz index: 4", "\t\talignment: center middle shrink-overflow", "\t\tfont:",
        f"\t\t\tname: {frame.font('pt')}",
        f"\t\t\tsize: {_n(frame.size('pt'))}",
        f"\t\t\tcolor: {_rgb(frame.colour('pt'))}", "\t\t\tseparator color: rgb(200,0,0)"]
    for field_name, key, col in (("illustrator", "artist", "artist"),
                                 ("secondary copyright", "credit", "artist")):
        ar = _rect(frame.box(key))
        L += [f"\t{field_name}:"] + [f"\t\t{k}: {v}" for k, v in ar.items()] + [
            "\t\tz index: 3", "\t\tfont:", f"\t\t\tname: {frame.font('info')}",
            f"\t\t\tsize: {_n(frame.size('info'))}",
            f"\t\t\tcolor: {_rgb(frame.colour(col))}"]
    if pts:
        br = _rect(frame.box("ptbox"))
        L += ["############################################################## P/T box",
              "extra card field:", "\ttype: choice", "\tname: pt box",
              "\tscript: card.card_color", "\teditable: false", "\tsave value: false",
              "extra card style:", "\tpt box:"] + \
            [f"\t\t{k}: {v}" for k, v in br.items()] + [
              "\t\tz index: 2", '\t\tvisible: { card.pt != "" }', "\t\trender style: image",
              "\t\timage: { fs_pt_box() }"]
    return "\n".join(L) + "\n"


def build(frame: Frame, out_dir: Path) -> Path:
    """Write the MSE frame folder (style file and pictures) in ``out_dir``."""
    names, pts = _files_for(frame)
    src = frame_dir(frame.slug)
    dest = Path(out_dir) / frame.folder_name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    done: set = set()
    for code, file in list(names.items()) + list(pts.items()):
        if file in done:
            continue
        slot = file[len("card-"):-4] if file.startswith("card-") else "pt-" + file[3:-4]
        pic = frame.pictures.get(slot)
        if not pic:
            continue
        card_picture(src / pic).save(dest / file, "PNG", optimize=True)
        done.add(file)
    sample = next((frame.pictures[k] for k in BASE + ["l"] if frame.pictures.get(k)), None)
    if sample:
        icon = card_picture(src / sample)
        icon.thumbnail((60, 84))
        icon.save(dest / "card-sample.png", "PNG")
    (dest / "style").write_text(style_text(frame), encoding="utf-8")
    return dest


def zip_frame(folder: Path) -> Path:
    out = folder.parent / (folder.name + ".zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                z.write(f, f"{folder.name}/{f.relative_to(folder).as_posix()}")
    return out


def install(frame: Frame, data_dir: Path) -> str:
    """Build the frame and put it in MSE's data folder (with MSE Studio's
    frame-pack installer; an older copy of this frame goes to the add-on's
    "replaced" folder). Returns the name cards use for it."""
    from mse_studio.core import mse_packages
    if not data_dir or not Path(data_dir).is_dir():
        raise FrameError("MSE's data folder wasn't found – set where MSE is in Settings.")
    work = _data() / "build"
    shutil.rmtree(work, ignore_errors=True)
    folder = build(frame, work)
    pack = zip_frame(folder)
    try:
        mse_packages.install_zip(pack, Path(data_dir), backup_root=_data() / "replaced")
    except mse_packages.PackError as e:
        raise FrameError(str(e)) from None
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return frame.style_name


def uninstall(frame: Frame, data_dir: Path) -> None:
    """Take the frame out of MSE's data folder (kept in the add-on's
    "replaced" folder)."""
    from mse_studio.core import mse_packages
    if data_dir and (Path(data_dir) / frame.folder_name).exists():
        mse_packages.remove_package(Path(data_dir), frame.folder_name, _data() / "replaced")


def is_installed(frame: Frame, data_dir: Optional[Path]) -> bool:
    return bool(data_dir) and (Path(data_dir) / frame.folder_name / "style").is_file()


# ------------------------------------------------------------------ a new frame
def new_frame(name: str, slots: dict, made_from: str = "", fonts: Optional[list] = None,
              font_names: Optional[dict] = None) -> Frame:
    """A frame from pictures ({slot: picture file or PIL image}): they're copied
    into its own folder, and the art box and text colours are guessed. Fonts
    that came with it are kept with it (``font_names``: which goes where)."""
    taken = {f.slug for f in load_frames()}
    frame = Frame(name=name.strip() or "My frame", made_from=made_from)
    frame.slug = slug_for(frame.name, taken)
    set_pictures(frame, slots)
    if fonts:
        keep_fonts(frame, fonts)
        frame.fonts.update(font_names if font_names is not None else guess_fonts(fonts))
    first = next((frame.pictures[k] for k in BASE + ["l"] if frame.pictures.get(k)), None)
    if first:
        img = card_picture(frame_dir(frame.slug) / first)
        frame.art, art_box = guess_art(img)
        if art_box:
            frame.boxes["art"] = art_box
        frame.colours = guess_colours(img, {k: frame.box(k) for k in TEXT_BOXES})
    return frame


def set_pictures(frame: Frame, slots: dict) -> None:
    """Copy pictures into the frame's folder: {slot: path, PIL image or None}."""
    d = frame_dir(frame.slug) / "pictures"
    d.mkdir(parents=True, exist_ok=True)
    for slot, src in slots.items():
        if src is None:
            frame.pictures.pop(slot, None)
            continue
        out = d / f"{slot}.png"
        if isinstance(src, Image.Image):
            src.save(out, "PNG")
        else:
            open_picture(Path(src)).save(out, "PNG")
        frame.pictures[slot] = f"pictures/{slot}.png"
    if any(k.startswith("pt-") and v is not None for k, v in slots.items()):
        fit_pt_boxes(frame)


def fit_pt_boxes(frame: Frame) -> bool:
    """P/T box pictures the size of the whole card (put together from a
    Photoshop file) are cut to the box, and the P/T box and its numbers are
    placed where it is on the card. Returns True when they were."""
    d = frame_dir(frame.slug)
    pts = {k: d / v for k, v in frame.pictures.items() if k.startswith("pt-") and v}
    imgs, box = {}, None
    for k, f in pts.items():
        try:
            im = open_picture(f)
        except Exception:  # noqa: BLE001 - a picture that can't be read
            continue
        if not is_card_shaped(im.size):
            continue
        im = im.crop(card_area(im.size))
        bb = im.getchannel("A").point(lambda a: 255 if a > 24 else 0).getbbox()
        if bb is None:
            continue
        imgs[k] = im
        box = bb if box is None else (min(box[0], bb[0]), min(box[1], bb[1]),
                                      max(box[2], bb[2]), max(box[3], bb[3]))
    if not imgs or box is None:
        return False
    w, h = next(iter(imgs.values())).size
    for k, im in imgs.items():
        im.crop(box).save(pts[k], "PNG")
    x, y, bw, bh = box[0] / w, box[1] / h, (box[2] - box[0]) / w, (box[3] - box[1]) / h
    frame.boxes["ptbox"] = [round(v, 5) for v in (x, y, bw, bh)]
    frame.boxes["pt"] = [round(v, 5) for v in (x + bw * 0.16, y + bh * 0.07, bw * 0.74,
                                                bh * 0.67)]
    return True
