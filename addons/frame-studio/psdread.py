"""Photoshop files (.psd, .psb) for frame templates: their layers and groups,
and pictures put together from them.

Read: 8-bit RGB, greyscale or CMYK files; pixel, text and shape layers (as
the pixels Photoshop saves with them), groups, layer masks, opacity, clipping
masks and the usual blend modes (normal, multiply, screen, overlay, soft and
hard light, linear dodge and burn, darken, lighten, difference, colour dodge
and burn). Not drawn: layer effects (shadows, strokes, glows), adjustment
layers and smart filters – Photoshop's own merged picture ("All layers")
has those, for the colour the file was saved showing.

Big files take a while: ``read`` reports its progress and can be stopped,
and shrinks layers as it goes (``max_w``) so a huge file doesn't fill the
memory."""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, Optional

import numpy as np
from PIL import Image


class PsdError(ValueError):
    pass


class Stopped(Exception):
    """Reading was stopped (Stop pressed)."""


# additional layer information keys
_TEXT = (b"TySh", b"tySh")
_ADJUST = {b"levl", b"curv", b"brit", b"hue ", b"hue2", b"blnc", b"vibA", b"phfl", b"mixr",
           b"clrL", b"nvrt", b"post", b"thrs", b"grdm", b"selc", b"expA", b"blwh"}
_BIG_KEYS = {b"LMsk", b"Lr16", b"Lr32", b"Layr", b"Mt16", b"Mt32", b"Mtrn", b"Alph", b"FMsk",
             b"lnk2", b"FEid", b"FXid", b"PxSD"}


@dataclass
class Layer:
    name: str
    box: tuple                     # left, top, right, bottom on the canvas
    hidden: bool
    image: Optional[Image.Image]   # RGBA, the layer's own size (None: empty / a group)
    opacity: float = 1.0           # 0..1 (opacity × fill)
    blend: str = "norm"            # Photoshop's blend key
    clipped: bool = False          # clipped to the layer under it
    kind: str = "pixel"            # pixel | text | adjust | group
    mask: Optional[tuple] = None   # (picture "L", (left, top), outside value 0/255)
    children: list = field(default_factory=list)    # a group's layers, bottom first
    key: int = -1                  # its place in the file (the same in a shrunk copy)

    @property
    def is_group(self) -> bool:
        return self.kind == "group"


@dataclass
class Psd:
    size: tuple                    # (width, height) – after shrinking
    full_size: tuple               # the file's own size
    layers: list                   # top level, bottom first (groups hold theirs)
    merged: Optional[Image.Image] = None

    def walk(self, nodes: Optional[list] = None):
        """Every layer and group, bottom first, groups before their layers."""
        for n in (self.layers if nodes is None else nodes):
            yield n
            if n.is_group:
                yield from self.walk(n.children)

    def scaled(self, width: int) -> "Psd":
        """The same layers shrunk to ``width`` (for quick small pictures)."""
        if width >= self.size[0]:
            return self
        s = width / self.size[0]
        return Psd((width, max(1, round(self.size[1] * s))), self.full_size,
                   [_scale_layer(n, s) for n in self.layers],
                   self.merged.resize((width, max(1, round(self.merged.height * s))),
                                      Image.BILINEAR) if self.merged is not None else None)


def _scale_layer(n: Layer, s: float) -> Layer:
    l, t, r, b = n.box
    img = n.image
    if img is not None:
        img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))),
                         Image.BILINEAR)
    mask = None
    if n.mask is not None:
        m, (mx, my), out = n.mask
        mask = (m.resize((max(1, round(m.width * s)), max(1, round(m.height * s))),
                         Image.BILINEAR), (round(mx * s), round(my * s)), out)
    return Layer(n.name, (round(l * s), round(t * s), round(r * s), round(b * s)), n.hidden,
                 img, n.opacity, n.blend, n.clipped, n.kind, mask,
                 [_scale_layer(c, s) for c in n.children], n.key)


def _u(fp: BinaryIO, n: int) -> int:
    b = fp.read(n)
    if len(b) != n:
        raise PsdError("The file ends too early.")
    return int.from_bytes(b, "big")


def _s(fp: BinaryIO, n: int) -> int:
    b = fp.read(n)
    if len(b) != n:
        raise PsdError("The file ends too early.")
    return int.from_bytes(b, "big", signed=True)


