"""Proxy decks people share (r/mpcproxies, Ko-fi, Discord) and the ones on
your PC: the store's list, the ones you add, paid ones you bought (their
download link added by you) and folders or zips you downloaded. Card names
come from the pictures' file names; credits stay with every deck and every
picture printed from it."""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from mse_studio.core import addons

from . import gdrive, local

ADDON_ID = "mpc-proxies"
VERSION = "1.1.0"
# Reddit wants apps to say who they are (a browser-like name gets "403 Blocked")
REDDIT_UA = f"windows:mse-studio.proxy-decks:{VERSION} (MSE Studio add-on)"
REDDIT_HOSTS = ("https://www.reddit.com", "https://old.reddit.com")
REDDIT_SEARCH = "/r/mpcproxies/search.{fmt}?q={q}&restrict_sr=1&sort={sort}&limit=50"
REDDIT_BROWSER = "https://www.reddit.com/r/mpcproxies/search/?q={q}&sort={sort}"
KOFI = re.compile(r"https?://(?:www\.)?ko-fi\.com/[\w/.-]+", re.I)
DRIVE = re.compile(r"https?://drive\.google\.com/[^\s)\]\"'<>]+", re.I)
REDDIT_POST = re.compile(r"https?://(?:www\.|old\.|new\.)?reddit\.com/r/\w+/comments/\w+[^\s)\]\"'<>]*",
                         re.I)
BACK_WORDS = re.compile(r"[\s_\-–(\[]*(?:back|reverse|b side|side b)[\s)\]]*$", re.I)
CARD_BACK = re.compile(r"^(?:card[\s_-]*backs?|cardbacks?|backs?|sleeve)(?:[\s_-]*\d{1,2})?$", re.I)
TOKEN = re.compile(r"\btokens?\b|\bemblem\b", re.I)
EXTRA_NAME = re.compile(r"^(?:extras?|bonus|alt(?:ernate)?|unused)\s*[-–:]\s*", re.I)
EXTRA_DIR = re.compile(r"^(?:tokens?|extras?|bonus|emblems?|counters?|alt(?:ernate)?s?(?: arts?)?|"
                       r"unused|maybe(?:board)?|sideboard)$", re.I)
BACK_DIR = re.compile(r"^(?:card ?backs?|backs?|sleeves?)$", re.I)
VARIANT = re.compile(r"\s+\d{1,2}$")


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
    local: list = field(default_factory=list)    # on this PC: its folders and zips
    root: str = ""                 # on this PC: the folder you added it with
    decklist: str = ""             # a decklist that came with it (a pasted post)

    @property
    def folder(self) -> str:
        return self.drive or gdrive.folder_id(self.bought_link)

    @property
    def on_pc(self) -> bool:
        return bool(self.local)

    @property
    def can_open(self) -> bool:
        return bool(self.local or self.folder)

    def credit(self) -> str:
        where = self.page or self.reddit or self.creator_link or \
            (gdrive.folder_link(self.drive) if self.drive else "")
        who = f" by {self.creator}" if self.creator and not self.creator.startswith("shared") \
            else (f" ({self.creator})" if self.creator else "")
        return f"{self.title}{who}" + (f" – {where}" if where else "")


def _make(d: dict) -> Deck:
    return Deck(**{k: v for k, v in d.items() if k in Deck.__dataclass_fields__})


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


def scratch(prefix: str) -> Path:
    """A new folder for pictures on their way into a deck or a viewer – in
    the add-on's data folder (emptied each time the page starts)."""
    import tempfile
    base = _data() / "tmp"
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=base))


def clear_scratch() -> None:
    import shutil
    shutil.rmtree(_data() / "tmp", ignore_errors=True)


def store_decks(path: Optional[Path] = None) -> list[Deck]:
    p = path or Path(__file__).with_name("catalogue.json")
    data = json.loads(p.read_text(encoding="utf-8"))
    return [_make(d) for d in data.get("decks", [])]


def roots() -> list[str]:
    """Folders on this PC you added (each one deck, or a folder of decks)."""
    return [r for r in _load("library.json", {}).get("roots", []) if isinstance(r, str)]


def add_root(path: str) -> None:
    lib = _load("library.json", {})
    rs = [r for r in lib.get("roots", []) if r.lower() != str(path).lower()]
    lib["roots"] = rs + [str(path)]
    _save("library.json", lib)


def remove_root(path: str) -> None:
    lib = _load("library.json", {})
    lib["roots"] = [r for r in lib.get("roots", []) if r.lower() != str(path).lower()]
    _save("library.json", lib)


