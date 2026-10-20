"""Paint studio's files: paintings are saved as OpenRaster (.ora, see
https://www.openraster.org) – the layered format Krita, GIMP and MyPaint
open too – and can be exported as PNG, JPG or one PNG per layer. Pictures
(and the layers of Photoshop files) can be brought in.

Only QImage, plain files and the paths passed in: no widgets, so all of this
can run in a Job on a worker thread. Pass a painting nobody is painting on
while it saves (``Layer.copy()`` the layers first if they might change)."""
from __future__ import annotations

import errno
import io
import math
import mmap
import os
import re
import secrets
import struct
import sys
import time
import warnings
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QColor, QColorSpace, QImage, QImageReader, QPainter

from .doc import BLENDS, FORMAT, Document, Layer, blank

__all__ = ["EXT", "save", "load", "thumbnail", "export_png", "export_jpg", "export_layers",
           "import_image", "import_psd_layers"]

EXT = ".ora"
MIMETYPE = b"image/openraster"
THUMB = 256                           # the thumbnail inside a painting, at most this size
MAX_SIDE = 30000                      # a painting or picture bigger than this isn't opened
MAX_PIXELS = 250_000_000              # (1 GB a layer)
MAX_XML = 32 * 1024 * 1024
MAX_MEMBER = 1536 * 1024 * 1024       # one picture inside a painting

_BLEND_BY_OP = {v[2]: k for k, v in BLENDS.items()}
_ALPHA_BYTE = 3 if sys.byteorder == "little" else 0      # in a FORMAT (ARGB32) pixel
_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
_FILE_BAD = re.compile(r'[<>:"/\\|?*]')
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')


# ====================================================================== saving
def save(doc: Document, path: Path) -> None:
    """Save the painting as OpenRaster: every layer (a PNG) with its name,
    opacity, blend, visibility and locks, the whole picture and a thumbnail.
    Written to a new file that then takes the old one's place, so a crash or a
    full disk never leaves half a painting."""
    path = Path(path)
    layers = list(doc.layers)
    if not layers:
        raise ValueError("There's nothing to save: the painting has no layers.")
    merged = doc.composite()
    thumb = _fit(merged, THUMB)

    root = ET.Element("image", {"version": "0.0.3", "w": str(doc.width), "h": str(doc.height)})
    stack = ET.SubElement(root, "stack")
    for i in range(len(layers) - 1, -1, -1):              # the top layer first
        lay = layers[i]
        attrs = {
            "name": _XML_BAD.sub("", lay.name or "") or f"Layer {i + 1}",
            "src": f"data/layer{i}.png",
            "x": "0",
            "y": "0",
            "opacity": _num(lay.opacity),
            "visibility": "visible" if lay.visible else "hidden",
            "composite-op": BLENDS.get(lay.blend, BLENDS["normal"])[2],
            "edit-locked": _xml_bool(lay.locked),          # OpenRaster's own (MyPaint, Krita)
            "mse-locked": _xml_bool(lay.locked),
            "mse-alpha-lock": _xml_bool(lay.alpha_lock),
            "mse-clip": _xml_bool(lay.clip),
        }
        if i == doc.active:
            attrs["selected"] = "true"
        ET.SubElement(stack, "layer", attrs)
    xml = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    stamp = time.localtime()[:6]

    def write(f) -> None:
        with zipfile.ZipFile(f, "w", allowZip64=True) as z:
            # OpenRaster: "mimetype" first and not compressed, so a reader
            # can tell what the file is from its first bytes
            _put(z, "mimetype", MIMETYPE, stamp, zipfile.ZIP_STORED)
            _put(z, "stack.xml", xml, stamp, zipfile.ZIP_DEFLATED)
            for i, lay in enumerate(layers):
                _put(z, f"data/layer{i}.png", _png(lay.image), stamp)
            _put(z, "mergedimage.png", _png(merged), stamp)
            _put(z, "Thumbnails/thumbnail.png", _png(thumb), stamp)

    _write_atomic(path, write)


def export_png(doc: Document, path: Path, background: Optional[QColor] = None) -> None:
    """The whole picture as a PNG – see-through where nothing is painted, or
    on ``background``."""
    path = Path(path)
    data = _png(doc.flattened(background))
    _write_atomic(path, lambda f: f.write(data))


