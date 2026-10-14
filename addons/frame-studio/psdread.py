"""Photoshop files (.psd, .psb) for frame templates: their layers and groups,
and pictures put together from them.

Read: 8-bit RGB, greyscale or CMYK files; pixel, text and shape layers (as
the pixels Photoshop saves with them), groups, layer masks, vector masks,
opacity and fill, clipping masks, the usual blend modes (normal, multiply,
screen, overlay, soft and hard light, linear dodge and burn, darken, lighten,
difference, colour dodge and burn) and the usual layer effects: colour
overlay, stroke (a solid colour), drop shadow and outer glow. Not drawn:
bevels, inner shadows and glows, gradient and pattern overlays, adjustment
layers and smart filters – Photoshop's own merged picture ("All layers") has
those, for the colour the file was saved showing.

Text layers also say what they are: their text, font, size, colour (a Colour
Overlay effect wins), alignment and – for paragraph text – their box
(``Layer.text``), so a template's text boxes can be found.

Big files take a while: ``read`` reports its progress and can be stopped,
and shrinks layers as it goes (``max_w``) so a huge file doesn't fill the
memory."""
from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, Optional

import numpy as np
from PIL import Image, ImageDraw


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
    vmask: Optional[dict] = None   # a vector mask (switched on): see _vector_mask
    text: Optional[dict] = None    # a text layer's text, font, size… (see _type_tool)
    shape: bool = False            # a shape layer (its pixels already follow its path)
    fx: Optional[dict] = None      # layer effects that are drawn (see _effects)
    fill: float = 1.0              # fill opacity (the paint, not the effects)

    @property
    def is_group(self) -> bool:
        return self.kind == "group"


@dataclass
class Psd:
    size: tuple                    # (width, height) – after shrinking
    full_size: tuple               # the file's own size
    layers: list                   # top level, bottom first (groups hold theirs)
    merged: Optional[Image.Image] = None
    dpi: float = 72.0              # the file's resolution (pixels per inch)
    angle: float = 120.0           # the global light (drop shadows that use it)

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
                                      Image.BILINEAR) if self.merged is not None else None,
                   self.dpi, self.angle)


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
                 [_scale_layer(c, s) for c in n.children], n.key, n.vmask, n.text, n.shape,
                 n.fx, n.fill)


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
        res_len = _u(fp, 4)                        # image resources: resolution, light
        dpi, angle = _resources(fp.read(res_len))
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
        return Psd(out_size, (width, height), layers, merged_img, dpi, angle)


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
    vmask, text, fx, solid, shape = None, None, None, None, False
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
            text = _safe(_type_tool, data)
        elif key in (b"vmsk", b"vsms"):
            vmask = _safe(_vector_mask, data)
        elif key in (b"lfx2", b"lmfx"):
            fx = _safe(_effects, data) or fx
        elif key == b"SoCo":
            solid = _safe(_solid_colour, data)
            shape = True
        elif key in (b"GdFl", b"PtFl", b"vscg", b"vogk"):
            shape = True
        elif key in _ADJUST:
            kind = "adjust"
        if ln % 2:                          # some writers pad to an even length
            here = fp.tell()
            if fp.read(4) not in (b"8BIM", b"8B64"):
                fp.seek(here + 1)
            else:
                fp.seek(here)
    fp.seek(end)
    if text is not None and fx:
        over = [e for e in fx.get("overlay", []) if e["opacity"] >= 0.5]
        if over:
            text["colour"] = over[0]["colour"]       # a Colour Overlay hides its own colour
        if fx.get("shadow"):
            text["shadow"] = dict(fx["shadow"][0])
    if fx:
        fx["opacity"] = opacity                      # the effects ignore the fill
    return {"name": name, "box": (left, top, right, bottom), "hidden": bool(flags & 0x02),
            "chans": chans, "section": section, "blend": blend, "opacity": opacity * fill,
            "clipped": clipping == 1, "kind": kind, "mask": mask, "image": None,
            "mask_img": None, "vmask": vmask, "text": text, "solid": solid,
            "shape": shape and vmask is not None, "fx": fx, "fill": fill}


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
                     rec["blend"], rec["clipped"], rec["kind"], rec["mask_img"], key=key,
                     vmask=rec.get("vmask"), text=rec.get("text"), shape=rec.get("shape", False),
                     fx=rec.get("fx"), fill=rec.get("fill", 1.0))
        if node.image is None and rec.get("solid") and node.vmask and rec["section"] == 0:
            node.vmask = dict(node.vmask, solid=rec["solid"])
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
    look = (w / max(1, psd.full_size[0]), psd.angle)      # effects: their scale and light
    canvas = _draw(psd.layers if nodes is None else nodes, (w, h), vis, cancel, look)
    return Image.fromarray(np.clip(canvas * 255 + 0.5, 0, 255).astype(np.uint8), "RGBA")