def local_id(ld) -> str:
    """A deck on this PC's id (the same every time it's scanned)."""
    return "local-" + hashlib.sha1(ld.key.encode("utf-8")).hexdigest()[:12]


def local_decks() -> list[Deck]:
    """The decks in the folders you added."""
    out, seen = [], set()
    for root in roots():
        for ld in local.scan(root):
            did = local_id(ld)
            if did in seen:
                continue
            seen.add(did)
            out.append(Deck(did, ld.title, notes="On this PC: " + "; ".join(ld.sources),
                            local=list(ld.sources), root=root))
    return out


def decks(with_local: bool = True) -> list[Deck]:
    """The store's decks, yours and the ones on this PC – with the links you
    added for paid ones and the credits you wrote."""
    bought = _load("bought.json", {})
    makers = _load("credits.json", {})
    out = store_decks()
    for d in _load("mine.json", []):
        deck = _make(d)
        deck.mine = True
        out.append(deck)
    if with_local:
        out += local_decks()
    for d in out:
        d.bought_link = bought.get(d.id, "")
        m = makers.get(d.id) or {}
        if m.get("creator"):
            d.creator = m["creator"]
        if m.get("link"):
            d.creator_link = m["link"]
    return out


def add_mine(deck: Deck) -> None:
    mine = [d for d in _load("mine.json", []) if d.get("id") != deck.id]
    deck.mine = True
    mine.append(asdict(deck))
    _save("mine.json", mine)


def remove_mine(deck_id: str) -> None:
    _save("mine.json", [d for d in _load("mine.json", []) if d.get("id") != deck_id])
    forget_listing(deck_id)


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


def set_maker(deck_id: str, creator: str, link: str = "") -> None:
    """Who made a deck (for its credit) – for decks on this PC, or to correct one."""
    makers = _load("credits.json", {})
    if creator or link:
        makers[deck_id] = {"creator": creator.strip(), "link": link.strip()}
    else:
        makers.pop(deck_id, None)
    _save("credits.json", makers)


# ------------------------------------------------------------------ imported decks are kept
def _listing_file(deck_id: str) -> Path:
    d = _data() / "decks"
    d.mkdir(exist_ok=True)
    return d / (re.sub(r"[^\w.-]+", "_", deck_id)[:80] + ".json")


def save_listing(deck_id: str, items: list, decklist: str = "") -> None:
    """A deck's file list, so it's there next time without asking Google again."""
    _listing_file(deck_id).write_text(json.dumps({
        "when": time.time(), "decklist": decklist,
        "items": [asdict(i) for i in items]}), encoding="utf-8")


def load_listing(deck_id: str):
    """(items, decklist text, when it was imported) or None."""
    try:
        data = json.loads(_listing_file(deck_id).read_text(encoding="utf-8"))
        items = [gdrive.Item(**{k: v for k, v in i.items() if k in gdrive.Item.__dataclass_fields__})
                 for i in data.get("items", [])]
        return items, data.get("decklist", ""), float(data.get("when") or 0)
    except (OSError, ValueError, TypeError):
        return None


def forget_listing(deck_id: str) -> None:
    try:
        _listing_file(deck_id).unlink()
    except OSError:
        pass


def is_imported(deck_id: str) -> bool:
    return _listing_file(deck_id).exists()


def last_deck() -> str:
    return str(_load("last.json", {}).get("deck") or "")


def set_last_deck(deck_id: str) -> None:
    _save("last.json", {"deck": deck_id})


def list_deck(deck: Deck, progress=None, cancel=None, http=None) -> tuple[list, str]:
    """(items, decklist text) of a deck: its Google Drive folder or its files
    on this PC."""
    if deck.on_pc:
        items = local.list_items(deck.local, cancel)
    else:
        _t, items = gdrive.list_folder(deck.folder, http=http, progress=progress, cancel=cancel)
    text = deck.decklist
    lists = [i for i in items if i.text and "list" in i.name.lower()] or \
        [i for i in items if i.text]
    if lists and not text:
        try:
            text = fetch(lists[0], http).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - counts of 1 instead
            text = ""
    return items, text


def fetch(item: gdrive.Item, http=None) -> bytes:
    """A picture's (or text file's) bytes at full size."""
    if item.kind in ("file", "zip"):
        return local.read(item)
    return gdrive.download(item.id, http=http)


