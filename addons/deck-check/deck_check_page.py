"""Deck check: reads exported decks (.deck.json, File → Export → Deck data)
and shows what the MTG engine would trip over – data to fix in MSE Studio,
wording that needs your ruling, and how each card maps onto Forge.

Only reads the files you pick. Its own data folder keeps the decks you had
open, your answers to the questions (answers.json), what you chose to ignore
(ignored.json) and each deck's last two
exports' card ids (exports.json), to warn when ids move between exports."""
from __future__ import annotations

import hashlib
import json
from html import escape as _escape
from collections import Counter, defaultdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSplitter,
                               QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from mse_studio.core import addons
from mse_studio.gui.common import error, info
from mse_studio.gui.nav import page_header

from .deckcheck.checks import run_all
from .deckcheck.deck import load_deck
from .deckcheck.history import compare, remember
from .deckcheck.mechanics import TIER_LABEL, classify
from .deckcheck.report import TITLES, ORDER, write_reports
from .deck_check_ai import KeywordAI

ADDON_ID = "deck-check"
# rulings about whole mechanics first: one answer settles many cards
QUESTION_ORDER = ["searches-itself", "keyword-ruling", "ai-keyword-question", "card-ruling", "keyword-clash", "unknown-keyword", "loyalty-on-nonwalker",
                  "permanent-imperative", "spell-etb", "no-cost", "singleton", "real-name", "split-subtype"]
TIER_COLOR = {"script": "#3a9a5f", "engine": "#c98a1a", "manual": "#d9534f", "reference": "#8a93a0"}


def escape(text: str) -> str:
    """For the detail panel's rich text: <, > and & only, so apostrophes and
    quotes stay as they are."""
    return _escape(text, quote=False)


def _data_file(name: str) -> Path:
    return Path(addons.data_dir(ADDON_ID)) / name


def _load_json(name: str, default):
    try:
        data = json.loads(_data_file(name).read_text(encoding="utf-8"))
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _save_json(name: str, data) -> None:
    f = _data_file(name)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


def _question_key(deck_name: str, f) -> str:
    """Stays the same when the deck is checked again, so answers come back. Uses the
    card's name rather than its id: ids can move between exports."""
    return hashlib.sha1(f"{deck_name}|{f.code}|{f.card}|{f.message}".encode()).hexdigest()[:16]


IGNORE_ROLE = Qt.UserRole + 1
# deck-wide notes whose wording changes with the numbers in them: ignoring one
# keeps it ignored when the counts change
WHOLE_DECK = {"deck-size", "ids-moved", "compact-symbol", "split-subtype", "custom-type", "color-identity"}


def _ignore_key(deck_name: str, f) -> str:
    text = "" if f.code in WHOLE_DECK else f.message
    return hashlib.sha1(f"ignore|{deck_name}|{f.code}|{f.card}|{text}".encode()).hexdigest()[:16]


class DeckCheckPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.analysed: list = []          # (deck, results, findings)
        self._deck_name = ""
        self.answers: dict = _load_json("answers.json", {})
        self.ignored: set = set(_load_json("ignored.json", []))
        self._ignore_btns: dict = {}

        lay = QVBoxLayout(self)
        lay.addWidget(page_header(
            "Deck check", "Checks exported decks (.deck.json) for the MTG engine: what to fix, what needs "
                          "your ruling, and which cards the Forge rules engine can run."))

        bar = QHBoxLayout()
        b = QPushButton("Open decks…")
        b.setToolTip("Pick .deck.json files (File → Export → Deck data → MSE Studio deck file)")
        b.clicked.connect(self.pick)
        bar.addWidget(b)
        self.again = QPushButton("Check again")
        self.again.setToolTip("Read the files again – after you've exported them again")
        self.again.clicked.connect(lambda: self.check([d.path for d, _, _ in self.analysed]))
        bar.addWidget(self.again)
        self.quick = QPushButton("Quick export")
        self.quick.setToolTip("Export the deck open in MSE Studio as a deck file again – where "
                              "it went last time – and check it straight away, no windows")
        self.quick.clicked.connect(self.quick_export)
        bar.addWidget(self.quick)
        self.deck_box = QComboBox()
        self.deck_box.currentIndexChanged.connect(self.show_deck)
        bar.addWidget(self.deck_box, 1)
        self.copy_btn = QPushButton("Copy my answers")
        self.copy_btn.setToolTip("Your answers to the questions, ready to paste into the chat")
        self.copy_btn.clicked.connect(self.copy_answers)
        bar.addWidget(self.copy_btn)
        self.save_btn = QPushButton("Save report…")
        self.save_btn.setToolTip("report.html, report.json and cards.csv in a folder you choose")
        self.save_btn.clicked.connect(self.save_report)
        bar.addWidget(self.save_btn)
        self.ai = KeywordAI(self)           # only when AI is switched on in MSE Studio
        bar.addWidget(self.ai.btn)
        lay.addLayout(bar)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        lay.addWidget(self.summary)

        self.tabs = QTabWidget()
        self.errors = self._tree(["Card", "Problem", "Fix"])
        self.questions = self._tree(["Card", "Question", "Your ruling"])
        self.infos = self._tree(["Card", "Note"])
        self.answer = QPlainTextEdit()
        self.answer.setPlaceholderText("Pick a question above, then type your ruling here – it's kept as you type.")
        self.answer.setMaximumHeight(90)
        self.answer.textChanged.connect(self._answered)
        cards_tab = QWidget()
        cl = QVBoxLayout(cards_tab)
        cl.setContentsMargins(0, 6, 0, 0)
        fl = QHBoxLayout()
        self.tier_box = QComboBox()
        self.tier_box.currentIndexChanged.connect(self._filter_cards)
        fl.addWidget(self.tier_box)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search cards")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_cards)
        fl.addWidget(self.search, 1)
        cl.addLayout(fl)
        self.cards = self._tree(["Card", "Tier", "Why"])
        cl.addWidget(self.cards, 1)
        self._question_item = None
        self.tabs.addTab(self._with_detail(self.errors), "Fix in MSE Studio")
        self.tabs.addTab(self._with_detail(self.questions, self.answer), "Questions for you")
        self.tabs.addTab(self._with_detail(self.infos), "Good to know")
        cl.addWidget(self._detail_for(self.cards))
        self.tabs.addTab(cards_tab, "Every card")
        lay.addWidget(self.tabs, 1)
        self._enable()

    # --- MSE Studio calls these ----------------------------------------
    def load(self):
        if not self.analysed:
            last = [Path(p) for p in _load_json("last.json", []) if Path(p).is_file()]
            if last:
                self.check(last, quiet=True)
        self._enable()

    def refresh(self):
        pass

    def shutdown(self):
        self._store_answers()
        self.ai.shutdown()

    # --------------------------------------------------------------------
    @staticmethod
    def _tree(headers):
        t = QTreeWidget()
        t.setHeaderLabels(headers)
        t.setWordWrap(True)
        t.setUniformRowHeights(False)
        t.setAlternatingRowColors(True)
        h = t.header()
        h.setStretchLastSection(True)
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        t.setColumnWidth(0, 220)
        if len(headers) > 2:
            h.setSectionResizeMode(1, QHeaderView.Interactive)
            t.setColumnWidth(1, 460)
        return t

    def _detail_for(self, tree, extra=None) -> QWidget:
        """The selected row's full text under the list (rows are cut short)."""
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 4, 0, 0)
        label = QLabel()
        label.setTextFormat(Qt.RichText)        # Qt guesses plain text when there's no tag
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setMinimumHeight(40)
        bl.addWidget(label)
        if extra is not None:
            bl.addWidget(extra)
        if tree is not self.cards:
            row = QHBoxLayout()
            b = QPushButton("Ignore")
            b.setToolTip("Hide this from the list and the counts (it moves to Ignored at the bottom)")
            b.setEnabled(False)
            b.clicked.connect(lambda: self._toggle_ignore(tree))
            row.addWidget(b)
            row.addStretch(1)
            bl.addLayout(row)
            self._ignore_btns[tree] = b
        tree.currentItemChanged.connect(lambda cur, _prev: self._show_detail(tree, label, cur))
        return box

    def _with_detail(self, tree, extra=None) -> QSplitter:
        sp = QSplitter(Qt.Vertical)
        sp.addWidget(tree)
        sp.addWidget(self._detail_for(tree, extra))
        sp.setStretchFactor(0, 4)
        sp.setStretchFactor(1, 1)
        return sp

    def _show_detail(self, tree, label, item):
        full = item.data(2, Qt.UserRole) if item is not None else None
        label.setText((full or "").replace("\n", "<br>"))
        btn = self._ignore_btns.get(tree)
        if btn is not None:
            key = item.data(0, IGNORE_ROLE) if item is not None else None
            btn.setEnabled(bool(key))
            btn.setText("Stop ignoring" if key in self.ignored else "Ignore")
        if tree is self.questions:
            self._question_item = item if item is not None and item.data(0, Qt.UserRole) else None
            self.answer.blockSignals(True)
            self.answer.setPlainText(self._question_item.text(2) if self._question_item else "")
            self.answer.setEnabled(self._question_item is not None)
            self.answer.blockSignals(False)

    def _enable(self):
        has = bool(self.analysed)
        for w in (self.again, self.deck_box, self.copy_btn, self.save_btn, self.tabs):
            w.setEnabled(has)
        if not has:
            self.summary.setText("Open one or more exported decks to check them – or <b>Quick "
                                 "export</b> the deck open in MSE Studio and check it. In MSE "
                                 "Studio: <b>File → Export → Deck data → MSE Studio deck "
                                 "file</b>.")

    def quick_export(self):
        """The deck open in MSE Studio as a deck file again – where MSE Studio's
        Quick export last put one, else its exports folder – then checked,
        with the other decks that were open."""
        main = self.main
        project = getattr(main, "project", None)
        if project is None:
            info(self, "Deck check", "Open a deck in MSE Studio first – Quick export exports "
                                     "that deck and checks it.")
            return
        if not main.save():
            return
        path = None
        try:
            from mse_studio.gui.export_dialog import last_export
            spec = last_export(main)
            if spec and spec.get("tab") == "data" and spec.get("kind") == "deckjson":
                path = Path(spec["path"])
        except (ImportError, KeyError, TypeError):
            pass
        from mse_studio.core import deck_export
        try:
            out = Path(deck_export.export(project, path))
        except OSError as e:
            error(self, "Deck check", f"Couldn't export {project.name}: {e}")
            return
        others = [Path(d.path) for d, _, _ in self.analysed if Path(d.path) != out]
        self.check([out] + others)
        i = next((n for n, (d, _, _) in enumerate(self.analysed) if Path(d.path) == out), -1)
        if i >= 0:
            self.deck_box.setCurrentIndex(i)
        try:
            main.statusBar().showMessage(f"Deck check: exported and checked {out}", 10000)
        except (AttributeError, RuntimeError):
            pass

    def pick(self):
        start = str(Path(self.analysed[0][0].path).parent) if self.analysed else ""
        paths, _ = QFileDialog.getOpenFileNames(self, "Decks to check", start,
                                                "MSE Studio decks (*.deck.json *.json)")
        if paths:
            self.check([Path(p) for p in paths])

    def check(self, paths, quiet=False):
        done, failed = [], []
        history = _load_json("exports.json", {})
        for p in paths:
            try:
                deck = load_deck(p)
                results, more = classify(deck)
                previous = remember(history, deck)
                since = compare(previous, deck) if previous else []
                done.append((deck, results, since + run_all(deck) + more))
            except Exception as e:          # a broken file shouldn't take the page down
                failed.append(f"{Path(p).name}: {e}")
        try:
            _save_json("exports.json", history)
        except OSError:
            pass
        if failed and not quiet:
            error(self, "Deck check", "Couldn't read:\n" + "\n".join(failed))
        if not done:
            return
        keep = self.deck_box.currentText()
        self.analysed = done
        self.ai.apply(done)
        _save_json("last.json", [str(d.path) for d, _, _ in done])
        self.deck_box.blockSignals(True)
        self.deck_box.clear()
        self.deck_box.addItems([d.name for d, _, _ in done])
        i = self.deck_box.findText(keep)
        self.deck_box.setCurrentIndex(max(i, 0))
        self.deck_box.blockSignals(False)
        self._enable()
        self.show_deck()

    def _current(self):
        i = self.deck_box.currentIndex()
        return self.analysed[i] if 0 <= i < len(self.analysed) else None

    def show_deck(self, *_):
        cur = self._current()
        if not cur:
            return
        deck, results, findings = cur
        self._deck_name = deck.name
        cards = [r for r in results if not r.version_of]       # each card once, its versions under it
        n_versions = len(results) - len(cards)
        tiers = Counter(r.tier for r in cards)
        kinds = Counter(f.kind for f in findings if _ignore_key(deck.name, f) not in self.ignored)
        parts = [f'<span style="color:{TIER_COLOR[t]}"><b>{tiers[t]}</b> {TIER_LABEL[t]}</span>'
                 for t in ("script", "engine", "manual", "reference") if tiers.get(t)]
        self.summary.setText(
            f"<b>{deck.name}</b> · {len(cards)} cards"
            + (f" (+{n_versions} alternate version{'s' if n_versions != 1 else ''})" if n_versions else "")
            + f" · commander: {', '.join(deck.commander) or 'none'}<br>"
            + " &nbsp;·&nbsp; ".join(parts)
            + f" &nbsp;·&nbsp; <b>{kinds['error']}</b> to fix &nbsp;·&nbsp; <b>{kinds['question']}</b> questions")
        self.tabs.setTabText(0, f"Fix in MSE Studio ({kinds['error']})")
        self.tabs.setTabText(1, f"Questions for you ({kinds['question']})")
        self.tabs.setTabText(2, f"Good to know ({kinds['info']})")
        self.tabs.setTabText(3, f"Every card ({len(cards)})")

        self._fill(self.errors, [f for f in findings if f.kind == "error"],
                   lambda f: [f.card, f.message, f.fix])
        self._fill(self.questions, [f for f in findings if f.kind == "question"],
                   lambda f: [f.card, f.message + (f"\n→ {f.fix}" if f.fix else ""),
                              self.answers.get(_question_key(deck.name, f), "")],
                   editable=deck.name)
        self._question_item = None
        self.answer.blockSignals(True)
        self.answer.clear()
        self.answer.setEnabled(False)
        self.answer.blockSignals(False)
        self._fill(self.infos, [f for f in findings if f.kind == "info"],
                   lambda f: [f.card, f.message + (f"\n→ {f.fix}" if f.fix else "")])

        self.cards.clear()
        order = ["manual", "engine", "script", "reference"]
        alts = defaultdict(list)
        for r in results:
            if r.version_of:
                alts[r.version_of_id].append(r)
        for r in sorted(cards, key=lambda r: (order.index(r.tier), r.card.name.lower())):
            it = self._card_item(r)
            for v in sorted(alts.get(r.card.id, []), key=lambda v: v.card.name.lower()):
                it.addChild(self._card_item(v))
            if it.childCount():
                it.setText(0, f"{r.card.name}  (+{it.childCount()})")
                it.setToolTip(0, it.toolTip(0) + "\n\nOther versions: "
                              + ", ".join(it.child(i).text(0) for i in range(it.childCount())))
            self.cards.addTopLevelItem(it)
        self.tier_box.blockSignals(True)
        self.tier_box.clear()
        self.tier_box.addItem(f"All tiers ({len(cards)})", "")
        for t in order:
            if tiers.get(t):
                self.tier_box.addItem(f"{TIER_LABEL[t]} ({tiers[t]})", t)
        self.tier_box.blockSignals(False)
        self._filter_cards()

    @staticmethod
    def _card_item(r) -> QTreeWidgetItem:
        """A row on Every card: the card (or one of its versions) and its tier."""
        why = "; ".join(r.reasons)
        if r.keywords:
            why += "\nKeywords: " + ", ".join(r.keywords)
        it = QTreeWidgetItem([r.card.name, TIER_LABEL[r.tier], why])
        it.setToolTip(0, f"{r.card.type_line.strip()}\n\n{r.card.rules_text}")
        it.setData(2, Qt.UserRole, f"<b>{escape(r.card.name)}</b> · {escape(r.card.type_line.strip())} "
                                   f"{escape(r.card.mana_cost)}<br>{escape(r.card.rules_text).replace(chr(10), '<br>')}"
                                   f"<br><br><i>{escape(why).replace(chr(10), '<br>')}</i>")
        it.setForeground(1, QColor(TIER_COLOR[r.tier]))
        it.setData(1, Qt.UserRole, r.tier)
        return it

    def _fill(self, tree, findings, columns, editable=None):
        tree.clear()
        deck_name = self._deck_name
        ignored = [f for f in findings if _ignore_key(deck_name, f) in self.ignored]
        groups = defaultdict(list)
        for f in findings:
            if f not in ignored:
                groups[f.code].append(f)
        order = QUESTION_ORDER if editable is not None else ORDER
        sections = [(TITLES.get(c, c), groups[c], False)
                    for c in sorted(groups, key=lambda c: order.index(c) if c in order else 999)]
        if ignored:
            sections.append(("Ignored", ignored, True))
        for title, fs, is_ignored in sections:
            top = QTreeWidgetItem([f"{title} ({len(fs)})"])
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            top.setFirstColumnSpanned(True)
            tree.addTopLevelItem(top)
            for f in fs:
                it = QTreeWidgetItem(top, columns(f))
                it.setData(0, IGNORE_ROLE, _ignore_key(deck_name, f))
                if is_ignored:
                    for col in range(tree.columnCount()):
                        it.setForeground(col, tree.palette().placeholderText())
                it.setToolTip(1, f.message)
                it.setData(2, Qt.UserRole, (f"<b>{escape(f.card)}</b><br>" if f.card else "") + escape(f.message)
                           + (f"<br><i>Fix: {escape(f.fix)}</i>" if f.fix else ""))
                if editable is not None:
                    it.setData(0, Qt.UserRole, _question_key(editable, f))
                    it.setData(1, Qt.UserRole, (f.card + ": " if f.card else "") + f.message)
            top.setExpanded(not is_ignored and len(fs) <= 12)
            top.setFirstColumnSpanned(True)

    def _toggle_ignore(self, tree):
        item = tree.currentItem()
        key = item.data(0, IGNORE_ROLE) if item is not None else None
        if not key:
            return
        if key in self.ignored:
            self.ignored.discard(key)
        else:
            self.ignored.add(key)
        try:
            _save_json("ignored.json", sorted(self.ignored))
        except OSError:
            pass
        tab = self.tabs.currentIndex()
        self.show_deck()
        self.tabs.setCurrentIndex(tab)

    def _answered(self):
        item = self._question_item
        if item is None:
            return
        key = item.data(0, Qt.UserRole)
        text = self.answer.toPlainText().strip()
        item.setText(2, text)
        if text:
            self.answers[key] = text
        else:
            self.answers.pop(key, None)
        self._store_answers()

    def _store_answers(self):
        try:
            _save_json("answers.json", self.answers)
        except OSError:
            pass

    def _filter_cards(self, *_):
        tier = self.tier_box.currentData() or ""
        q = self.search.text().strip().lower()
        for i in range(self.cards.topLevelItemCount()):
            it = self.cards.topLevelItem(i)
            text = " ".join(it.text(c) for c in range(3)).lower() + " " + it.toolTip(0).lower() \
                + " ".join(it.child(i).text(0).lower() for i in range(it.childCount()))
            it.setHidden(bool((tier and it.data(1, Qt.UserRole) != tier) or (q and q not in text)))

    def copy_answers(self):
        out = []
        for deck, _, findings in self.analysed:
            rows = [(f, self.answers.get(_question_key(deck.name, f))) for f in findings if f.kind == "question"]
            rows = [(f, a) for f, a in rows if a]
            if rows:
                out.append(f"## {deck.name}")
                out += [f"- Q: {(f.card + ': ') if f.card else ''}{f.message}\n  A: {a}" for f, a in rows]
        if not out:
            info(self, "Deck check", "No answers yet. On the Questions tab, pick a question and "
                                     "type your ruling in the box under the list.")
            return
        QApplication.clipboard().setText("\n".join(out))
        n = sum(1 for line in out if line.startswith("- Q:"))
        info(self, "Deck check", f"{n} answer{'s' if n != 1 else ''} copied – paste them into the chat.")

    def save_report(self):
        folder = QFileDialog.getExistingDirectory(self, "Save the report in",
                                                  str(Path(self.analysed[0][0].path).parent))
        if not folder:
            return
        try:
            write_reports(self.analysed, Path(folder))
        except OSError as e:
            error(self, "Deck check", f"Couldn't save the report: {e}")
            return
        info(self, "Deck check", f"Saved report.html, report.json and cards.csv in\n{folder}")
