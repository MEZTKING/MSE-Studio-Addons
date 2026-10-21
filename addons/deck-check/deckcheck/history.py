"""Compare an export with the previous export of the same deck.

The engine keys its translated cards on `id` (stays the same when a card is
renamed) and `text_hash` (changes when its game text changes), so ids that
move between exports would hand one card's translation to another card."""
from __future__ import annotations

from .checks import Finding
from .deck import Deck


def steady_ids(deck: Deck) -> bool:
    """Exported by an MSE Studio whose card ids stay with their card (it also
    writes "version" / "zone" for every card)."""
    return any("version" in c.raw or "zone" in c.raw for c in deck.cards)


def snapshot(deck: Deck) -> dict:
    return {"exported": deck.exported, "steady": steady_ids(deck),
            "cards": {c.id: [c.name, c.text_hash] for c in deck.cards}}


def compare(previous: dict, deck: Deck) -> list[Finding]:
    old = previous.get("cards") or {}
    if not old:
        return []
    out: list[Finding] = []
    old_by_name: dict[str, list[str]] = {}
    for cid, (name, _h) in old.items():
        old_by_name.setdefault(name, []).append(cid)
    new_names = {c.name for c in deck.cards}

    def renamed(c) -> bool:
        """Kept its id but took a name another card had: a rename, not a move."""
        return c.id in old and old[c.id][0] != c.name and old[c.id][0] not in new_names

    moved = [c for c in deck.cards
             if len(old_by_name.get(c.name, [])) == 1 and c.id not in old_by_name[c.name] and not renamed(c)]
    kept = [c for c in deck.cards if len(old_by_name.get(c.name, [])) == 1]
    if moved and steady_ids(deck) and not previous.get("steady"):
        # the first export with steady ids: every id is new once, nothing is mixed up
        out.append(Finding("info", "ids-renewed",
                           "This export comes from an MSE Studio whose card ids stay with their card, so every id "
                           "changed once compared with the previous export. From now on they won't move."))
        moved = []
    elif moved:
        stolen = [c for c in moved if c.id in old and old[c.id][0] != c.name]
        ex = "; ".join(f"{c.name} now has {old[c.id][0]}’s old id" for c in stolen[:3])
        out.append(Finding(
            "error", "ids-moved",
            f"{len(moved)} of {len(kept)} cards that kept their name got a different id than in the previous export"
            + (f" ({ex})" if ex else "") + ". Ids must stay with their card, or translated cards get mixed up.",
            fix="MSE Studio's export should keep each card's id (it looks like ids follow the card's position)"))
    # with ids shuffled, "kept its id" means nothing, so no renames then
    names = [] if moved else [(old[c.id][0], c.name) for c in deck.cards if renamed(c)]
    if names:
        out.append(Finding("info", "renamed", "Renamed since the last export: "
                           + "; ".join(f"{a} → {b}" for a, b in names[:10])))
    gone = sorted(set(old_by_name) - new_names - {a for a, _ in names})
    added = sorted({c.name for c in deck.cards} - set(old_by_name) - {b for _, b in names})
    if gone or added:
        out.append(Finding("info", "added-removed",
                           (f"New since the last export: {', '.join(added)}. " if added else "")
                           + (f"Gone since the last export: {', '.join(gone)}." if gone else "")))
    return out


def remember(store: dict, deck: Deck) -> dict | None:
    """Keep the last two exports of each deck in `store`; return the one to compare with."""
    entry = store.setdefault(deck.name, {})
    snap = snapshot(deck)
    cur = entry.get("current")
    if cur is None:
        entry["current"] = snap
    elif cur.get("exported") != snap["exported"] or cur.get("cards") != snap["cards"]:
        entry["previous"], entry["current"] = cur, snap
    return entry.get("previous")