# ------------------------------------------------------------------ cards from file names
def clean(text: str) -> str:
    """Without the invisible characters some file names carry."""
    text = unicodedata.normalize("NFKC", text or "")
    return "".join(ch for ch in text if unicodedata.category(ch) not in ("Cf", "Cc")).strip()


@dataclass
class NameInfo:
    name: str
    side: int = 0                  # 1: a back face ("… - Back")
    variant: int = 0               # "Command Tower 2": another picture of the same card
    extra: bool = False            # "Extra - Badlands"


def name_info(file_name: str) -> NameInfo:
    """What a picture's file name says: "001 - Sol Ring (Retro).png" is Sol
    Ring; "Anzrag, the Quake-Mole (Diablos, Tyrant of the Desert) (1).png" is
    Anzrag; "Delver of Secrets - Back.png" a back face; "Forest 2.png" another
    Forest picture; "Extra - Badlands.png" an extra."""
    stem = clean(Path(file_name).stem).replace("_", " ").strip()
    extra = bool(EXTRA_NAME.match(stem))
    stem = EXTRA_NAME.sub("", stem)
    stem = re.sub(r"^\d{1,3}[\s.\-–)]+", "", stem)                 # 001 - …
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)                      # … (1) (a copy)
    side = 0
    if BACK_WORDS.search(stem) and not CARD_BACK.match(stem):
        side = 1
        stem = BACK_WORDS.sub("", stem)
    stem = re.sub(r"\s*[(\[][^)\]]*[)\]]\s*$", "", stem).strip(" -–")  # (Retro) [Artist]
    stem = re.sub(r"\s+(front|face)$", "", stem, flags=re.I).strip()
    variant = 0
    m = VARIANT.search(stem)
    if m and len(stem) > 3:
        variant, stem = int(m.group(0)), stem[:m.start()]
    return NameInfo(re.sub(r"\s{2,}", " ", stem).strip(), side, variant, extra)


def card_name(file_name: str) -> tuple[str, int]:
    info = name_info(file_name)
    return info.name, info.side


def is_card_back(file_name: str, path: str = "") -> bool:
    stem = clean(Path(file_name).stem).replace("_", " ").strip()
    return bool(CARD_BACK.match(stem)) or any(BACK_DIR.match(p) for p in path.split("/") if p)


@dataclass
class Card:
    name: str
    front: Optional[gdrive.Item] = None
    back: Optional[gdrive.Item] = None
    count: int = 1
    section: str = "main"
    extra: bool = False            # a token, an extra, or not on the deck's own list
    variants: list = field(default_factory=list)   # other pictures of the same card
    category: str = ""             # its folder: Creature, Land…
    deck: str = ""                 # the deck it's from (its id)

    @property
    def token(self) -> bool:
        return bool(TOKEN.search(self.name)) or \
            any(re.match(r"^tokens?$", p, re.I) for p in (self.front.path if self.front else "")
                .split("/") if p)

    @property
    def key(self) -> str:
        return (self.deck + "|" if self.deck else "") + (self.front.id if self.front else self.name)


def cards_in(items: list, decklist_text: str = "", deck_id: str = "") -> tuple[list[Card], list]:
    """The deck's cards (front and back pictures, other pictures of the same
    card) and its card backs. With the deck's own decklist, its counts and
    commander are used; tokens, extras and cards that aren't on it are marked
    ``extra`` (added only when you pick them)."""
    by_name: dict[str, Card] = {}
    backs = []
    ordered = sorted((it for it in items if it.picture),
                     key=lambda it: (name_info(it.name).variant, it.name.lower()))
    for it in ordered:
        if is_card_back(it.name, it.path):
            backs.append(it)
            continue
        info = name_info(it.name)
        if not info.name:
            continue
        dirs = [p for p in it.path.split("/") if p]
        c = by_name.get(info.name.lower())
        if c is None:
            c = by_name[info.name.lower()] = Card(info.name, deck=deck_id,
                                                  category=dirs[-1] if dirs else "")
        if info.extra or any(EXTRA_DIR.match(p) for p in dirs):
            c.extra = True
        if info.side:
            if c.back is None:
                c.back = it
        elif c.front is None:
            c.front = it
        else:
            c.variants.append(it)
    cards = [c for c in by_name.values() if c.front is not None or c.back is not None]
    if decklist_text:
        from mse_studio.core import decklists as dl
        listed = {clean(e.name).lower(): e for e in dl.parse_text(decklist_text)}
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
    return sorted(cards, key=lambda c: (c.extra, c.section != "commander", c.name.lower())), backs


