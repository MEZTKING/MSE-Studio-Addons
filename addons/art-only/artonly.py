"""Art only: a card picture without its frame and text – just the art, for
your own cards. Two ways:

* **The art window** – a normal card: the art is in its window, so it's cut
  out (Scryfall's own cut-out for real cards, the sharpest there is).
* **Erase the frame and text** – a full-art or borderless card, the art
  under everything: the name bar, type line, text box, P/T and the bottom
  lines are painted over from the art around them. The boxes are a guess
  (a modern frame); paint more or less with the brush.

The fill: *Content-aware* (the default) rebuilds the painted-over parts from
patches of the art around them (PatchMatch, coarse to fine, as in photo
editors), so lines and textures carry on; *Quick* smooths over (OpenCV); AI
fill (when AI is switched on) is done by MSE Studio. Nothing here uses the
network itself (the Decklists page gets Scryfall's pictures)."""
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
FILLS = {"content": "Content-aware fill (best – a few seconds)",
         "smart": "Quick smooth fill",
         "mirror": "Mirror the art above it",
         "blur": "Soft blur"}
AI_FILL = ("ai", "AI fill")
AI_PROMPT = ("Repaint only the masked areas so the artwork carries on naturally where a card's "
             "name bar, type line, text box and border were. Match the painting's style, "
             "colours, lighting and detail. No text, letters, symbols, frames or borders – just "
             "the art.")


class Stopped(RuntimeError):
    pass


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


# ------------------------------------------------------------------ content-aware fill
_R = 2                     # patch radius: 5×5 patches
_P = 2 * _R + 1


def _telea(a, hole):
    import cv2
    import numpy as np
    u8 = np.clip(a, 0, 255).astype(np.uint8)
    return cv2.inpaint(u8, hole.astype(np.uint8) * 255, 5, cv2.INPAINT_TELEA).astype(np.float32)


def _vote(T, hole, ty, tx, sy, sx, best):
    """Each painted-over pixel: the mean of the patches over it, the closer
    matches counting more."""
    import numpy as np
    H, W = hole.shape
    sig = max(float(np.percentile(best, 75)), 1e-3) if len(best) else 1.0
    wgt = np.exp(-best / (2 * sig))
    acc = np.zeros((H * W, 3), np.float64)
    cnt = np.zeros(H * W, np.float64)
    for dy in range(-_R, _R + 1):
        for dx in range(-_R, _R + 1):
            py, px = ty + dy, tx + dx
            inh = hole[py, px]
            if not inh.any():
                continue
            idx = py[inh] * W + px[inh]
            col = T[sy[inh] + dy, sx[inh] + dx]
            wi = wgt[inh]
            cnt += np.bincount(idx, weights=wi, minlength=H * W)
            for c in range(3):
                acc[:, c] += np.bincount(idx, weights=col[:, c] * wi, minlength=H * W)
    got = cnt > 0
    flat = T.reshape(-1, 3).copy()
    flat[got] = (acc[got] / cnt[got, None]).astype(np.float32)
    return flat.reshape(H, W, 3)


def _areas(hole):
    """Where patches may come from (all known art) and the patches to fill
    (the ones touching the hole)."""
    import cv2
    import numpy as np
    k = np.ones((_P, _P), np.uint8)
    src_ok = cv2.erode((~hole).astype(np.uint8), k, borderType=cv2.BORDER_CONSTANT,
                       borderValue=0) > 0
    band = cv2.dilate(hole.astype(np.uint8), k) > 0
    band[:_R, :] = band[-_R:, :] = False
    band[:, :_R] = band[:, -_R:] = False
    return src_ok, band


def _patch_views(T):
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view
    Tp = np.pad(T, ((_R, _R), (_R, _R), (0, 0)), mode="edge")
    return sliding_window_view(Tp, (_P, _P), axis=(0, 1))          # H, W, 3, P, P


