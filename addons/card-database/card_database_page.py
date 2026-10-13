"""Card database: every Magic card on your PC (from Scryfall's bulk data).
Search and filter, pick random cards, build a whole deck around a commander,
and put cards in your deck as real cards or as your own cards to edit.

While it's installed, Decklists look cards up here first (no waiting for
Scryfall). Network: only when you download a bulk file, and for the cards'
pictures (from Scryfall's image server)."""
from __future__ import annotations

import random
import urllib.request
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListView, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPushButton, QSpinBox, QSplitter, QTabWidget,
                               QTextBrowser, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from mse_studio.core import decklists as dl
from mse_studio.gui import icons, thumbs
from mse_studio.gui.common import clear_tree, error, forget, Job, start
from mse_studio.gui.nav import page_header

from . import carddb

THUMB = QSize(110, 154)
TYPES = ["", "Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker",
         "Land", "Battle", "Legendary"]
RARITIES = [("Any rarity", ""), ("Common", "common"), ("Uncommon", "uncommon"),
            ("Rare", "rare"), ("Mythic", "mythic")]
RULES = [("Within these colours", "within"), ("Exactly these colours", "exactly"),
         ("Including these colours", "including")]


def _get(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "MSE-Studio card database",
                                               "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _lookup(entries):
    """Decklists' local card source (a plain function: no widgets involved)."""
    carddb.look_up(entries)


class CardDatabasePage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._jobs: list = []
        self.rows: list = []
        self.built = None
        self._seed = 1
        dl.add_local_source(_lookup)
        lay = QVBoxLayout(self)
        lay.addWidget(page_header(
            "Card database", "Every Magic card on your PC, from Scryfall's bulk data: search, "
                             "random cards, a whole deck around a commander – as real cards or "
                             "as your own cards to edit."))
        row = QHBoxLayout()
        self.db_lbl = QLabel()
        self.db_lbl.setWordWrap(True)
        row.addWidget(self.db_lbl, 1)
        b = QPushButton("Import a bulk file…")
        icons.set_icon(b, "folder_open")
        b.setToolTip("A Scryfall bulk data file you downloaded (.json or .json.gz): Oracle cards "
                     "(one per card) or Default cards (every printing)")
        b.clicked.connect(self.import_file)
        row.addWidget(b)
        dlb = QToolButton()
        dlb.setText("Download from Scryfall ▾")
        dlb.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(dlb)
        for kind, label in carddb.BULK_TYPES.items():
            m.addAction(label, lambda k=kind: self.download(k))
        dlb.setMenu(m)
        row.addWidget(dlb)
        b = QPushButton("Delete")
        b.setProperty("kind", "text")
        b.clicked.connect(self.delete_db)
        row.addWidget(b)
        lay.addLayout(row)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._search_tab(), "Search")
        self.tabs.addTab(self._build_tab(), "Build a deck")
        lay.addWidget(self.tabs, 1)
        thumbs.cache().ready.connect(self._thumb_ready)
        self._show_info()

    # ------------------------------------------------------------ MSE Studio calls these
    def load(self):
        dl.add_local_source(_lookup)
        self._show_info()

    def refresh(self):
        self._show_info()

    def shutdown(self):
        dl.remove_local_source(_lookup)
        forget(self._jobs)                # the page is going: nothing may call it back

    # ------------------------------------------------------------ the database file
    def _show_info(self):
        if not carddb.exists():
            self.db_lbl.setText("<b>No cards yet.</b> Import a Scryfall bulk file you downloaded, "
                                "or download one from Scryfall (Oracle cards is enough).")
            return
        conn = carddb.connect()
        try:
            i = carddb.info(conn)
            names = [r["name"] for r in conn.execute(
                "SELECT DISTINCT name FROM cards WHERE can_lead = 1 ORDER BY lname")]
        finally:
            conn.close()
        kind = carddb.BULK_TYPES.get(i.get("kind", ""), i.get("file", "")).split(" (")[0]
        self.db_lbl.setText(f"<b>{i['names']:,} cards</b> ({i['count']:,} printings) · {kind} "
                            f"· imported {i.get('imported', '?')}")
        comp = QCompleter(names, self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.lead.setCompleter(comp)

    def import_file(self, path: str = ""):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Scryfall bulk file", "",
                                                  "Scryfall bulk data (*.json *.json.gz *.gz)")
        if not path:
            return
        self._import(Path(path), "")

    def _import(self, path: Path, kind: str, delete_after: bool = False):
        def work(progress=None, cancel=None):
            try:
                return carddb.import_bulk(path, progress, cancel, kind=kind)
            finally:
                if delete_after:
                    path.unlink(missing_ok=True)

        self.db_lbl.setText("Reading the cards…")
        job = Job(work, label="Reading the card database")
        job.signals.progress.connect(lambda d, t, m: self.db_lbl.setText(m))
        job.signals.finished.connect(lambda n: (self._show_info(), self.main.statusBar()
                                                .showMessage(f"{n:,} cards in the database", 8000)))
        job.signals.failed.connect(lambda m: (self._show_info(), error(self, "Card database",
                                                                      m.splitlines()[0])))
        self._jobs.append(start(job))

    def download(self, kind: str):
        target = carddb.db_path().with_name(f"{kind}.json")

        def work(progress=None, cancel=None):
            files = carddb.bulk_downloads(_get)
            f = files.get(kind)
            if not f:
                raise carddb.CardDbError("Scryfall didn't list that bulk file.")
            req = urllib.request.Request(f["url"], headers={"User-Agent": "MSE-Studio"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r, open(target, "wb") as out:
                    total, done = int(r.headers.get("Content-Length") or f["size"] or 0), 0
                    while True:
                        if cancel is not None and cancel.cancelled:
                            raise carddb.CardDbError("Stopped.")
                        piece = r.read(1 << 20)
                        if not piece:
                            break
                        out.write(piece)
                        done += len(piece)
                        progress(done >> 20, max(1, total >> 20), f"Downloading {kind}: "
                                 f"{done >> 20} of {total >> 20} MB")
            except BaseException:
                target.unlink(missing_ok=True)      # no half-downloaded file left behind
                raise
            return target

        job = Job(work, label="Downloading Scryfall's cards")
        job.signals.progress.connect(lambda d, t, m: self.db_lbl.setText(m))
        job.signals.finished.connect(lambda p: self._import(Path(p), kind, delete_after=True))
        job.signals.failed.connect(lambda m: (self._show_info(), error(self, "Card database",
                                                                      m.splitlines()[0])))
        self._jobs.append(start(job))

    def delete_db(self):
        if not carddb.exists():
            return
        if QMessageBox.question(self, "Card database", "Delete the card database from this "
                                "PC? (You can import it again any time.)") != QMessageBox.Yes:
            return
        carddb.db_path().unlink(missing_ok=True)
        self._show_info()

    # ------------------------------------------------------------ search
    def _search_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGridLayout()
        self.text = QLineEdit()
        self.text.setPlaceholderText("Name, rules text or type (all the words)")
        self.text.returnPressed.connect(self.search)
        g.addWidget(self.text, 0, 0, 1, 4)
        crow = QHBoxLayout()
        self.color_btns = {}
        for c in "WUBRGC":
            b = QPushButton(c)
            b.setCheckable(True)
            b.setFixedWidth(34)
            b.setToolTip({"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green",
                          "C": "Colourless"}[c])
            self.color_btns[c] = b
            crow.addWidget(b)
        self.rule = QComboBox()
        for label, key in RULES:
            self.rule.addItem(label, key)
        crow.addWidget(self.rule)
        b = QPushButton("My deck's colours")
        b.setProperty("kind", "text")
        b.clicked.connect(self._deck_colors)
        crow.addWidget(b)
        crow.addStretch(1)
        g.addLayout(crow, 0, 4, 1, 4)
        self.type = QComboBox()
        for t in TYPES:
            self.type.addItem(t or "Any type", t)
        g.addWidget(self.type, 1, 0)
        mv = QHBoxLayout()
        mv.addWidget(QLabel("Mana value"))
        self.mv_min, self.mv_max = QSpinBox(), QSpinBox()
        for s, val in ((self.mv_min, 0), (self.mv_max, 16)):
            s.setRange(0, 16)
            s.setValue(val)
            mv.addWidget(s)
        g.addLayout(mv, 1, 1)
        self.rarity = QComboBox()
        for label, key in RARITIES:
            self.rarity.addItem(label, key)
        g.addWidget(self.rarity, 1, 2)
        self.legal = QCheckBox("Commander-legal")
        self.legal.setChecked(True)
        g.addWidget(self.legal, 1, 3)
        pr = QHBoxLayout()
        pr.addWidget(QLabel("Max $"))
        self.max_usd = QDoubleSpinBox()
        self.max_usd.setRange(0, 10000)
        self.max_usd.setSpecialValueText("any")
        self.max_usd.setToolTip("Leave out cards dearer than this (Scryfall's TCGplayer price; "
                                "the database's day)")
        pr.addWidget(self.max_usd)
        g.addLayout(pr, 1, 4)
        self.sort = QComboBox()
        for key, label in carddb.SORTS.items():
            self.sort.addItem(label, key)
        g.addWidget(self.sort, 1, 5)
        b = QPushButton("Search")
        b.setProperty("kind", "primary")
        icons.set_icon(b, "search")
        b.clicked.connect(self.search)
        g.addWidget(b, 1, 6)
        rr = QHBoxLayout()
        b = QPushButton("Random")
        icons.set_icon(b, "casino")
        b.setToolTip("Random cards that match the filters")
        b.clicked.connect(lambda: self.search(randomly=True))
        rr.addWidget(b)
        self.n_random = QSpinBox()
        self.n_random.setRange(1, 100)
        self.n_random.setValue(10)
        rr.addWidget(self.n_random)
        g.addLayout(rr, 1, 7)
        v.addLayout(g)
        self.found_lbl = QLabel()
        self.found_lbl.setObjectName("Hint")
        v.addWidget(self.found_lbl)
        split = QSplitter(Qt.Horizontal)
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setIconSize(THUMB)
        self.grid.setSpacing(6)
        self.grid.setWordWrap(True)
        self.grid.setSelectionMode(QListWidget.ExtendedSelection)
        self.grid.currentRowChanged.connect(lambda *_: self._details())
        split.addWidget(self.grid)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(6, 0, 0, 0)
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(True)
        rv.addWidget(self.details, 1)
        b = QPushButton("Add to my deck as real cards")
        icons.set_icon(b, "add")
        b.setToolTip("The selected cards, printed with their real picture")
        b.clicked.connect(lambda: self.add_real(self.selected()))
        rv.addWidget(b)
        b = QPushButton("Add to my deck to edit (my own cards)")
        icons.set_icon(b, "edit")
        b.setToolTip("New cards of your own with the selected cards' text and artwork, to "
                     "change as you like")
        b.clicked.connect(lambda: self.add_custom(self.selected()))
        rv.addWidget(b)
        b = QPushButton("Save as a decklist…")
        b.clicked.connect(lambda: self.save_list(self.selected() or self.rows))
        rv.addWidget(b)
        split.addWidget(right)
        split.setSizes([800, 330])
        v.addWidget(split, 1)
        return w

    def _filters(self) -> carddb.Filters:
        cols = "".join(c for c, b in self.color_btns.items() if b.isChecked())
        return carddb.Filters(
            text=self.text.text(), colors=cols, color_rule=self.rule.currentData(),
            types=self.type.currentData(), mv_min=self.mv_min.value() or None,
            mv_max=self.mv_max.value() if self.mv_max.value() < 16 else None,
            rarity=self.rarity.currentData(), commander_legal=self.legal.isChecked(),
            max_usd=self.max_usd.value() or None)

    def _deck_colors(self):
        from mse_studio.ai.planner import commander_of, deck_colors
        p = self.main.project
        if p is None:
            return
        cols = deck_colors(p, commander_of(p))
        for c, b in self.color_btns.items():
            b.setChecked(c in cols or (c == "C" and not cols))
        self.rule.setCurrentIndex(0)

    def search(self, randomly: bool = False):
        if not carddb.exists():
            self._show_info()
            return
        f, sort = self._filters(), self.sort.currentData()
        limit = self.n_random.value() if randomly else 300

        def work(progress=None, cancel=None):
            conn = carddb.connect()
            try:
                return [dict(r) for r in carddb.search(conn, f, sort, limit, randomly)]
            finally:
                conn.close()

        self.found_lbl.setText("Searching…")
        job = Job(work, label="Searching the card database")
        job.signals.finished.connect(self._show_rows)
        job.signals.failed.connect(lambda m: self.found_lbl.setText(m.splitlines()[0]))
        self._jobs.append(start(job))

    def _show_rows(self, rows: list):
        try:
            self.rows = rows
            self.grid.clear()
            for k, r in enumerate(rows):
                it = QListWidgetItem(r["name"])
                it.setData(Qt.UserRole, k)
                it.setSizeHint(QSize(THUMB.width() + 12, THUMB.height() + 36))
                pm = self._thumb(r)
                if pm is not None:
                    it.setIcon(QIcon(pm))
                self.grid.addItem(it)
            self.found_lbl.setText(f"{len(rows)} card(s)" + (" (the first 300 – narrow the "
                                                             "search)" if len(rows) >= 300 else ""))
            if rows:
                self.grid.setCurrentRow(0)
        except RuntimeError:
            pass

    def _thumb(self, r: dict):
        url = r.get("image")
        if not url:
            return None
        return thumbs.cache().get(f"carddb:{r['id']}", "1", lambda url=url: _get(url, 30))

    def _thumb_ready(self, source_id: str):
        try:
            if not source_id.startswith("carddb:"):
                return
            cid = source_id.split(":", 1)[1]
            for i in range(self.grid.count()):
                it = self.grid.item(i)
                r = self.rows[it.data(Qt.UserRole)]
                if r["id"] == cid:
                    pm = self._thumb(r)
                    if pm is not None:
                        it.setIcon(QIcon(pm))
        except (RuntimeError, IndexError):
            return

    def selected(self) -> list[dict]:
        return [self.rows[it.data(Qt.UserRole)] for it in self.grid.selectedItems()]

    def _details(self):
        it = self.grid.currentItem()
        if it is None:
            self.details.setHtml("")
            return
        r = self.rows[it.data(Qt.UserRole)]
        prices = " · ".join(x for x in (f"${r['usd']:.2f}" if r["usd"] is not None else "",
                                        f"€{r['eur']:.2f}" if r["eur"] is not None else "") if x)
        links = " · ".join(f"<a href='{u}'>{n}</a>" for n, u in
                           (("TCGplayer", r["tcgplayer"]), ("Cardmarket", r["cardmarket"])) if u)
        text = (r["oracle_text"] or "").replace("\n", "<br>")
        pt = f"<p><b>{r['power']}/{r['toughness']}</b></p>" if r["power"] or r["toughness"] else ""
        self.details.setHtml(
            f"<h3>{r['name']}</h3><p>{r['mana_cost'] or ''}</p><p><i>{r['type_line']}</i></p>"
            f"<p>{text}</p>{pt}<p style='color:gray'>{r['set_name']} ({r['set_code'].upper()}) "
            f"· {r['rarity']}" + (f" · EDHREC #{r['edhrec']}" if r["edhrec"] else "") + "</p>"
            + (f"<p>{prices}</p>" if prices else "") + (f"<p>{links}</p>" if links else ""))

    # ------------------------------------------------------------ into the deck
    def _entries(self, rows: list[dict]) -> list:
        return [dl.Entry(name=r["name"], card=carddb.card_of(r), scryfall_id=r["id"])
                for r in rows]

    def add_real(self, rows: list[dict]):
        p = self.main.project
        if p is None or not rows:
            return
        entries = self._entries(rows)
        self.main.cards_tab.editor.commit()
        n = dl.add_to_project(p, entries)
        self.main.record(f"Card database · {n} real card(s)")
        self.main.update_title()
        self.main.statusBar().showMessage(f"Added {n} real card(s) – they're on the Order page",
                                          8000)
        self.main.order_tab.real_pictures(entries)

    def add_custom(self, rows: list[dict]):
        if self.main.project is None or not rows:
            return
        self.main.decklists_tab.add_custom(self._entries(rows), "the card database",
                                           with_art=True, frame="mine")

    def save_list(self, rows: list[dict], name: str = "", entries=None):
        if not rows and not entries:
            return
        if not name:
            name, ok = QInputDialog.getText(self, "Save as a decklist", "Name:",
                                            text="From the card database")
            if not ok or not name.strip():
                return
        d = dl.Decklist(name.strip(), entries or self._entries(rows), "card database")
        dl.save(d)
        self.main.decklists_tab.refresh()
        self.main.statusBar().showMessage(f"Saved {d.name} on the Decklists page", 8000)

    # ------------------------------------------------------------ build a deck
    def _build_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        f = QFormLayout()
        lead = QHBoxLayout()
        self.lead = QLineEdit()
        self.lead.setPlaceholderText("A legendary creature (type to search)")
        lead.addWidget(self.lead, 1)
        b = QPushButton("My deck's commander")
        b.setProperty("kind", "text")
        b.clicked.connect(self._deck_commander)
        lead.addWidget(b)
        f.addRow("Commander", lead)
        nums = QHBoxLayout()
        self.counts = {}
        for key, label in (("lands", "Lands"), ("ramp", "Ramp"), ("draw", "Card draw"),
                           ("removal", "Removal"), ("wipe", "Wipes"), ("protection", "Protection")):
            s = QSpinBox()
            s.setRange(0, 60)
            s.setValue(carddb.DEFAULT_COUNTS[key])
            nums.addWidget(QLabel(label))
            nums.addWidget(s)
            self.counts[key] = s
        nums.addStretch(1)
        f.addRow("How many", nums)
        self.theme = QLineEdit()
        self.theme.setPlaceholderText("optional: theme words, e.g. counters lifelink zombies")
        f.addRow("Theme", self.theme)
        self.build_usd = QDoubleSpinBox()
        self.build_usd.setRange(0, 10000)
        self.build_usd.setSpecialValueText("any")
        self.build_usd.setToolTip("Leave out cards dearer than this (in US dollars)")
        f.addRow("Max price per card", self.build_usd)
        v.addLayout(f)
        row = QHBoxLayout()
        b = QPushButton("Build the deck")
        b.setProperty("kind", "primary")
        icons.set_icon(b, "auto_fix_high")
        b.clicked.connect(lambda: self.build(new=False))
        row.addWidget(b)
        b = QPushButton("Build again (other picks)")
        b.clicked.connect(lambda: self.build(new=True))
        row.addWidget(b)
        row.addStretch(1)
        self.build_lbl = QLabel()
        self.build_lbl.setObjectName("Hint")
        row.addWidget(self.build_lbl)
        v.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Card", "Mana value"])
        v.addWidget(self.tree, 1)
        row = QHBoxLayout()
        b = QPushButton("Save as a decklist")
        b.setToolTip("Playtest it, or add it to your deck, from the Decklists page")
        b.clicked.connect(self.save_built)
        row.addWidget(b)
        b = QPushButton("Add all to my deck as real cards")
        b.clicked.connect(self.add_built)
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        return w

    def _deck_commander(self):
        from mse_studio.ai.planner import commander_of
        p = self.main.project
        c = commander_of(p) if p is not None else None
        if c is not None:
            self.lead.setText(c.name)

    def build(self, new: bool = False):
        if not carddb.exists():
            self._show_info()
            return
        name = self.lead.text().strip()
        if not name:
            self.build_lbl.setText("Pick a commander first.")
            return
        if new:
            self._seed = random.randrange(1, 10 ** 6)
        counts = {k: s.value() for k, s in self.counts.items()}
        theme, seed, usd = self.theme.text(), self._seed, self.build_usd.value() or None

        def work(progress=None, cancel=None):
            conn = carddb.connect()
            try:
                deck = carddb.build_deck(conn, name, counts, theme, seed, usd)
                for p in deck.picks:          # plain data: the connection closes here
                    p.row = dict(p.row) if p.row is not None else None
                deck.lead = dict(deck.lead)
                return deck
            finally:
                conn.close()

        self.build_lbl.setText("Building…")
        job = Job(work, label="Building a deck")
        job.signals.finished.connect(self._show_built)
        job.signals.failed.connect(lambda m: self.build_lbl.setText(m.splitlines()[0]))
        self._jobs.append(start(job))

    def _show_built(self, deck):
        try:
            self.built = deck
            clear_tree(self.tree)
            groups = {}
            for p in deck.picks:
                g = groups.get(p.why)
                if g is None:
                    g = groups[p.why] = QTreeWidgetItem(self.tree, [p.why])
                    g.setFlags(Qt.ItemIsEnabled)
                QTreeWidgetItem(g, [f"{p.count}× {p.name}" if p.count > 1 else p.name,
                                    f"{p.row['cmc']:g}" if p.row else ""])
            for g in groups.values():
                n = sum(int(g.child(i).text(0).split("×")[0]) if "×" in g.child(i).text(0) else 1
                        for i in range(g.childCount()))
                g.setText(0, f"{g.text(0)} ({n})")
            self.tree.expandAll()
            self.tree.resizeColumnToContents(0)
            self.build_lbl.setText(f"{deck.size} cards with {deck.commander} · "
                                   + ("; ".join(deck.notes) if deck.notes else "ready"))
        except RuntimeError:
            pass

    def save_built(self):
        d = self.built
        if d is None:
            return
        self.save_list([], f"{d.commander} – built", d.entries())

    def add_built(self):
        d = self.built
        p = self.main.project
        if d is None or p is None:
            return
        entries = [e for e in d.entries() if e.found]
        n = dl.add_to_project(p, entries)
        self.main.record(f"Card database · built deck · {n} real card(s)")
        self.main.update_title()
        self.main.order_tab.real_pictures(entries)