def _draw(nodes: list, size: tuple, vis: Callable, cancel,
          look: tuple = (1.0, 120.0)) -> np.ndarray:
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
            src = _draw(node.children, size, vis, cancel, look)
            x0, y0 = 0, 0
        elif node.image is None and node.vmask and node.vmask.get("solid"):
            col = node.vmask["solid"].lstrip("#")       # a shape layer saved without pixels
            src = np.zeros((h, w, 4), dtype=np.float32)
            src[...] = [int(col[k:k + 2], 16) / 255 for k in (0, 2, 4)] + [1.0]
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
        shape = src[..., 3:4]
        m = _mask_for(node, x0, y0, sw, sh)
        if m is not None:
            shape = shape * m
        if node.vmask and not node.shape:
            shape = shape * _vmask_for(node.vmask, size)[y0:y0 + sh, x0:x0 + sw, None]
        if node.clipped:
            if base is None:
                continue
            shape = shape * _under(base, x0, y0, sw, sh)
        alpha = shape * node.opacity
        if not node.clipped:
            base = (x0, y0, alpha)
        if node.fx:
            src, x0, y0 = _with_effects(node, src[..., :3], shape[..., 0], x0, y0, size, look)
        else:
            src = np.concatenate([src[..., :3], alpha], axis=2)
        _over(canvas, x0, y0, src, node.blend)
    return canvas


# ------------------------------------------------------------------ layer effects
def _cv2():
    try:
        import cv2
        return cv2
    except Exception:  # noqa: BLE001 - OpenCV comes with MSE Studio; Pillow otherwise
        return None


def _blur(a: np.ndarray, radius: float) -> np.ndarray:
    if radius <= 0.3:
        return a
    cv2 = _cv2()
    if cv2 is not None:
        return cv2.GaussianBlur(a, (0, 0), radius / 2)
    from PIL import ImageFilter
    im = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8), "L")
    return np.asarray(im.filter(ImageFilter.GaussianBlur(radius / 2)), dtype=np.float32) / 255


def _distance(inside: np.ndarray) -> np.ndarray:
    """For each pixel not in ``inside``: how far the nearest one in it is."""
    cv2 = _cv2()
    if cv2 is not None:
        return cv2.distanceTransform((~inside).astype(np.uint8), cv2.DIST_L2, 5)
    from PIL import ImageFilter                     # slower: grow one pixel at a time
    out = np.full(inside.shape, 1e6, dtype=np.float32)
    out[inside] = 0
    grown = Image.fromarray(inside.astype(np.uint8) * 255, "L")
    for k in range(1, 64):
        grown = grown.filter(ImageFilter.MaxFilter(3))
        g = np.asarray(grown) > 127
        out[g & (out > k)] = k
        if g.all():
            break
    return out


def _paint(colour: str, a: np.ndarray, opacity: float) -> np.ndarray:
    c = colour.lstrip("#")
    out = np.empty(a.shape + (4,), dtype=np.float32)
    out[..., :3] = [int(c[k:k + 2], 16) / 255 for k in (0, 2, 4)]
    out[..., 3] = np.clip(a * opacity, 0, 1)
    return out


