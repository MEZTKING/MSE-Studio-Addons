"""The layers of a Photoshop file (.psd, .psb), each as a picture with its
transparency – enough for frame templates: 8-bit RGB or greyscale pixel
layers (raw, RLE or ZIP compressed). Groups, adjustment layers and effects
aren't drawn; hidden layers are included (a template often hides the colours
it isn't showing)."""
from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional

from PIL import Image


class PsdError(ValueError):
    pass


@dataclass
class Layer:
    name: str
    box: tuple                     # left, top, right, bottom on the canvas
    hidden: bool
    image: Optional[Image.Image]   # RGBA, the layer's own size (None: empty / a group)


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
        packed = data[table:]
        im = Image.frombytes("L", (w, h), packed, "packbits", "L")
        return im.tobytes()
    if comp in (2, 3):
        raw = zlib.decompress(data)
        if comp == 3:                   # ZIP with prediction: each row is differences
            import numpy as np
            a = np.frombuffer(raw[:w * h], dtype=np.uint8).reshape(h, w)
            a = np.cumsum(a, axis=1, dtype=np.uint8)
            return a.tobytes()
        return raw[:w * h]
    raise PsdError(f"Unknown compression {comp}.")


def read_layers(path: Path) -> tuple[tuple[int, int], list[Layer]]:
    """((width, height), layers from the bottom up)."""
    with open(path, "rb") as fp:
        if fp.read(4) != b"8BPS":
            raise PsdError("Not a Photoshop file.")
        version = _u(fp, 2)
        if version not in (1, 2):
            raise PsdError("Unknown Photoshop file version.")
        big = version == 2
        fp.read(6)
        fp.read(2)                                  # channels
        height, width = _u(fp, 4), _u(fp, 4)
        depth, mode = _u(fp, 2), _u(fp, 2)
        if depth != 8:
            raise PsdError(f"Only 8-bit Photoshop files can be read (this one is {depth}-bit).")
        if mode not in (1, 3):
            raise PsdError("Only RGB or greyscale Photoshop files can be read.")
        fp.seek(_u(fp, 4), 1)                      # colour mode data
        fp.seek(_u(fp, 4), 1)                      # image resources
        lm_len = _u(fp, 8 if big else 4)
        if lm_len == 0:
            return (width, height), []
        li_len = _u(fp, 8 if big else 4)
        if li_len == 0:
            return (width, height), []
        count = abs(_s(fp, 2))
        records = []
        for _ in range(count):
            top, left, bottom, right = (_s(fp, 4) for _ in range(4))
            nch = _u(fp, 2)
            chans = [(_s(fp, 2), _u(fp, 8 if big else 4)) for _ in range(nch)]
            if fp.read(4) not in (b"8BIM", b"8B64"):
                raise PsdError("Damaged layer record.")
            fp.read(4)                              # blend mode
            fp.read(1)                              # opacity
            fp.read(1)                              # clipping
            flags = _u(fp, 1)
            fp.read(1)
            extra = _u(fp, 4)
            end = fp.tell() + extra
            fp.seek(_u(fp, 4), 1)                   # layer mask data
            fp.seek(_u(fp, 4), 1)                   # blending ranges
            n = _u(fp, 1)
            name = fp.read(n).decode("mac_roman", "replace")
            fp.seek((4 - (n + 1) % 4) % 4, 1)       # padded to 4 bytes
            group = False
            while fp.tell() + 12 <= end:            # additional layer information
                sig = fp.read(4)
                if sig not in (b"8BIM", b"8B64"):
                    break
                key = fp.read(4)
                ln = _u(fp, 8 if big and key in (b"LMsk", b"Lr16", b"Lr32", b"Layr", b"Mt16",
                                                 b"Mt32", b"Mtrn", b"Alph", b"FMsk", b"lnk2",
                                                 b"FEid", b"FXid", b"PxSD") else 4)
                data = fp.read(ln)
                if key == b"luni" and len(data) >= 4:
                    k = int.from_bytes(data[:4], "big")
                    try:
                        name = data[4:4 + 2 * k].decode("utf-16-be").rstrip("\x00") or name
                    except UnicodeDecodeError:
                        pass
                elif key in (b"lsct", b"lsdk") and len(data) >= 4:
                    group = int.from_bytes(data[:4], "big") in (1, 2, 3)
                if ln % 2:                          # some writers pad to an even length
                    here = fp.tell()
                    if fp.read(4) not in (b"8BIM", b"8B64"):
                        fp.seek(here + 1)
                    else:
                        fp.seek(here)
            fp.seek(end)
            records.append((name, (left, top, right, bottom), bool(flags & 0x02), chans, group))
        layers = []
        for name, box, hidden, chans, group in records:
            w, h = box[2] - box[0], box[3] - box[1]
            planes = {}
            for cid, ln in chans:
                start = fp.tell()
                if ln < 2:
                    fp.seek(start + ln)
                    continue
                comp = _u(fp, 2)
                data = fp.read(ln - 2)
                if cid == -2 or cid < -2:           # layer masks: not used
                    continue
                cw, ch = (w, h)
                if w > 0 and h > 0:
                    try:
                        planes[cid] = _decode(data, comp, cw, ch, big)
                    except Exception:  # noqa: BLE001 - a channel that can't be read
                        pass
            img = None
            if not group and w > 0 and h > 0 and planes:
                def plane(cid, fill=0):
                    raw = planes.get(cid)
                    if raw is None or len(raw) < w * h:
                        return Image.new("L", (w, h), fill)
                    return Image.frombytes("L", (w, h), raw[:w * h])
                if mode == 3:
                    r, g, b = plane(0), plane(1), plane(2)
                else:
                    r = g = b = plane(0)
                a = plane(-1, 255)
                img = Image.merge("RGBA", (r, g, b, a))
            layers.append(Layer(name, box, hidden, img))
        return (width, height), layers


def layer_pictures(path: Path) -> list[tuple[str, Image.Image]]:
    """Each pixel layer on the whole canvas (top layer first), named."""
    size, layers = read_layers(path)
    out = []
    for lay in reversed(layers):
        if lay.image is None or lay.image.getbbox() is None:
            continue
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        canvas.paste(lay.image, (lay.box[0], lay.box[1]))
        out.append((lay.name + (" (hidden)" if lay.hidden else ""), canvas))
    return out
