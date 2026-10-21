"""Deck check: the AI on the deck's keywords – only when AI is switched on in
MSE Studio (Settings → Advanced → Experimental → AI) and that MSE Studio has
``mse_studio.ai.keyword_check``; otherwise there's no button and no word of it.

*Check keywords with AI* sends the open deck's keywords (and a few cards
using each) to the AI service set in MSE Studio, which never shows this add-on
the key. What it says is kept in the add-on's data folder (ai_keywords.json,
for each deck and keyword as it was when asked) and comes back on every check:

- a keyword that doesn't work as written → Fix in MSE Studio (with better
  reminder text when the AI has one),
- what only you can decide about it → Questions for you (answered and copied
  like the others),
- one that could be clearer, how the engine could run a keyword the mechanics
  file doesn't know yet, and notes about the keywords together → Good to know.

A keyword changed since it was asked about is left out until it's asked again."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PySide6.QtWidgets import QPushButton

from mse_studio.core import addons
from mse_studio.gui.common import error, info

from .deckcheck.checks import Finding
from .deckcheck.mechanics import TIER_LABEL, knowledge
from .deckcheck.report import TITLES

ADDON_ID = "deck-check"
FILE = "ai_keywords.json"
TIP = ("Ask the AI set in MSE Studio whether each of the deck's keywords works as written, what "
       "you still have to decide about it, and how the engine could run it")
TITLES.update({
    "ai-keyword": "Keywords the AI says don't work as written",
    "ai-keyword-question": "Deck keywords: what the AI asks",
    "ai-keyword-unclear": "Keywords the AI finds unclear",
    "ai-keyword-tier": "How the engine could run them (the AI's guess)",
    "ai-keyword-deck": "The AI on the keywords together",
    "ai-keyword-stale": "Changed since the AI looked",
})


def _ai():
    """MSE Studio's AI for add-ons and its keyword check, or None (an older
    MSE Studio, or AI switched off)."""
    try:
        from mse_studio.ai import for_addons, keyword_check
    except ImportError:
        return None
    return for_addons, keyword_check


def available(settings) -> bool:
    got = _ai()
    return got is not None and bool(getattr(got[0], "enabled", lambda s: False)(settings))


def fingerprint(dk) -> str:
    """The keyword as it was when the AI was asked."""
    return hashlib.sha1(f"{dk.name}|{dk.match}|{dk.reminder}".encode()).hexdigest()[:12]


def _file() -> Path:
    return Path(addons.data_dir(ADDON_ID)) / FILE


def load() -> dict:
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    f = _file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


def findings_for(deck, results, saved: dict) -> list[Finding]:
    """What the AI said about ``deck``'s keywords (``saved``: load()[deck name]),
    as findings. Cards using a keyword the mechanics file doesn't know get the
    AI's guess in their reasons (and Manual when it says so)."""
    got = _ai()
    if got is None or not saved:
        return []
    verdict_of = got[1].KeywordVerdict.from_dict
    kws = saved.get("keywords") or {}
    known = knowledge()["keywords"]
    out, stale = [], []
    for dk in deck.keywords:
        d = kws.get(dk.name.lower())
        if not isinstance(d, dict):
            continue
        if d.get("asked") != fingerprint(dk):
            stale.append(dk.name)
            continue
        v = verdict_of(d)
        if v.verdict == "problem":
            fix = f"reminder text: ({v.reminder})" if v.reminder else \
                "change it on MSE Studio's Keywords page"
            for p in v.problems or ["It doesn't work as written."]:
                out.append(Finding("error", "ai-keyword", f"{dk.name}: {p}", fix=fix))
        elif v.verdict == "unclear":
            fix = f"clearer reminder text: ({v.reminder})" if v.reminder else ""
            for p in v.problems or ["It could be read more than one way."]:
                out.append(Finding("info", "ai-keyword-unclear", f"{dk.name}: {p}", fix=fix))
        for q in v.questions:
            out.append(Finding("question", "ai-keyword-question", f"{dk.name}: {q}"))
        if v.tier and dk.name.lower() not in known:
            out.append(Finding("info", "ai-keyword-tier",
                               f"{dk.name}: {TIER_LABEL.get(v.tier, v.tier)}"
                               + (f" – {v.how}" if v.how else "")))
            for r in results:
                if dk.name not in r.keywords:
                    continue
                old = f"{dk.name}: not classified yet"
                new = f"{dk.name}: {v.how or TIER_LABEL.get(v.tier, v.tier)} (the AI's guess)"
                r.reasons = [new if x == old else x for x in r.reasons]
                if v.tier == "manual":
                    r.raise_to("manual", new)
    for n in saved.get("notes") or []:
        out.append(Finding("info", "ai-keyword-deck", str(n)))
    if stale:
        out.append(Finding("info", "ai-keyword-stale",
                           f"Changed since the AI looked at them: {', '.join(stale)}.",
                           fix="Check keywords with AI again"))
    return out