def export_jpg(doc: Document, path: Path, quality: int = 95) -> None:
    """The whole picture as a JPG on white."""
    from PIL import Image
    path = Path(path)
    quality = max(1, min(100, int(quality)))
    img = doc.flattened(QColor("white")).convertToFormat(QImage.Format_RGB888)
    w, h = img.width(), img.height()
    rows = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h)
    arr = np.ascontiguousarray(rows.reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3))
    buf = io.BytesIO()
    # full colour detail (no 4:2:0) at high quality: sharp coloured lines stay sharp
    Image.fromarray(arr, "RGB").save(buf, "JPEG", quality=quality, optimize=True,
                                     subsampling=0 if quality >= 90 else 2)
    data = buf.getvalue()
    _write_atomic(path, lambda f: f.write(data))


def export_layers(doc: Document, folder: Path) -> list[Path]:
    """One PNG per layer, the size of the painting, numbered from the bottom
    ("01 Background.png", "02 Layer 1.png"…). Files of the same name are
    replaced. Returns the files written."""
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise _save_error(folder, e) from e
    digits = max(2, len(str(len(doc.layers))))
    out = []
    for i, lay in enumerate(doc.layers):
        name = _FILE_BAD.sub("-", _CONTROL.sub("", lay.name or ""))
        name = re.sub(r"\s+", " ", name).strip(" .")[:80].strip(" .") or "Layer"
        path = folder / f"{i + 1:0{digits}d} {name}.png"
        data = _png(lay.image)
        _write_atomic(path, lambda f, d=data: f.write(d))
        out.append(path)
    return out


# ====================================================================== opening
def load(path: Path) -> Document:
    """Open an OpenRaster painting – one saved here, or by Krita, GIMP or
    MyPaint (layers in groups are taken out of their groups, in order)."""
    path = Path(path)
    bad = (f"“{path.name}” isn't a painting Paint studio can open (an OpenRaster .ora "
           "file), or it's damaged.")
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, EOFError, ValueError):
        raise ValueError(bad) from None
    except OSError as e:
        raise OSError(f"Couldn't open “{path.name}”: {_why(e)}.") from e
    with z:
        try:
            return _load_zip(z, path.name, bad)
        except (zipfile.BadZipFile, zlib.error, EOFError, KeyError, struct.error,
                RuntimeError, NotImplementedError, ET.ParseError):
            raise ValueError(bad) from None


def thumbnail(path: Path, size: int = 256) -> Optional[QImage]:
    """A painting's small picture (or its whole picture, made small) without
    opening its layers; None when there isn't one."""
    size = max(1, int(size or THUMB))
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            order = ["Thumbnails/thumbnail.png", "mergedimage.png"]
            if size > THUMB:
                order.reverse()
            for name in order:
                if name in names:
                    img = _decode(_member(z, name))
                    if not img.isNull():
                        return _fit(img, size)
    except Exception:
        return None
    return None


