"""Is there text on a card picture? Lines of letters are looked for where a
Magic card has them – the name bar, the type line, the rules text box and
the bottom lines – so full-art and textless proxies can be found from their
pictures (Scryfall only knows the real card's text).

Letters are found as rows of small shapes of the same height, side by side
(dark on light and light on dark, so text over art counts too). Art rarely
makes such rows; a picture with very busy art can still fool it now and
then. Nothing here uses the network."""
from __future__ import annotations

from typing import Optional

import numpy as np
from PIL import Image

WIDTH = 600                       # pictures are looked at this wide
# where a card has text, as parts of the card (left, top, right, bottom)
REGIONS = {
    "name": (0.04, 0.025, 0.96, 0.105),
    "type": (0.04, 0.545, 0.96, 0.625),
    "rules": (0.06, 0.615, 0.94, 0.915),
}
NEEDED = {"name": 1, "type": 1, "rules": 1}     # rows of letters that count as text


def card_area(size: tuple) -> tuple:
    """The card in a picture: without MPC's 1/8 in margin when it has it."""
    w, h = size
    if not w or not h:
        return 0, 0, w, h
    r = w / h
    if abs(r - 2.75 / 3.75) < abs(r - 2.5 / 3.5) and r < 0.8:
        bx, by = round(w * 0.125 / 2.75), round(h * 0.125 / 3.75)
        return bx, by, w - bx, h - by
    return 0, 0, w, h


def _glyphs(binary: np.ndarray) -> list:
    """Shapes the size of letters: (x, y, w, h)."""
    import cv2
    n, _labels, stats, _c = cv2.connectedComponentsWithStats(binary, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not 5 <= h <= 30 or not 1 <= w <= 34 or h > 7 * w:
            continue
        fill = area / float(w * h)
        if 0.12 <= fill <= 0.92:
            out.append((int(x), int(y), int(w), int(h)))
    return out


def _rows(glyphs: list, width: int) -> int:
    """Rows of letters: shapes of about the same height on one line, packed
    close together (words of a sentence), spanning a fair part of the box.
    Shapes in art are of all sizes and spread out."""
    if len(glyphs) < 5:
        return 0
    used = [False] * len(glyphs)
    order = sorted(range(len(glyphs)), key=lambda i: glyphs[i][1] + glyphs[i][3])
    rows = 0
    taken: list = []
    for i in order:
        if used[i]:
            continue
        _x, y, _w, h = glyphs[i]
        base = y + h
        line = [j for j in order if not used[j]
                and abs((glyphs[j][1] + glyphs[j][3]) - base) <= max(2, h * 0.25)
                and 0.5 * h <= glyphs[j][3] <= 1.7 * h]
        if len(line) < 5:
            continue
        line.sort(key=lambda j: glyphs[j][0])
        hm = float(np.median([glyphs[j][3] for j in line]))
        runs, run = [], [line[0]]
        for a, b in zip(line, line[1:]):
            gap = glyphs[b][0] - (glyphs[a][0] + glyphs[a][2])
            if -2 <= gap <= 1.2 * hm:
                run.append(b)
            else:
                runs.append(run)
                run = [b]
        runs.append(run)
        found = False
        for r in runs:
            if len(r) < 5:
                continue
            span = glyphs[r[-1]][0] + glyphs[r[-1]][2] - glyphs[r[0]][0]
            hs = np.array([glyphs[j][3] for j in r], dtype=float)
            if span < 0.1 * width or len(r) * hm / max(span, 1) < 0.6:
                continue                       # too short, or too spread out
            if hs.std() / max(hs.mean(), 1) > 0.35:
                continue                       # shapes of all sizes: not letters
            found = True
            break
        if found and not any(abs(base - t) < hm * 0.6 for t in taken):
            rows += 1
            taken.append(base)
        for j in line:
            used[j] = True
    return rows


def _region_rows(gray: np.ndarray) -> int:
    import cv2
    rows = 0
    for inverse in (False, True):
        mode = cv2.THRESH_BINARY_INV if not inverse else cv2.THRESH_BINARY
        b = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, mode, 25, 18)
        rows = max(rows, _rows(_glyphs(b), gray.shape[1]))
    return rows


def text_regions(img: Image.Image) -> dict:
    """{"name": rows, "type": rows, "rules": rows} – the rows of letters found."""
    img = img.convert("L")
    img = img.crop(card_area(img.size))
    if img.width != WIDTH:
        img = img.resize((WIDTH, max(1, round(img.height * WIDTH / img.width))), Image.LANCZOS)
    a = np.asarray(img)
    h, w = a.shape
    out = {}
    for name, (x0, y0, x1, y1) in REGIONS.items():
        part = np.ascontiguousarray(a[round(y0 * h):round(y1 * h), round(x0 * w):round(x1 * w)])
        out[name] = _region_rows(part) if part.size else 0
    return out


def scan(img: Image.Image) -> dict:
    """{"rules": bool, "any": bool} – rules text, and any text at all."""
    rows = text_regions(img)
    found = {k: rows.get(k, 0) >= n for k, n in NEEDED.items()}
    return {"rules": found["rules"], "any": any(found.values()), "rows": rows}


def scan_file(data: bytes) -> Optional[dict]:
    import io
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            return scan(im)
    except Exception:  # noqa: BLE001 - not a picture
        return None
