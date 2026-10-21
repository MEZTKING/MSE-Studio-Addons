"""Mechanical checks on a deck: things that are wrong in the data, whatever the engine.

Every check returns Findings. `kind` is:
  "error"    - the data is wrong or unusable; fix it in MSE Studio
  "question" - the data is valid but the meaning is unclear; needs the author's ruling
  "info"     - worth knowing, nothing to fix
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .deck import Card, Deck

DATA = Path(__file__).parent / "data"


@dataclass
class Finding:
    kind: str
    code: str
    message: str
    card: str = ""          # card name, empty for deck-level findings
    card_id: str = ""
    fix: str = ""           # suggested fix, if any


@lru_cache
def forge_keywords() -> list[str]:
    return [k for k in (DATA / "forge_keywords.txt").read_text(encoding="utf-8").splitlines() if k]


@lru_cache
def real_card_names() -> frozenset[str]:
    return frozenset(n for n in (DATA / "real_card_names.txt").read_text(encoding="utf-8").splitlines() if n)


# Keyword actions and ability words Forge supports that aren't in its Keyword enum.
KEYWORD_ACTIONS = {
    "surveil", "scry", "proliferate", "investigate", "connive", "explore", "fight", "mill",
    "manifest", "cloak", "populate", "amass", "adapt", "bolster", "support", "learn", "venture",
    "goad", "detain", "monstrosity", "regenerate", "transform", "meld", "incubate", "discover",
    "suspect", "collect evidence", "forage", "time travel", "the monarch", "first-strike",
    "lifelink", "deathtouch", "vigilance", "trample", "haste", "indestructible", "shroud",
}
CARD_TYPES = {"artifact", "battle", "conspiracy", "creature", "dungeon", "enchantment", "instant",
              "kindred", "land", "phenomenon", "plane", "planeswalker", "scheme", "sorcery", "tribal",
              "vanguard"}
SUPERTYPES = {"basic", "legendary", "snow", "world", "ongoing", "host", "token"}
BASIC_LANDS = {"plains", "island", "swamp", "mountain", "forest", "wastes"}

MANA_SYMBOL = re.compile(r"^(\d+|[WUBRGCXYZS]|[WUBRGC]/[WUBRGP]|2/[WUBRG]|[WUBRG]/[WUBRG]/P)$")
TEXT_SYMBOL = re.compile(r"^(\d+|[WUBRGCXYZSTQE]|[WUBRGC]/[WUBRGP]|2/[WUBRG]|[WUBRG]/[WUBRG]/P|PW|CHAOS)$")


def _f(kind, code, msg, card: Card | None = None, fix=""):
    return Finding(kind, code, msg, card.name if card else "", card.id if card else "", fix)


# ---------- mana ----------

def split_symbol(group: str) -> str | None:
    """Suggest a correct spelling for a malformed brace group like '3BG', 'T3' or '5W/U'."""
    g = group.upper().replace(" ", "")
    m = re.fullmatch(r"(\d*)([WUBRGC]/[WUBRGP])", g)
    if m:
        return (f"{{{m.group(1)}}}" if m.group(1) else "") + f"{{{m.group(2)}}}"
    if not re.fullmatch(r"[0-9WUBRGCXTQ]+", g):
        return None
    tap = [c for c in g if c in "TQ"]
    num = re.findall(r"\d+", g)
    rest = [c for c in re.sub(r"[\dTQ]", "", g)]
    mana = "".join(f"{{{n}}}" for n in num) + "".join(f"{{{c}}}" for c in rest)
    parts = [f"{{{t}}}" for t in tap] + ([mana] if mana else [])
    return ", ".join(parts)


def mana_value_of(cost: str) -> float:
    total = 0.0
    for g in re.findall(r"\{([^}]*)\}", cost):
        if g.isdigit():
            total += int(g)
        elif g in ("X", "Y", "Z"):
            pass
        elif g.startswith("2/"):
            total += 2
        elif g == "½":
            total += 0.5
        else:
            total += 1
    return total


def cost_colors(text: str) -> set[str]:
    out = set()
    for g in re.findall(r"\{([^}]*)\}", text):
        out |= {c for c in g.upper() if c in "WUBRG"} if re.fullmatch(r"[WUBRG2C/P]+", g.upper()) else set()
    return out


def check_mana(card: Card) -> list[Finding]:
    out = []
    cost = card.mana_cost
    if cost:
        leftovers = re.sub(r"\{[^}]*\}", "", cost).strip()
        if leftovers:
            out.append(_f("error", "cost-syntax", f"Mana cost '{cost}' has text outside braces.", card))
        bad = [g for g in re.findall(r"\{([^}]*)\}", cost) if not MANA_SYMBOL.match(g)]
        for g in bad:
            out.append(_f("error", "cost-symbol", f"Mana cost symbol {{{g}}} isn't a valid mana symbol.", card,
                          split_symbol(g) or ""))
        if not bad:
            mv = mana_value_of(cost)
            if abs(mv - card.mana_value) > 0.01:
                out.append(_f("error", "mana-value", f"mana_value is {card.mana_value:g} but the cost {cost} adds up to {mv:g}.", card))
    for g in sorted(set(re.findall(r"\{([^}]*)\}", card.rules_text))):
        if not TEXT_SYMBOL.match(g):
            fix = split_symbol(g)
            if fix:
                out.append(_f("info", "compact-symbol", f"{{{g}}} → {fix}", card))
            else:
                out.append(_f("error", "text-symbol",
                              f"Rules text uses {{{g}}}, which isn't a Magic symbol, so the engine can't tell what it costs.", card))
    return out


# ---------- types, P/T, loyalty ----------

def check_types(card: Card) -> list[Finding]:
    out = []
    if is_art_card(card):
        return []
    unknown_types = [t for t in card.types if t.lower() not in CARD_TYPES]
    if unknown_types:
        out.append(_f("info", "custom-type", ", ".join(unknown_types), card))
    unknown_super = [t for t in card.supertypes if t.lower() not in SUPERTYPES]
    if unknown_super:
        out.append(_f("info", "custom-supertype", f"Supertype(s) {', '.join(unknown_super)} don't exist in Magic.", card))
    split = [s for s in card.subtypes if s in ("of", "the", "The", "Card") or (s and s[0].islower())]
    if split:
        tail = card.type_line.split("—", 1)[-1].strip() if "—" in card.type_line else ""
        out.append(_f("info", "split-subtype", tail, card))
    return out


PT_OK = re.compile(r"^(\d+|\*|X|\d+\+\*|\*\+\d+|-\d+)$")


def check_pt(card: Card) -> list[Finding]:
    out = []
    is_creature = card.has_type("Creature")
    is_vehicle = "vehicle" in (s.lower() for s in card.subtypes)
    for label, v in (("power", card.power), ("toughness", card.toughness)):
        if v and not PT_OK.match(v):
            out.append(_f("error", "pt-value", f"{label.capitalize()} is '{v}', which isn't a number.", card))
    if (is_creature or is_vehicle) and not (card.power and card.toughness):
        out.append(_f("error", "pt-missing", "Creature/Vehicle without power and toughness.", card))
    loyalty_lines = [ln for ln in card.lines if re.match(r"^[+−–-]?\d+:\s", ln) or re.match(r"^[+−–-]X:\s", ln)]
    if loyalty_lines and not card.has_type("Planeswalker"):
        out.append(_f("question", "loyalty-on-nonwalker",
                      f"Has loyalty abilities ({loyalty_lines[0][:30]}…) but isn't a planeswalker and has no loyalty.", card,
                      "make it a Planeswalker with a starting loyalty, or say what pays for these abilities"))
    elif card.has_type("Planeswalker") and not card.loyalty:
        out.append(_f("error", "loyalty-missing", "Planeswalker without starting loyalty.", card))
    return out


# ---------- text ----------

TRUNCATED_END = re.compile(r"\b(add|the|a|an|to|and|or|of|with|for|your|then)$", re.IGNORECASE)
IMPERATIVE = re.compile(r"^(Search|Draw|Destroy|Exile|Create|Return|Deal|Put|Attach|Gain|Target|Each|You gain|You draw|"
                        r"You may search|Remove|Counter|Tap|Untap|Reveal|Look)\b")
SELF_REF_SUBJECT = re.compile(
    r"^(?:When|Whenever|As|If)\s+([A-Z][^,]*?)\s+(?:enters|comes into play|deals|attacks|blocks|dies|is put|leaves|"
    r"becomes|transforms|would)\b")
NOT_A_NAME = re.compile(r"^(A|An|Another|One|Each|Target|This|That|It|He|She|They|You|Creatures?|Enchanted|Equipped|"
                        r"All|Your|An opponent|A player|Lady|Knightmare|Imperial Palace)\b")


def check_text(card: Card, deck_names: set[str]) -> list[Finding]:
    out = []
    lines = card.lines
    if not lines and not card.has_type("Land") and not card.has_type("Creature") and card.count >= 0:
        out.append(_f("error", "empty-text", "No rules text on a non-creature, non-land card.", card))
    for ln in lines:
        stripped = ln.rstrip(" .")
        if TRUNCATED_END.search(stripped) and not stripped.lower().endswith("to your mana pool"):
            out.append(_f("error", "truncated", f"Line looks cut off: “{ln}”", card))
        m = re.match(r"^(\{[^}]*\}(?:,\s*\{[^}]*\})*)\s*:\s*(.*)$", ln)
        if m and m.group(2).strip(" .").lower() in (card.base_name.lower(), card.short_name.lower(), ""):
            out.append(_f("error", "no-effect", f"Activated ability has no effect: “{ln}”", card))
    # self references that don't match the card's name
    names_lower = {n.lower() for n in deck_names}
    for ln in lines:
        m = SELF_REF_SUBJECT.match(ln)
        if not m:
            continue
        subj = re.split(r"\s+(?:or|and)\s+|\s+(?=[a-z]{3,}\b(?<!\bvi)(?<!\bzi)(?<!\bla)(?<!\bel)(?<!\bof)(?<!\bthe))", m.group(1).strip())[0]
        subj = re.sub(r"^The\s+", "", subj)
        if NOT_A_NAME.match(subj) or len(subj) < 3:
            continue
        own = {card.base_name.lower(), card.short_name.lower(), card.base_name.split(" ")[0].lower()}
        if subj.lower() in own or subj.lower() in names_lower:
            continue
        if any(subj.lower() in n or n.startswith(subj.lower()) for n in own):
            continue
        out.append(_f("error", "wrong-self-name",
                      f"Text says “{subj}” but this card is named “{card.base_name}”.", card,
                      f"replace “{subj}” with “{card.short_name}” (or “this card”)"))
    # named-card references
    for m in re.finditer(r"(?:card|creature)s? named\s+[‘'\"“]?([A-Z][^.,‘’'\"”]*(?:,\s*[Tt]he [^.,‘’'\"”]+)?)", card.rules_text):
        ref = m.group(1).strip().rstrip(".")
        ref = re.split(r"\s+(?:is|on|from|put|and|in|or)\b", ref)[0].strip()
        if ref.lower() in (card.base_name.lower(), card.short_name.lower()) and "Search" in card.rules_text:
            out.append(_f("question", "searches-itself",
                          f"Searches for a card named “{ref}”, which is this card's own name.", card,
                          "was the card renamed instead of the name in its text?"))
        elif ref.lower() not in names_lower and not any(n.startswith(ref.lower()) for n in names_lower):
            out.append(_f("error", "missing-named-card", f"Refers to a card named “{ref}”, but no card in the deck has that name.", card))
    # spells that 'enter the battlefield'
    if not card.is_permanent and re.search(r"\benters the battlefield\b", card.rules_text, re.IGNORECASE):
        own = (card.base_name.lower(), card.short_name.lower(), "this")
        for ln in lines:
            m = re.match(r"^When(?:ever)?\s+(.+?)\s+enters the battlefield", ln, re.IGNORECASE)
            if m and (m.group(1).lower() in own or m.group(1).lower().startswith(card.short_name.lower())):
                out.append(_f("question", "spell-etb",
                              f"{'/'.join(card.types)} can't enter the battlefield, so “{ln[:60]}…” never happens.", card,
                              "drop the 'When … enters' part so it happens on resolution"))
    # permanents with spell-like lines
    if card.is_permanent and card.count > 0 and "rules" not in card.type_line.lower():
        for i, ln in enumerate(lines):
            prev = lines[i - 1] if i else ""
            if prev.endswith((":", "—", "-")) or re.match(r"^[+−–-]?\d+:", prev):
                continue
            first = ln.split(".")[0]
            if re.search(r"\b(when|whenever|at the beginning)\b", first, re.I) or \
                    (ln.startswith("Each") and re.search(r"\b(has|have|gets?|can|can't|cannot|plays?|costs?)\b", first)):
                continue
            if IMPERATIVE.match(ln) and ":" not in first:
                out.append(_f("question", "permanent-imperative",
                              f"“{ln[:70]}…” has no trigger, so a {'/'.join(card.types).lower()} never does it.", card,
                              "start it with “When this enters, …” (or say when it happens)"))
                break
    return out


def find_real_names(text: str, exclude: set[str]) -> set[str]:
    names = real_card_names()
    words = re.findall(r"[\w’'\-]+|,", text)
    found = set()
    for n in range(2, 7):
        for i in range(len(words) - n + 1):
            chunk = words[i:i + n]
            if chunk[0] == "," or chunk[-1] == ",":
                continue
            cand = " ".join(chunk).replace(" ,", ",").replace("’", "'")
            if cand in names and cand.lower() not in exclude:
                found.add(cand)
    # drop names contained in a longer found name
    return {f for f in found if not any(f != g and f in g for g in found)}


COMMON_PHRASES = {"Black Knight", "Lady of the Mountain", "Counter Spell", "Lose Life"}


def check_leftover_names(card: Card, deck_names: set[str], deck_keywords: set[str] = frozenset()) -> list[Finding]:
    exclude = {n.lower() for n in deck_names} | {card.base_name.lower()} | {k.lower() for k in deck_keywords}
    found = find_real_names(card.rules_text, exclude) - COMMON_PHRASES
    return [_f("error", "leftover-name",
               f"Text mentions “{n}”, a real Magic card that isn't in this deck. Probably left over from the card this was based on.",
               card, f"replace “{n}” with “{card.short_name}”") for n in sorted(found)]


# ---------- casting ----------

def check_castable(card: Card) -> list[Finding]:
    if card.mana_cost or card.has_type("Land") or card.is_token or card.count == 0 or card.back_of \
            or card.base_name.lower().endswith(" token"):
        return []
    if not card.types or any(t.lower() not in CARD_TYPES for t in card.types) \
            or "herbal" in (x.lower() for x in card.subtypes):
        return []
    return [_f("question", "no-cost",
               "No mana cost, so it can't be cast. Is it the back face of another card, a token, or a card that starts outside the deck?",
               card, "give it a cost, or mark it as a back face (back_of) / token / bag card in MSE Studio")]


# ---------- deck level ----------

def check_deck(deck: Deck) -> list[Finding]:
    out: list[Finding] = []
    names = {c.base_name for c in deck.cards} | {c.name for c in deck.cards}

    # keywords
    for kw in deck.keywords:
        if kw.keyword != kw.keyword.strip():
            out.append(_f("error", "keyword-space", f"Deck keyword “{kw.keyword}” has extra spaces around its name."))
        if "CARDNAME>" in kw.reminder or "this_or_that(" in kw.reminder or "(param" in kw.reminder:
            out.append(_f("error", "keyword-template", f"Reminder text of “{kw.name}” still has template code: “{kw.reminder}”."))
        elif re.search(r"\w  +\w", kw.reminder):
            out.append(_f("error", "keyword-template",
                          f"Reminder text of “{kw.name}” has a blank where a name should be: “{kw.reminder}”.",
                          fix="write “this creature” (or the card's name) in the gap"))
        clash = next((fk for fk in forge_keywords() if fk.lower() == kw.name.lower()), None)
        if clash:
            out.append(_f("question", "keyword-clash",
                          f"Deck keyword “{kw.name}” has the same name as the real Magic keyword “{clash}”, which means something else.",
                          fix=f"rename it, or confirm it should replace real {clash} in your games"))
        used = sum(1 for c in deck.cards if kw.pattern().search(c.rules_text))
        if used == 0:
            out.append(_f("info", "keyword-unused", f"Deck keyword “{kw.name}” isn't used on any card."))

    # commander
    cmd_cards = [c for c in deck.cards if c.base_name in deck.commander or c.name in deck.commander or c.is_commander]
    if not cmd_cards:
        out.append(_f("error", "commander-missing", f"Commander {deck.commander} isn't among the cards."))
    identity: set[str] = set()
    for c in cmd_cards:
        if not c.mana_cost:
            out.append(_f("error", "commander-no-cost",
                          "Commander has no mana cost, so it can't be cast from the command zone.", c))
        if not (c.has_type("Creature") and any(s.lower() == "legendary" for s in c.supertypes)) \
                and "can be your commander" not in c.rules_text:
            out.append(_f("error", "commander-type", "Commander isn't a legendary creature.", c))
        identity |= cost_colors(c.mana_cost) | cost_colors(c.rules_text) | set(c.color_identity.upper())
    if deck.format == "commander" and cmd_cards:
        outside = [c for c in deck.cards if c.count > 0 and not c.is_token
                   and (set(c.color_identity.upper()) | cost_colors(c.mana_cost)) - identity]
        if outside:
            ident = "".join(sorted(identity, key="WUBRG".index)) or "colorless"
            out.append(_f("error", "color-identity",
                          f"Commander's colour identity is {ident}, but {len(outside)} cards are outside it "
                          f"(e.g. {', '.join(c.name for c in outside[:4])}). Under Commander rules they're not allowed.",
                          fix="give the commander a mana cost or colour indicator, or allow it as a house rule"))

    # size and singleton
    if deck.format == "commander":
        in_list = [c for c in deck.cards if c.count > 0 and not c.is_token]
        total = sum(c.count for c in in_list)
        groups = _likely_outside_deck(deck)
        est_out = sum(len(v) for v in groups.values())
        detail = "; ".join(f"{k}: {len(v)}" for k, v in groups.items() if v)
        if total > 100:
            # often a card pool: the 100 aren't chosen yet and the rest sit out of the game
            # (Deck check lets you ignore this one)
            out.append(_f("error", "deck-size",
                          f"{total} cards, but a Commander deck is exactly 100. If this is a pool to build the deck "
                          f"from, the rest stay out of the game until you pick the 100. About {est_out} of them aren't "
                          f"deck cards anyway ({detail}), leaving ~{total - est_out} candidates.",
                          fix="pick the 100 (simulations can help decide what to cut), or ignore this while it's a pool"))
        elif total < 100:
            out.append(_f("error", "deck-size", f"Only {total} cards; a Commander deck is exactly 100."))
        for base, g in art_groups(deck).items():
            versions = ", ".join(c.name for c in g["all"])
            if g["mixup"]:
                blank_cards = [c for c in g["all"] if not is_art_card(c) and not (c.rules_text.strip() or c.mana_cost)]
                out.append(_f("error", "art-mixup",
                              f"{', '.join(c.name for c in g['mixup'])} is marked “Art Card”, but it's the only version of "
                              f"“{base}” with a cost and rules text"
                              + (f", while {', '.join(c.name for c in blank_cards)} (blank) is still a playable card type"
                                 if blank_cards else "") + ". The card would have nothing to play.",
                              fix="mark the blank versions as Art Card and give the full one its real type back"))
            if g["blank"] and not g["mixup"]:
                out.append(_f("info", "art-blank",
                              f"{', '.join(c.name for c in g['blank'])}: art only. "
                              f"Played with {g['main'].name}'s cost and text.",
                              fix="nothing to do; or copy the text over so the printed cards match"))
            if g["same"]:
                if len(g["texts"]) > 1:
                    out.append(_f("info", "alt-arts",
                                  f"“{base}” has {len(g['all'])} arts ({versions}). The wording differs a little but "
                                  f"means the same, so they're one card; the engine uses {g['main'].name}'s text."))
            else:
                out.append(_f("error", "singleton",
                              f"“{base}” is the name of {len(g['texts'])} different cards ({versions}): "
                              "their rules don't match, so they aren't alternate arts.",
                              fix="give the different cards different names (or make the arts' texts match)"))
    return out


def _meaning(card: Card) -> str:
    """Rules text with wording-only differences removed: the card's own name, "also",
    punctuation and spacing."""
    t = card.rules_text.lower()
    for n in sorted({card.base_name, card.short_name}, key=len, reverse=True):
        t = t.replace(n.lower(), "~")
    t = re.sub(r"\balso\b", " ", t)
    t = re.sub(r"[^\w{}/+~-]+", " ", t)
    return " ".join([card.mana_cost, "/".join(card.types), card.power, card.toughness, t.strip()])


def is_art_card(card: Card) -> bool:
    """Marked as an art card in MSE Studio (type line "Art Card"): a picture only."""
    return any(t.lower() == "art" for t in card.types)


def art_groups(deck: Deck) -> dict[str, dict]:
    """Cards sharing a name ([Art N] versions): one card with several arts, or
    different cards that happen to share a name. Basic lands aren't grouped.

    Art-only versions (marked "Art Card", or with no cost and no text) play with
    the full version's cost and text; `mixup` lists art-marked versions that are
    the only ones carrying the card's game text."""
    by_base: dict[str, list[Card]] = defaultdict(list)
    for c in deck.cards:
        if c.count <= 0 or c.is_token or c.real or c.base_name.lower() in BASIC_LANDS \
                or any(s.lower() == "basic" for s in c.supertypes):
            continue
        by_base[c.base_name].append(c)
    groups = {}
    for base, cs in by_base.items():
        if len(cs) < 2:
            continue
        has_text = lambda c: bool(c.rules_text.strip() or c.mana_cost)
        art_only = [c for c in cs if is_art_card(c) or not has_text(c)]
        played = [c for c in cs if c not in art_only and has_text(c)]
        mixup = []
        if not played:
            # the game text only lives on a version marked as art
            mixup = [c for c in cs if is_art_card(c) and has_text(c)]
            played = mixup or cs
        main = max(played, key=lambda c: (len(c.rules_text), bool(c.mana_cost)))
        texts = {c.rules_text.strip() for c in played}
        groups[base] = {"all": cs, "blank": [c for c in art_only if c not in played], "main": main,
                        "mixup": mixup, "texts": texts, "same": len({_meaning(c) for c in played}) == 1}
    return groups


