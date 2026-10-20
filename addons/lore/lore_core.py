"""The deck's lore without the page: what's kept (lore.json in the deck's
folder, so it goes with the deck and its backups), the cards about each
entry, and entries gathered from the cards themselves."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

FILE = "lore.json"
KINDS = (("character", "Characters"), ("place", "Places"), ("group", "Groups and peoples"),
         ("item", "Items"), ("event", "Events"), ("other", "Other"))
KIND_LABEL = dict(KINDS)
ONE = {"character": "A character", "place": "A place", "group": "A group or people",
       "item": "An item", "event": "An event", "other": "Something else"}
# the card a lore entry becomes: (type, sub type – None: the entry's own name)
CARD_TYPE = {"character": ("Legendary Creature", ""), "place": ("Legendary Land", ""),
             "item": ("Legendary Artifact", ""), "event": ("Sorcery", ""),
             "group": ("Creature", None), "other": ("Enchantment", "")}
# creature types that say what someone does, not who they are: not groups
_CLASSES = {"advisor", "artificer", "assassin", "bard", "berserker", "cleric", "druid",
            "knight", "monk", "ninja", "noble", "peasant", "pilot", "pirate", "ranger",
            "rogue", "samurai", "scout", "shaman", "soldier", "warlock", "warrior", "wizard",
            "citizen", "mercenary", "mystic", "hero", "human", "token"}
# words a name can start with that aren't a first name
_NOT_FIRST_NAMES = {"the", "lady", "lord", "sir", "dame", "king", "queen", "prince",
                    "princess", "captain", "doctor", "master", "mistress", "old", "young",
                    "saint", "father", "mother", "brother", "sister", "general", "emperor",
                    "empress", "duke", "duchess", "count", "countess"}
_SPEAKER = re.compile(r"[—–]\s*([A-Z][^\n\"“”—–]{1,60}?)\s*[.,]?\s*$", re.M)


@dataclass
class Entry:
    name: str
    kind: str = "other"
    text: str = ""
    aliases: list = field(default_factory=list)
    when: str = ""                    # events: when it happens (they're sorted by it)

    def names(self) -> list[str]:
        """Every name it goes by: its own, the others, the short one before a
        comma ("Name, the Title" → "Name") and a character's first name."""
        out = [self.name] + [a for a in self.aliases if a]
        short = self.name.split(",")[0].strip()
        if short != self.name and len(short) > 2:
            out.append(short)
        first = short.split()[0] if short.split() else ""
        if self.kind == "character" and first != short and len(first) > 2 and \
                first.lower() not in _NOT_FIRST_NAMES:
            out.append(first)
        return list(dict.fromkeys(n.strip() for n in out if n.strip()))

    def to_dict(self) -> dict:
        d = {"name": self.name, "kind": self.kind, "text": self.text}
        if self.aliases:
            d["aliases"] = list(self.aliases)
        if self.when:
            d["when"] = self.when
        return d

    @classmethod
    def from_dict(cls, d) -> Optional["Entry"]:
        if not isinstance(d, dict) or not str(d.get("name") or "").strip():
            return None
        kind = str(d.get("kind") or "other")
        aliases = d.get("aliases") if isinstance(d.get("aliases"), list) else []
        return cls(str(d["name"]).strip(), kind if kind in KIND_LABEL else "other",
                   str(d.get("text") or ""), [str(a) for a in aliases if str(a).strip()],
                   str(d.get("when") or ""))


@dataclass
class Lore:
    world: str = ""
    entries: list = field(default_factory=list)

    def find(self, name: str) -> Optional[Entry]:
        low = (name or "").strip().lower()
        return next((e for e in self.entries if low in (n.lower() for n in e.names())), None)

    def ordered(self, kind: str = "") -> list[Entry]:
        """By kind (characters first), then by name – events by when."""
        order = [k for k, _l in KINDS]

        def key(e: Entry):
            first = order.index(e.kind) if e.kind in order else len(order)
            if e.kind == "event" and e.when:
                return first, 0, _natural(e.when), e.name.lower()
            return first, 1, [], e.name.lower()
        return sorted((e for e in self.entries if not kind or e.kind == kind), key=key)


def _natural(s: str) -> list:
    return [(0, int(t)) if t.isdigit() else (1, t.lower()) for t in re.findall(r"\d+|\D+", s)]


# ------------------------------------------------------------------ keeping
def path(project) -> Path:
    return Path(project.folder) / FILE