def pair_faces(cards: list[Card], entries: list, pool: Optional[list] = None
               ) -> tuple[list[Card], list]:
    """After the cards are looked up: "Terra, Magical Adept" and "Esper Terra"
    are the two faces of one card, so the second picture is printed on the
    first one's back (and isn't a card of its own). The back's picture may be
    any card of the deck (``pool``), ticked or not."""
    pool = list(pool or []) + list(cards)
    pictures = {}
    for c in pool:
        pictures.setdefault(c.name.lower(), c.front)
    where = {c.name.lower(): i for i, c in enumerate(cards)}
    drop: set = set()
    for i, (c, e) in enumerate(zip(cards, entries)):
        faces = (getattr(e, "card", None) or {}).get("faces") or []
        if i in drop or c.back is not None or len(faces) < 2:
            continue
        if clean(str(faces[0].get("name", ""))).lower() != c.name.lower():
            continue
        back = clean(str(faces[1].get("name", ""))).lower()
        if back not in pictures or back == c.name.lower():
            continue
        c.back = pictures[back]
        j = where.get(back)
        if j is not None and j != i:
            drop.add(j)
    keep = [k for k in range(len(cards)) if k not in drop]
    return [cards[k] for k in keep], [entries[k] for k in keep]


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
    text: str = ""

    @property
    def price(self) -> str:
        return "free" if self.drive else "paid"


def links_in(text: str) -> tuple[list[str], list[str]]:
    """Google Drive folder links and Ko-fi links in a post."""
    text = html.unescape(text or "")
    drive = list(dict.fromkeys(u.rstrip(".,") for u in DRIVE.findall(text)
                               if gdrive.folder_id(u)))
    kofi = list(dict.fromkeys(u.rstrip(".,") for u in KOFI.findall(text)))
    return drive, kofi