def _with_effects(node: Layer, rgb: np.ndarray, shape: np.ndarray, x0: int, y0: int,
                  size: tuple, look: tuple) -> tuple:
    """A layer with its drop shadows and outer glows under it, colour overlays
    on its paint and strokes around it – grown by what the effects reach."""
    fx, (s, global_angle) = node.fx, look
    reach = 0.0
    for e in fx.get("stroke", []):
        reach = max(reach, e["size"])
    for e in fx.get("shadow", []):
        reach = max(reach, e["distance"] + e["size"])
    for e in fx.get("glow", []):
        reach = max(reach, e["size"])
    pad = int(np.ceil(reach * s)) + 2
    w, h = size
    sh, sw = shape.shape
    nx0, ny0 = max(0, x0 - pad), max(0, y0 - pad)
    nx1, ny1 = min(w, x0 + sw + pad), min(h, y0 + sh + pad)
    H, W = ny1 - ny0, nx1 - nx0
    a = np.zeros((H, W), dtype=np.float32)
    a[y0 - ny0:y0 - ny0 + sh, x0 - nx0:x0 - nx0 + sw] = shape
    paint = np.zeros((H, W, 3), dtype=np.float32)
    paint[y0 - ny0:y0 - ny0 + sh, x0 - nx0:x0 - nx0 + sw] = rgb
    out = np.zeros((H, W, 4), dtype=np.float32)
    fill = node.fill
    for e in fx.get("shadow", []):                  # under the layer
        ang = np.radians(global_angle if e.get("global_angle") else e["angle"])
        dx, dy = -np.cos(ang) * e["distance"] * s, np.sin(ang) * e["distance"] * s
        moved = np.zeros_like(a)
        ix, iy = int(round(dx)), int(round(dy))
        src_y = slice(max(0, -iy), H - max(0, iy))
        src_x = slice(max(0, -ix), W - max(0, ix))
        moved[max(0, iy):H - max(0, -iy), max(0, ix):W - max(0, -ix)] = a[src_y, src_x]
        sa = _blur(moved, e["size"] * s)
        if e.get("spread"):
            sa = np.clip(sa / max(0.05, 1 - e["spread"]), 0, 1)
        if fill < 1 and e.get("knockout", True):
            sa = sa * (1 - a)
        _over(out, 0, 0, _paint(e["colour"], sa, e["opacity"]), e["blend"])
    for e in fx.get("glow", []):
        ga = _blur(a, e["size"] * s)
        ga = np.clip(ga * (1 + 3 * e.get("spread", 0)) * 1.5, 0, 1)
        _over(out, 0, 0, _paint(e["colour"], ga, e["opacity"]), e["blend"])
    for e in fx.get("overlay", []):                 # on the layer's own paint
        c = e["colour"].lstrip("#")
        col = np.array([int(c[k:k + 2], 16) / 255 for k in (0, 2, 4)], dtype=np.float32)
        mixed = _blend(e["blend"], paint, np.broadcast_to(col, paint.shape))
        paint = paint * (1 - e["opacity"]) + mixed * e["opacity"]
    _over(out, 0, 0, np.concatenate([paint, (a * fill)[..., None]], axis=2), "norm")
    for e in fx.get("stroke", []):                  # around it, on top
        inside = a >= 0.5
        size_px = e["size"] * s
        if e["position"] == "inside":
            ring = np.clip(size_px + 0.5 - _distance(~inside), 0, 1) * a
        elif e["position"] == "center":
            ring = np.clip(size_px / 2 + 0.5 - _distance(inside), 0, 1) * (1 - a) + \
                np.clip(size_px / 2 + 0.5 - _distance(~inside), 0, 1) * a
        else:
            ring = np.clip(size_px + 0.5 - _distance(inside), 0, 1) * (1 - a)
        _over(out, 0, 0, _paint(e["colour"], ring, e["opacity"]), e["blend"])
    out[..., 3] *= fx.get("opacity", 1.0)
    return out, nx0, ny0


def _vmask_for(vm: dict, size: tuple) -> np.ndarray:
    """A vector mask over the whole canvas (0..1), drawn once per size."""
    cache = vm.setdefault("_drawn", {})
    if size not in cache:
        cache[size] = np.round(vector_alpha(vm, size) * 255).astype(np.uint8)
    return cache[size].astype(np.float32) / 255


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


# ------------------------------------------------------------------ what layers say
def _safe(fn, data):
    """Additional layer information that can't be read is left out."""
    try:
        return fn(data)
    except Exception:  # noqa: BLE001 - an unusual block: the layer is still drawn
        return None


def _resources(data: bytes) -> tuple[float, float]:
    """(pixels per inch, the global light's angle) from the image resources."""
    dpi, angle = 72.0, 120.0
    i = 0
    while i + 12 <= len(data) and data[i:i + 4] == b"8BIM":
        rid = int.from_bytes(data[i + 4:i + 6], "big")
        n = data[i + 6]
        j = i + 7 + n + ((n + 1) % 2)              # Pascal name, padded to even
        size = int.from_bytes(data[j:j + 4], "big")
        body = data[j + 4:j + 4 + size]
        if rid == 0x03ED and len(body) >= 4:
            v = int.from_bytes(body[:4], "big") / 65536
            dpi = v if v > 0 else 72.0
        elif rid == 0x040D and len(body) >= 4:
            angle = float(int.from_bytes(body[:4], "big", signed=True))
        i = j + 4 + size + (size % 2)
    return dpi, angle