def _load_zip(z: zipfile.ZipFile, name: str, bad: str) -> Document:
    names = set(z.namelist())
    lookup = {n.lower(): n for n in names}
    if "stack.xml" not in names:
        raise ValueError(bad)
    if "mimetype" in names and not _member(z, "mimetype", 4096).strip().startswith(MIMETYPE):
        raise ValueError(bad)                      # another zip (a .kra, an .odt…)
    xml = _member(z, "stack.xml", MAX_XML)
    if b"<!ENTITY" in xml:
        raise ValueError(bad)
    root = ET.fromstring(xml)
    if _tag(root) != "image":
        raise ValueError(bad)

    w, h = _int(root.get("w")), _int(root.get("h"))
    if w <= 0 or h <= 0:                           # no size: take the whole picture's
        size = _png_size(_member(z, "mergedimage.png")) if "mergedimage.png" in names else None
        if not size:
            raise ValueError(f"“{name}” doesn't say how big the painting is, so it can't "
                             "be opened.")
        w, h = size
    if w > MAX_SIDE or h > MAX_SIDE or w * h > MAX_PIXELS:
        raise ValueError(f"“{name}” is too big to open ({w} × {h} pixels).")

    entries: list = []
    top = next((el for el in root if _tag(el) == "stack"), None)
    if top is not None:
        _walk(top, 0, 0, 1.0, True, entries, 0)

    def no_memory() -> ValueError:
        return ValueError(f"There isn't enough memory to open “{name}” ({w} × {h} pixels, "
                          f"{max(1, len(entries))} layers).")

    layers: list[Layer] = []
    selected = None
    found = 0
    for n, (el, x, y, opacity, visible) in enumerate(entries):
        img = None
        src = (el.get("src") or "").replace("\\", "/")
        while src.startswith("./"):
            src = src[2:]
        src = src.lstrip("/")
        src = src if src in names else lookup.get(src.lower())
        if src:
            try:
                pic = _decode(_member(z, src))
            except (ValueError, KeyError, zipfile.BadZipFile, zlib.error, EOFError,
                    RuntimeError, NotImplementedError):
                pic = QImage()                      # a damaged layer: left empty
            if not pic.isNull():
                found += 1
                img = pic if (x, y) == (0, 0) and pic.size() == QSize(w, h) else _place(pic, x, y, w, h)
        if img is None:
            img = blank(w, h)
        if img.isNull():
            raise no_memory()
        locked = el.get("mse-locked")
        lay = Layer(el.get("name") or f"Layer {n + 1}", img,
                    opacity=round(opacity, 4), visible=visible,
                    blend=_BLEND_BY_OP.get((el.get("composite-op") or "").strip().lower(),
                                           "normal"),
                    locked=_true(locked if locked is not None else el.get("edit-locked")),
                    alpha_lock=_true(el.get("mse-alpha-lock")),
                    clip=_true(el.get("mse-clip")))
        if _true(el.get("selected")):
            selected = n
        layers.append(lay)

    if not found and "mergedimage.png" in names:   # no layer could be read: the whole picture
        pic = _decode(_member(z, "mergedimage.png"))
        if not pic.isNull():
            img = pic if pic.size() == QSize(w, h) else _place(pic, 0, 0, w, h)
            if img.isNull():
                raise no_memory()
            layers, selected = [Layer("Background", img)], 0
    if not layers:
        raise ValueError(f"“{name}” has no layers in it.")

    doc = Document(w, h)
    doc.layers = layers
    doc.active = selected if selected is not None else len(layers) - 1
    doc.dirty = False
    return doc


def _walk(stack: ET.Element, x: int, y: int, opacity: float, visible: bool,
          out: list, depth: int) -> None:
    """The layers in ``stack`` and the groups in it, bottom-up (OpenRaster
    lists the top one first). A group's place, opacity and visibility pass to
    its layers."""
    if depth > 64:
        return
    for el in reversed(list(stack)):
        tag = _tag(el)
        if tag not in ("stack", "layer"):
            continue
        ex, ey = x + _int(el.get("x")), y + _int(el.get("y"))
        op = opacity * _opacity(el.get("opacity"))
        vis = visible and (el.get("visibility") or "visible").strip().lower() != "hidden"
        if tag == "stack":
            _walk(el, ex, ey, op, vis, out, depth + 1)
        else:
            out.append((el, ex, ey, op, vis))


# ====================================================================== bringing pictures in
def import_image(path: Path) -> QImage:
    """Any picture Qt or Pillow can read (PNG, JPG, WEBP, BMP, TIFF, GIF, a
    Photoshop file flattened…), turned the right way up, as a FORMAT QImage."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"“{path.name}” couldn't be found.")
    too_big = ValueError(f"“{path.name}” is too big to bring in. Make it smaller than "
                         f"{MAX_SIDE} pixels a side first.")
    img = _qt_read(QImageReader(str(path)), too_big)
    if img.isNull():
        img = _pil_read(path, too_big)
    if img.isNull() and path.suffix.lower() in (".psd", ".psb"):
        got = import_psd_layers(path)
        if got:
            flat = Document(got[0], got[1])
            flat.layers = got[2]
            img = flat.composite()
    if img.isNull():
        img = _cv_read(path)
    if img.isNull():
        raise ValueError(f"“{path.name}” couldn't be opened as a picture. Try saving it as a "
                         "PNG or JPG first.")
    if img.width() > MAX_SIDE or img.height() > MAX_SIDE or img.width() * img.height() > MAX_PIXELS:
        raise too_big
    return img


def import_psd_layers(path: Path) -> Optional[tuple[int, int, list[Layer]]]:
    """The layers of a Photoshop file (.psd/.psb, RGB or greyscale, 8 or 16
    bits): (width, height, layers bottom-up), each layer the size of the
    picture with its pixels where they were. Kept: names, opacity (and fill),
    blend (when Paint studio has it), hidden, clipping masks, layer masks and
    locks; layers in groups are taken out of them (the group's opacity and
    visibility passed on). Text and shapes come as Photoshop last drew them;
    layer effects (shadows, strokes, overlays) and adjustment layers are left
    out. None when the file has no layers or can't be read."""
    try:
        got = _read_psd(Path(path))
    except Exception:
        return None
    return got if got and got[2] else None