def _decode(data: bytes, comp: int, w: int, h: int, big: bool) -> bytes:
    """One channel's pixels (w × h bytes)."""
    if comp == 0:
        return data[:w * h]
    if comp == 1:                       # PackBits, each row; a table of row sizes first
        table = h * (4 if big else 2)
        im = Image.frombytes("L", (w, h), data[table:], "packbits", "L")
        return im.tobytes()
    if comp in (2, 3):
        raw = zlib.decompress(data)
        if comp == 3:                   # ZIP with prediction: each row is differences
            a = np.frombuffer(raw[:w * h], dtype=np.uint8).reshape(h, w)
            return np.cumsum(a, axis=1, dtype=np.uint8).tobytes()
        return raw[:w * h]
    raise PsdError(f"Unknown compression {comp}.")


def _merged(fp: BinaryIO, size: tuple, channels: int, mode: int, big: bool) -> Optional[Image.Image]:
    """The merged picture Photoshop saves at the end of the file."""
    w, h = size
    try:
        comp = _u(fp, 2)
        if comp == 1:
            counts = [_u(fp, 4 if big else 2) for _ in range(channels * h)]
            planes = []
            for c in range(channels):
                data = fp.read(sum(counts[c * h:(c + 1) * h]))
                planes.append(Image.frombytes("L", (w, h), data, "packbits", "L"))
        elif comp == 0:
            planes = [Image.frombytes("L", (w, h), fp.read(w * h)) for _ in range(channels)]
        else:
            return None
    except Exception:  # noqa: BLE001 - no merged picture
        return None
    n = {1: 1, 3: 3, 4: 4}[mode]
    return _to_rgba(mode, planes, planes[n] if len(planes) > n else None)