class _Reader:
    def __init__(self, data: bytes):
        self.d, self.i = data, 0

    def take(self, n: int) -> bytes:
        b = self.d[self.i:self.i + n]
        if len(b) != n:
            raise PsdError("short")
        self.i += n
        return b

    def u32(self) -> int:
        return int.from_bytes(self.take(4), "big")

    def i32(self) -> int:
        return int.from_bytes(self.take(4), "big", signed=True)

    def f64(self) -> float:
        return struct.unpack(">d", self.take(8))[0]

    def uni(self) -> str:
        return self.take(2 * self.u32()).decode("utf-16-be", "replace").rstrip("\x00")

    def key(self) -> str:
        n = self.u32()
        return self.take(n or 4).decode("latin-1").strip()


def _descriptor(r: _Reader) -> dict:
    """A Photoshop "action descriptor": {key: value}."""
    r.uni()
    r.key()
    out = {}
    for _ in range(r.u32()):
        k = r.key()
        out[k] = _dvalue(r, r.take(4))
    return out


def _dvalue(r: _Reader, t: bytes):
    if t in (b"Objc", b"GlbO"):
        return _descriptor(r)
    if t == b"VlLs":
        return [_dvalue(r, r.take(4)) for _ in range(r.u32())]
    if t == b"doub":
        return r.f64()
    if t == b"UntF":
        r.take(4)
        return r.f64()
    if t == b"UnFl":
        r.take(4)
        return [r.f64() for _ in range(r.u32())]
    if t == b"TEXT":
        return r.uni()
    if t == b"enum":
        r.key()
        return r.key()
    if t == b"long":
        return r.i32()
    if t == b"comp":
        return int.from_bytes(r.take(8), "big", signed=True)
    if t == b"bool":
        return r.take(1) != b"\x00"
    if t in (b"type", b"GlbC"):
        r.uni()
        return r.key()
    if t in (b"tdta", b"alis", b"Pth "):
        return r.take(r.u32())
    if t == b"obj ":
        for _ in range(r.u32()):
            kind = r.take(4)
            if kind == b"prop":
                r.uni(), r.key(), r.key()
            elif kind == b"Clss":
                r.uni(), r.key()
            elif kind == b"Enmr":
                r.uni(), r.key(), r.key(), r.key()
            elif kind == b"rele":
                r.uni(), r.key(), r.u32()
            elif kind in (b"Idnt", b"indx"):
                r.u32()
            elif kind == b"name":
                r.uni(), r.key(), r.uni()
            else:
                raise PsdError("reference")
        return None
    raise PsdError(f"descriptor type {t!r}")


def _rgb(d) -> Optional[str]:
    """"#rrggbb" from a descriptor colour (RGB, greyscale or CMYK)."""
    if not isinstance(d, dict):
        return None
    if "Rd" in d:
        r, g, b = d.get("Rd", 0), d.get("Grn", 0), d.get("Bl", 0)
    elif "Gry" in d:
        r = g = b = 255 * (1 - d["Gry"] / 100)
    elif "Cyn" in d:
        k = 1 - d.get("Blck", 0) / 100
        r, g, b = (255 * (1 - d.get(c, 0) / 100) * k for c in ("Cyn", "Mgnt", "Ylw"))
    else:
        return None
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in (r, g, b))


def _solid_colour(data: bytes) -> Optional[str]:
    r = _Reader(data)
    r.u32()
    return _rgb(_descriptor(r).get("Clr"))


_FX_BLEND = {"Nrml": "norm", "Mltp": "mul ", "Scrn": "scrn", "Ovrl": "over", "HrdL": "hLit",
             "SftL": "sLit", "Drkn": "dark", "Lghn": "lite", "Dfrn": "diff", "CDdg": "div ",
             "CBrn": "idiv", "linearDodge": "lddg", "linearBurn": "lbrn"}


