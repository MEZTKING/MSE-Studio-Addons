"""Proxy decks people share (r/mpcproxies, Ko-fi): the store's list, the
ones you add, and paid ones you bought (their download link added by you).
Card names come from the pictures' file names; credits stay with every deck
and every picture printed from it."""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from mse_studio.core import addons

from . import gdrive

ADDON_ID = "mpc-proxies"
REDDIT_SEARCH = ("https://www.reddit.com/r/mpcproxies/search.json?q={q}&restrict_sr=1"
                 "&sort={sort}&limit=50")
KOFI = re.compile(r"https?://(?:www\.)?ko-fi\.com/[\w/.-]+", re.I)
DRIVE = re.compile(r"https?://drive\.google\.com/[^\s)\]\"'<>]+", re.I)
BACK_WORDS = re.compile(r"[\s_\-–(\[]*(?:back|reverse|b side|side b)[\s)\]]*$", re.I)
CARD_BACK = re.compile(r"^(?:card[\s_-]*back|cardback|back)$", re.I)
TOKEN = re.compile(r"\btokens?\b|\bemblem\b", re.I)


@dataclass
class Deck:
    id: str
    title: str
    creator: str = ""
    creator_link: str = ""
    page: str = ""                 # Ko-fi (or any shop) page
    reddit: str = ""
    drive: str = ""                # the Google Drive folder id
    price: str = "free"            # free | paid
    notes: str = ""
    tags: list = field(default_factory=list)
    mine: bool = False             # added by you
    bought_link: str = ""          # paid: the download link you got

    @property
    def folder(self) -> str:
        return self.drive or gdrive.folder_id(self.bought_link)

    @property
    def can_open(self) -> bool:
        return bool(self.folder)

    def credit(self) -> str:
        where = self.page or self.reddit or self.creator_link or \
            (gdrive.folder_link(self.drive) if self.drive else "")
        who = f" by {self.creator}" if self.creator and not self.creator.startswith("shared") \
            else (f" ({self.creator})" if self.creator else "")
        return f"{self.title}{who}" + (f" – {where}" if where else "")


# ------------------------------------------------------------------ the lists
def _data() -> Path:
    return addons.data_dir(ADDON_ID)