def _to_rgba(mode: int, planes: list, alpha: Optional[Image.Image]) -> Image.Image:
    size = planes[0].size
    if mode == 4 and len(planes) >= 4:      # CMYK: saved as 255 − ink
        c, m, y, k = (np.asarray(p, dtype=np.uint16) for p in planes[:4])
        r, g, b = ((ch * k // 255).astype(np.uint8) for ch in (c, m, y))
        rgb = [Image.fromarray(r), Image.fromarray(g), Image.fromarray(b)]
    elif mode == 3 and len(planes) >= 3:
        rgb = planes[:3]
    else:
        rgb = [planes[0]] * 3
    return Image.merge("RGBA", (*rgb, alpha if alpha is not None else Image.new("L", size, 255)))


def read(path: Path, max_w: int = 0, progress: Optional[Callable] = None,
         cancel=None, merged: bool = True) -> Psd:
    """A Photoshop file's layers. ``max_w``: shrink everything to at most
    this wide. ``progress(done, total, text)``; ``cancel.cancelled`` stops it
    (raises ``Stopped``)."""
    def stop():
        if cancel is not None and getattr(cancel, "cancelled", False):
            raise Stopped()

    with open(path, "rb") as fp:
        if fp.read(4) != b"8BPS":
            raise PsdError("Not a Photoshop file.")
        version = _u(fp, 2)
        if version not in (1, 2):
            raise PsdError("Unknown Photoshop file version.")
        big = version == 2
        fp.read(6)
        channels = _u(fp, 2)
        height, width = _u(fp, 4), _u(fp, 4)
        depth, mode = _u(fp, 2), _u(fp, 2)
        if depth != 8:
            raise PsdError(f"This Photoshop file is {depth}-bit; only 8-bit ones can be read. "
                           "Open it in Photoshop (or Photopea) and choose Image → Mode → "
                           "8 Bits/Channel, or save each colour as a PNG.")
        if mode not in (1, 3, 4):
            raise PsdError("Only RGB, greyscale or CMYK Photoshop files can be read.")
        s = min(1.0, max_w / width) if max_w else 1.0
        out_size = (max(1, round(width * s)), max(1, round(height * s)))
        fp.seek(_u(fp, 4), 1)                      # colour mode data
        fp.seek(_u(fp, 4), 1)                      # image resources
        lm_len = _u(fp, 8 if big else 4)
        lm_end = fp.tell() + lm_len
        records = []
        if lm_len:
            li_len = _u(fp, 8 if big else 4)
            if li_len:
                count = abs(_s(fp, 2))
                for _ in range(count):
                    records.append(_record(fp, big))
                for k, rec in enumerate(records):
                    stop()
                    if progress:
                        progress(k, len(records), f"Reading layer {k + 1} of {len(records)}: "
                                                  f"{rec['name']}")
                    _channels(fp, rec, mode, big, s)
        layers = _tree(records)
        merged_img = None
        if merged:
            stop()
            fp.seek(lm_end)
            merged_img = _merged(fp, (width, height), channels, mode, big)
            if merged_img is not None and s < 1:
                merged_img = merged_img.resize(out_size, Image.BILINEAR)
        if progress:
            progress(len(records), max(1, len(records)), "Read")
        return Psd(out_size, (width, height), layers, merged_img)


def _record(fp: BinaryIO, big: bool) -> dict:
    top, left, bottom, right = (_s(fp, 4) for _ in range(4))
    nch = _u(fp, 2)
    chans = [(_s(fp, 2), _u(fp, 8 if big else 4)) for _ in range(nch)]
    if fp.read(4) not in (b"8BIM", b"8B64"):
        raise PsdError("Damaged layer record.")
    blend = fp.read(4).decode("latin-1")
    opacity = _u(fp, 1) / 255
    clipping = _u(fp, 1)
    flags = _u(fp, 1)
    fp.read(1)
    extra = _u(fp, 4)
    end = fp.tell() + extra
    mask = None
    mlen = _u(fp, 4)
    if mlen >= 18:
        mt, ml, mb, mr = (_s(fp, 4) for _ in range(4))
        default = _u(fp, 1)
        mflags = _u(fp, 1)
        fp.seek(mlen - 18, 1)
        if not mflags & 0x02 and mr > ml and mb > mt:          # not switched off
            mask = ((ml, mt, mr, mb), 255 if default >= 128 else 0)
        elif not mflags & 0x02:
            mask = ((0, 0, 0, 0), 255 if default >= 128 else 0)
    else:
        fp.seek(mlen, 1)
    fp.seek(_u(fp, 4), 1)                   # blending ranges
    n = _u(fp, 1)
    name = fp.read(n).decode("mac_roman", "replace")
    fp.seek((4 - (n + 1) % 4) % 4, 1)       # padded to 4 bytes
    section, kind, fill = 0, "pixel", 1.0
    while fp.tell() + 12 <= end:            # additional layer information
        sig = fp.read(4)
        if sig not in (b"8BIM", b"8B64"):
            break
        key = fp.read(4)
        ln = _u(fp, 8 if big and key in _BIG_KEYS else 4)
        data = fp.read(ln)
        if key == b"luni" and len(data) >= 4:
            k = int.from_bytes(data[:4], "big")
            try:
                name = data[4:4 + 2 * k].decode("utf-16-be").rstrip("\x00") or name
            except UnicodeDecodeError:
                pass
        elif key in (b"lsct", b"lsdk") and len(data) >= 4:
            section = int.from_bytes(data[:4], "big")
            if len(data) >= 12 and data[4:8] == b"8BIM":
                blend = data[8:12].decode("latin-1")
        elif key == b"iOpa" and data:
            fill = data[0] / 255
        elif key in _TEXT:
            kind = "text"
        elif key in _ADJUST:
            kind = "adjust"
        if ln % 2:                          # some writers pad to an even length
            here = fp.tell()
            if fp.read(4) not in (b"8BIM", b"8B64"):
                fp.seek(here + 1)
            else:
                fp.seek(here)
    fp.seek(end)
    return {"name": name, "box": (left, top, right, bottom), "hidden": bool(flags & 0x02),
            "chans": chans, "section": section, "blend": blend, "opacity": opacity * fill,
            "clipped": clipping == 1, "kind": kind, "mask": mask, "image": None,
            "mask_img": None}


def _channels(fp: BinaryIO, rec: dict, mode: int, big: bool, s: float) -> None:
    """Read (and shrink) a layer's pixels and its mask."""
    l, t, r, b = rec["box"]
    w, h = r - l, b - t
    planes, mask_raw = {}, None
    for cid, ln in rec["chans"]:
        start = fp.tell()
        if ln < 2:
            fp.seek(start + ln)
            continue
        comp = _u(fp, 2)
        data = fp.read(ln - 2)
        if cid == -2 and rec["mask"] is not None:
            (ml, mt, mr, mb), _out = rec["mask"]
            if mr > ml and mb > mt:
                try:
                    mask_raw = _decode(data, comp, mr - ml, mb - mt, big)
                except Exception:  # noqa: BLE001 - a mask that can't be read
                    mask_raw = None
            continue
        if cid < -1 or rec["section"] in (1, 2, 3) or w <= 0 or h <= 0:
            continue
        try:
            planes[cid] = _decode(data, comp, w, h, big)
        except Exception:  # noqa: BLE001 - a channel that can't be read
            pass
    if planes and w > 0 and h > 0:
        def plane(cid, fill=0):
            raw = planes.get(cid)
            if raw is None or len(raw) < w * h:
                return Image.new("L", (w, h), fill)
            return Image.frombytes("L", (w, h), raw[:w * h])
        ids = {1: [0], 3: [0, 1, 2], 4: [0, 1, 2, 3]}[mode]
        img = _to_rgba(mode, [plane(c, 255 if mode == 4 else 0) for c in ids], plane(-1, 255))
        if img.getchannel("A").getbbox() is not None:
            if s < 1:
                img = img.resize((max(1, round(w * s)), max(1, round(h * s))), Image.BILINEAR)
            rec["image"] = img
    if rec["mask"] is not None:
        (ml, mt, mr, mb), out = rec["mask"]
        if mask_raw is not None and mr > ml and mb > mt:
            m = Image.frombytes("L", (mr - ml, mb - mt), mask_raw[:(mr - ml) * (mb - mt)])
            if s < 1:
                m = m.resize((max(1, round(m.width * s)), max(1, round(m.height * s))),
                             Image.BILINEAR)
            rec["mask_img"] = (m, (round(ml * s), round(mt * s)), out)
        else:
            rec["mask_img"] = (Image.new("L", (1, 1), out), (0, 0), out)
    rec["box"] = (round(l * s), round(t * s), round(r * s), round(b * s))


def _tree(records: list) -> list:
    """Records (bottom first, a group's end marker before its layers and its
    header after them) as a tree."""
    stack: list = [[]]
    for key, rec in enumerate(records):
        if rec["section"] == 3:                    # the bottom of a group
            stack.append([])
            continue
        node = Layer(rec["name"], rec["box"], rec["hidden"], rec["image"], rec["opacity"],
                     rec["blend"], rec["clipped"], rec["kind"], rec["mask_img"], key=key)
        if rec["section"] in (1, 2):               # a group's header: its layers are done
            node.kind, node.image = "group", None
            node.children = stack.pop() if len(stack) > 1 else []
            if node.blend == "pass":
                node.blend = "norm"
        stack[-1].append(node)
    while len(stack) > 1:                          # a damaged file: keep what's there
        orphans = stack.pop()
        stack[-1].extend(orphans)
    return stack[0]


# ------------------------------------------------------------------ putting layers together
def _blend(key: str, cb: np.ndarray, cs: np.ndarray) -> np.ndarray:
    if key == "mul ":
        return cb * cs
    if key == "scrn":
        return cb + cs - cb * cs
    if key in ("over", "hLit"):
        a, b = (cs, cb) if key == "over" else (cb, cs)     # overlay = hard light swapped
        return np.where(b <= 0.5, 2 * a * b, 1 - 2 * (1 - a) * (1 - b))
    if key == "sLit":
        d = np.where(cb <= 0.25, ((16 * cb - 12) * cb + 4) * cb, np.sqrt(cb))
        return np.where(cs <= 0.5, cb - (1 - 2 * cs) * cb * (1 - cb), cb + (2 * cs - 1) * (d - cb))
    if key == "lddg":
        return np.minimum(1, cb + cs)
    if key == "lbrn":
        return np.maximum(0, cb + cs - 1)
    if key == "dark":
        return np.minimum(cb, cs)
    if key == "lite":
        return np.maximum(cb, cs)
    if key == "diff":
        return np.abs(cb - cs)
    if key == "div ":
        return np.where(cs >= 1, 1, np.minimum(1, cb / np.maximum(1e-6, 1 - cs)))
    if key == "idiv":
        return np.where(cs <= 0, 0, 1 - np.minimum(1, (1 - cb) / np.maximum(1e-6, cs)))
    return cs


def _over(canvas: np.ndarray, x: int, y: int, src: np.ndarray, blend: str) -> None:
    h, w = src.shape[:2]
    dst = canvas[y:y + h, x:x + w]
    sa, da = src[..., 3:4], dst[..., 3:4]
    cs, cb = src[..., :3], dst[..., :3]
    if blend != "norm":
        cs = (1 - da) * cs + da * _blend(blend, cb, cs)
    ao = sa + da * (1 - sa)
    co = (sa * cs + da * cb * (1 - sa)) / np.maximum(ao, 1e-6)
    dst[..., :3] = np.where(ao > 0, co, 0)
    dst[..., 3:4] = ao


def _mask_for(node: Layer, x0: int, y0: int, w: int, h: int) -> Optional[np.ndarray]:
    """The layer mask over a part of the canvas (0..1), or None."""
    if node.mask is None:
        return None
    m, (mx, my), out = node.mask
    full = Image.new("L", (w, h), out)
    full.paste(m, (mx - x0, my - y0))
    return np.asarray(full, dtype=np.float32)[..., None] / 255


def composite(psd: Psd, visible: Optional[Callable[[Layer], bool]] = None,
              nodes: Optional[list] = None, cancel=None) -> Image.Image:
    """The layers put together (RGBA). ``visible(layer)`` says which are drawn
    (default: as the file was saved, without adjustment layers)."""
    vis = visible or (lambda n: not n.hidden)
    w, h = psd.size
    canvas = _draw(psd.layers if nodes is None else nodes, (w, h), vis, cancel)
    return Image.fromarray(np.clip(canvas * 255 + 0.5, 0, 255).astype(np.uint8), "RGBA")


def _draw(nodes: list, size: tuple, vis: Callable, cancel) -> np.ndarray:
    w, h = size
    canvas = np.zeros((h, w, 4), dtype=np.float32)
    base: Optional[tuple] = None              # (x, y, coverage) clipped layers use
    for node in nodes:
        if cancel is not None and getattr(cancel, "cancelled", False):
            raise Stopped()
        shown = node.kind in ("pixel", "text", "group") and vis(node)
        if not shown:
            if not node.clipped:
                base = None
            continue
        if node.is_group:
            src = _draw(node.children, size, vis, cancel)
            x0, y0 = 0, 0
        else:
            if node.image is None:
                if not node.clipped:
                    base = None
                continue
            l, t = node.box[0], node.box[1]
            x0, y0 = max(0, l), max(0, t)
            x1, y1 = min(w, l + node.image.width), min(h, t + node.image.height)
            if x1 <= x0 or y1 <= y0:
                if not node.clipped:
                    base = None
                continue
            src = np.asarray(node.image.crop((x0 - l, y0 - t, x1 - l, y1 - t)),
                             dtype=np.float32) / 255
        sh, sw = src.shape[:2]
        alpha = src[..., 3:4] * node.opacity
        m = _mask_for(node, x0, y0, sw, sh)
        if m is not None:
            alpha = alpha * m
        if node.clipped:
            if base is None:
                continue
            alpha = alpha * _under(base, x0, y0, sw, sh)
        else:
            base = (x0, y0, alpha)
        src = np.concatenate([src[..., :3], alpha], axis=2)
        _over(canvas, x0, y0, src, node.blend)
    return canvas


def _under(base: tuple, x0: int, y0: int, w: int, h: int) -> np.ndarray:
    """The clipping layer's coverage over a part of the canvas."""
    bx, by, ba = base
    out = np.zeros((h, w, 1), dtype=np.float32)
    ix0, iy0 = max(x0, bx), max(y0, by)
    ix1, iy1 = min(x0 + w, bx + ba.shape[1]), min(y0 + h, by + ba.shape[0])
    if ix1 > ix0 and iy1 > iy0:
        out[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0] = ba[iy0 - by:iy1 - by, ix0 - bx:ix1 - bx]
    return out


def layer_pictures(path: Path) -> list[tuple[str, Image.Image]]:
    """Each pixel layer on the whole canvas (top layer first), named."""
    psd = read(path, merged=False)
    out = []
    for lay in reversed([n for n in psd.walk() if n.kind == "pixel" and n.image is not None]):
        canvas = Image.new("RGBA", psd.size, (0, 0, 0, 0))
        canvas.paste(lay.image, (lay.box[0], lay.box[1]))
        out.append((lay.name + (" (hidden)" if lay.hidden else ""), canvas))
    return out


def read_layers(path: Path) -> tuple[tuple[int, int], list[Layer]]:
    """((width, height), the pixel layers from the bottom up) – as before 1.1."""
    psd = read(path, merged=False)
    return psd.size, [n for n in psd.walk() if not n.is_group]