def load(project) -> Lore:
    """The deck's lore (an empty one when there's none yet, or it can't be read)."""
    try:
        d = json.loads(path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Lore()
    if not isinstance(d, dict):
        return Lore()
    entries = [e for e in (Entry.from_dict(x) for x in d.get("entries") or []) if e]
    return Lore(str(d.get("world") or ""), entries)


def save(project, lore: Lore) -> None:
    out = path(project)
    text = json.dumps({"world": lore.world, "entries": [e.to_dict() for e in lore.entries]},
                      ensure_ascii=False, indent=1)
    tmp = out.with_suffix(".partial")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(out)


# ------------------------------------------------------------------ cards
_FIELDS = ("name", "super_type", "sub_type", "rule_text", "flavor_text",
           "name_2", "super_type_2", "sub_type_2", "rule_text_2", "flavor_text_2")


def card_text(card) -> str:
    """Everything written on a card (both faces)."""
    return "\n".join(t for t in (_text(card, f) for f in _FIELDS) if t)


def _text(card, f: str) -> str:
    try:
        return str(card.text(f) or "")
    except Exception:  # noqa: BLE001 - a card without that field
        return ""


def _name_rx(names: list[str]) -> Optional[re.Pattern]:
    names = [re.escape(n) for n in names if len(n) > 1]
    if not names:
        return None
    return re.compile(r"(?<![\w])(?:" + "|".join(sorted(names, key=len, reverse=True)) +
                      r")(?![\w])", re.I)


def mentions(cards, entry: Entry) -> list[int]:
    """The cards (their places in the deck) about an entry: it's named in
    their name, type, rules or flavour text."""
    rx = _name_rx(entry.names())
    if rx is None:
        return []
    return [i for i, c in enumerate(cards) if rx.search(card_text(c))]


def quotes(cards, entry: Entry) -> list[str]:
    """Flavour text said by the entry, or about it."""
    rx = _name_rx(entry.names())
    if rx is None:
        return []
    out = []
    for c in cards:
        for f in ("flavor_text", "flavor_text_2"):
            t = _text(c, f).strip()
            if t and rx.search(t) and t not in out:
                out.append(t)
    return out


def speakers(cards) -> dict:
    """Who speaks in flavour text ("…” — Name"): name → how often."""
    out: dict = {}
    for c in cards:
        for f in ("flavor_text", "flavor_text_2"):
            for m in _SPEAKER.finditer(_text(c, f)):
                who = m.group(1).strip().rstrip(".,")
                if 1 < len(who) <= 60:
                    out[who] = out.get(who, 0) + 1
    return out


def links(lore: Lore, entry: Entry) -> tuple[list[str], list[str]]:
    """(the entries this one's text names, the entries whose text names it)."""
    own = _name_rx(entry.names())
    names, named_by = [], []
    for other in lore.entries:
        if other is entry:
            continue
        rx = _name_rx(other.names())
        if rx is not None and rx.search(entry.text):
            names.append(other.name)
        if own is not None and own.search(other.text):
            named_by.append(other.name)
    return names, named_by


def gather(project, lore: Lore, characters=()) -> list[tuple[Entry, str]]:
    """Entries the deck's cards suggest, with why – the ones the lore hasn't
    got yet: legendary creatures (characters), legendary lands (places),
    legendary artifacts (items), sagas (events), who speaks in flavour text,
    the types many cards share (groups) and ``characters`` saved with the
    deck (their story)."""
    cards = list(project.set.cards)
    have = {n.lower() for e in lore.entries for n in e.names()}
    out: list[tuple[Entry, str]] = []

    def add(entry: Entry, why: str):
        if any(n.lower() in have for n in entry.names()):
            return
        have.update(n.lower() for n in entry.names())
        out.append((entry, why))
    for ch in characters:
        add(Entry(ch.name, "character", (ch.story or "")[:4000]), "saved with the deck")
    for c in cards:
        sup = _text(c, "super_type").lower()
        name = (getattr(c, "name", "") or "").strip()
        if not name or "legendary" not in sup:
            if "saga" in _text(c, "sub_type").lower() and name:
                add(Entry(name, "event"), "a saga card")
            continue
        kind = "character" if ("creature" in sup or "planeswalker" in sup) else \
            "place" if "land" in sup else "item" if "artifact" in sup else "other"
        add(Entry(name, kind), f"a legendary {kind_word(sup)} card")
    for who, n in sorted(speakers(cards).items(), key=lambda kv: -kv[1]):
        add(Entry(who, "character"),
            f"speaks in {n} card's flavour text" if n == 1 else
            f"speaks in {n} cards' flavour text")
    counts: dict = {}
    for c in cards:
        for t in re.split(r"\s+", _text(c, "sub_type")):
            t = t.strip()
            if t and t.lower() not in _CLASSES and t[:1].isupper():
                counts[t] = counts.get(t, 0) + 1
    for t, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if n >= 3:
            add(Entry(t, "group"), f"{n} cards are {t}")
    return out


def kind_word(super_type: str) -> str:
    low = super_type.lower()
    for w in ("planeswalker", "creature", "land", "artifact", "enchantment"):
        if w in low:
            return w
    return "card"


def unknown_speakers(cards, lore: Lore) -> list[tuple[str, int]]:
    """Who speaks in flavour text but isn't in the lore yet."""
    return [(w, n) for w, n in sorted(speakers(cards).items(), key=lambda kv: -kv[1])
            if lore.find(w) is None]


def card_fields(entry: Entry) -> dict:
    """A new card for an entry: its name, a type that fits, a line of it as
    flavour text."""
    sup, sub = CARD_TYPE.get(entry.kind, CARD_TYPE["other"])
    first = re.split(r"(?<=[.!?])\s", entry.text.strip(), maxsplit=1)[0] if entry.text else ""
    out = {"name": entry.name, "super_type": sup,
           "sub_type": entry.name if sub is None else sub}
    if first and len(first) <= 160:
        out["flavor_text"] = first
    return out


def as_markdown(lore: Lore, deck_name: str = "", cards=()) -> str:
    """The lore as a text file (Markdown): the world, then each kind."""
    cards = list(cards)
    lines = [f"# {deck_name + ' – ' if deck_name else ''}Lore", ""]
    if lore.world.strip():
        lines += ["## The world", "", lore.world.strip(), ""]
    for kind, label in KINDS:
        entries = lore.ordered(kind)
        if not entries:
            continue
        lines += [f"## {label}", ""]
        for e in entries:
            lines.append(f"### {e.name}" + (f" ({e.when})" if e.when else ""))
            others = [a for a in e.aliases if a]
            if others:
                lines.append(f"*Also: {', '.join(others)}*")
            if e.text.strip():
                lines += ["", e.text.strip()]
            about = [getattr(cards[i], "name", "") for i in mentions(cards, e)]
            if about:
                lines += ["", "Cards: " + ", ".join(n for n in about if n)]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