# ====================================================================== PSD
_PSD_BLENDS = {b"norm": "normal", b"mul ": "multiply", b"scrn": "screen", b"over": "overlay",
               b"sLit": "soft-light", b"hLit": "hard-light", b"dark": "darken",
               b"lite": "lighten", b"div ": "color-dodge", b"idiv": "color-burn",
               b"lddg": "add", b"diff": "difference", b"smud": "exclusion"}
_SIGS = (b"8BIM", b"8B64")
_PSB_LONG = {b"LMsk", b"Lr16", b"Lr32", b"Layr", b"Mt16", b"Mt32", b"Mtrn", b"Alph", b"FMsk",
             b"lnk2", b"FEid", b"FXid", b"PxSD"}       # PSB: these blocks have 8-byte lengths
_PSD_TAGS = {b"luni", b"lsct", b"lsdk", b"iOpa", b"lspf"}
_PSD_ADJUST = {b"brit", b"levl", b"curv", b"expA", b"vibA", b"hue ", b"hue2", b"blnc", b"blwh",
               b"phfl", b"mixr", b"clrL", b"nvrt", b"post", b"thrs", b"selc", b"grdm"}


class _Bin:
    """Big-endian numbers from a PSD, never past its end."""

    def __init__(self, buf, pos: int, psb: bool):
        self.buf, self.pos, self.psb, self.end = buf, pos, psb, len(buf)

    def read(self, n: int) -> bytes:
        if n < 0 or self.pos + n > self.end:
            raise ValueError("past the end of the file")
        b = self.buf[self.pos:self.pos + n]
        self.pos += n
        return b

    def skip(self, n: int) -> None:
        if n < 0 or self.pos + n > self.end:
            raise ValueError("past the end of the file")
        self.pos += n

    def num(self, fmt: str) -> int:
        return struct.unpack(fmt, self.read(struct.calcsize(fmt)))[0]

    def length(self) -> int:
        return self.num(">Q" if self.psb else ">I")


def _sig_at(buf, pos: int, end: int) -> Optional[int]:
    """Where the next tagged block starts (blocks are padded to 2 or 4 bytes)."""
    for p in (pos, (pos + 1) & ~1, (pos + 3) & ~3):
        if p + 12 <= end and buf[p:p + 4] in _SIGS:
            return p
    return None


def _read_psd(path: Path) -> Optional[tuple[int, int, list[Layer]]]:
    with open(path, "rb") as f:
        head = f.read(26)
        if len(head) < 26 or head[:4] != b"8BPS":
            return None
        version = struct.unpack(">H", head[4:6])[0]
        height, width, depth, mode = struct.unpack(">IIHH", head[14:26])
        if version not in (1, 2) or mode not in (1, 3) or depth not in (8, 16):
            return None                    # CMYK, Lab, 32-bit…: flattened by Pillow instead
        if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE) or width * height > MAX_PIXELS:
            return None
        if os.fstat(f.fileno()).st_size < 40:
            return None
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
            psb = version == 2
            r = _Bin(m, 26, psb)
            r.skip(r.num(">I"))           # colour mode data
            r.skip(r.num(">I"))           # image resources
            size = r.length()
            if not size:
                return None               # a flat file
            end = min(r.pos + size, len(m))
            info = r.length()
            start = r.pos
            found = None
            if info:
                found = _psd_records(m, start, psb), depth
            else:                         # 16-bit files keep their layers in a block further on
                r.skip(r.num(">I"))       # the global layer mask
                pos = r.pos
                while True:
                    p = _sig_at(m, pos, end)
                    if p is None:
                        break
                    key = m[p + 4:p + 8]
                    long = psb and key in _PSB_LONG
                    n = struct.unpack(">Q" if long else ">I", m[p + 8:p + (16 if long else 12)])[0]
                    data = p + (16 if long else 12)
                    if key in (b"Lr16", b"Layr"):
                        found = _psd_records(m, data, psb), (16 if key == b"Lr16" else depth)
                        break
                    pos = data + n
            if not found:
                return None
            (records, data_pos), bits = found
            layers = _psd_layers(m, records, data_pos, width, height, bits, mode == 1, psb)
            return width, height, layers