def _likely_outside_deck(deck: Deck) -> dict[str, list[Card]]:
    g: dict[str, list[Card]] = {"tokens": [], "rules/emblem/code cards": [], "bag cards": [],
                                "probable back faces": [], "extra alt-arts": []}
    seen_base: set[str] = set()
    transform_targets = " ".join(c.rules_text for c in deck.cards).lower()
    for c in deck.cards:
        if c.count <= 0:
            continue
        tl = c.type_line.lower()
        if c.is_token or c.name.lower().endswith(" token") or "token" in tl:
            g["tokens"].append(c)
        elif any(t.lower() in ("emblem", "code") for t in c.types) or "rules" in tl or "emblem" in tl:
            g["rules/emblem/code cards"].append(c)
        elif "herbal" in [s.lower() for s in c.subtypes] and not c.mana_cost:
            g["bag cards"].append(c)
        elif not c.mana_cost and not c.has_type("Land") and c.base_name.lower() not in transform_targets:
            g["probable back faces"].append(c)
        elif not c.mana_cost and not c.has_type("Land") and c.short_name.lower() in transform_targets:
            g["probable back faces"].append(c)
        elif is_art_card(c) or (c.base_name in seen_base and c.base_name.lower() not in BASIC_LANDS):
            g["extra alt-arts"].append(c)
        seen_base.add(c.base_name)
    return g


