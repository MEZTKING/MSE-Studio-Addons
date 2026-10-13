"""Card prices: what the real cards of a deck (or a decklist) cost at
TCGplayer (US dollars) and Cardmarket (euros), the cheapest printing of each,
totals per store and the cheapest mix of the two, in your currency.

Prices are Scryfall's: TCGplayer's market price and Cardmarket's trend price,
updated once a day. They come from the Card database add-on's file when it's
there (no waiting), else from Scryfall. Exchange rates are the European
Central Bank's, from frankfurter.app."""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from mse_studio.core import addons

SCRYFALL = "https://api.scryfall.com"
FX_APIS = ("https://api.frankfurter.dev/v1/latest?base=USD",     # Frankfurter, now
           "https://api.frankfurter.app/latest?from=USD")         # and its old address
STORES = {"tcgplayer": "TCGplayer", "cardmarket": "Cardmarket"}
CURRENCIES = {"USD": "$", "EUR": "€", "GBP": "£", "AUD": "A$", "CAD": "C$", "NZD": "NZ$",
              "JPY": "¥", "SEK": "kr ", "PLN": "zł "}
_last = [0.0]


def _get(url: str, data: Optional[dict] = None, timeout: float = 30) -> dict:
    """Scryfall: no more than two searches a second, as it asks."""
    if "scryfall.com" in url:
        wait = 0.55 - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": "MSE-Studio card prices", "Accept": "application/json",
        **({"Content-Type": "application/json"} if body else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def database() -> Optional[Path]:
    """The Card database add-on's file, if there is one (read only)."""
    p = addons.config_dir() / "addon-data" / "card-database" / "cards.sqlite"
    return p if p.is_file() and p.stat().st_size > 0 else None


def data_dir() -> Path:
    return addons.data_dir("card-prices")


# ------------------------------------------------------------------ prices
@dataclass
class Price:
    name: str
    count: int = 1
    usd: Optional[float] = None          # TCGplayer, each
    eur: Optional[float] = None          # Cardmarket, each
    usd_set: str = ""                    # the printing that price is for
    eur_set: str = ""
    tcgplayer: str = ""                  # links to buy it
    cardmarket: str = ""
    found: bool = False


def _num(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _keys(foil: bool) -> tuple[str, str]:
    return ("usd_foil", "eur_foil") if foil else ("usd", "eur")


def _apply(p: Price, printings: list[dict], foil: bool) -> None:
    """The cheapest printing at each store (printings: Scryfall-like dicts)."""
    ku, ke = _keys(foil)
    for c in printings:
        u, e = _num((c.get("prices") or {}).get(ku)), _num((c.get("prices") or {}).get(ke))
        label = f"{c.get('set_name', '')} ({str(c.get('set', '')).upper()})".strip()
        buy = c.get("purchase_uris") or {}
        if u is not None and (p.usd is None or u < p.usd):
            p.usd, p.usd_set, p.tcgplayer = u, label, buy.get("tcgplayer", p.tcgplayer)
        if e is not None and (p.eur is None or e < p.eur):
            p.eur, p.eur_set, p.cardmarket = e, label, buy.get("cardmarket", p.cardmarket)
        p.tcgplayer = p.tcgplayer or buy.get("tcgplayer", "")
        p.cardmarket = p.cardmarket or buy.get("cardmarket", "")
        p.found = True


def has_every_printing(path: Path) -> bool:
    """Was the card database made from a bulk file with every printing (so it
    knows each card's cheapest one)?"""
    try:
        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = 'kind'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return bool(row) and row[0] in ("default_cards", "all_cards")


def _from_database(path: Path, prices: list[Price], cheapest: bool, foil: bool) -> None:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    ku, ke = _keys(foil)
    try:
        for p in prices:
            lname = p.name.lower()
            rows = conn.execute("SELECT * FROM cards WHERE lname = ? OR lname LIKE ? "
                                "ORDER BY released DESC", (lname, lname + " // %")).fetchall()
            if not rows:
                continue
            if not cheapest:
                rows = rows[:1]
            _apply(p, [{"prices": {ku: r[ku], ke: r[ke]}, "set": r["set_code"],
                        "set_name": r["set_name"],
                        "purchase_uris": {"tcgplayer": r["tcgplayer"],
                                          "cardmarket": r["cardmarket"]}} for r in rows], foil)
    finally:
        conn.close()


def _from_scryfall(prices: list[Price], cheapest: bool, foil: bool,
                   progress: Callable[[int, int, str], None], cancel=None,
                   get: Callable = _get) -> None:
    todo = [p for p in prices if not p.found]
    if cheapest:
        for k, p in enumerate(todo):
            if cancel is not None and getattr(cancel, "cancelled", False):
                return
            progress(k, len(todo), f"Prices of every printing: {p.name}")
            q = urllib.parse.quote(f'!"{p.name}"')
            url = f"{SCRYFALL}/cards/search?q={q}&unique=prints"
            try:
                while url:
                    res = get(url)
                    _apply(p, res.get("data") or [], foil)
                    url = res.get("next_page") if res.get("has_more") else ""
            except Exception:  # noqa: BLE001 - no such card, or Scryfall busy
                continue
        return
    for i in range(0, len(todo), 75):
        if cancel is not None and getattr(cancel, "cancelled", False):
            return
        chunk = todo[i:i + 75]
        progress(i, len(todo), "Prices from Scryfall…")
        try:
            res = get(f"{SCRYFALL}/cards/collection",
                      {"identifiers": [{"name": p.name} for p in chunk]})
        except Exception:  # noqa: BLE001
            continue
        by = {}
        for c in res.get("data") or []:
            by[c.get("name", "").lower()] = c
            for f in c.get("card_faces") or []:
                by.setdefault(f.get("name", "").lower(), c)
        for p in chunk:
            c = by.get(p.name.lower())
            if c is not None:
                _apply(p, [c], foil)


def look_up(cards: list[tuple[str, int]], cheapest: bool = True, foil: bool = False,
            progress: Optional[Callable[[int, int, str], None]] = None, cancel=None,
            get: Callable = _get, db: Optional[Path] = None) -> list[Price]:
    """Prices for [(name, copies)]: from the card database first, Scryfall
    for the rest."""
    say = progress or (lambda d, t, m: None)
    merged: dict[str, Price] = {}
    for name, n in cards:
        key = name.split(" // ")[0].strip()
        if not key:
            continue
        if key.lower() in merged:
            merged[key.lower()].count += n
        else:
            merged[key.lower()] = Price(key, n)
    prices = list(merged.values())
    path = db if db is not None else database()
    if path is not None and Path(path).is_file() and (not cheapest or has_every_printing(path)):
        say(0, 0, "Prices from the card database…")
        _from_database(path, prices, cheapest, foil)
    _from_scryfall(prices, cheapest, foil, say, cancel, get)
    return prices


# ------------------------------------------------------------------ money
def rates(get: Callable = _get, max_age_h: float = 12) -> dict[str, float]:
    """1 US dollar in other currencies (ECB rates via Frankfurter), kept a
    few hours."""
    cache = data_dir() / "rates.json"
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if time.time() - saved.get("time", 0) < max_age_h * 3600:
            return saved["rates"]
    except (OSError, ValueError, KeyError):
        saved = None
    for url in FX_APIS:
        try:
            res = get(url)
            out = {"USD": 1.0, **{k: float(v) for k, v in (res.get("rates") or {}).items()}}
        except Exception:  # noqa: BLE001 - try the next; old rates are better than none
            continue
        if len(out) > 1:
            cache.write_text(json.dumps({"time": time.time(), "rates": out}), encoding="utf-8")
            return out
    return saved["rates"] if saved else {"USD": 1.0}


def convert(amount: Optional[float], frm: str, to: str, fx: dict[str, float]) -> Optional[float]:
    if amount is None:
        return None
    if frm == to:
        return amount
    if frm not in fx or to not in fx:
        return None
    return amount / fx[frm] * fx[to]


def money(amount: Optional[float], currency: str) -> str:
    if amount is None:
        return "–"
    sym = CURRENCIES.get(currency, currency + " ")
    return f"{sym}{amount:,.0f}" if currency == "JPY" else f"{sym}{amount:,.2f}"


@dataclass
class Totals:
    tcgplayer: float = 0.0
    cardmarket: float = 0.0
    cheapest: float = 0.0
    missing_tcg: int = 0
    missing_cm: int = 0
    missing_both: int = 0
    cheapest_store: dict = None       # name -> "tcgplayer" | "cardmarket"
    both: int = 0                     # copies priced at both stores…
    both_tcgplayer: float = 0.0       # …and what they cost at each
    both_cardmarket: float = 0.0


def totals(prices: list[Price], currency: str, fx: dict[str, float]) -> Totals:
    t = Totals(cheapest_store={})
    for p in prices:
        u = convert(p.usd, "USD", currency, fx)
        e = convert(p.eur, "EUR", currency, fx)
        if u is not None:
            t.tcgplayer += u * p.count
        else:
            t.missing_tcg += p.count
        if e is not None:
            t.cardmarket += e * p.count
        else:
            t.missing_cm += p.count
        if u is not None and e is not None:
            t.both += p.count
            t.both_tcgplayer += u * p.count
            t.both_cardmarket += e * p.count
        best = min((x for x in ((u, "tcgplayer"), (e, "cardmarket")) if x[0] is not None),
                   default=None)
        if best is None:
            t.missing_both += p.count
        else:
            t.cheapest += best[0] * p.count
            t.cheapest_store[p.name] = best[1]
    return t


# ------------------------------------------------------------------ buying
def tcgplayer_mass_entry(prices: list[Price]) -> str:
    """TCGplayer's Mass Entry page with the cards filled in."""
    lines = "||".join(f"{p.count} {p.name}" for p in prices)
    return "https://www.tcgplayer.com/massentry?productline=Magic&c=" + urllib.parse.quote(lines)


def wants_list(prices: list[Price]) -> str:
    """"1 Sol Ring" lines: Cardmarket's Wants lists (and most stores) take them."""
    return "\n".join(f"{p.count} {p.name}" for p in prices) + "\n"


def csv_text(prices: list[Price], currency: str, fx: dict[str, float]) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Count", "Card", f"TCGplayer ({currency})", "TCGplayer printing",
                f"Cardmarket ({currency})", "Cardmarket printing"])
    for p in prices:
        u, e = convert(p.usd, "USD", currency, fx), convert(p.eur, "EUR", currency, fx)
        w.writerow([p.count, p.name, f"{u:.2f}" if u is not None else "", p.usd_set,
                    f"{e:.2f}" if e is not None else "", p.eur_set])
    return buf.getvalue()