class KeywordAI:
    """The page's *Check keywords with AI* button and what it found."""

    def __init__(self, page):
        self.page = page
        self.jobs: list = []
        self.saved = load()
        self.btn = QPushButton("Check keywords with AI")
        self.btn.setToolTip(TIP)
        self.btn.clicked.connect(self.ask)
        self.btn.setVisible(available(page.main.settings))     # AI switched off: none

    def apply(self, analysed) -> None:
        """Add what the AI said to each checked deck (after every check)."""
        for deck, results, findings in analysed:
            more = findings_for(deck, results, self.saved.get(deck.name) or {})
            classified = {f.message.split(":")[0] for f in more if f.code == "ai-keyword-tier"}
            if classified:
                findings[:] = [f for f in findings if not (
                    f.code == "keyword-unclassified"
                    and any(f"“{k}”" in f.message for k in classified))]
            findings.extend(more)

    def ask(self) -> None:
        got = _ai()
        cur = self.page._current()
        if got is None or cur is None or self.jobs or not available(self.page.main.settings):
            return
        for_addons, keyword_check = got
        why = for_addons.not_ready(self.page.main.settings)
        if why:
            error(self.page, "Deck check", why)
            return
        deck = cur[0]
        if not deck.keywords:
            info(self.page, "Deck check", f"{deck.name} has no keywords of its own.")
            return
        settings = self.page.main.settings
        kws = [keyword_check.as_dict(k) for k in deck.keywords]
        uses = keyword_check.cards_using(kws, [(c.name, c.rules_text) for c in deck.cards
                                               if not c.real])
        asked = {dk.name.lower(): fingerprint(dk) for dk in deck.keywords}
        name = deck.name

        def run(progress=None, cancel=None):
            found, notes = keyword_check.check_keywords(settings, kws, uses, name,
                                                        engine=True, progress=progress)
            return name, asked, found, notes
        from mse_studio.gui.common import Job, start
        job = Job(run, label="Asking the AI about the keywords")
        job.signals.finished.connect(self._answered)
        job.signals.failed.connect(self._failed)
        job.signals.cancelled.connect(self._stopped)
        self.jobs.append(start(job))
        self.btn.setEnabled(False)
        self.btn.setText("Asking the AI…")
        self.btn.setToolTip(f"Asking {for_addons.service(settings)} – Stop (or Esc) cancels it")

    def _ended(self) -> None:
        self.jobs.clear()
        self.btn.setEnabled(True)
        self.btn.setText("Check keywords with AI")
        self.btn.setToolTip(TIP)

    def _answered(self, result) -> None:
        try:
            self._ended()
            name, asked, found, notes = result
            entry = {"keywords": {}, "notes": list(notes)}
            for v in found:
                d = v.to_dict()
                d["asked"] = asked.get(v.keyword.lower(), "")
                entry["keywords"][v.keyword.lower()] = d
            self.saved[name] = entry
            try:
                save(self.saved)
            except OSError:
                pass
            page = self.page
            page.check([d.path for d, _, _ in page.analysed], quiet=True)
            bad = sum(1 for v in found if v.verdict == "problem")
            asks = sum(len(v.questions) for v in found)
            info(page, "Deck check",
                 f"The AI looked at {len(found)} keyword{'s' if len(found) != 1 else ''}: "
                 f"{bad} that don't work as written (Fix in MSE Studio), {asks} question"
                 f"{'s' if asks != 1 else ''} for you, the rest under Good to know. "
                 "It can be wrong – you decide.")
        except RuntimeError:                  # the page went away
            return

    def _failed(self, msg: str) -> None:
        try:
            self._ended()
            error(self.page, "Deck check", msg)
        except RuntimeError:
            return

    def _stopped(self) -> None:
        try:
            self._ended()
        except RuntimeError:
            return

    def shutdown(self) -> None:
        from mse_studio.gui.common import forget
        forget(self.jobs)
        self.jobs.clear()