def check_real_cards(deck: Deck) -> list[Finding]:
    """Custom entries whose name is a real card: real card, or a name clash."""
    out = []
    names = real_card_names()
    basics = [c for c in deck.cards if c.base_name in names and not c.real and c.base_name.lower() in BASIC_LANDS]
    if basics:
        out.append(_f("info", "real-basics",
                      f"{len(basics)} basic lands (e.g. {basics[0].name}) aren't marked “real”; the engine will treat them as the real basics."))
    for c in deck.cards:
        if c.real or c.base_name.lower() in BASIC_LANDS or c.base_name not in names:
            continue
        out.append(_f("question", "real-name",
                      f"“{c.base_name}” is also the name of a real Magic card. Is this the real card or your own?", c,
                      "mark it real: true in MSE Studio, or rename it"))
    return out


def run_all(deck: Deck) -> list[Finding]:
    names = {c.base_name for c in deck.cards} | {c.short_name for c in deck.cards}
    kws = {k.name for k in deck.keywords}
    out = check_deck(deck) + check_real_cards(deck)
    art_only = {c.id for g in art_groups(deck).values() for c in g["blank"]}
    for c in deck.cards:
        if c.real or c.id in art_only or is_art_card(c):
            continue
        text = check_text(c, names)
        wrong = " ".join(f.message for f in text if f.code == "wrong-self-name")
        leftovers = [f for f in check_leftover_names(c, names, kws) if f.message.split("“")[1].split("”")[0] not in wrong]
        out += check_mana(c) + check_types(c) + check_pt(c) + text + leftovers + check_castable(c)
    return _group(out)


