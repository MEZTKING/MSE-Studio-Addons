"""Art only: a card picture without its frame and text – just the art, for
your own cards. Two ways:

* **The art window** – a normal card: the art is in its window, so it's cut
  out (Scryfall's own cut-out for real cards, the sharpest there is).
* **Erase the frame and text** – a full-art or borderless card, the art
  under everything: the name bar, type line, text box, P/T and the bottom
  lines are painted over from the art around them. The boxes are a guess
  (a modern frame); paint more or less with the brush.

Big boxes painted over get soft – fine under a new frame's text box, which
covers most of it again. Nothing here uses the network (the Decklists page
gets Scryfall's pictures)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter

# a modern (M15) card, as parts of its width / height
ART_BOX = (29 / 375, 59 / 523, 316 / 375, 231 / 523)
ERASE = {                          # what a full-art card has over its art
    "name bar": (18 / 375, 22 / 523, 339 / 375, 38 / 523),
    "type line": (18 / 375, 290 / 523, 339 / 375, 32 / 523),
    "text box": (24 / 375, 322 / 523, 327 / 375, 166 / 523),
    "P/T": (268 / 375, 460 / 523, 92 / 375, 46 / 523),
    "bottom lines": (14 / 375, 484 / 523, 347 / 375, 36 / 523),
}
BORDER = 13 / 375                  # the black border of a printed card
FILLS = {"smart": "Smart fill (from the art around it)",
         "mirror": "Mirror the art above it",
         "blur": "Soft blur"}


def card_area(size: tuple[int, int]) -> tuple[int, int, int, int]:
    """The card in a picture: without MPC's 1/8 in margin when it has it."""
    w, h = size
    if not w or not h:
        return 0, 0, w, h
    r = w / h
    if abs(r - 2.75 / 3.75) < abs(r - 2.5 / 3.5) and r < 0.8:
        bx, by = round(w * 0.125 / 2.75), round(h * 0.125 / 3.75)
        return bx, by, w - bx, h - by
    return 0, 0, w, h


def open_card(path: Path) -> Image.Image:
    """The card alone (no MPC margin), RGB."""
    from PIL import ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
    return im.crop(card_area(im.size))


def _px(img_size, box) -> tuple[int, int, int, int]:
    w, h = img_size
    x, y, bw, bh = box
    return round(x * w), round(y * h), round((x + bw) * w), round((y + bh) * h)


def art_window(img: Image.Image) -> Image.Image:
    """The art window of a normal card."""
    return img.crop(_px(img.size, ART_BOX))


def guess_mode(img: Image.Image) -> str:
    """"window" for a normal card (plain frame around the art), "full" for a
    full-art or borderless one (the art goes on beside its window)."""
    import numpy as np
    a = np.asarray(img.convert("L"), dtype=np.float32)
    h, w = a.shape
    x0, y0, x1, y1 = _px(img.size, ART_BOX)
    strips = [a[y0:y1, max(0, round(w * 0.02)):max(1, x0 - 2)],     # left of the window
              a[y0:y1, min(w - 1, x1 + 2):min(w, round(w * 0.98))]]  # right of it
    spread = [float(s.std()) for s in strips if s.size > 50]
    if not spread:
        return "window"
    return "window" if max(spread) < 14 else "full"


def default_mask(size: tuple[int, int], parts: Optional[list] = None,
                 border: bool = True) -> Image.Image:
    """The parts of a full-art card to paint over ('L', 255 = erase)."""
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    for name in parts or list(ERASE):
        d.rectangle(_px(size, ERASE[name]), fill=255)
    if border:
        w, h = size
        b = max(1, round(w * BORDER))
        d.rectangle((0, 0, w, b), fill=255)
        d.rectangle((0, h - b, w, h), fill=255)
        d.rectangle((0, 0, b, h), fill=255)
        d.rectangle((w - b, 0, w, h), fill=255)
    return m


def _smart(img: Image.Image, mask: Image.Image) -> Image.Image:
    """Painted over from the art around it (OpenCV's inpainting, done small
    and scaled up so big boxes stay smooth), with a little grain."""
    import cv2
    import numpy as np
    w, h = img.size
    scale = min(1.0, 420 / max(w, h))
    sw, sh = max(8, round(w * scale)), max(8, round(h * scale))
    small = np.asarray(img.resize((sw, sh), Image.LANCZOS))[:, :, ::-1].copy()
    m = np.asarray(mask.resize((sw, sh), Image.BILINEAR))
    m = (m > 32).astype(np.uint8) * 255
    m = cv2.dilate(m, np.ones((3, 3), np.uint8))
    filled = cv2.inpaint(small, m, 7, cv2.INPAINT_TELEA)
    big = Image.fromarray(filled[:, :, ::-1].copy()).resize((w, h), Image.BICUBIC)
    grain = np.random.default_rng(7).normal(0, 3.5, (h, w, 1))
    big = Image.fromarray(np.clip(np.asarray(big, dtype=np.float32) + grain, 0, 255)
                          .astype(np.uint8))
    return big


def _mirror(img: Image.Image, mask: Image.Image) -> Image.Image:
    """Each painted band filled with the art just above it, flipped."""
    if not mask.getbbox():
        return img.copy()
    import numpy as np
    a = np.asarray(img).copy()
    m = np.asarray(mask) > 32
    h = a.shape[0]
    has = m.any(axis=1)
    y = 0
    while y < h:
        if not has[y]:
            y += 1
            continue
        top = y
        while y < h and has[y]:
            y += 1
        for yy in range(top, y):             # top down: rows already filled can be used
            src = min(h - 1, max(0, 2 * top - yy - 1))
            cols = m[yy]
            a[yy, cols] = a[src, cols]
    return Image.fromarray(a)


def _blur(img: Image.Image, mask: Image.Image) -> Image.Image:
    r = max(8, img.width // 25)
    return _smart(img, mask).filter(ImageFilter.GaussianBlur(r // 2))


def erase(img: Image.Image, mask: Image.Image, fill: str = "smart",
          feather: int = 0) -> Image.Image:
    """The picture with the masked parts painted over."""
    mask = mask.convert("L").resize(img.size, Image.NEAREST)
    if mask.getbbox() is None:
        return img.copy()
    filled = {"mirror": _mirror, "blur": _blur}.get(fill, _smart)(img, mask)
    soft = mask.filter(ImageFilter.GaussianBlur(feather or max(1, img.width // 300)))
    return Image.composite(filled, img, soft)


def keep_art(path: Path, mode: str = "", mask: Optional[Image.Image] = None,
             fill: str = "smart") -> Image.Image:
    """The art of a card picture: its window cut out, or the card with its
    frame and text painted over."""
    img = open_card(path)
    mode = mode or guess_mode(img)
    if mode == "window":
        return art_window(img)
    return erase(img, mask if mask is not None else default_mask(img.size), fill)


def file_name(name: str) -> str:
    import re
    return (re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", name).strip(" .") or "card") + " – art only"
