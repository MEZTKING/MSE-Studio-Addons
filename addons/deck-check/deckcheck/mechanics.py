"""Sort cards into tiers: what Forge can run as-is, what needs engine code, what stays manual."""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache

from .checks import DATA, KEYWORD_ACTIONS, Finding, forge_keywords, is_art_card, versions
from .deck import Card, Deck

TIERS = ("script", "engine", "manual")
TIER_LABEL = {
    "script": "Forge script",
    "engine": "Needs engine code",
    "manual": "Manual",
    "reference": "Not played",
}


@lru_cache
def knowledge() -> dict:
    return json.loads((DATA / "mechanics.json").read_text(encoding="utf-8"))


@dataclass
class CardResult:
    card: Card
    tier: str = "script"
    reasons: list[str] = field(default_factory=list)   # why the tier is what it is
    keywords: list[str] = field(default_factory=list)  # deck keywords used
    real_keywords: list[str] = field(default_factory=list)
    unknown_keywords: list[str] = field(default_factory=list)
    version_of: str = ""        # the card this is an alternate version of (art, art only)
    version_of_id: str = ""

    def raise_to(self, tier: str, reason: str):
        if TIERS.index(tier) > TIERS.index(self.tier):
            self.tier = tier
        if reason not in self.reasons:
            self.reasons.append(reason)


def _real_keyword(piece: str) -> str | None:
    p = piece.strip().lower().replace("first-strike", "first strike")
    for kw in sorted(forge_keywords(), key=len, reverse=True):
        k = kw.lower()
        if p == k or p.startswith(k + " ") or p.startswith(k + "—") or p.startswith(k + " {"):
            return kw
    if p in KEYWORD_ACTIONS or any(p.startswith(a + " ") for a in KEYWORD_ACTIONS):
        return piece.strip()
    return None


def _keyword_line_pieces(line: str) -> list[str] | None:
    """If the line is a comma-separated keyword list, return its pieces."""
    if line.endswith(".") or ":" in line or len(line) > 90:
        return None
    if line.startswith(("(", "[", "“", "-", "\"")) or re.match(r"^\d", line):
        return None
    pieces = [p.strip() for p in re.split(r",(?![^{]*\})", line) if p.strip()]
    if all(len(p.split()) <= 5 and p[0].isupper() and not re.search(r"[.\[\]()“”]|-\d|/\d", p)
           and not re.search(r"\b(you|target|whenever|when|each|your|this|all|get|gets)\b", p, re.I)
           for p in pieces):
        return pieces
    return None


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("’", "'").replace("‘", "'").replace("“", '"')
                  .replace("”", '"')).lower()


def _still_applies(note: dict, card: Card) -> bool:
    """A note or question about a card's wording is only shown while the card still
    says it: its "if_text", else the first quoted words of the question (up to "…")."""
    want = note.get("if_text")
    if not want:
        m = re.search(r"“([^”]+)”", note.get("question", ""))
        want = m.group(1).split("…")[0].strip(" .") if m else ""
    return not want or _plain(want) in _plain(card.rules_text)


def classify(deck: Deck) -> tuple[list[CardResult], list[Finding]]:
    kb = knowledge()
    kw_info = kb["keywords"]
    patterns = [(re.compile(p["regex"], re.IGNORECASE), p) for p in kb["patterns"]]
    card_notes = kb["cards"]
    findings: list[Finding] = []
    results = []

    # deck keyword questions (once per deck)
    for dk in deck.keywords:
        info = kw_info.get(dk.name.lower())
        if info and info.get("question") and any(dk.pattern().search(c.rules_text) for c in deck.cards):
            findings.append(Finding("question", "keyword-ruling", f"{dk.name}: {info['question']}",
                                    card="", fix=""))
        elif not info:
            findings.append(Finding("info", "keyword-unclassified",
                                    f"Deck keyword “{dk.name}” isn't in the mechanics file yet; the AI translation will have to classify it."))

    for c in deck.cards:
        r = CardResult(c)
        if c.real:
            r.reasons.append("real card: Forge has it")
            results.append(r)
            continue
        tl = c.type_line.lower()
        if any(t.lower() == "art" for t in c.types):
            r.tier = "reference"
            r.reasons.append("art card: a picture of another version, not played on its own")
            results.append(r)
            continue
        if "rules" in tl and "emblem" in tl:
            r.tier = "reference"
            r.reasons.append("rules reference card, not played")
            results.append(r)
            continue

        # deck keywords used anywhere in the text
        for dk in deck.keywords:
            if dk.pattern().search(c.rules_text):
                r.keywords.append(dk.name)
                info = kw_info.get(dk.name.lower())
                if info:
                    r.raise_to(info["tier"], f"{dk.name}: {info['how']}")
                else:
                    r.raise_to("engine", f"{dk.name}: not classified yet")

        # keyword lines: real vs unknown
        deck_kw_names = {k.name.lower() for k in deck.keywords}
        for line in c.lines[:2]:
            pieces = _keyword_line_pieces(line)
            if not pieces:
                continue
            for p in pieces:
                if any(k.pattern().search(p) for k in deck.keywords) or p.lower() in deck_kw_names:
                    continue
                real = _real_keyword(p)
                if real:
                    r.real_keywords.append(real)
                elif not re.match(r"^\d+/\d+$", p):
                    r.unknown_keywords.append(p)
        for uk in r.unknown_keywords:
            head = re.split(r"\s*\{", uk)[0]
            close = difflib.get_close_matches(head.lower(), [k.lower() for k in forge_keywords()], n=1, cutoff=0.8)
            if close:
                real = next(k for k in forge_keywords() if k.lower() == close[0])
                findings.append(Finding("error", "misspelled-keyword", f"“{uk}” — did you mean the Magic keyword “{real}”?",
                                        c.name, c.id, f"spell it “{real}”"))
                r.real_keywords.append(real)
            else:
                r.raise_to("engine", f"undefined keyword: {uk}")
                findings.append(Finding("question", "unknown-keyword",
                                        f"Uses “{uk}”, which is neither a Magic keyword nor one of this deck's keywords.",
                                        c.name, c.id, "add it to the deck's keywords with reminder text"))

        for rx, p in patterns:
            if rx.search(c.rules_text):
                r.raise_to(p["tier"], p["label"])

        if any(t.lower() == "code" for t in c.types):
            r.raise_to("engine", "Code card type (Geass system)")

        note = card_notes.get(c.name) or (card_notes.get(c.base_name) if not c.marker else None)
        if note and not _still_applies(note, c):
            note = None
        if note:
            if note.get("tier"):
                r.raise_to(note["tier"], note.get("note", "see note"))
            elif note.get("note"):
                r.reasons.append(note["note"])
            if note.get("question"):
                findings.append(Finding("question", "card-ruling", note["question"], c.name, c.id))

        if not r.reasons:
            r.reasons.append("standard Magic wording")
        results.append(r)
    # alternate versions follow their card: same tier, art-only ones aren't played
    alt = versions(deck)
    by_id = {r.card.id: r for r in results}
    for r in results:
        main = alt.get(r.card.id)
        if main is None:
            continue
        r.version_of, r.version_of_id = main.name, main.id
        if is_art_card(r.card) or not (r.card.rules_text.strip() or r.card.mana_cost):
            r.tier, r.reasons = "reference", [f"art only: a picture of {main.name}"]
        else:
            m = by_id.get(main.id)
            r.tier = m.tier if m else r.tier
            r.reasons = [f"alternate art of {main.name}: plays as that card"]
    return results, findings
