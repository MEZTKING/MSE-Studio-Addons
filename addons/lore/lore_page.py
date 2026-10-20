"""Lore: the deck's world – its characters, places, groups, items and events,
what each is, and the cards about each. Kept with the deck as lore.json.

Looking a series' characters or a character's story up goes online (AniList
for anime and manga, the series' fan wiki, Wikipedia) – only from the buttons
that say so."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QPlainTextEdit,
                               QPushButton, QScrollArea, QSplitter, QToolButton, QVBoxLayout,
                               QWidget)

from . import lore_core as lc

ROW = Qt.UserRole          # an entry's place in lore.entries
HEAD = Qt.UserRole + 1     # a heading row (not an entry)


class LorePage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.lore = lc.Lore()
        self.entry: Optional[lc.Entry] = None
        self._filling = False
        self._jobs: list = []
        self._job = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(700)
        self._save_timer.timeout.connect(self.save)
        lay = QVBoxLayout(self)
        from mse_studio.gui.nav import page_header
        lay.addWidget(page_header(
            "Lore", "The deck's world: its characters, places, groups, items and events – "
                    "what each is, and the cards about each. Kept with the deck "
                    f"({lc.FILE})."))

        # the world
        wrow = QHBoxLayout()
        wl = QLabel("The world")
        wl.setToolTip("Where and when the cards happen, what's going on, the mood")
        wrow.addWidget(wl)
        self.world = QPlainTextEdit()
        self.world.setPlaceholderText("Where and when the cards happen, what's going on, the "
                                      "mood…")
        self.world.setMaximumHeight(80)
        self.world.textChanged.connect(self._world_changed)
        wrow.addWidget(self.world, 1)
        self.plan_btn = QPushButton("From the plan")
        self.plan_btn.setToolTip("What the deck is about (Guide → Start here → Plan the deck)")
        self.plan_btn.clicked.connect(self.from_plan)
        wrow.addWidget(self.plan_btn, 0, Qt.AlignTop)
        lay.addLayout(wrow)

        split = QSplitter(Qt.Horizontal)
        # ---- left: the entries
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        frow = QHBoxLayout()
        self.kind_filter = QComboBox()
        self.kind_filter.addItem("Everything", "")
        for k, label in lc.KINDS:
            self.kind_filter.addItem(label, k)
        self.kind_filter.currentIndexChanged.connect(self.fill)
        frow.addWidget(self.kind_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.fill)
        frow.addWidget(self.search, 1)
        lv.addLayout(frow)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._picked)
        lv.addWidget(self.list, 1)
        brow = QHBoxLayout()
        add = QToolButton()
        add.setText("Add ▾")
        add.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(add)
        for k, _label in lc.KINDS:
            m.addAction(lc.ONE[k], lambda kk=k: self.add_entry(kk))
        add.setMenu(m)
        brow.addWidget(add)
        b = QPushButton("From my cards…")
        b.setToolTip("Characters, places, items and groups the deck's cards already have – "
                     "legendary cards, who speaks in flavour text, types many cards share – "
                     "and characters saved with the deck")
        b.clicked.connect(self.gather)
        brow.addWidget(b)
        b = QPushButton("A series' characters…")
        b.setToolTip("Every character of a series, looked up online (AniList for anime and "
                     "manga, else the series' fan wiki)")
        b.clicked.connect(self.series_cast)
        brow.addWidget(b)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self.remove)
        brow.addWidget(self.remove_btn)
        brow.addStretch(1)
        lv.addLayout(brow)
        split.addWidget(left)

        # ---- right: one entry
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.textEdited.connect(self._edited)
        form.addRow("Name", self.name)
        self.kind = QComboBox()
        for k, _label in lc.KINDS:
            self.kind.addItem(lc.ONE[k], k)
        self.kind.currentIndexChanged.connect(self._edited)
        form.addRow("Kind", self.kind)
        self.aliases = QLineEdit()
        self.aliases.setPlaceholderText("Other names, titles or nicknames, with commas between")
        self.aliases.textEdited.connect(self._edited)
        form.addRow("Also called", self.aliases)
        self.when = QLineEdit()
        self.when.setPlaceholderText("When it happens – a year, a chapter, “before the war”… "
                                     "(events are sorted by it)")
        self.when.textEdited.connect(self._edited)
        self.when_label = QLabel("When")
        form.addRow(self.when_label, self.when)
        rv.addLayout(form)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Who or what it is, its story, how it fits in the world…")
        self.text.textChanged.connect(self._text_changed)
        rv.addWidget(self.text, 2)
        self.links = QLabel()
        self.links.setWordWrap(True)
        self.links.setTextFormat(Qt.RichText)
        self.links.linkActivated.connect(self._link)
        rv.addWidget(self.links)
        rv.addWidget(QLabel("Cards about it"))
        self.cards = QListWidget()
        self.cards.setToolTip("Cards that name it (or one of its other names) – double-click to "
                              "open one")
        self.cards.itemDoubleClicked.connect(self._open_card)
        rv.addWidget(self.cards, 1)
        self.quotes = QLabel()
        self.quotes.setWordWrap(True)
        self.quotes.setObjectName("Hint")
        rv.addWidget(self.quotes)
        arow = QHBoxLayout()
        self.card_btn = QPushButton("A new card for it")
        self.card_btn.setToolTip("Adds a card with its name and a type that fits (a legendary "
                                 "creature for a character, a legendary land for a place…) "
                                 "and opens it on the Cards page")
        self.card_btn.clicked.connect(self.new_card)
        arow.addWidget(self.card_btn)
        self.story_btn = QPushButton("Abilities from its story…")
        self.story_btn.setToolTip("Abilities that fit what's written here (MSE Studio's "
                                  "Abilities from a character's story)")
        self.story_btn.clicked.connect(self.story_abilities)
        arow.addWidget(self.story_btn)
        self.lookup_btn = QPushButton("Look up its story")
        self.lookup_btn.setToolTip("Looks the name up online – the series' fan wiki, AniList, "
                                   "Wikipedia – and adds what it finds under what's written "
                                   "here")
        self.lookup_btn.clicked.connect(self.look_up)
        arow.addWidget(self.lookup_btn)
        arow.addStretch(1)
        rv.addLayout(arow)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(right)
        split.addWidget(scroll)
        split.setSizes([360, 760])
        lay.addWidget(split, 1)

        bottom = QHBoxLayout()
        self.checks = QLabel()
        self.checks.setObjectName("Hint")
        self.checks.setWordWrap(True)
        self.checks.setTextFormat(Qt.RichText)
        self.checks.linkActivated.connect(self._check_link)
        bottom.addWidget(self.checks, 1)
        self.cast_cards_btn = QPushButton("Cards for the characters…")
        self.cast_cards_btn.setToolTip("A card for each character ticked, made from what's "
                                       "written about them – their type, colours and the "
                                       "abilities that fit")
        self.cast_cards_btn.clicked.connect(self.cards_for_characters)
        bottom.addWidget(self.cast_cards_btn)
        b = QPushButton("Save as a text file…")
        b.clicked.connect(self.export)
        bottom.addWidget(b)
        b = QPushButton("Copy")
        b.setProperty("kind", "text")
        b.clicked.connect(self.copy)
        bottom.addWidget(b)
        lay.addLayout(bottom)
        self._show_entry(None)

    # ------------------------------------------------------------ MSE Studio calls these
    def load(self):
        """A deck was opened."""
        self.save()
        p = self.main.project
        self.lore = lc.load(p) if p is not None else lc.Lore()
        self.entry = None
        self.world.blockSignals(True)
        self.world.setPlainText(self.lore.world)
        self.world.blockSignals(False)
        self.fill()

    def refresh(self):
        """The page was opened: the cards may have changed."""
        self.fill()
        self._show_entry(self.entry)

    def shutdown(self):
        self.save()
        self._save_timer.stop()
        try:
            from mse_studio.gui.common import forget
            forget(self._jobs)
        except ImportError:
            pass

    # ------------------------------------------------------------ the list
    def _cards(self) -> list:
        p = self.main.project
        return list(p.set.cards) if p is not None else []

    def fill(self, *_):
        cur = self.entry
        kind = self.kind_filter.currentData() or ""
        q = self.search.text().strip().lower()
        cards = self._cards()
        self.list.blockSignals(True)
        self.list.clear()
        last = None
        for e in self.lore.ordered(kind):
            if q and q not in e.name.lower() and q not in e.text.lower() and \
                    not any(q in a.lower() for a in e.aliases):
                continue
            if e.kind != last and not kind:
                head = QListWidgetItem(lc.KIND_LABEL.get(e.kind, "Other"))
                head.setFlags(Qt.NoItemFlags)
                head.setData(HEAD, True)
                f = head.font()
                f.setBold(True)
                head.setFont(f)
                self.list.addItem(head)
                last = e.kind
            n = len(lc.mentions(cards, e))
            it = QListWidgetItem(e.name + (f"   · {n} card{'s' if n != 1 else ''}" if n else ""))
            it.setData(ROW, self.lore.entries.index(e))
            it.setToolTip(e.text[:300] or "Nothing written yet")
            if e.kind == "character":
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Unchecked)
            self.list.addItem(it)
            if e is cur:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if cur is not None and self.list.currentItem() is None:
            self._show_entry(None)
        self._checks()

    def _picked(self, it, _prev=None):
        if it is None or it.data(HEAD):
            return
        i = it.data(ROW)
        if isinstance(i, int) and 0 <= i < len(self.lore.entries):
            self._show_entry(self.lore.entries[i])

    def _link(self, href: str):
        try:
            self.select(self.lore.entries[int(href.split(":", 1)[1])].name)
        except (ValueError, IndexError):
            return

    def select(self, name: str):
        e = self.lore.find(name)
        if e is None:
            return
        self.kind_filter.setCurrentIndex(0)
        self.search.clear()
        self.entry = e
        self.fill()
        self._show_entry(e)

    def ticked_characters(self) -> list:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.flags() & Qt.ItemIsUserCheckable and it.checkState() == Qt.Checked:
                out.append(self.lore.entries[it.data(ROW)])
        return out

    # ------------------------------------------------------------ one entry
    def _show_entry(self, e: Optional[lc.Entry]):
        self.entry = e
        on = e is not None
        for w in (self.name, self.kind, self.aliases, self.when, self.text, self.card_btn,
                  self.story_btn, self.lookup_btn, self.remove_btn):
            w.setEnabled(on)
        self._filling = True
        try:
            self.name.setText(e.name if on else "")
            self.kind.setCurrentIndex(max(0, self.kind.findData(e.kind if on else "other")))
            self.aliases.setText(", ".join(e.aliases) if on else "")
            self.when.setText(e.when if on else "")
            self.text.setPlainText(e.text if on else "")
        finally:
            self._filling = False
        self.when.setVisible(on and e.kind == "event")
        self.when_label.setVisible(on and e.kind == "event")
        self.story_btn.setVisible(not on or e.kind in ("character", "group"))
        self._about_it()

    def _about_it(self):
        """The cards about the entry, its quotes and its links to the others."""
        e = self.entry
        self.cards.clear()
        if e is None:
            self.links.setText("<span style='opacity:.7'>Pick something on the left – or add "
                               "a character, a place, a group… with Add, or gather them "
                               "from your cards.</span>")
            self.quotes.setText("")
            return
        cards = self._cards()
        for i in lc.mentions(cards, e):
            c = cards[i]
            it = QListWidgetItem(f"{c.name}  — {lc._text(c, 'super_type')}")
            it.setData(ROW, i)
            self.cards.addItem(it)
        if not self.cards.count():
            self.cards.addItem("No card names it yet – A new card for it, or name it in a "
                               "card's rules or flavour text.")
        self._links()
        qs = lc.quotes(cards, e)[:3]
        self.quotes.setText(("Quotes: " + "  ·  ".join(q.replace("\n", " ") for q in qs))
                            if qs else "")

    def _links(self):
        """The other entries this one names, and the ones that name it."""
        e = self.entry
        if e is None:
            return
        names, named_by = lc.links(self.lore, e)

        def linked(xs):
            import html
            return ", ".join(f"<a href='entry:{self.lore.entries.index(self.lore.find(x))}'>"
                             f"{html.escape(x)}</a>" for x in xs if self.lore.find(x))
        bits = []
        if names:
            bits.append(f"It mentions: {linked(names)}")
        if named_by:
            bits.append(f"Mentioned by: {linked(named_by)}")
        self.links.setText(" · ".join(bits))

    def _edited(self, *_):
        e = self.entry
        if e is None or self._filling:
            return
        name = self.name.text().strip()
        if name:
            e.name = name
        e.kind = self.kind.currentData() or "other"
        e.aliases = [a.strip() for a in self.aliases.text().split(",") if a.strip()]
        e.when = self.when.text().strip()
        self.when.setVisible(e.kind == "event")
        self.when_label.setVisible(e.kind == "event")
        self.story_btn.setVisible(e.kind in ("character", "group"))
        self._changed()
        self.fill()
        self._about_it()

    def _text_changed(self):
        if self.entry is not None and not self._filling:
            self.entry.text = self.text.toPlainText()
            self._changed()
            self._links()

    def _world_changed(self):
        self.lore.world = self.world.toPlainText()
        self._changed()

    def _changed(self):
        self._save_timer.start()

    def save(self):
        self._save_timer.stop()
        p = self.main.project
        if p is None:
            return
        if not self.lore.entries and not self.lore.world.strip() and not lc.path(p).exists():
            return                       # nothing written: no file
        try:
            lc.save(p, self.lore)
        except OSError as e:
            self.checks.setText(f"Couldn't save the lore: {e}")

    # ------------------------------------------------------------ adding
    def add_entry(self, kind: str, name: str = "", text: str = "") -> Optional[lc.Entry]:
        if self.main.project is None:
            return None
        base = name or {"character": "New character", "place": "New place",
                        "group": "New group", "item": "New item", "event": "New event"
                        }.get(kind, "New entry")
        name, n = base, 2
        while self.lore.find(name) is not None:
            name, n = f"{base} {n}", n + 1
        e = lc.Entry(name, kind, text)
        self.lore.entries.append(e)
        self.entry = e
        self._changed()
        self.kind_filter.setCurrentIndex(0)
        self.fill()
        self._show_entry(e)
        if not text:
            self.name.setFocus()
            self.name.selectAll()
        return e

    def remove(self):
        e = self.entry
        if e is None:
            return
        try:
            from mse_studio.gui.common import ask_delete
            if not ask_delete(self, f"Remove {e.name} from the lore? (The cards stay.)"):
                return
        except ImportError:
            pass
        self.lore.entries.remove(e)
        self.entry = None
        self._changed()
        self.fill()
        self._show_entry(None)

    def gather(self):
        p = self.main.project
        if p is None:
            return
        try:
            from mse_studio.core import lore as story
            saved = story.deck_characters(p)
        except Exception:  # noqa: BLE001 - older MSE Studio: no saved characters
            saved = []
        found = lc.gather(p, self.lore, saved)
        if not found:
            self.checks.setText("Nothing new in your cards – everything they name is in the "
                                "lore already.")
            return
        picked = self._pick(found, "From my cards",
                            "What the deck's cards already have – tick what goes in the lore:")
        for e in picked:
            self.lore.entries.append(e)
        if picked:
            self._changed()
            self.fill()
            self.checks.setText(f"Added {len(picked)} to the lore.")

    def _pick(self, found: list, title: str, text: str) -> list:
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(560, 520)
        v = QVBoxLayout(dlg)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        lst = QListWidget()
        for i, (e, why) in enumerate(found):
            it = QListWidgetItem(f"{e.name} — {lc.ONE.get(e.kind, 'something').lower()}"
                                 + (f" ({why})" if why else ""))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(ROW, i)
            lst.addItem(it)
        v.addWidget(lst, 1)
        row = QHBoxLayout()
        for label, state in (("All", Qt.Checked), ("None", Qt.Unchecked)):
            b = QPushButton(label)
            b.setProperty("kind", "text")
            b.clicked.connect(lambda _=False, st=state: [lst.item(i).setCheckState(st)
                                                         for i in range(lst.count())])
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Add the ticked ones")
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        out = []
        if dlg.exec() == QDialog.Accepted:
            out = [found[lst.item(i).data(ROW)][0] for i in range(lst.count())
                   if lst.item(i).checkState() == Qt.Checked]
        dlg.hide()
        dlg.deleteLater()                 # the page's own: not kept hidden
        return out

    def from_plan(self):
        p = self.main.project
        if p is None:
            return
        try:
            from mse_studio.core import start_guide
            idea = str(start_guide.plan(p).get("idea") or "").strip()
        except Exception:  # noqa: BLE001 - older MSE Studio
            idea = ""
        if not idea:
            self.checks.setText("The deck's plan says nothing yet (Guide → Start here → Plan "
                                "the deck).")
            return
        cur = self.world.toPlainText().strip()
        self.world.setPlainText(idea if not cur else cur + "\n\n" + idea)

    # ------------------------------------------------------------ online
    def _start(self, job, text: str, done, failed=None):
        from mse_studio.gui.common import start
        self._job = job
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(done)
        job.signals.failed.connect(failed or self._failed)
        self.checks.setText(text)
        self._jobs.append(start(job))

    def _progress(self, _d: int, _t: int, text: str):
        try:
            if text:
                self.checks.setText(text)
        except RuntimeError:
            return

    def _failed(self, msg: str):
        try:
            self._job = None
            self.checks.setText("Stopped." if msg.strip() == "Stopped." else
                                (msg.splitlines()[0] if msg else "Something went wrong."))
        except RuntimeError:
            return

    def _series(self) -> tuple[str, str]:
        p = self.main.project
        if p is None:
            return "", ""
        return str(p.config.get("lore_series") or ""), str(p.config.get("lore_kind") or "")

    def series_cast(self):
        """Every character of a series, looked up online, to add."""
        if self.main.project is None or self._job is not None:
            return
        from mse_studio.core import lore as story
        series, kind = self._series()
        dlg = QDialog(self)
        dlg.setWindowTitle("A series' characters")
        f = QFormLayout(dlg)
        hint = QLabel("Looked up online: AniList for an anime or manga (with what it says "
                      "about each), else the series' fan wiki.")
        hint.setWordWrap(True)
        f.addRow(hint)
        name = QLineEdit(series)
        name.setPlaceholderText("The series' name – or its fan wiki's address")
        f.addRow("Series", name)
        kinds = QComboBox()
        for k, label in story.SOURCE_KINDS:
            kinds.addItem(label, k)
        kinds.setCurrentIndex(max(0, kinds.findData(kind)))
        f.addRow("It's", kinds)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Find their characters")
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        ok = dlg.exec() == QDialog.Accepted
        series, kind = name.text().strip(), kinds.currentData() or ""
        dlg.hide()
        dlg.deleteLater()
        if not ok or not series:
            return
        p = self.main.project
        p.config["lore_series"], p.config["lore_kind"] = series, kind
        p.dirty = True
        from mse_studio.gui.common import Job
        self._start(Job(story.cast, series, kind=kind, label="Finding the characters"),
                    f"Looking for the characters of {series}…", self._cast_found)

    def _cast_found(self, result):
        try:
            self._job = None
            members, source = result
            have = {n.lower() for e in self.lore.entries for n in e.names()}
            found = [(lc.Entry(m.name, "character", m.text),
                      m.role + (" – " if m.role else "") + source)
                     for m in members if m.name.lower() not in have]
            if not found:
                self.checks.setText("No new characters were found – check the series' name, "
                                    "or give its fan wiki's address.")
                return
            picked = self._pick(found, "A series' characters",
                                f"{len(found)} characters from {source} – tick the ones that "
                                "go in the lore:")
            self.lore.entries.extend(picked)
            if picked:
                self._changed()
                self.fill()
            self.checks.setText(f"Added {len(picked)} characters.")
        except RuntimeError:
            return

    def look_up(self):
        e = self.entry
        if e is None or self._job is not None:
            return
        from mse_studio.core import lore as story
        from mse_studio.gui.common import Job
        series, kind = self._series()
        self._looking = e
        self._start(Job(story.lookup, e.name, series, kind=kind,
                        label=f"Looking up {e.name}"),
                    f"Looking up {e.name}…", self._looked_up)

    def _looked_up(self, result):
        try:
            self._job = None
            pages, _problems = result
            e = getattr(self, "_looking", None)
            if e is None or e not in self.lore.entries:
                return
            if not pages:
                self.checks.setText(f"Nothing was found for {e.name} – set the series with "
                                    "A series' characters…, or write their story yourself.")
                return
            pg = pages[0]
            story_text = (pg.about().strip() + "\n\n" + pg.story().strip()).strip()[:6000]
            e.text = (e.text.rstrip() + "\n\n" if e.text.strip() else "") + story_text
            self._changed()
            if e is self.entry:
                self._show_entry(e)
            self.checks.setText(f"Added what {pg.source} says about {e.name}.")
        except RuntimeError:
            return

    # ------------------------------------------------------------ cards
    def _open_card(self, it):
        i = it.data(ROW)
        if not isinstance(i, int):
            return
        main = self.main
        main.tabs.setCurrentWidget(main.cards_tab)
        main.cards_tab.select_row(i)

    def new_card(self):
        e = self.entry
        p = self.main.project
        if e is None or p is None:
            return
        from mse_studio.core import card_ideas as ci
        f = lc.card_fields(e)
        idea = ci.CardIdea(f["name"], "", f["super_type"], f["sub_type"], "",
                           flavor_text=f.get("flavor_text", ""), rarity="rare",
                           source="Lore")
        self._add_cards([idea], f"Lore · a card for {e.name}")

    def _add_cards(self, ideas: list, label: str):
        """Cards into the deck (MSE Studio's card ideas), the first opened."""
        from mse_studio.core import card_ideas as ci
        main, p = self.main, self.main.project
        try:
            main.cards_tab.editor.commit()
        except Exception:  # noqa: BLE001 - nothing open
            pass
        rows = ci.add_to_deck(p, ideas)
        if not rows:
            return
        main.record(label, row=rows[0])
        main.cards_tab.reload(rows[0])
        if hasattr(main, "update_title"):
            main.update_title()
        main.tabs.setCurrentWidget(main.cards_tab)
        main.cards_tab.select_row(rows[0])

    def story_abilities(self):
        e = self.entry
        if e is None:
            return
        try:
            from mse_studio.gui.lore_dialog import open_for
            open_for(self.main, name=e.name, story=e.text)
        except (ImportError, TypeError):
            self.checks.setText("This needs MSE Studio 0.25.0 or newer.")

    def cards_for_characters(self):
        """A card for each ticked character (or the one picked), made from
        what's written about them."""
        chars = self.ticked_characters() or (
            [self.entry] if self.entry is not None and self.entry.kind == "character" else [])
        if not chars or self.main.project is None:
            self.checks.setText("Tick the characters on the left first (or pick one).")
            return
        try:
            from mse_studio.core import lore as story
        except ImportError:
            story = None
        if not hasattr(story, "character_card"):
            self.checks.setText("This needs MSE Studio 0.25.0 or newer.")
            return
        if self._job is not None:
            return
        from mse_studio.gui.common import Job
        todo = [(e.name, e.text) for e in chars]
        self._start(Job(_character_cards, todo, label="Making the characters' cards"),
                    f"Making {len(todo)} card{'s' if len(todo) != 1 else ''}…",
                    self._cards_made)

    def _cards_made(self, cards):
        try:
            self._job = None
            if not cards or self.main.project is None:
                return
            self._add_cards(cards, f"Lore · cards for {len(cards)} character"
                                   f"{'s' if len(cards) != 1 else ''}")
            self.checks.setText(f"Added {len(cards)} card{'s' if len(cards) != 1 else ''} – "
                                "change anything on the Cards page.")
        except RuntimeError:
            return

    # ------------------------------------------------------------ checks and sharing
    def _checks(self):
        p = self.main.project
        if p is None:
            self.checks.setText("")
            return
        cards = self._cards()
        bits = []
        unknown = lc.unknown_speakers(cards, self.lore)
        if unknown:
            names = ", ".join(w for w, _n in unknown[:4]) + ("…" if len(unknown) > 4 else "")
            bits.append(f"{len(unknown)} speak in flavour text but aren't in the lore: {names} "
                        f"– <a href='speakers'>add them</a>")
        lonely = [e for e in self.lore.entries if not lc.mentions(cards, e)]
        if lonely and self.lore.entries:
            bits.append(f"{len(lonely)} of {len(self.lore.entries)} have no card yet")
        self.checks.setText(" · ".join(bits))

    def _check_link(self, what: str):
        if what == "speakers":
            for who, _n in lc.unknown_speakers(self._cards(), self.lore):
                self.lore.entries.append(lc.Entry(who, "character"))
            self._changed()
            self.fill()

    def export(self):
        p = self.main.project
        if p is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save the lore",
                                              str(Path(p.folder) / f"{p.name} – lore.md"),
                                              "Text (*.md *.txt)")
        if not path:
            return
        try:
            Path(path).write_text(lc.as_markdown(self.lore, p.name, self._cards()),
                                  encoding="utf-8")
        except OSError as e:
            self.checks.setText(f"Couldn't save it: {e}")
            return
        self.checks.setText(f"Saved {Path(path).name}")

    def copy(self):
        p = self.main.project
        if p is None:
            return
        QApplication.clipboard().setText(lc.as_markdown(self.lore, p.name, self._cards()))
        self.checks.setText("Copied the lore as text.")


def _character_cards(todo, progress=None, cancel=None) -> list:
    """A card for each (name, story) – on a worker thread: no widgets."""
    from mse_studio.core import lore as story
    out = []
    for i, (name, text) in enumerate(todo):
        if cancel is not None and cancel.cancelled:
            break
        if progress:
            progress(i, len(todo), f"Making {name}'s card ({i + 1} of {len(todo)})…")
        out.append(story.character_card(name, text))
    return out
