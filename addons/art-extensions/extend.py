"""One picture across several cards: where each card's art box falls on it.

The cards lie side by side (``cols`` a row, ``gap`` millimetres apart), the
picture covers them all; each card's art box – where its frame shows art,
as MSE Studio found it on the frame – gets the part of the picture behind
it, so laid out together the art carries on from card to card.

Kept with the deck in ``art_extensions.json`` (it goes with the deck and its
backups); the pictures are copied into the deck's "Art extensions" folder."""
from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

CARD_W, CARD_H = 63.0, 88.0             # a card, in millimetres
FILE = "art_extensions.json"
FOLDER = "Art extensions"


@dataclass
class Group:
    name: str
    picture: str = ""                   # in the deck's folder (or a full path)
    cards: list = field(default_factory=list)   # card ids, in order
    cols: int = 2                       # cards a row
    gap: float = 0.0                    # mm between cards laid side by side
    zoom: float = 1.0                   # 1 = the picture just covers the cards
    dx: float = 0.0                     # -1 (left) … 1 (right)
    dy: float = 0.0                     # -1 (top) … 1 (bottom)
    mode: str = "cards"                 # MODES
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @classmethod
    def from_dict(cls, d: dict) -> "Group":
        g = cls(str(d.get("name") or "Art extension"))
        g.picture = str(d.get("picture") or "")
        g.cards = [str(c) for c in d.get("cards") or [] if c]
        g.cols = max(1, min(12, int(d.get("cols") or 2)))
        g.gap = max(0.0, min(20.0, float(d.get("gap") or 0)))
        g.zoom = max(1.0, min(8.0, float(d.get("zoom") or 1)))
        g.dx = max(-1.0, min(1.0, float(d.get("dx") or 0)))
        g.dy = max(-1.0, min(1.0, float(d.get("dy") or 0)))
        g.mode = d.get("mode") if d.get("mode") in MODES else "cards"
        g.id = str(d.get("id") or g.id)
        return g


def load(folder) -> list[Group]:
    try:
        data = json.loads((Path(folder) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [Group.from_dict(d) for d in (data.get("groups") or []) if isinstance(d, dict)]


def save(folder, groups: list[Group]) -> None:
    (Path(folder) / FILE).write_text(json.dumps({"groups": [asdict(g) for g in groups]},
                                                indent=1, ensure_ascii=False),
                                     encoding="utf-8")


def keep_picture(folder, path) -> str:
    """The picture copied into the deck's folder (so it goes with the deck);
    returns its path there, relative to the deck."""
    path = Path(path)
    dst_dir = Path(folder) / FOLDER
    try:
        path.resolve().relative_to(Path(folder).resolve())
        return str(path.resolve().relative_to(Path(folder).resolve()))   # already in it
    except ValueError:
        pass
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / path.name
    k = 2
    while dst.exists() and dst.stat().st_size != path.stat().st_size:
        dst = dst_dir / f"{path.stem} {k}{path.suffix}"
        k += 1
    if not dst.exists():
        shutil.copyfile(path, dst)
    return str(dst.relative_to(Path(folder)))


def picture_path(folder, g: Group) -> Path:
    p = Path(g.picture)
    return p if p.is_absolute() else Path(folder) / p


MODES = {"cards": "As if the cards lie side by side (their frames cover some of it)",
         "boxes": "Art box to art box (none of the picture is hidden)"}


def layout(cells: list, cols: int, gap: float) -> tuple[list, tuple[float, float]]:
    """Cells (width, height in mm) laid out ``cols`` a row, ``gap`` apart:
    (each cell's top left corner, (width, height) of them all)."""
    cols = max(1, cols)
    out, y, width = [], 0.0, 0.0
    for r in range(0, len(cells), cols):
        row = cells[r:r + cols]
        x = 0.0
        for w, _h in row:
            out.append((x, y))
            x += w + gap
        width = max(width, x - gap)
        y += max(h for _w, h in row) + gap
    return out, (width, max(0.0, y - gap))


def art_box(frac: tuple, aspect: float = 0.0) -> tuple[float, float, float, float]:
    """The art box on a card in mm from its place as fractions of the card
    (x, y, w, h); ``aspect`` (width / height) – the art's own shape – sets
    the height when given."""
    x, y, w, h = (float(v) for v in frac)
    aw = w * CARD_W
    ah = aw / aspect if aspect else h * CARD_H
    return x * CARD_W, y * CARD_H, aw, ah


def placement(pic: tuple[int, int], size_mm: tuple[float, float], zoom: float = 1.0,
              dx: float = 0.0, dy: float = 0.0) -> tuple[float, float, float]:
    """(pixels a mm, left, top): the cards on the picture, as big as it lets
    them be (``zoom`` > 1: smaller, so they cover less of it; ``dx`` / ``dy``
    move them across it)."""
    pw, ph = pic
    w, h = size_mm
    if w <= 0 or h <= 0:
        return 1.0, 0.0, 0.0
    s = min(pw / w, ph / h) / max(1.0, zoom)
    free_x, free_y = pw - w * s, ph - h * s
    return s, free_x * (0.5 + dx / 2), free_y * (0.5 + dy / 2)


def plan(pic: tuple[int, int], g: "Group", boxes: list) -> list[dict]:
    """Where each card goes on the picture, in its pixels: {"card": [x, y, w,
    h], "art": [x, y, w, h]} (``art`` is the part that goes on the card).
    ``boxes``: each card's art box in mm (``art_box``), in the group's order."""
    if g.mode == "boxes":
        cells = [(w, h) for _x, _y, w, h in boxes]
        inner = [(0.0, 0.0, w, h) for _x, _y, w, h in boxes]
    else:
        cells = [(CARD_W, CARD_H)] * len(boxes)
        inner = list(boxes)
    corners, size = layout(cells, g.cols, g.gap)
    s, ox, oy = placement(pic, size, g.zoom, g.dx, g.dy)
    out = []
    for (cx, cy), (cw, ch), (ax, ay, aw, ah) in zip(corners, cells, inner):
        card = [ox + cx * s, oy + cy * s, cw * s, ch * s]
        art = [ox + (cx + ax) * s, oy + (cy + ay) * s, aw * s, ah * s]
        out.append({"card": card, "art": art})
    return out


def crop_of(box: list, pic: tuple[int, int]) -> list[int]:
    """A box on the picture as a crop in whole pixels, kept inside it."""
    x, y, w, h = box
    x, y = max(0, min(round(x), pic[0] - 1)), max(0, min(round(y), pic[1] - 1))
    return [x, y, max(1, min(round(w), pic[0] - x)), max(1, min(round(h), pic[1] - y))]
