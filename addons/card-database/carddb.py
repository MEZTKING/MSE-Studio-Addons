"""The card database: Scryfall's bulk data (every Magic card) in a small
SQLite file on your PC, so cards can be searched, picked at random and looked
up without asking Scryfall card by card.

Bulk files are big (the Oracle cards file is about 160 MB, all printings
about 500 MB) – they're read a piece at a time, never all at once."""
from __future__ import annotations

import gzip
import io
import json
import random
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional

from mse_studio.core import decklists as dl
from mse_studio.core import addons

BULK_API = "https://api.scryfall.com/bulk-data"
BULK_TYPES = {"oracle_cards": "Oracle cards – one per card (about 160 MB)",
              "default_cards": "Default cards – every printing, English (about 500 MB)"}
COLORS = "WUBRG"
SKIP_LAYOUTS = {"art_series", "vanguard", "scheme", "planar", "double_faced_token"}
SKIP_SET_TYPES = {"memorabilia", "minigame", "alchemy", "treasure_chest"}
ODD_SETS = ("funny", "memorabilia", "token", "promo")   # picked last for a name

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id TEXT PRIMARY KEY, oracle_id TEXT, name TEXT, lname TEXT, mana_cost TEXT,
    cmc REAL, type_line TEXT, ltype TEXT, oracle_text TEXT, ltext TEXT,
    colors TEXT, identity TEXT, power TEXT, toughness TEXT, loyalty TEXT,
    rarity TEXT, set_code TEXT, set_name TEXT, set_type TEXT, number TEXT,
    released TEXT, layout TEXT, commander_legal INTEGER, can_lead INTEGER,
    edhrec INTEGER, usd REAL, usd_foil REAL, eur REAL, eur_foil REAL, tix REAL,
    tcgplayer TEXT, cardmarket TEXT, artist TEXT, image TEXT, card_json TEXT);