def _effects(data: bytes) -> Optional[dict]:
    """The layer effects that are switched on and drawn: {"overlay", "stroke",
    "shadow", "glow": [{"colour", "opacity", "blend", "size"…}]}."""
    r = _Reader(data)
    r.u32()
    r.u32()
    d = _descriptor(r)
    if d.get("masterFXSwitch") is False:
        return None
    out: dict = {}
    for key, kind in (("SoFi", "overlay"), ("FrFX", "stroke"), ("DrSh", "shadow"),
                      ("OrGl", "glow")):
        found = d.get(key + "Multi")
        found = found if isinstance(found, list) else [d.get(key)]
        for e in found:
            if not isinstance(e, dict) or not e.get("enab", True) or e.get("present") is False:
                continue                                  # switched off, or left over
            col = _rgb(e.get("Clr"))
            if col is None or (kind == "stroke" and e.get("PntT") not in (None, "SClr")):
                continue                                  # gradients and patterns: not drawn
            item = {"colour": col, "opacity": float(e.get("Opct", 100)) / 100,
                    "blend": _FX_BLEND.get(e.get("Md"), "norm")}
            if kind == "stroke":
                item["size"] = float(e.get("Sz", 3))
                item["position"] = {"InsF": "inside", "CtrF": "center"}.get(e.get("Styl"),
                                                                            "outside")
            elif kind == "shadow":
                item.update(angle=float(e.get("lagl", 120)), global_angle=e.get("uglg", True),
                            distance=float(e.get("Dstn", 5)), size=float(e.get("blur", 5)),
                            spread=float(e.get("Ckmt", 0)) / 100,
                            knockout=e.get("layerConceals", True))
            elif kind == "glow":
                item.update(size=float(e.get("blur", 5)), spread=float(e.get("Ckmt", 0)) / 100)
            out.setdefault(kind, []).append(item)
    return out or None


# vector masks: {"invert", "components": [(operation, [(closed, [(pre, anchor, leave)])])]}
# with each point (x, y) as parts of the canvas
def _vector_mask(data: bytes) -> Optional[dict]:
    r = _Reader(data)
    r.u32()
    flags = r.u32()
    if flags & 4:                                  # switched off
        return None
    comps: list = []
    current = None
    fill_all = False
    while r.i + 26 <= len(r.d):
        sel = int.from_bytes(r.take(2), "big")
        body = r.take(24)
        if sel in (0, 3):                          # a subpath's length record
            count = int.from_bytes(body[0:2], "big")
            op = int.from_bytes(body[2:4], "big", signed=True)
            current = (sel == 0, [], count)
            if op == -1 and comps:                 # part of the shape before it
                comps[-1][1].append(current)
            else:
                comps.append((op, [current]))
        elif sel in (1, 2, 4, 5) and current is not None:
            v = struct.unpack(">6i", body)
            pts = [(v[k + 1] / 2 ** 24, v[k] / 2 ** 24) for k in (0, 2, 4)]
            current[1].append(tuple(pts))
        elif sel == 8:
            fill_all = int.from_bytes(body[0:2], "big") == 1
    if not comps and not fill_all:
        return None
    return {"invert": bool(flags & 1), "components": comps, "fill_all": fill_all}


def _bezier(knots: list, closed: bool, w: int, h: int) -> list:
    """A subpath as points on a w × h canvas."""
    pts = []
    n = len(knots)
    for k in range(n if closed else n - 1):
        a, b = knots[k], knots[(k + 1) % n]
        p0, p1, p2, p3 = a[1], a[2], b[0], b[1]
        length = (abs(p3[0] - p0[0]) * w + abs(p3[1] - p0[1]) * h)
        steps = 1 if (p0, p1) == (p0, p0) and (p2, p3) == (p3, p3) else \
            max(4, min(48, int(length / 6)))
        for s in range(steps):
            t = s / steps
            u = 1 - t
            x = u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0]
            y = u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]
            pts.append((x * w, y * h))
    if not closed and knots:
        pts.append((knots[-1][1][0] * w, knots[-1][1][1] * h))
    return pts


