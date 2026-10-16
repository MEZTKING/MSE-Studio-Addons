"""Goldfishing the deck: opening hands, mulligans, draws, and the odds of
having what you need by a given turn. (Until MSE Studio 0.25 this was
mse_studio.core.playtest.)"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from math import comb
from typing import Callable, Optional

from mse_studio.core import deck_guide, deck_stats

HAND = 7


@dataclass
class Game:
    """One game. Cards are indices into the deck's card list."""
    deck: list[int]
    commander: Optional[int] = None
    seed: Optional[int] = None
    free_mulligan: bool = True  # multiplayer Commander: the first mulligan is free
    library: list[int] = field(default_factory=list)
    hand: list[int] = field(default_factory=list)
    battlefield: list[int] = field(default_factory=list)
    graveyard: list[int] = field(default_factory=list)
    tapped: set = field(default_factory=set)
    life: int = 40
    poison: int = 0
    turn: int = 0
    mulligans: int = 0
    to_bottom: int = 0          # London mulligan: cards still to put on the bottom
    log: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.rng = random.Random(self.seed)
        self.new_game()

    def new_game(self):
        self.library = [i for i in self.deck if i != self.commander]
        self.rng.shuffle(self.library)
        self.hand, self.battlefield, self.graveyard = [], [], []
        self.tapped, self.life, self.poison = set(), 40, 0
        self.turn, self.mulligans, self.to_bottom = 0, 0, 0
        self.log = ["New game – shuffled"]
        self.draw(HAND)

    def draw(self, n: int = 1) -> list[int]:
        got = self.library[:n]
        del self.library[:n]
        self.hand += got
        return got

    def mulligan(self):
        """London mulligan: shuffle the hand back, draw seven, then put one card
        on the bottom for each mulligan (the first one is free in multiplayer)."""
        self.library += self.hand
        self.hand = []
        self.rng.shuffle(self.library)
        self.mulligans += 1
        self.draw(HAND)
        self.to_bottom = min(self.mulligans - (1 if self.free_mulligan else 0), len(self.hand))
        self.log.append(f"Mulligan {self.mulligans} – put {self.to_bottom} on the bottom")

    def bottom(self, card: int):
        if card in self.hand and self.to_bottom > 0:
            self.hand.remove(card)
            self.library.append(card)
            self.to_bottom -= 1

    def to_top(self, card: int):
        if card in self.hand:
            self.hand.remove(card)
            self.library.insert(0, card)

    def to_library_bottom(self, card: int):
        if card in self.hand:
            self.hand.remove(card)
            self.library.append(card)

    def discard(self, card: int):
        self.tapped.discard(card)
        for zone in (self.hand, self.battlefield):
            if card in zone:
                zone.remove(card)
                self.graveyard.append(card)
                return

    def to_hand(self, card: int):
        self.tapped.discard(card)
        for zone in (self.battlefield, self.graveyard):
            if card in zone:
                zone.remove(card)
                self.hand.append(card)
                return

    def tap(self, card: int):
        if card in self.battlefield:
            self.tapped ^= {card}

    def next_turn(self, on_play: bool = True):
        self.turn += 1
        self.tapped.clear()                     # untap step
        if not (on_play and self.turn == 1):
            self.draw(1)
        self.log.append(f"Turn {self.turn}")

    def play(self, card: int):
        if card in self.hand:
            self.hand.remove(card)
            self.battlefield.append(card)


# ------------------------------------------------------------------ odds
def at_least(population: int, successes: int, draws: int, k: int) -> float:
    """Hypergeometric: chance of at least ``k`` successes in ``draws`` cards."""
    draws = max(0, min(draws, population))
    if k <= 0:
        return 1.0
    total = comb(population, draws)
    if total == 0:
        return 0.0
    miss = sum(comb(successes, i) * comb(population - successes, draws - i)
               for i in range(0, min(k, successes + 1)) if draws - i >= 0)
    return max(0.0, min(1.0, 1 - miss / total))


def cards_seen(turn: int, on_play: bool = True) -> int:
    """Cards seen by your ``turn``-th turn (opening seven plus draws)."""
    return HAND + max(0, turn - (1 if on_play else 0))


def by_turn(population: int, successes: int, k: int, turns: int = 10,
            on_play: bool = True) -> list[float]:
    return [at_least(population, successes, cards_seen(t, on_play), k)
            for t in range(1, turns + 1)]


def simulate(flags: list[bool], trials: int = 10000, seed: int = 1) -> dict:
    """Opening hands: how often 0..7 'flagged' cards (usually lands) show up."""
    rng = random.Random(seed)
    counts = [0] * (HAND + 1)
    idx = list(range(len(flags)))
    if len(idx) < HAND:
        return {"counts": counts, "average": 0.0, "keepable": 0.0}
    for _ in range(trials):
        n = sum(1 for i in rng.sample(idx, HAND) if flags[i])
        counts[n] += 1
    avg = sum(i * c for i, c in enumerate(counts)) / trials
    keep = sum(counts[2:6]) / trials
    return {"counts": counts, "average": round(avg, 2), "keepable": round(keep * 100, 1)}


# ------------------------------------------------------------- what to count
def matchers(project) -> dict[str, Callable]:
    """Things to look for: lands, card types, roles, single cards."""
    out: dict[str, Callable] = {
        "Lands": lambda c: "land" in deck_stats.card_types(c),
        "Mana sources (lands + rocks/dorks)": lambda c: bool(deck_stats.produces(c)),
    }
    for t in ("creature", "instant", "sorcery", "artifact", "enchantment", "planeswalker"):
        out[t.capitalize() + "s"] = (lambda t: lambda c: t in deck_stats.card_types(c))(t)
    for r in deck_guide.ROLES:
        out[f"Role: {deck_guide.ROLE_LABELS[r]}"] = (
            lambda r: lambda c: r in deck_guide.roles_for(project, c)[0])(r)
    return out