CREATE INDEX IF NOT EXISTS cards_lname ON cards(lname);
CREATE INDEX IF NOT EXISTS cards_oracle ON cards(oracle_id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class CardDbError(RuntimeError):
    pass


def db_path() -> Path:
    """Where the database is kept (outside the add-on, so updates keep it).
    The Card prices add-on reads it from here too."""
    return addons.data_dir("card-database") / "cards.sqlite"


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    p = Path(path or db_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def exists(path: Optional[Path] = None) -> bool:
    p = Path(path or db_path())
    return p.is_file() and p.stat().st_size > 0


def info(conn: sqlite3.Connection) -> dict:
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    meta["count"] = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    meta["names"] = conn.execute("SELECT COUNT(DISTINCT lname) FROM cards").fetchone()[0]
    return meta


# ------------------------------------------------------------------ reading a bulk file
def _is_gzip(path: Path) -> bool:
    with open(path, "rb") as f:
        return f.read(2) == b"\x1f\x8b"


def iter_bulk(path: Path, progress: Optional[Callable[[float], None]] = None,
              chunk: int = 1 << 20) -> Iterator[dict]:
    """The cards of a Scryfall bulk file one by one, reading a piece at a
    time: a JSON list (.json) or one card per line (.jsonl), compressed (.gz)
    or not. ``progress(fraction)`` now and then."""
    path = Path(path)
    size = max(1, path.stat().st_size)
    dec = json.JSONDecoder()
    zipped = _is_gzip(path)
    read = 0
    with (gzip.open(path, "rb") if zipped else open(path, "rb")) as raw:
        f = io.TextIOWrapper(raw, encoding="utf-8-sig")
        buf, pos, started = "", 0, False
        while True:
            text = f.read(chunk)
            read = raw.fileobj.tell() if zipped else raw.tell()
            buf = buf[pos:] + text
            pos = 0
            if progress:
                progress(min(1.0, read / size))
            if not started:
                first = buf.lstrip()[:1]
                if not first:
                    if not text:
                        raise CardDbError("That isn't a Scryfall bulk file (no cards in it).")
                    continue
                if first == "[":               # a JSON list
                    pos, started = buf.find("[") + 1, True
                elif first == "{":             # one card per line (.jsonl)
                    pos, started = buf.find("{"), True
                else:
                    raise CardDbError("That isn't a Scryfall bulk file (no list of cards).")
            while True:
                while pos < len(buf) and buf[pos] in " \r\n\t,":
                    pos += 1
                if pos < len(buf) and buf[pos] == "]":
                    return
                if pos >= len(buf):
                    break
                try:
                    obj, end = dec.raw_decode(buf, pos)
                except json.JSONDecodeError:
                    if not text:
                        raise CardDbError("The bulk file ends in the middle of a card – "
                                          "download it again.") from None
                    break                      # the rest of this card is in the next piece
                pos = end
                if isinstance(obj, dict):
                    yield obj
            if not text:
                return


def _price(prices: dict, key: str) -> Optional[float]:
    try:
        v = prices.get(key)
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _can_lead(card: dict) -> bool:
    tl = card.get("type_line", "").split(" // ")[0].lower()
    text = card.get("oracle_text") or " ".join(f.get("oracle_text", "")
                                               for f in card.get("card_faces") or [])
    return ("legendary" in tl and "creature" in tl) or "can be your commander" in text.lower()


def _row(card: dict) -> Optional[tuple]:
    if card.get("object") not in (None, "card"):
        return None
    if card.get("lang") not in (None, "en"):        # All cards: other languages' printings
        return None
    if card.get("layout") in SKIP_LAYOUTS or card.get("set_type") in SKIP_SET_TYPES:
        return None
    games = card.get("games")
    if games is not None and "paper" not in games:
        return None
    faces = card.get("card_faces") or []
    text = card.get("oracle_text") or "\n//\n".join(f.get("oracle_text", "") for f in faces)
    cost = card.get("mana_cost") or " // ".join(f.get("mana_cost", "") for f in faces
                                                if f.get("mana_cost"))
    front = faces[0] if faces else {}
    prices = card.get("prices") or {}
    buy = card.get("purchase_uris") or {}
    trimmed = dl.card_from_scryfall(card)
    name = card.get("name", "")
    return (card.get("id"), card.get("oracle_id") or front.get("oracle_id"), name, name.lower(),
            cost, float(card.get("cmc") or 0), card.get("type_line", ""),
            card.get("type_line", "").lower(), text, text.lower(),
            "".join(c for c in COLORS if c in (card.get("colors") or front.get("colors") or [])),
            "".join(c for c in COLORS if c in (card.get("color_identity") or [])),
            card.get("power") or front.get("power", ""),
            card.get("toughness") or front.get("toughness", ""),
            card.get("loyalty") or front.get("loyalty", ""), card.get("rarity", ""),
            card.get("set", ""), card.get("set_name", ""), card.get("set_type", ""),
            card.get("collector_number", ""), card.get("released_at", ""),
            card.get("layout", ""),
            1 if (card.get("legalities") or {}).get("commander") == "legal" else 0,
            1 if _can_lead(card) else 0, card.get("edhrec_rank"),
            _price(prices, "usd"), _price(prices, "usd_foil"), _price(prices, "eur"),
            _price(prices, "eur_foil"), _price(prices, "tix"),
            buy.get("tcgplayer", ""), buy.get("cardmarket", ""), card.get("artist", ""),
            trimmed.get("image", ""), json.dumps(trimmed, ensure_ascii=False))


def import_bulk(path: Path, progress: Optional[Callable[[int, int, str], None]] = None,
                cancel=None, db: Optional[Path] = None, kind: str = "") -> int:
    """Read a Scryfall bulk file into the database (replacing what was
    there). Returns how many cards were added."""
    say = progress or (lambda d, t, m: None)
    target = Path(db or db_path())
    tmp = target.with_name(target.name + ".new")
    tmp.unlink(missing_ok=True)
    conn = connect(tmp)
    n, batch = 0, []
    sql = f"INSERT OR REPLACE INTO cards VALUES ({','.join('?' * 35)})"
    try:
        for card in iter_bulk(Path(path), lambda f: say(int(f * 1000), 1000,
                                                         f"Reading cards… {n:,}")):
            if cancel is not None and getattr(cancel, "cancelled", False):
                raise CardDbError("Stopped.")
            row = _row(card)
            if row is None or not row[0]:
                continue
            batch.append(row)
            n += 1
            if len(batch) >= 2000:
                conn.executemany(sql, batch)
                batch.clear()
        if batch:
            conn.executemany(sql, batch)
        if n == 0:
            raise CardDbError("No cards in that file – is it one of Scryfall's bulk files?")
        conn.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", [
            ("file", Path(path).name), ("kind", kind or _guess_kind(Path(path).name)),
            ("imported", time.strftime("%Y-%m-%d %H:%M"))])
        conn.commit()
    finally:
        conn.close()
    target.unlink(missing_ok=True)
    tmp.replace(target)
    return n