def _psd_records(m, pos: int, psb: bool) -> tuple[list[dict], int]:
    """The layer records and where their pixels start."""
    r = _Bin(m, pos, psb)
    count = abs(r.num(">h"))
    recs = []
    for _ in range(count):
        rect = tuple(r.num(">i") for _ in range(4))          # top, left, bottom, right
        n = r.num(">H")
        if n > 56:
            raise ValueError("not a layer")
        chans = [(r.num(">h"), r.length()) for _ in range(n)]
        if r.read(4) not in _SIGS:
            raise ValueError("not a layer")
        blend = r.read(4)
        opacity, clipping, flags = r.read(3)
        r.skip(1)
        extra = r.num(">I")
        end = r.pos + extra
        mask = r.read(r.num(">I"))
        r.skip(r.num(">I"))                                  # blending ranges
        raw_name = r.read(r.read(1)[0])
        pos = r.pos + (-(1 + len(raw_name)) % 4)            # the name is padded to 4 bytes
        tags: dict = {}
        while True:
            p = _sig_at(m, pos, end)
            if p is None:
                break
            key = m[p + 4:p + 8]
            long = psb and key in _PSB_LONG
            ln = struct.unpack(">Q" if long else ">I", m[p + 8:p + (16 if long else 12)])[0]
            data = p + (16 if long else 12)
            if key in _PSD_TAGS:
                tags[key] = m[data:min(data + ln, end)]
            elif key in _PSD_ADJUST:
                tags[b"adjust"] = b"1"
            pos = data + ln
        if end > r.end:
            raise ValueError("past the end of the file")
        r.pos = end
        name = raw_name.decode("cp1252", "replace")
        uni = tags.get(b"luni", b"")
        if len(uni) >= 4:
            k = struct.unpack(">I", uni[:4])[0]
            name = uni[4:4 + 2 * k].decode("utf-16-be", "replace").rstrip("\x00") or name
        sect = tags.get(b"lsct") or tags.get(b"lsdk") or b""
        prot = tags.get(b"lspf", b"")
        recs.append({
            "rect": rect, "chans": chans, "blend": blend, "opacity": opacity,
            "clip": clipping == 1, "hidden": bool(flags & 2), "mask": mask, "name": name,
            "section": struct.unpack(">I", sect[:4])[0] if len(sect) >= 4 else 0,
            "fill": tags[b"iOpa"][0] if tags.get(b"iOpa") else 255,
            "prot": struct.unpack(">I", prot[:4])[0] if len(prot) >= 4 else 0,
            "adjust": b"adjust" in tags,
        })
    return recs, r.pos