def _em(T, hole, nnf, rng, em_iters, pm_iters, check):
    """PatchMatch: for every patch over the hole, the most alike patch of
    known art; then the hole is painted from them – a few rounds."""
    import numpy as np
    H, W = hole.shape
    src_ok, band = _areas(hole)
    if src_ok.sum() < 16:
        return T, nnf
    sy_all, sx_all = np.nonzero(src_ok)
    ty, tx = np.nonzero(band)
    n = len(ty)
    if nnf is None or nnf[0].shape != hole.shape:
        k = rng.integers(0, len(sy_all), n)
        sy, sx = sy_all[k], sx_all[k]
    else:
        sy, sx = nnf[0][ty, tx].copy(), nnf[1][ty, tx].copy()
        bad = ~nnf[2][ty, tx] | ~src_ok[np.clip(sy, 0, H - 1), np.clip(sx, 0, W - 1)]
        k = rng.integers(0, len(sy_all), int(bad.sum()))
        sy[bad], sx[bad] = sy_all[k], sx_all[k]
    for _e in range(em_iters):
        check()
        V = _patch_views(T)
        A = V[ty, tx].reshape(n, -1)

        def dist(cy, cx, ok):
            d = np.full(n, np.inf, np.float32)
            if ok.any():
                diff = A[ok] - V[cy[ok], cx[ok]].reshape(int(ok.sum()), -1)
                d[ok] = np.einsum("ij,ij->i", diff, diff)
            return d

        best = dist(sy, sx, np.ones(n, bool))
        NY = np.zeros((H, W), np.int64)
        NX = np.zeros((H, W), np.int64)

        def take(cy, cx):
            nonlocal sy, sx, best
            cy, cx = np.clip(cy, 0, H - 1), np.clip(cx, 0, W - 1)
            d = dist(cy, cx, src_ok[cy, cx])
            better = d < best
            sy, sx, best = np.where(better, cy, sy), np.where(better, cx, sx), \
                np.where(better, d, best)

        for it in range(pm_iters):
            sign = 1 if it % 2 == 0 else -1
            for step in (1, 2, 4):
                for dy, dx in ((0, step * sign), (step * sign, 0)):
                    NY[ty, tx], NX[ty, tx] = sy, sx
                    qy, qx = np.clip(ty - dy, 0, H - 1), np.clip(tx - dx, 0, W - 1)
                    inb = band[qy, qx]
                    take(np.where(inb, NY[qy, qx] + dy, sy), np.where(inb, NX[qy, qx] + dx, sx))
            rad = max(H, W)
            while rad >= 1:
                take(sy + rng.integers(-rad, rad + 1, n), sx + rng.integers(-rad, rad + 1, n))
                rad //= 2
        T = _vote(T, hole, ty, tx, sy, sx, best)
    NY = np.zeros((H, W), np.int64)
    NX = np.zeros((H, W), np.int64)
    NY[ty, tx], NX[ty, tx] = sy, sx
    return T, (NY, NX, band)


def _refine(T, hole, nnf, f, chunk=120000):
    """At full size: every patch copied from where the smaller fill found it,
    so the painted-over parts are as sharp as the art around them."""
    import numpy as np
    H, W = hole.shape
    NY, NX, has = nnf
    h, w = has.shape
    src_ok, band = _areas(hole)
    ty, tx = np.nonzero(band)
    yw = np.minimum((ty / f).astype(np.int64), h - 1)
    xw = np.minimum((tx / f).astype(np.int64), w - 1)
    sy = np.rint(NY[yw, xw] * f + (ty - yw * f)).astype(np.int64)
    sx = np.rint(NX[yw, xw] * f + (tx - xw * f)).astype(np.int64)
    ok = has[yw, xw] & (sy >= 0) & (sy < H) & (sx >= 0) & (sx < W)
    ok[ok] &= src_ok[sy[ok], sx[ok]]
    ty, tx, sy, sx = ty[ok], tx[ok], sy[ok], sx[ok]
    V = _patch_views(T)
    best = np.empty(len(ty), np.float32)
    for i in range(0, len(ty), chunk):
        d = V[ty[i:i + chunk], tx[i:i + chunk]].reshape(-1, 3 * _P * _P) - \
            V[sy[i:i + chunk], sx[i:i + chunk]].reshape(-1, 3 * _P * _P)
        best[i:i + chunk] = np.einsum("ij,ij->i", d, d)
    return _vote(T, hole, ty, tx, sy, sx, best)