def _guess_kind(name: str) -> str:
    for k in ("oracle_cards", "default_cards", "all_cards", "unique_artwork"):
        if k.replace("_", "-") in name or k in name:
            return k
    return ""


FILE_URL = re.compile(r"\.(?:jsonl?|jsonl?\.gz|gz)(?:\?|$)", re.I)


def _file_urls(obj) -> list[str]:
    """Every address of a bulk file in Scryfall's answer, wherever it is
    (``download_uri``, or newer names for the .json / .jsonl files)."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v.startswith("http") and FILE_URL.search(v) and \
                    "api.scryfall.com" not in v:
                out.append(v)
            elif isinstance(v, (dict, list)):
                out += _file_urls(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _file_urls(v)
    return out


def bulk_downloads(http: Callable[[str], bytes]) -> dict[str, dict]:
    """Scryfall's bulk files: kind -> {url, size, updated}. The smallest
    form of each file is picked (compressed, one card per line)."""
    data = json.loads(http(BULK_API).decode("utf-8"))
    out = {}
    for b in data.get("data", []):
        if b.get("type") not in BULK_TYPES:
            continue
        urls = _file_urls(b)
        if not urls and b.get("uri"):           # ask for the file's own details
            try:
                urls = _file_urls(json.loads(http(b["uri"]).decode("utf-8")))
            except Exception:  # noqa: BLE001 - reported below as not listed
                urls = []
        urls.sort(key=lambda u: (not u.lower().split("?")[0].endswith(".gz"),
                                 ".jsonl" not in u.lower()))
        if urls:
            out[b["type"]] = {"url": urls[0], "size": b.get("size") or b.get(
                "compressed_size") or 0, "updated": b.get("updated_at", "")}
    return out


# ------------------------------------------------------------------ looking cards up
_BEST = (f"ORDER BY (set_type IN ({','.join(repr(s) for s in ODD_SETS)})), "
         "(image = ''), released DESC")


def best_printing(conn: sqlite3.Connection, name: str) -> Optional[sqlite3.Row]:
    """The usual printing of a card by name (front face names work too)."""
    lname = name.strip().lower()
    row = conn.execute(f"SELECT * FROM cards WHERE lname = ? {_BEST} LIMIT 1",
                       (lname,)).fetchone()
    if row is None:                  # a double-faced card by one face's name
        row = conn.execute(f"SELECT * FROM cards WHERE lname LIKE ? OR lname LIKE ? "
                           f"{_BEST} LIMIT 1", (lname + " // %", "% // " + lname)).fetchone()
    return row


def printing(conn: sqlite3.Connection, set_code: str, number: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM cards WHERE set_code = ? AND number = ? LIMIT 1",
                        (set_code.lower(), number)).fetchone()


def card_of(row) -> dict:
    return json.loads(row["card_json"])


def entry_of(row, count: int = 1, section: str = "main") -> dl.Entry:
    card = card_of(row)
    return dl.Entry(name=row["name"], count=count, section=section, card=card,
                    scryfall_id=row["id"])


def look_up(entries: list, path: Optional[Path] = None) -> None:
    """For Decklists: fill in the cards the database knows (registered with
    MSE Studio as a local card source)."""
    if not exists(path):
        return
    conn = connect(path)
    try:
        for e in entries:
            if e.found:
                continue
            row = None
            if e.scryfall_id:
                row = conn.execute("SELECT * FROM cards WHERE id = ?", (e.scryfall_id,)).fetchone()
            if row is None and e.set and e.number:
                row = printing(conn, e.set, e.number)
            if row is None:
                row = best_printing(conn, e.name)
            if row is not None:
                e.card = card_of(row)
                e.scryfall_id = e.scryfall_id or row["id"]
    finally:
        conn.close()


# ------------------------------------------------------------------ searching
@dataclass
class Filters:
    text: str = ""                  # name, rules text or type contains (all words)
    colors: str = ""                # e.g. "BG"
    color_rule: str = "within"      # within (identity ⊆ colours) | exactly | including
    types: str = ""                 # creature, instant, … ("" = any)
    mv_min: Optional[float] = None
    mv_max: Optional[float] = None
    rarity: str = ""
    commander_legal: bool = True
    can_lead: bool = False          # only cards that can be a commander
    max_usd: Optional[float] = None


def _where(f: Filters) -> tuple[str, list]:
    where, args = ["1=1"], []
    for word in f.text.lower().split():
        where.append("(lname LIKE ? OR ltext LIKE ? OR ltype LIKE ?)")
        args += [f"%{word}%"] * 3
    cols = "".join(c for c in COLORS if c in f.colors.upper())
    colorless = "C" in f.colors.upper()
    if cols or colorless:
        if f.color_rule == "exactly":
            where.append("identity = ?")
            args.append(cols)
        elif f.color_rule == "including":
            for c in cols:
                where.append("identity LIKE ?")
                args.append(f"%{c}%")
        else:                        # within the colours (a commander's identity)
            for c in COLORS:
                if c not in cols:
                    where.append("identity NOT LIKE ?")
                    args.append(f"%{c}%")
    if f.types:
        where.append("ltype LIKE ?")
        args.append(f"%{f.types.lower()}%")
    if f.mv_min is not None:
        where.append("cmc >= ?")
        args.append(f.mv_min)
    if f.mv_max is not None:
        where.append("cmc <= ?")
        args.append(f.mv_max)
    if f.rarity:
        where.append("rarity = ?")
        args.append(f.rarity)
    if f.commander_legal:
        where.append("commander_legal = 1")
    if f.can_lead:
        where.append("can_lead = 1")
    if f.max_usd is not None:
        where.append("(usd IS NULL OR usd <= ?)")
        args.append(f.max_usd)
    return " AND ".join(where), args


SORTS = {"name": "Name", "mv": "Mana value", "popular": "Most played (EDHREC)",
         "cheap": "Cheapest", "new": "Newest"}
_SORT_KEYS = {"name": lambda r: r["lname"],
              "mv": lambda r: (r["cmc"], r["lname"]),
              "popular": lambda r: (r["edhrec"] if r["edhrec"] is not None else 10 ** 9,
                                    r["lname"]),
              "cheap": lambda r: (_cheapest(r), r["lname"])}


def search(conn: sqlite3.Connection, f: Filters, sort: str = "name", limit: int = 200,
           randomly: bool = False) -> list[sqlite3.Row]:
    """Cards matching the filters, one per name (its usual printing)."""
    where, args = _where(f)
    rows = conn.execute(f"SELECT * FROM cards WHERE {where} {_BEST}", args).fetchall()
    seen, out = set(), []
    for r in rows:
        if r["lname"] not in seen:
            seen.add(r["lname"])
            out.append(r)
    if randomly:
        random.shuffle(out)
    elif sort == "new":                      # newest first, A–Z within a date
        out.sort(key=_SORT_KEYS["name"])
        out.sort(key=lambda r: r["released"] or "", reverse=True)
    else:
        out.sort(key=_SORT_KEYS.get(sort, _SORT_KEYS["name"]))
    return out[:limit]


def _cheapest(r) -> float:
    vals = [v for v in (r["usd"], r["eur"]) if v is not None]
    return min(vals) if vals else 10 ** 9


# ------------------------------------------------------------------ building a deck
DEFAULT_COUNTS = {"lands": 36, "ramp": 10, "draw": 10, "removal": 8, "wipe": 3,
                  "protection": 3}
_THEME_STOP = set("""a an the of to and or your you this that it its with for from
each any target card cards creature creatures control controls whenever when
put put onto into on at as be is are if then may can until end turn player
players opponent opponents battlefield graveyard hand library one two three
gets get gain gains has have up down beginning step""".split())


@dataclass
class Style:
    """A way to play: how many of each kind of card, how many creatures, the
    mana curve, and what it likes."""
    label: str
    tip: str
    counts: dict
    creatures: float = 0.6            # share of the deck's other spells that are creatures
    max_mv: float = 0                 # cards above this cost count less (0: no limit)
    roles: dict = field(default_factory=dict)     # role → bonus
    words: tuple = ()                 # words on cards it likes


STYLES = {
    "balanced": Style("Balanced (midrange)", "A bit of everything: the usual numbers",
                      dict(DEFAULT_COUNTS)),
    "aggressive": Style("Aggressive", "Cheap creatures that attack early – haste, combat, few "
                        "wipes", {"lands": 33, "ramp": 8, "draw": 8, "removal": 6, "wipe": 0,
                                  "protection": 4},
                        0.75, 3.5, {"evasion": 0.3, "anthem": 0.4, "trick": 0.2, "burn": 0.2},
                        ("haste", "attacks", "attack", "combat", "double", "menace", "trample",
                         "first", "strike")),
    "defensive": Style("Defensive (control)", "Answer everything, win late: removal, wipes, "
                       "counterspells, life gain", {"lands": 37, "ramp": 10, "draw": 12,
                                                    "removal": 12, "wipe": 5, "protection": 3},
                       0.35, 0, {"counter": 0.5, "lifegain": 0.25, "lock": 0.2,
                                 "graveyardhate": 0.2},
                       ("defender", "counter", "prevent", "tap", "lifelink", "can't")),
    "ramp": Style("Ramp (big spells)", "Lots of mana early for huge threats later",
                  {"lands": 38, "ramp": 16, "draw": 9, "removal": 7, "wipe": 2, "protection": 2},
                  0.55, 0, {"landsearch": 0.4, "finisher": 0.4},
                  ("trample", "x", "landfall")),
    "go-wide": Style("Go wide (tokens)", "Many small creatures and tokens, then pump them all",
                     {"lands": 35, "ramp": 9, "draw": 10, "removal": 6, "wipe": 1,
                      "protection": 4},
                     0.5, 4.5, {"tokens": 0.6, "anthem": 0.6, "sacrifice": 0.2},
                     ("token", "tokens", "populate", "convoke")),
    "voltron": Style("Voltron (one big threat)", "Make one creature (often the commander) huge "
                     "and hard to stop", {"lands": 36, "ramp": 10, "draw": 8, "removal": 6,
                                          "wipe": 1, "protection": 9},
                     0.3, 0, {"protection": 0.5, "evasion": 0.3},
                     ("equipment", "equipped", "aura", "enchanted", "attach", "hexproof",
                      "indestructible", "double", "shroud")),
    "spells": Style("Spells (spellslinger)", "Instants and sorceries – copy them, get paid for "
                    "casting them", {"lands": 35, "ramp": 10, "draw": 12, "removal": 9,
                                     "wipe": 3, "protection": 3},
                    0.25, 4.5, {"copy": 0.5, "counter": 0.2, "burn": 0.2},
                    ("instant", "sorcery", "cast", "copy", "prowess", "magecraft", "storm")),
    "combo": Style("Combo (find the pieces)", "Card draw and tutors to put a winning "
                   "combination together", {"lands": 34, "ramp": 12, "draw": 12, "removal": 6,
                                            "wipe": 2, "protection": 4},
                   0.4, 0, {"tutor": 0.7, "draw": 0.2}, ("search", "untap", "infinite")),
    "graveyard": Style("Graveyard (reanimator)", "Fill the graveyard and bring the best back",
                       {"lands": 36, "ramp": 8, "draw": 10, "removal": 8, "wipe": 3,
                        "protection": 3},
                       0.55, 0, {"recursion": 0.6, "mill": 0.4, "discard": 0.2},
                       ("graveyard", "return", "mill", "dies", "flashback", "escape")),
    "casual": Style("Casual (group fun)", "Friendly and splashy: group hug, big creatures, no "
                    "harsh locks", {"lands": 37, "ramp": 10, "draw": 10, "removal": 6, "wipe": 2,
                                    "protection": 3},
                    0.6, 0, {"finisher": 0.3, "lifegain": 0.2},
                    ("each", "players", "draw")),
}

POWER = {
    "casual": ("Casual – fun cards, nothing harsh", 0.5),
    "focused": ("Focused – good cards, some staples", 1.0),
    "high": ("High power – the strongest cards", 1.7),
}

# ready-made themes: (words on the cards, roles) – tribes match the type line too
THEMES = {
    "+1/+1 counters": ({"counter", "counters", "proliferate", "modified", "adapt", "evolve"},
                       {"counters"}),
    "Tokens (go wide)": ({"token", "tokens", "populate", "convoke"}, {"tokens", "anthem"}),
    "Sacrifice (aristocrats)": ({"sacrifice", "dies", "died", "blood"}, {"sacrifice"}),
    "Life gain": ({"lifelink", "life"}, {"lifegain"}),
    "Graveyard (reanimator)": ({"graveyard", "reanimate", "mill", "flashback", "escape"},
                               {"recursion", "mill"}),
    "Spells (spellslinger)": ({"instant", "sorcery", "prowess", "magecraft", "storm"}, {"copy"}),
    "Artifacts": ({"artifact", "artifacts", "treasure", "equipment", "construct", "thopter"},
                  set()),
    "Enchantments": ({"enchantment", "enchantments", "aura", "auras", "constellation", "saga"},
                     set()),
    "Equipment and auras (voltron)": ({"equipment", "equipped", "aura", "enchanted", "attach"},
                                      {"protection"}),
    "Landfall (lands)": ({"landfall", "land", "lands"}, {"landsearch"}),
    "Blink (flicker)": ({"exile", "return", "enters", "flicker"}, {"flicker"}),
    "Mill": ({"mill", "mills"}, {"mill"}),
    "Card draw (wheels)": ({"draw", "draws", "discard", "wheel"}, {"draw", "discard"}),
    "Treasure, Clues and Food": ({"treasure", "clue", "clues", "food", "blood"}, set()),
    "Poison (infect)": ({"infect", "poison", "toxic", "proliferate"}, {"poison"}),
    "Planeswalkers (superfriends)": ({"planeswalker", "planeswalkers", "loyalty"}, set()),
    "Burn (direct damage)": ({"damage"}, {"burn"}),
    "Steal their stuff": ({"control", "exchange", "steal"}, {"steal"}),
    "Copies and clones": ({"copy", "clone", "copies"}, {"copy"}),
    "Flyers": ({"flying"}, {"evasion"}),
    "Extra combats": ({"combat", "attack", "attacks", "additional"}, set()),
    "Group hug": ({"each", "players", "player"}, set()),
    "Vehicles": ({"vehicle", "vehicles", "crew"}, set()),
    "Discard": ({"discard", "discards"}, {"discard"}),
    "Dragons": ({"dragon", "dragons"}, set()),
    "Elves": ({"elf", "elves"}, set()),
    "Zombies": ({"zombie", "zombies"}, set()),
    "Goblins": ({"goblin", "goblins"}, set()),
    "Vampires": ({"vampire", "vampires"}, set()),
    "Angels": ({"angel", "angels"}, set()),
    "Merfolk": ({"merfolk"}, set()),
    "Wizards": ({"wizard", "wizards"}, set()),
    "Dinosaurs": ({"dinosaur", "dinosaurs"}, set()),
    "Knights": ({"knight", "knights"}, set()),
    "Spirits": ({"spirit", "spirits"}, set()),
    "Humans": ({"human", "humans"}, set()),
    "Cats": ({"cat", "cats"}, set()),
    "Pirates": ({"pirate", "pirates"}, set()),
    "Demons": ({"demon", "demons"}, set()),
    "Slivers": ({"sliver", "slivers"}, set()),
    "Warriors": ({"warrior", "warriors"}, set()),
    "Elementals": ({"elemental", "elementals"}, set()),
    "Faeries": ({"faerie", "faeries"}, set()),
    "Rats": ({"rat", "rats"}, set()),
}

# what "avoid" options leave out
EXTRA_TURN = re.compile(r"extra turn")
LAND_DESTRUCTION = re.compile(r"destroy all lands|each player sacrifices [^.]*lands|"
                              r"destroy each land")


@dataclass
class Pick:
    name: str
    why: str
    row: object = None
    count: int = 1


@dataclass
class BuiltDeck:
    commander: str
    identity: str
    picks: list = field(default_factory=list)       # [Pick]
    notes: list = field(default_factory=list)
    lead: object = None                              # the commander's row
    spares: dict = field(default_factory=dict)       # why → [rows] the next best picks

    @property
    def size(self) -> int:
        return 1 + sum(p.count for p in self.picks)

    def entries(self, picks: Optional[list] = None, commander: bool = True) -> list:
        out = []
        if commander:
            out.append(entry_of(self.lead, 1, "commander") if self.lead is not None else
                       dl.Entry(name=self.commander, section="commander"))
        for p in (self.picks if picks is None else picks):
            out.append(entry_of(p.row, p.count) if p.row is not None else
                       dl.Entry(name=p.name, count=p.count))
        return out

    def swap(self, pick: "Pick") -> Optional["Pick"]:
        """Another card for the same job (the next best one). Returns the new
        pick, or None when there's no other."""
        taken = {p.name.lower() for p in self.picks}
        for r in self.spares.get(pick.why, []):
            if r["lname"] not in taken:
                new = Pick(r["name"], pick.why, r)
                self.picks[self.picks.index(pick)] = new
                self.spares[pick.why] = [x for x in self.spares[pick.why] if x is not r] + \
                    ([pick.row] if pick.row is not None else [])
                return new
        return None


