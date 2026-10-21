"""python -m deckcheck DECK.deck.json [...] [--out DIR]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .checks import run_all
from .history import compare
from .deck import load_deck
from .mechanics import classify


def analyse(path, previous=None):
    deck = load_deck(path)
    findings = run_all(deck)
    results, more = classify(deck)
    if previous is not None:
        from .history import snapshot
        findings = compare(snapshot(load_deck(previous)), deck) + findings
    return deck, results, findings + more


def main(argv=None):
    ap = argparse.ArgumentParser(prog="deckcheck", description="Check MSE Studio decks before converting them for the engine.")
    ap.add_argument("decks", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, help="write report.html, report.json and cards.csv here")
    ap.add_argument("--text", action="store_true", help="print findings as plain text")
    ap.add_argument("--previous", type=Path, help="an earlier export of the (single) deck, to check ids stayed put")
    a = ap.parse_args(argv)
    if a.previous and len(a.decks) != 1:
        ap.error("--previous works with one deck")

    analysed = [analyse(p, a.previous) for p in a.decks]
    if a.text or not a.out:
        for deck, results, findings in analysed:
            print(f"\n=== {deck.name}")
            tiers = {}
            for r in results:
                tiers[r.tier] = tiers.get(r.tier, 0) + 1
            print("tiers:", tiers)
            for f in findings:
                print(f"[{f.kind}] {f.code} | {f.card} | {f.message}" + (f"  -> {f.fix}" if f.fix else ""))
    if a.out:
        from .report import write_reports
        write_reports(analysed, a.out)
        print(f"Report written to {a.out / 'report.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