def _get(url: str, http=None, ua: str = "") -> bytes:
    if http is not None:
        return http(url)
    req = urllib.request.Request(url, headers={"User-Agent": ua or gdrive.UA,
                                               "Accept": "application/json, text/html, */*"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _reddit(paths: list[str], http=None) -> tuple[str, bytes]:
    """The first of Reddit's addresses that answers: (format, body)."""
    last: Exception | None = None
    for path in paths:
        for host in REDDIT_HOSTS:
            try:
                return ("rss" if ".rss" in path.split("?")[0] else "json"), \
                    _get(host + path, http, REDDIT_UA)
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 404:
                    break
            except Exception as e:  # noqa: BLE001 - try the next address
                last = e
    blocked = isinstance(last, urllib.error.HTTPError) and last.code in (403, 429)
    raise RuntimeError(
        ("Reddit blocked MSE Studio's search for now (it does that to apps sometimes). "
         if blocked else f"Reddit didn't answer ({last}). ") +
        "Search in your browser instead – Search in my browser – and paste a post's link "
        "(or the whole post) into Add a link.")


def _atom(body: bytes) -> list[dict]:
    """Entries of a Reddit RSS (Atom) feed: title, author, link, html."""
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(body)
    out = []
    for e in root.findall("a:entry", ns):
        link = e.find("a:link", ns)
        out.append({"title": (e.findtext("a:title", "", ns) or "").strip(),
                    "author": (e.findtext("a:author/a:name", "", ns) or "").replace("/u/", ""),
                    "link": link.get("href", "") if link is not None else "",
                    "html": e.findtext("a:content", "", ns) or "",
                    "updated": e.findtext("a:updated", "", ns) or ""})
    return out


def _post_from_json(d: dict, extra_text: str = "") -> Post:
    text = " ".join(str(d.get(k) or "") for k in ("url", "selftext")) + " " + extra_text
    drive, kofi = links_in(text)
    return Post(d.get("title", ""), d.get("author", ""),
                "https://www.reddit.com" + d.get("permalink", ""), drive, kofi,
                d.get("link_flair_text") or "", float(d.get("created_utc") or 0),
                str(d.get("selftext") or ""))


def search_reddit(query: str = "EDH deck", sort: str = "relevance",
                  http: Optional[Callable] = None) -> list[Post]:
    """Posts on r/mpcproxies (Reddit's public search), with the Drive and
    Ko-fi links found in them."""
    q = urllib.parse.quote(query)
    fmt, body = _reddit([REDDIT_SEARCH.format(fmt="json", q=q, sort=sort),
                         REDDIT_SEARCH.format(fmt="rss", q=q, sort=sort)], http)
    if fmt == "rss":
        out = []
        for e in _atom(body):
            drive, kofi = links_in(e["html"])
            out.append(Post(html.unescape(e["title"]), e["author"], e["link"], drive, kofi,
                            text=re.sub(r"<[^>]+>", " ", html.unescape(e["html"]))))
        return out
    data = json.loads(body.decode("utf-8"))
    return [_post_from_json(child.get("data") or {})
            for child in (data.get("data") or {}).get("children") or []]


def search_in_browser(query: str, sort: str = "relevance") -> str:
    return REDDIT_BROWSER.format(q=urllib.parse.quote(query), sort=sort)


def reddit_post(link: str, http=None) -> Post:
    """One post: its title, maker, text, and the links in it and in the
    maker's own comments (where Drive links often are)."""
    m = re.search(r"reddit\.com(/r/\w+/comments/\w+)", link)
    if not m:
        raise ValueError("That isn't a Reddit post link.")
    fmt, body = _reddit([m.group(1) + "/.json", m.group(1) + "/.rss"], http)
    if fmt == "rss":
        entries = _atom(body)
        if not entries:
            raise ValueError("Reddit didn't show that post.")
        first = entries[0]
        by_maker = " ".join(e["html"] for e in entries if e["author"] == first["author"])
        drive, kofi = links_in(by_maker)
        return Post(html.unescape(first["title"]), first["author"], link, drive, kofi,
                    text=re.sub(r"<[^>]+>", "\n", html.unescape(first["html"])))
    data = json.loads(body.decode("utf-8"))
    post = data[0]["data"]["children"][0]["data"]
    comments = data[1]["data"]["children"] if len(data) > 1 else []
    own = " ".join(str((c.get("data") or {}).get("body") or "") for c in comments
                   if (c.get("data") or {}).get("author") == post.get("author"))
    return _post_from_json(post, own)


def deck_from_post(post: Post) -> Deck:
    return Deck(re.sub(r"[^a-z0-9]+", "-", post.title.lower()).strip("-")[:60] or "post",
                post.title, f"u/{post.author}" if post.author else "",
                f"https://www.reddit.com/user/{post.author}" if post.author else "",
                post.kofi[0] if post.kofi else "", post.link,
                gdrive.folder_id(post.drive[0]) if post.drive else "", post.price, mine=True,
                decklist=decklist_in(post.text))


# ------------------------------------------------------------------ adding a deck from a link
def decklist_in(text: str) -> str:
    """The decklist in a post ("1 Sol Ring" lines), or "" when there isn't one."""
    keep, n = [], 0
    for line in html.unescape(text or "").splitlines():
        s = clean(re.sub(r"^[\s*•>-]+", "", line))
        if re.match(r"^(?:SB:\s*)?\d{1,2}\s*x?\s+[A-Za-z\"'].{1,140}$", s):
            keep.append(s)
            n += 1
        elif re.match(r"^(?:commanders?|deck|main ?deck|sideboard|tokens|companion)\s*:?$", s, re.I):
            keep.append(s.rstrip(":"))
    return "\n".join(keep) if n >= 8 else ""


def kofi_page(link: str, http=None) -> dict:
    """What a Ko-fi page says: its title, maker, whether it costs money, and
    a Google Drive link if the page shows one."""
    page = _get(link, http).decode("utf-8", errors="replace")

    def meta(prop: str) -> str:
        m = re.search(r'<meta[^>]+(?:property|name)=["\']' + prop + r'["\'][^>]*content=["\']([^"\']*)',
                      page, re.I) or \
            re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']' + prop,
                      page, re.I)
        return html.unescape(m.group(1)).strip() if m else ""
    title = meta("og:title") or (re.search(r"<title>(.*?)</title>", page, re.S | re.I) or [""])[0]
    title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
    maker = ""
    m = re.search(r"\s[-–|]\s*(.+?)'s Ko-fi(?: Shop)?\s*$", title) or \
        re.search(r"\bby\s+(.+?)\s*$", title)
    if m:
        maker, title = m.group(1).strip(), title[:m.start()].strip()
    shop = re.search(r"ko-fi\.com/(?!s/)([\w-]+)", page)
    desc = meta("og:description") or meta("description")
    drive, _k = links_in(desc + " " + page)
    amount = re.search(r"(?:£|\$|€|US\$)\s?(\d+(?:[.,]\d{2})?)", desc + " " + page)
    free = re.search(r"\b(?:free|pay what you want|\$0(?:\.00)?|£0(?:\.00)?)\b", desc, re.I)
    paid = bool(amount and float(amount.group(1).replace(",", ".")) > 0) and not free
    return {"title": title, "creator": maker, "creator_link":
            f"https://ko-fi.com/{shop.group(1)}" if shop else "",
            "notes": desc[:300], "drive": drive, "price": "paid" if paid else "free"}


def describe(text: str, http=None, progress=None, online: bool = True) -> Deck:
    """A deck from what you paste: a Google Drive folder link, a Reddit post,
    a Ko-fi page – or a whole post copied from Reddit or Discord (its links
    and decklist are found in it). With ``online``, asks each site for the
    title and the maker; what it can't find stays blank for you to fill in."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Paste a link, or a whole post with its links.")
    drive, kofi = links_in(text)
    reddit = REDDIT_POST.findall(text)
    deck = Deck("", "", page=kofi[0] if kofi else "", reddit=reddit[0] if reddit else "",
                drive=gdrive.folder_id(drive[0]) if drive else gdrive.folder_id(text),
                decklist=decklist_in(text), mine=True)
    one_link = "\n" not in text and " " not in text
    if not one_link:
        first = next((clean(line) for line in text.splitlines()
                      if clean(line) and not re.search(r"https?://", line)), "")
        if 3 <= len(first) <= 120:
            deck.title = first
    notes = []
    if reddit and one_link and online:
        if progress:
            progress("Reading the Reddit post…")
        try:
            post = reddit_post(reddit[0], http)
            deck.title = deck.title or post.title
            deck.creator = f"u/{post.author}" if post.author else ""
            deck.creator_link = f"https://www.reddit.com/user/{post.author}" if post.author else ""
            deck.drive = deck.drive or (gdrive.folder_id(post.drive[0]) if post.drive else "")
            deck.page = deck.page or (post.kofi[0] if post.kofi else "")
            deck.decklist = deck.decklist or decklist_in(post.text)
        except Exception as e:  # noqa: BLE001 - filled in by hand instead
            notes.append(f"Reddit: {e}")
    if deck.page and (one_link or not deck.drive) and online:
        if progress:
            progress("Reading the Ko-fi page…")
        try:
            k = kofi_page(deck.page, http)
            deck.title = deck.title or k["title"]
            deck.creator = deck.creator or k["creator"]
            deck.creator_link = deck.creator_link or k["creator_link"]
            deck.drive = deck.drive or (gdrive.folder_id(k["drive"][0]) if k["drive"] else "")
            deck.notes = k["notes"]
            if not deck.drive:
                deck.price = k["price"]
        except Exception as e:  # noqa: BLE001
            notes.append(f"Ko-fi: {e}")
    if deck.drive and not deck.title and online:
        if progress:
            progress("Reading the Google Drive folder…")
        try:
            deck.title = gdrive.read_folder(deck.drive, http)[0]
        except Exception as e:  # noqa: BLE001
            notes.append(f"Google Drive: {e}")
    if not deck.drive and not deck.page:
        raise ValueError("No Google Drive folder or Ko-fi link in that. Paste a Google Drive "
                         "folder link, a Reddit post, a Ko-fi page, or a whole post with links.")
    if not deck.drive:
        deck.price = deck.price if deck.page else "free"
        if deck.price == "free" and deck.page:
            deck.notes = (deck.notes + " " if deck.notes else "") + \
                "Download it on Ko-fi, then add the Google Drive link you get."
    deck.title = deck.title or "My proxy deck"
    deck.id = re.sub(r"[^a-z0-9]+", "-", deck.title.lower()).strip("-")[:60] or \
        f"deck-{int(time.time())}"
    if notes and not deck.notes:
        deck.notes = "Couldn't read everything: " + "; ".join(n.splitlines()[0][:120] for n in notes)
    return deck


def deck_from_link(link: str, title: str = "", creator: str = "", page: str = "",
                   price: str = "free") -> Deck:
    """A deck you add by hand: a Google Drive folder link (and where it's from)."""
    fid = gdrive.folder_id(link)
    if not fid and not KOFI.match(link or ""):
        raise ValueError("Paste a Google Drive folder link (or a Ko-fi page link).")
    if not fid:
        page, price = page or link.strip(), "paid"
    did = re.sub(r"[^a-z0-9]+", "-", (title or fid or page).lower()).strip("-")[:60] or \
        f"deck-{int(time.time())}"
    return Deck(did, title or "My proxy deck", creator, "", page,
                link.strip() if "reddit.com" in link else "", fid, price, mine=True)