def theme_words(text: str) -> set[str]:
    words = set(re.findall(r"[a-z][a-z+/-]{2,}", (text or "").lower()))
    return {w for w in words if w not in _THEME_STOP}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z'+/-]*", (text or "").lower()))


def build_deck(conn: sqlite3.Connection, commander: str, counts: Optional[dict] = None,
               theme: str = "", seed: Optional[int] = None,
               max_usd: Optional[float] = None, style: str = "balanced",
               power: str = "focused", themes: Optional[list] = None,
               avoid: Optional[set] = None) -> BuiltDeck:
    """A Commander deck around ``commander``: lands (staples and basics),
    ramp, card draw, removal, wipes and protection in the numbers asked for,
    then the cards that fit the commander, the play ``style`` and the
    ``themes`` best. Only cards in its colours and legal in Commander; one
    of each (but basics). ``avoid``: "extra turns", "land destruction",
    "tutors", "stax"."""
    from mse_studio.core import mana_base as mb
    from mse_studio.core import roles
    lead = best_printing(conn, commander)
    if lead is None:
        raise CardDbError(f"{commander} isn't in the card database.")
    st = STYLES.get(style) or STYLES["balanced"]
    counts = {**DEFAULT_COUNTS, **st.counts, **(counts or {})}
    pop_weight = POWER.get(power, POWER["focused"])[1]
    avoid = set(avoid or ())
    if power == "casual":
        avoid |= {"extra turns", "land destruction", "stax"}
    identity = lead["identity"]
    rng = random.Random(seed)
    deck = BuiltDeck(lead["name"], identity, lead=lead)
    themes_words = theme_words(lead["oracle_text"]) | \
        theme_words(lead["type_line"].split("—")[-1]) | theme_words(theme)
    theme_roles: set = set()
    for t in themes or ():
        words, rls = THEMES.get(t, (set(), set()))
        themes_words |= set(words)
        theme_roles |= set(rls)
    style_words = set(st.words)
    pool = search(conn, Filters(colors=identity or "C", color_rule="within",
                                commander_legal=True, max_usd=max_usd), limit=10 ** 6)
    pool = [r for r in pool if r["lname"] != lead["lname"] and r["layout"] not in ("token",)
            and "basic land" not in r["ltype"]]
    roles_of = {r["lname"]: roles.detect(r["ltext"]) for r in pool}

    def avoided(r) -> bool:
        t = r["ltext"]
        return (("extra turns" in avoid and EXTRA_TURN.search(t) is not None) or
                ("land destruction" in avoid and LAND_DESTRUCTION.search(t) is not None) or
                ("tutors" in avoid and "tutor" in roles_of[r["lname"]]) or
                ("stax" in avoid and "lock" in roles_of[r["lname"]]))
    pool = [r for r in pool if not avoided(r)]
    by_name = {r["lname"]: r for r in pool}
    taken: set[str] = set()

    def score(r) -> float:
        rank = r["edhrec"] if r["edhrec"] is not None else 30000
        pop = pop_weight / (1.0 + rank / 2000.0)
        words = _words(r["oracle_text"] + " " + r["type_line"])
        rl = roles_of.get(r["lname"], [])
        s = pop + 0.35 * len(themes_words & words) + 0.45 * len(theme_roles & set(rl))
        s += sum(st.roles.get(x, 0) for x in rl) + 0.2 * len(style_words & words)
        if st.max_mv and (r["cmc"] or 0) > st.max_mv:
            s -= 0.35 * ((r["cmc"] or 0) - st.max_mv)
        return s + rng.random() * 0.15

    def take(rows, n: int, why: str):
        ranked = sorted(rows, key=score, reverse=True)
        for r in ranked:
            if n <= 0:
                break
            if r["lname"] in taken:
                continue
            taken.add(r["lname"])
            deck.picks.append(Pick(r["name"], why, r))
            n -= 1
        spare = deck.spares.setdefault(why, [])
        spare += [r for r in ranked if r["lname"] not in taken][:15]

    nonland = [r for r in pool if "land" not in r["ltype"].split("//")[0]]
    # ramp: the usual mana rocks first
    staples = {s.name.lower(): s for s in mb.staples(identity)}
    rocks = [by_name[n] for n, s in staples.items() if n in by_name and s.group == "Mana rocks"]
    take(rocks[:4], min(4, counts["ramp"]), "Ramp (a staple)")
    have = sum(1 for p in deck.picks if p.why.startswith("Ramp"))
    take([r for r in nonland if "ramp" in roles_of[r["lname"]] or
          "manarock" in roles_of[r["lname"]]], counts["ramp"] - have, "Ramp")
    for role, label in (("draw", "Card draw"), ("removal", "Removal"), ("wipe", "Board wipe"),
                        ("protection", "Protection")):
        take([r for r in nonland if role in roles_of[r["lname"]]], counts[role], label)
    # lands: staples for the colours, then basics
    lands_wanted = counts["lands"]
    land_staples = [by_name[n] for n, s in staples.items() if n in by_name and
                    s.group != "Mana rocks" and "land" in by_name[n]["ltype"]]
    n_colors = len(identity)
    nonbasic = min(len(land_staples), {0: 2, 1: 4, 2: 10, 3: 14}.get(n_colors, 16),
                   lands_wanted)
    take(land_staples, nonbasic, "Land (fixing)")
    # the rest: what fits the commander, the style and the themes best
    spells_left = 99 - lands_wanted - sum(p.count for p in deck.picks
                                         if not p.why.startswith("Land"))
    creatures = [r for r in nonland if "creature" in r["ltype"]]
    take(creatures, max(0, int(spells_left * st.creatures)), "Fits the deck – creatures")
    spells_left = 99 - lands_wanted - sum(p.count for p in deck.picks
                                         if not p.why.startswith("Land"))
    take(nonland, max(0, spells_left), "Fits the deck – other spells")
    # basics, split by the colours' mana symbols in the picks
    lands_have = sum(p.count for p in deck.picks if p.why.startswith("Land"))
    basics = max(0, 99 - sum(p.count for p in deck.picks))
    if identity:
        pips = {c: sum((p.row["mana_cost"] or "").count("{" + c) for p in deck.picks)
                for c in identity}
        total = sum(pips.values())
        split = {c: int(basics * (pips[c] / total if total else 1 / n_colors)) for c in identity}
        split[max(identity, key=lambda c: pips[c])] += basics - sum(split.values())
        names = {c: mb.BASICS[c] for c in identity}
    else:
        split, names = {"C": basics}, {"C": "Wastes"}
    for c, n in split.items():
        if n > 0:
            deck.picks.append(Pick(names[c], "Basic land", best_printing(conn, names[c]), n))
    if lands_have + basics < lands_wanted - 2:
        deck.notes.append("Not enough cards matched to fill every slot – try fewer filters.")
    return deck