def _load(name: str, default):
    try:
        return json.loads((_data() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(name: str, value) -> None:
    (_data() / name).write_text(json.dumps(value, indent=2), encoding="utf-8")


def store_decks(path: Optional[Path] = None) -> list[Deck]:
    p = path or Path(__file__).with_name("catalogue.json")
    data = json.loads(p.read_text(encoding="utf-8"))
    return [Deck(**{k: v for k, v in d.items() if k in Deck.__dataclass_fields__})
            for d in data.get("decks", [])]


def decks() -> list[Deck]:
    """The store's decks and yours, with the links you added for paid ones."""
    bought = _load("bought.json", {})
    out = store_decks()
    for d in _load("mine.json", []):
        deck = Deck(**{k: v for k, v in d.items() if k in Deck.__dataclass_fields__})
        deck.mine = True
        out.append(deck)
    for d in out:
        d.bought_link = bought.get(d.id, "")
    return out


def add_mine(deck: Deck) -> None:
    mine = [d for d in _load("mine.json", []) if d.get("id") != deck.id]
    deck.mine = True
    mine.append(asdict(deck))
    _save("mine.json", mine)


def remove_mine(deck_id: str) -> None:
    _save("mine.json", [d for d in _load("mine.json", []) if d.get("id") != deck_id])


def set_bought(deck_id: str, link: str) -> None:
    """The download link you got after buying a paid deck."""
    if link and not gdrive.folder_id(link):
        raise ValueError("That isn't a Google Drive folder link.")
    bought = _load("bought.json", {})
    if link:
        bought[deck_id] = link.strip()
    else:
        bought.pop(deck_id, None)
    _save("bought.json", bought)


def deck_from_link(link: str, title: str = "", creator: str = "", page: str = "",
                   price: str = "free") -> Deck:
    """A deck you add: a Google Drive folder link (and where it's from)."""
    fid = gdrive.folder_id(link)
    if not fid and not KOFI.match(link or ""):
        raise ValueError("Paste a Google Drive folder link (or a Ko-fi page link).")
    if not fid:
        page, price = page or link.strip(), "paid"
    did = re.sub(r"[^a-z0-9]+", "-", (title or fid or page).lower()).strip("-")[:60] or \
        f"deck-{int(time.time())}"
    return Deck(did, title or "My proxy deck", creator, "", page,
                link.strip() if "reddit.com" in link else "", fid, price, mine=True)


# ------------------------------------------------------------------ cards from file names
def card_name(file_name: str) -> tuple[str, int]:
    """("Sol Ring", 0) from "001 - Sol Ring (Retro).png"; side 1 for a back
    face ("Delver of Secrets - Back.png"); ("", 0) for something else."""
    stem = Path(file_name).stem.replace("_", " ").strip()
    stem = re.sub(r"^\d{1,3}[\s.\-–)]+", "", stem)                 # 001 - …
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)                      # … (1) (a copy)
    side = 0
    if BACK_WORDS.search(stem) and not CARD_BACK.match(stem):
        side = 1
        stem = BACK_WORDS.sub("", stem)
    stem = re.sub(r"\s*[(\[][^)\]]*[)\]]\s*$", "", stem).strip(" -–")  # (Retro) [Artist]
    stem = re.sub(r"\s+(front|face)$", "", stem, flags=re.I).strip()
    return re.sub(r"\s{2,}", " ", stem), side


def is_card_back(file_name: str) -> bool:
    return bool(CARD_BACK.match(Path(file_name).stem.replace("_", " ").strip()))


@dataclass
class Card:
    name: str
    front: Optional[gdrive.Item] = None
    back: Optional[gdrive.Item] = None
    count: int = 1
    section: str = "main"
    extra: bool = False            # a token, or not on the deck's own list: added when picked

    @property
    def token(self) -> bool:
        return bool(TOKEN.search(self.name)) or "token" in (self.front.path if self.front
                                                             else "").lower()


def cards_in(items: list[gdrive.Item], decklist_text: str = "") -> tuple[list[Card], list]:
    """The deck's cards (front and back pictures) and its card backs. With
    the deck's own decklist, its counts and commander are used; tokens and
    cards that aren't on it are marked ``extra``."""
    by_name: dict[str, Card] = {}
    backs = []
    for it in items:
        if not it.picture:
            continue
        if is_card_back(it.name):
            backs.append(it)
            continue
        name, side = card_name(it.name)
        if not name:
            continue
        c = by_name.setdefault(name.lower(), Card(name))
        if side and c.back is None:
            c.back = it
        elif not side and c.front is None:
            c.front = it
    cards = [c for c in by_name.values() if c.front is not None or c.back is not None]
    if decklist_text:
        from mse_studio.core import decklists as dl
        listed = {e.name.lower(): e for e in dl.parse_text(decklist_text)}
        for c in cards:
            e = listed.get(c.name.lower()) or next(
                (x for n, x in listed.items() if n.split(" // ")[0] == c.name.lower()), None)
            if e is not None:
                c.count, c.section = e.count, e.section
            else:
                c.extra = True
    for c in cards:
        if c.front is None:                       # only a back picture: it's the front
            c.front, c.back = c.back, None
        if c.token:
            c.extra = True
    return sorted(cards, key=lambda c: (c.extra, c.section != "commander", c.name.lower())), \
        backs


# ------------------------------------------------------------------ r/mpcproxies
@dataclass
class Post:
    title: str
    author: str
    link: str                      # the Reddit post
    drive: list = field(default_factory=list)
    kofi: list = field(default_factory=list)
    flair: str = ""
    created: float = 0.0

    @property
    def price(self) -> str:
        return "free" if self.drive else "paid"


def links_in(text: str) -> tuple[list[str], list[str]]:
    """Google Drive folder links and Ko-fi links in a post."""
    drive = list(dict.fromkeys(u for u in DRIVE.findall(text or "") if gdrive.folder_id(u)))
    kofi = list(dict.fromkeys(KOFI.findall(text or "")))
    return drive, kofi


def search_reddit(query: str = "EDH deck", sort: str = "relevance",
                  http: Optional[Callable] = None) -> list[Post]:
    """Posts on r/mpcproxies (Reddit's public search), with the Drive and
    Ko-fi links found in them."""
    url = REDDIT_SEARCH.format(q=urllib.parse.quote(query), sort=sort)
    try:
        data = json.loads((http or gdrive._http)(url).decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Reddit didn't answer ({e}). It limits apps sometimes – try again "
                           "in a minute, or search r/mpcproxies in your browser and paste a "
                           "post's link with Add a link.") from e
    out = []
    for child in (data.get("data") or {}).get("children") or []:
        d = child.get("data") or {}
        text = " ".join(str(d.get(k) or "") for k in ("url", "selftext"))
        drive, kofi = links_in(text)
        out.append(Post(d.get("title", ""), d.get("author", ""),
                        "https://www.reddit.com" + d.get("permalink", ""), drive, kofi,
                        d.get("link_flair_text") or "", float(d.get("created_utc") or 0)))
    return out


def deck_from_post(post: Post) -> Deck:
    d = Deck(re.sub(r"[^a-z0-9]+", "-", post.title.lower()).strip("-")[:60] or "post",
             post.title, f"u/{post.author}" if post.author else "",
             f"https://www.reddit.com/user/{post.author}" if post.author else "",
             post.kofi[0] if post.kofi else "", post.link,
             gdrive.folder_id(post.drive[0]) if post.drive else "", post.price, mine=True)
    return d