def content_fill(img: Image.Image, mask: Image.Image, side: int = 512, progress=None,
                 cancel=None) -> Image.Image:
    """Content-aware fill: the masked parts rebuilt from patches of the art
    around them, coarse to fine, then at full size. A few seconds."""
    import cv2
    import numpy as np
    rng = np.random.default_rng(7)

    def check():
        if cancel is not None and getattr(cancel, "cancelled", False):
            raise Stopped("Stopped")
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    hole = np.asarray(mask.convert("L").resize(img.size, Image.NEAREST)) > 32
    if not hole.any():
        return img.copy()
    H0, W0 = hole.shape
    s = min(1.0, side / max(H0, W0))
    W, H = max(16, round(W0 * s)), max(16, round(H0 * s))
    A = cv2.resize(rgb, (W, H), interpolation=cv2.INTER_AREA)
    M = cv2.resize(hole.astype(np.float32), (W, H), interpolation=cv2.INTER_AREA) > 0.01
    pyr = [(A, M)]
    while min(pyr[-1][1].shape) >= 128 and len(pyr) < 5:
        a, m = pyr[-1]
        size = (a.shape[1] // 2, a.shape[0] // 2)
        pyr.append((cv2.resize(a, size, interpolation=cv2.INTER_AREA),
                    cv2.resize(m.astype(np.float32), size, interpolation=cv2.INTER_AREA) > 0.5))
    pyr.reverse()
    est, nnf = None, None
    for i, (a, m) in enumerate(pyr):
        check()
        if progress is not None:
            progress(i, len(pyr) + 1, "Content-aware fill…")
        if est is None:
            est = _telea(a, m)
        else:
            est = np.where(m[..., None], cv2.resize(est, (a.shape[1], a.shape[0]),
                                                    interpolation=cv2.INTER_LINEAR), a)
            size = (a.shape[1], a.shape[0])
            nnf = tuple(cv2.resize((x * 2 if j < 2 else x).astype(np.float32), size,
                                   interpolation=cv2.INTER_NEAREST).astype(
                        np.int64 if j < 2 else bool) for j, x in enumerate(nnf))
        last = i == len(pyr) - 1
        est, nnf = _em(est, m, nnf, rng, 3 if last else 5, 3 if last else 4, check)
        est = np.where(m[..., None], est, a)
    check()
    if progress is not None:
        progress(len(pyr), len(pyr) + 1, "Content-aware fill: full size…")
    up = cv2.resize(est, (W0, H0), interpolation=cv2.INTER_CUBIC)
    start = np.where(hole[..., None], up, rgb)
    out = _refine(start, hole, nnf, W0 / W) if s < 1.0 else start
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def _blur(img: Image.Image, mask: Image.Image) -> Image.Image:
    r = max(8, img.width // 25)
    return _smart(img, mask).filter(ImageFilter.GaussianBlur(r // 2))


def erase(img: Image.Image, mask: Image.Image, fill: str = "content",
          feather: int = 0, progress=None, cancel=None) -> Image.Image:
    """The picture with the masked parts painted over."""
    mask = mask.convert("L").resize(img.size, Image.NEAREST)
    if mask.getbbox() is None:
        return img.copy()
    if fill == "content":
        filled = content_fill(img, mask, progress=progress, cancel=cancel)
    else:
        filled = {"mirror": _mirror, "blur": _blur}.get(fill, _smart)(img, mask)
    soft = mask.filter(ImageFilter.GaussianBlur(feather or max(1, img.width // 300)))
    return Image.composite(filled, img, soft)


def keep_art(path: Path, mode: str = "", mask: Optional[Image.Image] = None,
             fill: str = "content") -> Image.Image:
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