def _group(findings: list[Finding]) -> list[Finding]:
    """Collapse per-card notes that are really one deck-wide pattern."""
    out = [f for f in findings if f.code not in ("compact-symbol", "split-subtype", "custom-type")]
    compact = [f for f in findings if f.code == "compact-symbol"]
    if compact:
        ex = sorted({f.message for f in compact})[:4]
        out.append(Finding("info", "compact-symbol",
                           f"{len({f.card for f in compact})} cards write several mana symbols in one pair of braces "
                           f"({'; '.join(ex)} …). The converter reads these fine, but other tools won't.",
                           fix="optionally have MSE Studio's export write one symbol per brace"))
    split = defaultdict(list)
    for f in findings:
        if f.code == "split-subtype":
            split[f.message].append(f.card)
    if split:
        listing = "; ".join(f"“{t}” ({len(cs)})" for t, cs in sorted(split.items(), key=lambda kv: -len(kv[1])))
        out.append(Finding("question", "split-subtype",
                           f"Multi-word subtypes are split word by word, so e.g. “Curiosity Card” becomes the two types "
                           f"Curiosity and Card. Affected: {listing}.",
                           fix="say which are one type (e.g. Shogi Piece → one subtype “Shogi-Piece”), and drop filler words like “Card”, “of”, “The”"))
    ctypes = defaultdict(list)
    for f in findings:
        if f.code == "custom-type":
            ctypes[f.message].append(f.card)
    for t, cs in ctypes.items():
        out.append(Finding("info", "custom-type",
                           f"Card type “{t}” doesn't exist in Magic ({len(cs)} cards, e.g. {', '.join(cs[:3])}). "
                           "The engine has to be told what it does and which zone these cards start in."))
    return out