def _psd_layers(m, recs: list[dict], pos: int, width: int, height: int, bits: int,
                grey: bool, psb: bool) -> list[Layer]:
    out: list[Layer] = []
    groups: list[list[int]] = [[]]       # the layers in each group still open
    for rec in recs:                     # bottom-up
        chans = {}
        for cid, ln in rec["chans"]:     # each channel's pixels follow the one before
            chans[cid] = (pos, ln)
            pos += ln
        if rec["section"] == 3:          # the bottom of a group
            groups.append([])
            continue
        if rec["section"] in (1, 2):     # the group itself, above its layers
            members = groups.pop() if len(groups) > 1 else []
            for i in members:
                out[i].opacity = round(out[i].opacity * rec["opacity"] / 255, 4)
                out[i].visible = out[i].visible and not rec["hidden"]
            groups[-1].extend(members)
            continue
        if rec["adjust"]:                # an adjustment layer (levels, curves…): no pixels
            continue
        try:
            img = _psd_pixels(m, rec, chans, width, height, bits, grey, psb)
        except (ValueError, struct.error, zlib.error, OSError):
            img = blank(width, height)
        if img.isNull():
            raise MemoryError("not enough memory for the layers")
        prot = rec["prot"]
        out.append(Layer(rec["name"] or f"Layer {len(out) + 1}", img,
                         opacity=round(rec["opacity"] / 255 * rec["fill"] / 255, 4),
                         blend=_PSD_BLENDS.get(rec["blend"], "normal"),
                         visible=not rec["hidden"],
                         locked=bool(prot & 0x80000000 or prot & 2),
                         alpha_lock=bool(prot & 1),
                         clip=rec["clip"] and bool(out)))
        groups[-1].append(len(out) - 1)
    return out


def _psd_pixels(m, rec: dict, chans: dict, width: int, height: int, bits: int,
                grey: bool, psb: bool) -> QImage:
    img = blank(width, height)
    top, left, bottom, right = rec["rect"]
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0 or w * h > MAX_PIXELS:
        return img

    def get(cid, cw=w, ch=h):
        return _psd_channel(m, *chans[cid], cw, ch, bits, psb) if cid in chans else None

    colour = [get(0)] * 3 if grey else [get(0), get(1), get(2)]
    alpha = get(-1)
    if alpha is None and all(c is None for c in colour):
        return img
    if alpha is None:
        alpha = np.full((h, w), 255, np.uint8)
    alpha = _psd_masks(rec, chans, alpha, get)
    zero = np.zeros((h, w), np.uint8)
    rgba = np.dstack([c if c is not None else zero for c in colour] + [alpha])
    _place(_rgba_image(rgba), left, top, width, height, into=img)
    return img


def _psd_masks(rec: dict, chans: dict, alpha: np.ndarray, get: Callable) -> np.ndarray:
    """The layer's alpha with its layer masks (not switched off) applied."""
    data = rec["mask"]
    if len(data) < 18:
        return alpha
    masks = [(-2, struct.unpack(">4i", data[:16]), data[16], data[17])]
    off = 18
    if data[17] & 16 and len(data) > 18:                   # mask parameters come first
        pf = data[18]
        off = 19 + (pf & 1) + 8 * bool(pf & 2) + bool(pf & 4) + 8 * bool(pf & 8)
    if len(data) >= off + 18:                              # the "real" user mask (-3)
        masks.append((-3, struct.unpack(">4i", data[off + 2:off + 18]), data[off + 1], data[off]))
    top, left, bottom, right = rec["rect"]
    for cid, (mt, ml, mb, mr), default, flags in masks:
        if cid not in chans or flags & 2:                  # none, or switched off
            continue
        full = np.full(alpha.shape, 255 if default >= 128 else 0, np.uint8)
        t, l, b, r = max(top, mt), max(left, ml), min(bottom, mb), min(right, mr)
        if b > t and r > l:
            mask = get(cid, mr - ml, mb - mt)
            if mask is None:
                continue
            full[t - top:b - top, l - left:r - left] = mask[t - mt:b - mt, l - ml:r - ml]
        alpha = ((alpha.astype(np.uint16) * full + 127) // 255).astype(np.uint8)
    return alpha


def _psd_channel(m, pos: int, length: int, w: int, h: int, bits: int,
                 psb: bool) -> Optional[np.ndarray]:
    """One channel's pixels as 8-bit rows (None when they can't be read)."""
    if length < 2 or w <= 0 or h <= 0 or pos + 2 > len(m):
        return None
    comp = struct.unpack(">H", m[pos:pos + 2])[0]
    size = 2 if bits == 16 else 1
    row = w * size
    need = row * h
    start, end = pos + 2, min(pos + length, len(m))
    if comp == 0:                                          # raw
        raw = m[start:start + need]
    elif comp == 1:                                        # PackBits, after each row's length
        raw = _unpack_bits(m[start + (4 if psb else 2) * h:end], row, h)
    elif comp in (2, 3):                                   # zip (3: with prediction)
        raw = zlib.decompressobj().decompress(m[start:end], need)
    else:
        return None
    if raw is None or len(raw) < need:
        return None
    a = np.frombuffer(raw, np.uint8 if size == 1 else ">u2", count=w * h).reshape(h, w)
    if comp == 3:
        a = np.cumsum(a.astype(np.uint8 if size == 1 else np.uint16), axis=1,
                      dtype=np.uint8 if size == 1 else np.uint16)
    if size == 2:
        a = ((a.astype(np.uint32) * 255 + 32767) // 65535).astype(np.uint8)
    return a


def _unpack_bits(data: bytes, row: int, h: int) -> Optional[bytes]:
    from PIL import Image
    try:
        return Image.frombytes("L", (row, h), data, "packbits", "L").tobytes()
    except Exception:
        return None


# ====================================================================== pictures
def _png(img: QImage) -> bytes:
    """A PNG of ``img`` with straight (not premultiplied) alpha – no alpha at
    all when every pixel is solid."""
    if img.format() != FORMAT:
        img = img.convertToFormat(FORMAT)
    out = img.convertToFormat(QImage.Format_RGB32 if _opaque(img) else QImage.Format_ARGB32)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    ok = not out.isNull() and out.save(buf, "PNG")
    buf.close()
    if not ok:
        raise OSError("there isn't enough memory to make the picture")
    return data.data()


def _opaque(img: QImage) -> bool:
    if img.isNull():
        return False
    w, h = img.width(), img.height()
    rows = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h)
    alpha = rows.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)[..., _ALPHA_BYTE]
    return bool(alpha.min() == 255)


