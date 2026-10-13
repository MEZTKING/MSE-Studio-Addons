"""An MPCFill order file (the .xml mpcfill.com's *Download → XML* gives you,
the one mpc-autofill reads): which picture goes on each card, front and
back, how many of each, and the card back."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OrderCard:
    name: str                      # the card's name (from the picture's file name)
    front: str                     # the picture's id (a Google Drive file)
    picture: str = ""              # the picture's file name on MPCFill
    count: int = 1
    back: str = ""                 # its own back, for double-faced cards
    back_picture: str = ""


@dataclass
class Order:
    cards: list = field(default_factory=list)
    cardback: str = ""             # the picture id of the card back
    quantity: int = 0
    stock: str = ""

    @property
    def total(self) -> int:
        return sum(c.count for c in self.cards)


def card_name(picture: str, query: str = "") -> str:
    """"Sol Ring" from "Sol Ring (Retro).png" – else the search it was found with."""
    stem = Path(picture or "").stem.replace("_", " ").strip()
    stem = re.sub(r"\s*[(\[][^)\]]*[)\]]\s*$", "", stem)
    stem = re.sub(r"\s*[(\[][^)\]]*[)\]]\s*$", "", stem).strip(" -–")
    if stem:
        return stem
    return " ".join(w[:1].upper() + w[1:] for w in (query or "").split())


def _slots(text: str) -> list[int]:
    return [int(s) for s in re.findall(r"\d+", text or "")]


def read(path: Path) -> Order:
    """The order in an MPCFill .xml file."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as e:
        raise ValueError(f"That isn't an MPCFill order file ({e}).") from None
    if root.tag != "order":
        raise ValueError("That isn't an MPCFill order file – on mpcfill.com, use "
                         "Download → XML.")
    order = Order()
    d = root.find("details")
    if d is not None:
        order.quantity = int(d.findtext("quantity") or 0)
        order.stock = d.findtext("stock") or ""
    backs: dict[int, tuple[str, str]] = {}
    for c in root.findall("backs/card"):
        for s in _slots(c.findtext("slots")):
            backs[s] = ((c.findtext("id") or "").strip(), c.findtext("name") or "")
    for c in root.findall("fronts/card"):
        fid = (c.findtext("id") or "").strip()
        if not fid:
            continue
        slots = _slots(c.findtext("slots"))
        picture = c.findtext("name") or ""
        back = next((backs[s] for s in slots if s in backs), ("", ""))
        order.cards.append(OrderCard(card_name(picture, c.findtext("query") or ""), fid,
                                     picture, max(1, len(slots)), back[0], back[1]))
    order.cardback = (root.findtext("cardback") or "").strip()
    return order