def vector_bounds(vm: Optional[dict]) -> Optional[tuple]:
    """A vector mask's outline: (left, top, right, bottom) as parts of the canvas."""
    if not vm:
        return None
    xs, ys = [], []
    for _op, subs in vm["components"]:
        for _closed, knots, _n in subs:
            for k in knots:
                xs.append(k[1][0])
                ys.append(k[1][1])
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def vector_alpha(vm: dict, size: tuple, ss: int = 3) -> np.ndarray:
    """A vector mask drawn on a canvas (h × w, 0..1), smoothed edges."""
    w, h = size
    W, H = w * ss, h * ss
    mask = np.full((h, w), 1.0 if vm.get("fill_all") and not vm["components"] else 0.0,
                   dtype=np.float32)
    first = True
    for op, subs in vm["components"]:
        plane = np.zeros((h, w), dtype=np.float32)
        for closed, knots, _n in subs:
            if not closed or len(knots) < 2:
                continue
            pts = _bezier(knots, True, W, H)
            if len(pts) < 3:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            x0, y0 = max(0, int(min(xs)) // ss * ss), max(0, int(min(ys)) // ss * ss)
            x1 = min(W, (int(max(xs)) // ss + 2) * ss)
            y1 = min(H, (int(max(ys)) // ss + 2) * ss)
            if x1 <= x0 or y1 <= y0:
                continue
            im = Image.new("L", (x1 - x0, y1 - y0), 0)
            ImageDraw.Draw(im).polygon([(x - x0, y - y0) for x, y in pts], fill=255)
            im = im.resize(((x1 - x0) // ss, (y1 - y0) // ss), Image.BOX)
            part = np.asarray(im, dtype=np.float32) / 255
            sy, sx = y0 // ss, x0 // ss
            region = plane[sy:sy + part.shape[0], sx:sx + part.shape[1]]
            part = part[:region.shape[0], :region.shape[1]]
            region[...] = np.abs(region - part)            # even-odd inside one shape
        if op == 0:                                         # exclude overlapping
            mask = mask + plane - 2 * mask * plane
        elif op == 2:                                       # subtract
            if first:
                mask = 1 - mask
            mask = np.maximum(0, mask - plane)
        elif op == 3:                                       # intersect
            if first:
                mask = 1 - mask
            mask = mask * plane
        else:                                               # combine
            mask = mask + plane - mask * plane
        first = False
    mask = np.clip(mask, 0, 1)
    return 1 - mask if vm.get("invert") else mask


# ------------------------------------------------------------------ text layers
_ED_NUM = re.compile(rb"[-+]?(?:\d+\.?\d*|\.\d+)")


def engine_data(data: bytes):
    """Photoshop's text engine data (a PostScript-like text) as dicts and lists."""
    i, n = 0, len(data)

    def ws():
        nonlocal i
        while i < n and data[i] in b" \t\r\n\x00":
            i += 1

    def name() -> str:
        nonlocal i
        i += 1
        j = i
        while i < n and data[i] not in b" \t\r\n/[]<>()":
            i += 1
        return data[j:i].decode("latin-1")

    def string() -> str:
        nonlocal i
        i += 1
        out = bytearray()
        while i < n:
            c = data[i]
            if c == 0x5C and i + 1 < n:            # \( \) \\
                out.append(data[i + 1])
                i += 2
                continue
            if c == 0x29:
                i += 1
                break
            out.append(c)
            i += 1
        b = bytes(out)
        if b.startswith(b"\xfe\xff"):
            return b[2:].decode("utf-16-be", "replace")
        return b.decode("latin-1")

    def value(depth: int = 0):
        nonlocal i
        if depth > 200:
            raise PsdError("too deep")
        ws()
        if data.startswith(b"<<", i):
            i += 2
            d = {}
            while True:
                ws()
                if i >= n or data.startswith(b">>", i):
                    i += 2
                    return d
                if data[i:i + 1] != b"/":
                    raise PsdError("engine data")
                k = name()
                d[k] = value(depth + 1)
        c = data[i:i + 1]
        if c == b"[":
            i += 1
            lst = []
            while True:
                ws()
                if i >= n or data[i:i + 1] == b"]":
                    i += 1
                    return lst
                lst.append(value(depth + 1))
        if c == b"(":
            return string()
        if c == b"/":
            return name()
        for word, v in ((b"true", True), (b"false", False)):
            if data.startswith(word, i):
                i += len(word)
                return v
        m = _ED_NUM.match(data, i)
        if m:
            i = m.end()
            s = m.group()
            return float(s) if b"." in s else int(s)
        raise PsdError("engine data")

    return value()


_JUSTIFY = {0: "left", 1: "right", 2: "center"}


def _type_tool(data: bytes) -> Optional[dict]:
    """A text layer: {"text", "font" (PostScript name), "fonts", "size" (in the
    text's own points), "scale" (its transform's), "colour", "align",
    "origin" (point text: where its baseline starts, on the full-size canvas),
    "box" (paragraph text: left, top, right, bottom on the canvas, full size)}."""
    r = _Reader(data)
    r.take(2)
    xx, xy, yx, yy, tx, ty = struct.unpack(">6d", r.take(48))
    r.take(2)
    r.u32()
    desc = _descriptor(r)
    out = {"text": str(desc.get("Txt", "")).replace("\r", "\n").strip(),
           "font": "", "fonts": [], "size": 0.0, "colour": None, "align": "left",
           "box": None, "scale": (yx * yx + yy * yy) ** 0.5 or 1.0, "origin": (tx, ty)}
    raw = desc.get("EngineData")
    if not isinstance(raw, bytes):
        return out
    ed = engine_data(raw)
    eng = ed.get("EngineDict") or {}
    res = ed.get("ResourceDict") or ed.get("DocumentResources") or {}
    fonts = [str(f.get("Name", "")) for f in res.get("FontSet", []) if isinstance(f, dict)]
    sheets = res.get("StyleSheetSet") or []
    normal = res.get("TheNormalStyleSheet", 0)
    base = {}
    if isinstance(normal, int) and 0 <= normal < len(sheets):
        base = dict(sheets[normal].get("StyleSheetData") or {})
    sr = eng.get("StyleRun") or {}
    runs = sr.get("RunArray") or [{}]
    lens = sr.get("RunLengthArray") or [1] * len(runs)
    text = str((eng.get("Editor") or {}).get("Text", "")).replace("\r", "\n")
    best, best_len = 0, -1
    for k, ln in enumerate(lens[:len(runs)]):        # the longest run that isn't spaces
        start = sum(lens[:k])
        chunk = text[start:start + int(ln)].strip() if text else "x"
        if chunk and ln > best_len:
            best, best_len = k, ln
    run = runs[best] if best < len(runs) else {}
    data_ = dict(base)
    data_.update(((run.get("StyleSheet") or {}).get("StyleSheetData")) or {})
    fi = data_.get("Font", 0)
    if isinstance(fi, int) and 0 <= fi < len(fonts):
        out["font"] = fonts[fi]
    used = []
    for rr in runs:
        k = (((rr.get("StyleSheet") or {}).get("StyleSheetData")) or {}).get("Font")
        if isinstance(k, int) and 0 <= k < len(fonts) and fonts[k] not in used:
            used.append(fonts[k])
    out["fonts"] = used or ([out["font"]] if out["font"] else [])
    out["size"] = float(data_.get("FontSize", 0) or 0)
    vals = (data_.get("FillColor") or {}).get("Values")
    if isinstance(vals, list) and len(vals) >= 4:
        out["colour"] = "#%02x%02x%02x" % tuple(max(0, min(255, round(float(v) * 255)))
                                                for v in vals[1:4])
    pr = ((eng.get("ParagraphRun") or {}).get("RunArray") or [{}])[0]
    props = ((pr.get("ParagraphSheet") or {}).get("Properties")) or {}
    j = props.get("Justification")
    if j is None:
        psheets = res.get("ParagraphSheetSet") or []
        pn = res.get("TheNormalParagraphSheet", 0)
        if isinstance(pn, int) and 0 <= pn < len(psheets):
            j = (psheets[pn].get("Properties") or {}).get("Justification")
    out["align"] = _JUSTIFY.get(j, "justify" if isinstance(j, int) and j > 2 else "left")
    shapes = ((eng.get("Rendered") or {}).get("Shapes") or {}).get("Children") or [{}]
    ph = ((shapes[0].get("Cookie") or {}).get("Photoshop")) or {}
    bb = ph.get("BoxBounds")
    if ph.get("ShapeType") == 1 and isinstance(bb, list) and len(bb) == 4:
        x0, y0, x1, y1 = (float(v) for v in bb)
        pts = [(xx * x + yx * y + tx, xy * x + yy * y + ty) for x in (x0, x1) for y in (y0, y1)]
        out["box"] = (min(p[0] for p in pts), min(p[1] for p in pts),
                      max(p[0] for p in pts), max(p[1] for p in pts))
    return out