def _fit(img: QImage, size: int) -> QImage:
    if img.width() <= size and img.height() <= size:
        return img
    return img.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def _place(pic: QImage, x: int, y: int, w: int, h: int, into: Optional[QImage] = None) -> QImage:
    """``pic`` at (x, y) on a see-through picture w × h (or into ``into``)."""
    img = into if into is not None else blank(w, h)
    if img.isNull():
        return img
    p = QPainter(img)
    p.setCompositionMode(QPainter.CompositionMode_Source)
    p.drawImage(x, y, pic)
    p.end()
    return img


def _rgba_image(rgba: np.ndarray) -> QImage:
    """(h, w, 4) straight RGBA bytes → a FORMAT QImage that owns its pixels."""
    rgba = np.ascontiguousarray(rgba, dtype=np.uint8)
    h, w = rgba.shape[:2]
    img = QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888)
    return img.convertToFormat(FORMAT)          # a new picture: doesn't keep ``rgba``


def _decode(data: bytes) -> QImage:
    """A picture (PNG…) from bytes as FORMAT; a null QImage when unreadable."""
    size = _png_size(data)
    if size and size[0] * size[1] > MAX_PIXELS:
        return QImage()
    ba = QByteArray(data)
    buf = QBuffer(ba)
    buf.open(QIODevice.ReadOnly)
    img = _qt_read(QImageReader(buf), None)
    buf.close()
    if img.isNull():                             # Qt won't read pictures over 256 MB
        img = _cv_decode(np.frombuffer(data, np.uint8))
    return img


def _qt_read(reader: QImageReader, too_big: Optional[Exception]) -> QImage:
    reader.setAutoTransform(True)
    s = reader.size()
    if s.isValid():
        if too_big is not None and (s.width() > MAX_SIDE or s.height() > MAX_SIDE
                                    or s.width() * s.height() > MAX_PIXELS):
            raise too_big
        limit = QImageReader.allocationLimit()
        if limit and s.width() * s.height() * 4 > limit * 1024 * 1024:
            return QImage()                      # over Qt's limit: another reader takes it
    img = reader.read()
    if img.isNull():
        return img
    img = img.convertToFormat(FORMAT)
    try:                                         # a photo in another colour space (P3…)
        cs = img.colorSpace()
        if cs.isValid() and cs != QColorSpace(QColorSpace.SRgb):
            img.convertToColorSpace(QColorSpace(QColorSpace.SRgb))
    except Exception:
        pass
    return img


