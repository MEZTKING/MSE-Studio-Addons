"""Load MSE Studio .deck.json files into plain dataclasses."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# "[Art N]": a picture of the card, not played. "[Alt N]": an alternate, played as the card.
VERSION_SUFFIX = re.compile(r"\s*\[(Art|Alt)\s*(\d+)\]\s*$", re.IGNORECASE)


@dataclass
class Card:
    id: str
    text_hash: str
    name: str
    count: int
    mana_cost: str
    mana_value: float
    type_line: str
    supertypes: list[str]
    types: list[str]
    subtypes: list[str]
    rules_text: str
    power: str
    toughness: str
    loyalty: str
    colors: str
    color_identity: str
    is_token: bool
    is_commander: bool
    real: bool
    back_of: str
    raw: dict = field(repr=False)

    @property
    def base_name(self) -> str:
        """Name without an ' [Art N]' / ' [Alt N]' suffix."""
        return VERSION_SUFFIX.sub("", self.name).strip()

    @property
    def marker(self) -> str:
        """"art" (a picture, not played) or "alt" (an alternate, played as the card):
        the export's "version" field when it has one, else '[Art N]' / '[Alt N]'."""
        v = str(self.raw.get("version") or "").lower()
        if v in ("art", "alt"):
            return v
        m = VERSION_SUFFIX.search(self.name)
        return m.group(1).lower() if m else ""

    @property
    def version_of(self) -> str:
        """The export's "version_of": the id of the card this is a version of."""
        return str(self.raw.get("version_of") or "")

    @property
    def marker_number(self) -> int:
        m = VERSION_SUFFIX.search(self.name)
        return int(m.group(2)) if m else 0

    @property
    def short_name(self) -> str:
        """'Lady Lihua, The Crystal Pavilion' -> 'Lady Lihua'."""
        return self.base_name.split(",")[0].strip()

    @property
    def lines(self) -> list[str]:
        return [ln.strip() for ln in self.rules_text.splitlines() if ln.strip()]

    def has_type(self, t: str) -> bool:
        return t.lower() in (x.lower() for x in self.types)

    @property
    def is_permanent(self) -> bool:
        return not (self.has_type("Instant") or self.has_type("Sorcery"))


@dataclass
class DeckKeyword:
    keyword: str
    match: str
    reminder: str

    @property
    def name(self) -> str:
        return self.keyword.strip()

    def pattern(self) -> re.Pattern:
        """Regex for the keyword as it appears in rules text."""
        parts = re.split(r"(\{number\}|\{name\}|\{cost\})", self.match.strip() or self.name)
        rx = ""
        for p in parts:
            if p == "{number}":
                rx += r"\{?\d+\}?"
            elif p in ("{name}", "{cost}"):
                rx += r"[^,.\n]+"
            else:
                rx += re.escape(p)
        return re.compile(r"(?<![\w-])" + rx + r"(?![\w-])", re.IGNORECASE)


@dataclass
class Deck:
    path: Path
    name: str
    format: str
    commander: list[str]
    color_identity: str
    keywords: list[DeckKeyword]
    cards: list[Card]
    format_version: int
    exported: str = ""


def _card(d: dict) -> Card:
    def s(k):
        v = d.get(k, "")
        return "" if v is None else str(v)

    try:
        mv = float(d.get("mana_value") or 0)
    except (TypeError, ValueError):
        mv = 0.0
    return Card(
        id=s("id"), text_hash=s("text_hash"), name=s("name").strip(), count=int(d.get("count") or 0),
        mana_cost=s("mana_cost").strip(), mana_value=mv, type_line=s("type_line"),
        supertypes=list(d.get("supertypes") or []), types=list(d.get("types") or []),
        subtypes=list(d.get("subtypes") or []), rules_text=s("rules_text"),
        power=s("power").strip(), toughness=s("toughness").strip(), loyalty=s("loyalty").strip(),
        colors=s("colors"), color_identity=s("color_identity"),
        is_token=bool(d.get("is_token")), is_commander=bool(d.get("is_commander")),
        real=bool(d.get("real")), back_of=s("back_of"), raw=d,
    )


def load_deck(path: str | Path) -> Deck:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("format") != "mse-studio-deck":
        raise ValueError(f"{path.name}: not an MSE Studio deck file")
    if int(data.get("format_version", 1)) > 1:
        raise ValueError(f"{path.name}: format_version {data['format_version']} is newer than this checker understands")
    deck = data.get("deck", {})
    return Deck(
        path=path,
        name=deck.get("name") or path.stem,
        format=deck.get("format", ""),
        commander=list(deck.get("commander") or []),
        color_identity=deck.get("color_identity", ""),
        keywords=[DeckKeyword(k.get("keyword", ""), k.get("match", k.get("keyword", "")), k.get("reminder", ""))
                  for k in data.get("keywords", [])],
        cards=[_card(c) for c in data.get("cards", [])],
        format_version=int(data.get("format_version", 1)),
        exported=str(data.get("exported") or ""),
    )