def _pil_read(path: Path, too_big: Exception) -> QImage:
    from PIL import Image, ImageOps
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with Image.open(path) as im:
                if im.width > MAX_SIDE or im.height > MAX_SIDE or im.width * im.height > MAX_PIXELS:
                    raise too_big
                im = ImageOps.exif_transpose(im) or im
                if im.mode.startswith("I;16"):
                    im = Image.fromarray((np.asarray(im, dtype=np.uint16) >> 8).astype(np.uint8), "L")
                elif im.mode in ("I", "F"):
                    arr = np.asarray(im, dtype=np.float64)
                    top = 65535.0 if arr.max(initial=0) > 255 else 255.0
                    im = Image.fromarray(np.clip(arr / top * 255 + 0.5, 0, 255).astype(np.uint8), "L")
                rgba = np.asarray(im.convert("RGBA"))
        return _rgba_image(rgba)
    except ValueError as e:
        if e is too_big:
            raise
        return QImage()
    except Exception:
        return QImage()


def _cv_read(path: Path) -> QImage:
    try:
        return _cv_decode(np.fromfile(str(path), np.uint8))   # (cv2.imread can't take every path)
    except Exception:
        return QImage()


def _cv_decode(data: np.ndarray) -> QImage:
    try:
        import cv2
        arr = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        if arr is None:
            return QImage()
        if arr.dtype == np.uint16:
            arr = (arr >> 8).astype(np.uint8)
        elif arr.dtype != np.uint8:
            return QImage()
        if arr.ndim == 2:
            arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2RGBA)
        elif arr.shape[2] == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGBA)
        elif arr.shape[2] == 4:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2RGBA)
        else:
            return QImage()
        return _rgba_image(arr)
    except Exception:
        return QImage()


def _png_size(data: bytes) -> Optional[tuple[int, int]]:
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return (w, h) if w and h else None
    return None


# ====================================================================== files
def _put(z: zipfile.ZipFile, name: str, data: bytes, stamp: tuple,
         compress: int = zipfile.ZIP_STORED) -> None:
    info = zipfile.ZipInfo(name, date_time=stamp)
    info.compress_type = compress          # PNGs are squeezed already: stored
    info.external_attr = 0o644 << 16
    z.writestr(info, data)


def _member(z: zipfile.ZipFile, name: str, limit: int = MAX_MEMBER) -> bytes:
    info = z.getinfo(name)
    if info.file_size > limit:
        raise ValueError(f"{name} is too big")
    return z.read(info)


def _write_atomic(path: Path, write: Callable) -> None:
    """``write(file)`` into a new file next to ``path``, which then takes
    ``path``'s place: a crash or a full disk never leaves half a file."""
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        try:
            with open(tmp, "xb") as f:
                write(f)
                f.flush()
                os.fsync(f.fileno())
            _replace(tmp, path)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
    except OSError as e:
        raise _save_error(path, e) from e


def _replace(tmp: Path, path: Path, attempts: int = 25) -> None:
    """``os.replace``, waiting a moment while Windows says the file is in use
    (a virus scanner or a cloud drive looking at it)."""
    for i in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(min(0.25, 0.02 * (i + 1)))


def _save_error(path: Path, e: OSError) -> OSError:
    if isinstance(e, PermissionError):
        why = "that folder can't be written to, or the file is open in another program"
    elif getattr(e, "errno", None) == errno.ENOSPC:
        why = "the disk is full"
    else:
        why = _why(e)
    return OSError(f"Couldn't save “{path.name}”: {why}.")


def _why(e: OSError) -> str:
    return (getattr(e, "strerror", None) or str(e) or "something went wrong").rstrip(".")


# ====================================================================== small things
def _tag(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def _int(v: Optional[str]) -> int:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    return int(round(f)) if math.isfinite(f) and abs(f) < 1e7 else 0


def _opacity(v: Optional[str]) -> float:
    try:
        f = float(v) if v is not None else 1.0
    except ValueError:
        return 1.0
    return max(0.0, min(1.0, f)) if math.isfinite(f) else 1.0


def _num(v: float) -> str:
    v = max(0.0, min(1.0, float(v))) if math.isfinite(float(v)) else 1.0
    return f"{v:.4f}".rstrip("0").rstrip(".") or "0"


def _true(v: Optional[str]) -> bool:
    return v is not None and v.strip().lower() in ("true", "1", "yes")


def _xml_bool(v: bool) -> str:
    return "true" if v else "false"
