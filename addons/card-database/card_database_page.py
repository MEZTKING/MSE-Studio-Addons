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

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListView, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPushButton, QSlider, QSpinBox, QSplitter,
                               QTabWidget,
                               QTextBrowser, QToolButton, QVBoxLayout, QWidget)

from mse_studio.core import decklists as dl
from mse_studio.gui import icons, thumbs
from mse_studio.gui.common import error, forget, Job, start
from mse_studio.gui.nav import page_header

from . import carddb

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


VIEW_SORTS = [("name", "Name"), ("mv", "Mana value"), ("colour", "Colour"),
              ("type", "Card type"), ("popular", "Most played"), ("cheap", "Cheapest"),
              ("new", "Newest")]
_TYPE_ORDER = ["creature", "planeswalker", "battle", "instant", "sorcery", "artifact",
               "enchantment", "land"]


def _sort_key(r: dict, key: str):
    name = r.get("lname") or ""
    if key == "mv":
        return (r.get("cmc") or 0, name)
    if key == "colour":
        ident = r.get("identity") or ""
        return (len(ident) if ident else 9, "WUBRG".find(ident[:1]) if ident else 9, ident,
                name)
    if key == "type":
        t = (r.get("ltype") or "").split("—")[0]
        return (next((i for i, x in enumerate(_TYPE_ORDER) if x in t), 99), name)
    if key == "popular":
        return (r.get("edhrec") if r.get("edhrec") is not None else 10 ** 9, name)
    if key == "cheap":
        vals = [v for v in (r.get("usd"), r.get("eur")) if v is not None]
        return (min(vals) if vals else 10 ** 9, name)
    if key == "new":
        return ("".join(chr(255 - ord(c)) for c in (r.get("released") or "")), name)
    return name


def _load_prefs() -> dict:
    import json
    try:
        from mse_studio.core import addons
        return json.loads((addons.data_dir("card-database") / "prefs.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_prefs(prefs: dict) -> None:
    import json
    try:
        from mse_studio.core import addons
        f = addons.data_dir("card-database") / "prefs.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(prefs), encoding="utf-8")
    except OSError:
        pass


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
        self._prefs = _load_prefs()
        lay = QVBoxLayout(self)
        self.header = page_header(
            "Card database", "Every Magic card on your PC, from Scryfall's bulk data: search, "
                             "random cards, a whole deck around a commander – as real cards or "
                             "as your own cards to edit.")
        lay.addWidget(self.header)
        self.db_box = QWidget()
        row = QHBoxLayout(self.db_box)
        row.setContentsMargins(0, 0, 0, 0)
        self.db_lbl = QLabel()
        self.db_lbl.setWordWrap(True)
        row.addWidget(self.db_lbl, 1)
        b = QPushButton("Import a bulk file…")
        icons.set_icon(b, "folder_open")
        b.setToolTip("A Scryfall bulk data file you downloaded (.json, .jsonl or .gz): Oracle cards "
                     "(one per card), Default cards (every printing) or All cards (its English "
                     "printings are kept)")
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
        lay.addWidget(self.db_box)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._search_tab(), "Search")
        self.tabs.addTab(self._build_tab(), "Build a deck")
        lay.addWidget(self.tabs, 1)
        thumbs.cache().ready.connect(self._thumb_ready)
        if hasattr(thumbs, "large"):
            thumbs.large().ready.connect(self._thumb_ready)
        self._apply_size()
        if self._prefs.get("big_view"):
            self._set_big(True)
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

    def _prices_on(self) -> bool:
        """Prices are for the Card prices add-on: only when it's installed and on."""
        try:
            from mse_studio.core import addons
            a = addons.get("card-prices")
            return a is not None and addons.is_enabled(a, self.main.settings)
        except Exception:  # noqa: BLE001
            return False

    def _show_prices(self):
        on = self._prices_on()
        self.price_box.setVisible(on)
        self.build_price.setVisible(on)
        self.build_price_lbl.setVisible(on)

    # ------------------------------------------------------------ the database file
    def _show_info(self):
        self._show_prices()
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
                                                  "Scryfall bulk data (*.json *.jsonl *.json.gz *.jsonl.gz *.gz)")
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
        target = carddb.db_path().with_name(f"{kind}.download")

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
        self.filters_box = QWidget()
        g = QGridLayout(self.filters_box)
        g.setContentsMargins(0, 0, 0, 0)
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
        self.price_box = QWidget()
        pr = QHBoxLayout(self.price_box)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.addWidget(QLabel("Max $"))
        self.max_usd = QDoubleSpinBox()
        self.max_usd.setRange(0, 10000)
        self.max_usd.setSpecialValueText("any")
        self.max_usd.setToolTip("Leave out cards dearer than this (Scryfall's TCGplayer price; "
                                "the database's day) – with the Card prices add-on")
        pr.addWidget(self.max_usd)
        g.addWidget(self.price_box, 1, 4)
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
        v.addWidget(self.filters_box)
        bar, self.found_find, self.found_sort, self.found_lbl = self._view_bar(
            [("found", "As found")] + VIEW_SORTS, self._show_found)
        v.addLayout(bar)
        split = QSplitter(Qt.Horizontal)
        self.grid = self._make_grid(self._search_menu, self._details,
                                    lambda: self.view_full(self.rows[self.grid.currentItem()
                                                                     .data(Qt.UserRole)]))
        split.addWidget(self.grid)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(6, 0, 0, 0)
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(True)
        rv.addWidget(self.details, 1)
        b = QPushButton("Add to my order (real cards)")
        icons.set_icon(b, "shopping_cart")
        b.setToolTip("The selected cards, printed with their real picture – straight to the "
                     "Order page")
        b.clicked.connect(lambda: self.add_real(self.selected()))
        rv.addWidget(b)
        b = QToolButton()
        b.setText("Add to my deck to edit ▾")
        b.setPopupMode(QToolButton.InstantPopup)
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.setIcon(icons.icon("edit"))
        b.setToolTip("New cards of your own with the selected cards' text and artwork, to "
                     "change as you like")
        em = QMenu(b)
        self._fill_edit_menu(em, self.selected)
        b.setMenu(em)
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
            max_usd=(self.max_usd.value() or None) if self._prices_on() else None)

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
            self._show_found()
        except RuntimeError:
            pass

    def _show_found(self, *_):
        rows = self.rows
        q = self.found_find.text().strip().lower()
        order = [k for k, r in enumerate(rows) if not q or q in r["lname"] or
                 q in (r["ltype"] or "")]
        key = self.found_sort.currentData()
        if key and key != "found":
            order.sort(key=lambda k: _sort_key(rows[k], key))
            self._set_pref("found_sort", key)
        self.grid.clear()
        for k in order:
            r = rows[k]
            it = QListWidgetItem(r["name"])
            it.setData(Qt.UserRole, k)
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            pm = self._thumb(r)
            if pm is not None:
                it.setIcon(QIcon(pm))
            self.grid.addItem(it)
        self.found_lbl.setText(f"{len(rows)} card(s)" + (f", {len(order)} shown" if q else "")
                               + (" (the first 300 – narrow the search)" if len(rows) >= 300
                                  else ""))
        if order:
            self.grid.setCurrentRow(0)

    def _thumb(self, r: dict):
        url = r.get("image")
        if not url:
            return None
        cache = thumbs.large() if self._size() > 260 and hasattr(thumbs, "large") else \
            thumbs.cache()
        return cache.get(f"carddb:{r['id']}", "1", lambda url=url: _get(url, 30))

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
            d = self.built
            for i in range(self.built_grid.count() if d is not None else 0):
                it = self.built_grid.item(i)
                k = it.data(Qt.UserRole)
                r = d.lead if k == -1 else (d.picks[k].row if 0 <= k < len(d.picks) else None)
                if r and r.get("id") == cid:
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
        self.details.setHtml(self._card_html(self.rows[it.data(Qt.UserRole)]))

    def _card_html(self, r: dict) -> str:
        prices = " · ".join(x for x in (f"${r['usd']:.2f}" if r["usd"] is not None else "",
                                        f"€{r['eur']:.2f}" if r["eur"] is not None else "") if x)
        links = " · ".join(f"<a href='{u}'>{n}</a>" for n, u in
                           (("TCGplayer", r["tcgplayer"]), ("Cardmarket", r["cardmarket"])) if u)
        text = (r["oracle_text"] or "").replace("\n", "<br>")
        pt = f"<p><b>{r['power']}/{r['toughness']}</b></p>" if r["power"] or r["toughness"] else ""
        if not self._prices_on():
            prices = links = ""
        return (f"<h3>{r['name']}</h3><p>{r['mana_cost'] or ''}</p><p><i>{r['type_line']}</i></p>"
                f"<p>{text}</p>{pt}<p style='color:gray'>{r['set_name']} ({r['set_code'].upper()}) "
                f"· {r['rarity']}" + (f" · EDHREC #{r['edhrec']}" if r["edhrec"] else "") + "</p>"
                + (f"<p>{prices}</p>" if prices else "") + (f"<p>{links}</p>" if links else ""))

    # ------------------------------------------------------------ how the cards are shown
    def _make_grid(self, menu_fn, details_fn, full_fn) -> QListWidget:
        g = QListWidget()
        g.setViewMode(QListView.IconMode)
        g.setResizeMode(QListView.Adjust)
        g.setMovement(QListView.Static)
        g.setSpacing(6)
        g.setWordWrap(True)
        g.setSelectionMode(QListWidget.ExtendedSelection)
        g.currentRowChanged.connect(lambda *_: details_fn())
        g.setContextMenuPolicy(Qt.CustomContextMenu)
        g.customContextMenuRequested.connect(menu_fn)
        g.itemDoubleClicked.connect(lambda *_: full_fn())
        return g

    def _view_bar(self, sorts: list, refill):
        """Find / Sort / Size / Bigger view above a grid."""
        bar = QHBoxLayout()
        find = QLineEdit()
        find.setPlaceholderText("Find in these…")
        find.setClearButtonEnabled(True)
        find.setMaximumWidth(220)
        find.textChanged.connect(lambda *_: refill())
        bar.addWidget(find)
        bar.addWidget(QLabel("Sort by"))
        sort = QComboBox()
        for key, label in sorts:
            if key == "cheap" and not self._prices_on():
                continue
            sort.addItem(label, key)
        pref = self._prefs.get("found_sort" if sorts[0][0] == "found" else "built_sort")
        if pref and sort.findData(pref) >= 0:
            sort.setCurrentIndex(sort.findData(pref))
        sort.currentIndexChanged.connect(lambda *_: refill())
        bar.addWidget(sort)
        bar.addWidget(QLabel("Size"))
        size = QSlider(Qt.Horizontal)
        size.setRange(80, 420)
        size.setValue(self._size())
        size.setFixedWidth(140)
        size.setToolTip("How big the cards are")
        size.valueChanged.connect(self._size_moved)
        size.sliderReleased.connect(self._apply_size)
        self._size_sliders = getattr(self, "_size_sliders", []) + [size]
        bar.addWidget(size)
        big = QPushButton("Bigger view")
        big.setCheckable(True)
        icons.set_icon(big, "fullscreen")
        big.setToolTip("More room for the cards: hides the search and build options (click "
                       "again to bring them back)")
        big.toggled.connect(self._set_big)
        self._big_btns = getattr(self, "_big_btns", []) + [big]
        bar.addWidget(big)
        bar.addStretch(1)
        count = QLabel()
        count.setObjectName("Hint")
        bar.addWidget(count)
        return bar, find, sort, count

    def _size(self) -> int:
        return int(self._prefs.get("size") or 110)

    def _size_moved(self, v: int):
        for sl in getattr(self, "_size_sliders", []):
            if sl.value() != v:
                sl.blockSignals(True)
                sl.setValue(v)
                sl.blockSignals(False)
        self._prefs["size"] = v
        if not any(sl.isSliderDown() for sl in self._size_sliders):
            self._apply_size()

    def _apply_size(self):
        w = self._size()
        self._set_pref("size", w)
        t = QSize(w, round(w * 1.4))
        for g in (getattr(self, "grid", None), getattr(self, "built_grid", None)):
            if g is not None:
                g.setIconSize(t)
                g.setGridSize(QSize(w + 18, t.height() + 44))
        if getattr(self, "rows", None):
            self._show_found()
        if getattr(self, "built", None) is not None:
            self._fill_built()

    def _set_big(self, on: bool):
        for b in getattr(self, "_big_btns", []):
            if b.isChecked() != on:
                b.blockSignals(True)
                b.setChecked(on)
                b.blockSignals(False)
            b.setText("Normal view" if on else "Bigger view")
            icons.set_icon(b, "fullscreen_exit" if on else "fullscreen")
        for w in (self.header, self.db_box, getattr(self, "filters_box", None),
                  getattr(self, "build_opts", None)):
            if w is not None:
                w.setVisible(not on)
        self._set_pref("big_view", on)

    def _set_pref(self, key: str, value):
        if self._prefs.get(key) != value:
            self._prefs[key] = value
            _save_prefs(self._prefs)

    def _search_menu(self, pos):
        if self.grid.itemAt(pos) is None:
            return
        m = self._card_menu(self.selected())
        m.addSeparator()
        m.addAction("Save the selected as a decklist…",
                    lambda: self.save_list(self.selected() or self.rows))
        m.exec(self.grid.viewport().mapToGlobal(pos))

    def _card_menu(self, rows: list) -> QMenu:
        """What every card offers: like the Decklists and Proxy decks pages."""
        n = len(rows)
        m = QMenu(self)
        if not rows:
            return m
        first = rows[0]
        m.addAction(icons.icon("zoom_in"), "See it full size", lambda: self.view_full(first))
        m.addSeparator()
        a = m.addAction(icons.icon("shopping_cart"),
                        "Add to my order (a real card, printed as it is)" if n == 1 else
                        f"Add the {n} to my order (real cards, printed as they are)",
                        lambda: self.add_real(rows))
        a.setEnabled(self.main.project is not None)
        edit = m.addMenu(icons.icon("edit"), "Add to my deck to edit" if n == 1 else
                         f"Add the {n} to my deck to edit")
        edit.setEnabled(self.main.project is not None)
        self._fill_edit_menu(edit, lambda: rows)
        self._tools_menu(m, first)
        m.addSeparator()
        sid = first.get("id", "")
        if sid:
            m.addAction(icons.icon("open_in_new"), "Open on Scryfall",
                        lambda: QDesktopServices.openUrl(QUrl(f"https://scryfall.com/card/"
                                                              f"{first['set_code']}/"
                                                              f"{first['number']}")))
        return m

    def _fill_edit_menu(self, menu: QMenu, rows_fn):
        for label, frame, art in (("With its artwork, in my frame", "mine", True),
                                  ("With its artwork, in a frame like the real card", "real",
                                   True),
                                  ("Text only (no artwork)", "mine", False)):
            menu.addAction(label, lambda f=frame, a=art: self.add_custom(rows_fn(), f, a))

    def _tools_menu(self, menu: QMenu, row: dict):
        """Picture tools from other add-ons (Keep only the art…)."""
        try:
            from mse_studio.core import picture_tools
        except ImportError:
            return
        tools = picture_tools.tools()
        if not tools:
            a = menu.addAction(icons.icon("brush"), "Keep only the art (Art only add-on)")
            a.setEnabled(False)
            a.setToolTip("Get the Art only add-on: Manage → Add-ons → Store")
            return
        for t in tools:
            a = menu.addAction(icons.icon("brush"), t.label,
                               lambda t=t: self._full_then(row, lambda path: picture_tools.run(
                                   t, self, path, {"name": row["name"],
                                                   "card": carddb.card_of(row), "kind": "real",
                                                   "credit": f"Art by {row.get('artist') or '?'}"
                                                             " · Scryfall"})))
            a.setToolTip(t.tooltip)

    def view_full(self, row: dict):
        """The card's biggest picture (Scryfall's), in MSE Studio's viewer."""
        def show(path):
            from mse_studio.gui.image_viewer import ImageViewer
            ImageViewer(self, [path]).exec()
        self._full_then(row, show)

    def _full_then(self, row: dict, fn):
        card = carddb.card_of(row)

        def work(progress=None, cancel=None):
            progress(0, 0, f"Getting {row['name']}…")
            fetch = getattr(dl, "fetch_full", None)        # MSE Studio 0.17
            if fetch is not None:
                return fetch(card)
            from mse_studio.core import addons
            out = addons.data_dir("card-database") / "pictures" / f"{row['id']}.jpg"
            if not out.exists():
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(_get(row["image"], 60))
            return out

        def done(path):
            try:
                fn(Path(path))
            except RuntimeError:
                return
        job = Job(work, label=f"Getting {row['name']}")
        job.signals.finished.connect(done)
        job.signals.failed.connect(lambda m: error(self, "Card database",
                                                   "Couldn't get the picture: " +
                                                   m.splitlines()[0]))
        self._jobs.append(start(job))

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

    def add_custom(self, rows: list[dict], frame: str = "mine", with_art: bool = True):
        if self.main.project is None or not rows:
            return
        self.main.decklists_tab.add_custom(self._entries(rows), "the card database",
                                           with_art=with_art, frame=frame)

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
        self.build_opts = QWidget()
        ov = QVBoxLayout(self.build_opts)
        ov.setContentsMargins(0, 0, 0, 0)
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
        how = QHBoxLayout()
        self.style = QComboBox()
        for key, st in carddb.STYLES.items():
            self.style.addItem(st.label, key)
            self.style.setItemData(self.style.count() - 1, st.tip, Qt.ToolTipRole)
        self.style.setToolTip("How the deck plays: it sets the numbers below and what kind of "
                              "cards it likes")
        self.style.currentIndexChanged.connect(self._style_changed)
        how.addWidget(self.style)
        how.addWidget(QLabel("Power"))
        self.power = QComboBox()
        for key, (label, _w) in carddb.POWER.items():
            self.power.addItem(label, key)
        self.power.setCurrentIndex(self.power.findData("focused"))
        self.power.setToolTip("Casual leaves out extra turns, land destruction and locks; high "
                              "power picks the most played cards")
        how.addWidget(self.power)
        how.addStretch(1)
        f.addRow("Play style", how)
        th = QHBoxLayout()
        self.theme_btn = QToolButton()
        self.theme_btn.setText("Themes ▾")
        self.theme_btn.setPopupMode(QToolButton.InstantPopup)
        self.theme_btn.setToolTip("Ready-made themes and tribes – tick as many as you like")
        tm = QMenu(self.theme_btn)
        self.theme_acts = {}
        for name in carddb.THEMES:
            a = tm.addAction(name)
            a.setCheckable(True)
            a.toggled.connect(self._themes_changed)
            self.theme_acts[name] = a
        self.theme_btn.setMenu(tm)
        th.addWidget(self.theme_btn)
        self.theme_lbl = QLabel("none")
        self.theme_lbl.setObjectName("Hint")
        th.addWidget(self.theme_lbl)
        self.theme = QLineEdit()
        self.theme.setPlaceholderText("and/or your own theme words, e.g. counters lifelink")
        th.addWidget(self.theme, 1)
        f.addRow("Themes", th)
        nums = QHBoxLayout()
        self.counts = {}
        for key, label in (("lands", "Lands"), ("ramp", "Ramp"), ("draw", "Card draw"),
                           ("removal", "Removal"), ("wipe", "Wipes"), ("protection", "Protection")):
            sb = QSpinBox()
            sb.setRange(0, 60)
            sb.setValue(carddb.DEFAULT_COUNTS[key])
            nums.addWidget(QLabel(label))
            nums.addWidget(sb)
            self.counts[key] = sb
        nums.addStretch(1)
        f.addRow("How many", nums)
        opts = QHBoxLayout()
        self.avoid = {}
        for key, label in (("extra turns", "No extra turns"),
                           ("land destruction", "No land destruction"),
                           ("tutors", "No tutors"), ("stax", "No taxes or locks")):
            cb = QCheckBox(label)
            opts.addWidget(cb)
            self.avoid[key] = cb
        opts.addStretch(1)
        f.addRow("Leave out", opts)
        self.build_price = QDoubleSpinBox()
        self.build_price.setRange(0, 10000)
        self.build_price.setSpecialValueText("any")
        self.build_price.setToolTip("Leave out cards dearer than this (in US dollars) – with the "
                                    "Card prices add-on")
        self.build_price_lbl = QLabel("Max price per card")
        f.addRow(self.build_price_lbl, self.build_price)
        self.build_usd = self.build_price            # the name before 1.1
        ov.addLayout(f)
        v.addWidget(self.build_opts)
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
        # the cards it picked: pictures, pick some or all
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        bar, self.built_find, self.built_sort, self.built_count = self._view_bar(
            [("deck", "Deck order")] + VIEW_SORTS, self._fill_built)
        self.built_show = QComboBox()
        self.built_show.setToolTip("One group of the deck: ramp, card draw, lands…")
        self.built_show.currentIndexChanged.connect(lambda *_: self._fill_built())
        bar.insertWidget(0, self.built_show)
        bar.insertWidget(0, QLabel("Show"))
        lv.addLayout(bar)
        self.built_grid = self._make_grid(self._built_menu, self._built_details,
                                          self._built_full)
        self.built_grid.setToolTip("Click a card to see it; Ctrl+click or Shift+click to pick "
                                   "several; right-click for more; double-click: full size")
        try:
            from mse_studio.gui.common import delete_key
            delete_key(self.built_grid, self.drop_picked)
        except ImportError:
            pass
        lv.addWidget(self.built_grid, 1)
        split.addWidget(left)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(6, 0, 0, 0)
        self.built_info = QTextBrowser()
        self.built_info.setOpenExternalLinks(True)
        rv.addWidget(self.built_info, 1)
        for label, icon, tip, fn in (
                ("Add the picked to my order (real cards)", "shopping_cart",
                 "The cards you picked, printed with their real picture – straight to the "
                 "Order page", lambda: self.add_real(self.built_rows())),
                ("Add the picked to my deck to edit", "edit",
                 "New cards of your own with the picked cards' text and artwork, in your frame",
                 lambda: self.add_custom(self.built_rows())),
                ("Another card for this job", "refresh",
                 "Swap the picked cards for the next best ones doing the same job",
                 self.swap_picked),
                ("Take out of the deck", "delete", "Leave the picked cards out of this build",
                 self.drop_picked)):
            b = QPushButton(label)
            icons.set_icon(b, icon)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            rv.addWidget(b)
        split.addWidget(right)
        split.setSizes([800, 330])
        v.addWidget(split, 1)
        row = QHBoxLayout()
        b = QPushButton("Make a new deck with it…")
        b.setProperty("kind", "primary")
        icons.set_icon(b, "create_new_folder")
        b.setToolTip("A new MSE Studio deck with all these cards as real cards (the commander "
                     "as its commander) – for a deck you're starting")
        b.clicked.connect(self.new_deck_from_build)
        row.addWidget(b)
        b = QPushButton("Save as a decklist")
        b.setToolTip("Playtest it, or add it to a deck, from the Decklists page")
        b.clicked.connect(self.save_built)
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        return w

    def _style_changed(self, *_):
        st = carddb.STYLES.get(self.style.currentData())
        if st is None:
            return
        for k, sb in self.counts.items():
            sb.setValue({**carddb.DEFAULT_COUNTS, **st.counts}.get(k, sb.value()))

    def _themes_changed(self, *_):
        on = [n for n, a in self.theme_acts.items() if a.isChecked()]
        self.theme_lbl.setText(", ".join(on[:3]) + (f" +{len(on) - 3}" if len(on) > 3 else "")
                               if on else "none")

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
        counts = {k: sb.value() for k, sb in self.counts.items()}
        theme, seed = self.theme.text(), self._seed
        usd = (self.build_price.value() or None) if self._prices_on() else None
        style, power = self.style.currentData(), self.power.currentData()
        themes = [n for n, a in self.theme_acts.items() if a.isChecked()]
        avoid = {k for k, cb in self.avoid.items() if cb.isChecked()}

        def work(progress=None, cancel=None):
            conn = carddb.connect()
            try:
                deck = carddb.build_deck(conn, name, counts, theme, seed, usd, style=style,
                                         power=power, themes=themes, avoid=avoid)
                for p in deck.picks:          # plain data: the connection closes here
                    p.row = dict(p.row) if p.row is not None else None
                deck.lead = dict(deck.lead)
                deck.spares = {k: [dict(r) for r in v] for k, v in deck.spares.items()}
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
            keep = self.built_show.currentData()
            self.built_show.blockSignals(True)
            self.built_show.clear()
            self.built_show.addItem("Every card", "")
            groups = []
            for p in deck.picks:
                if p.why not in groups:
                    groups.append(p.why)
            for g in groups:
                n = sum(p.count for p in deck.picks if p.why == g)
                self.built_show.addItem(f"{g} ({n})", g)
            self.built_show.setCurrentIndex(max(0, self.built_show.findData(keep)))
            self.built_show.blockSignals(False)
            self._fill_built()
            self.build_lbl.setText(f"{deck.size} cards with {deck.commander} · "
                                   + ("; ".join(deck.notes) if deck.notes else "ready"))
        except RuntimeError:
            pass

    def _fill_built(self):
        d = self.built
        self.built_grid.clear()
        if d is None:
            return
        want = self.built_show.currentData() or ""
        q = self.built_find.text().strip().lower()
        shown = [(-1, None)] if not want else []
        shown += [(k, p) for k, p in enumerate(d.picks) if not want or p.why == want]
        if q:
            shown = [(k, p) for k, p in shown
                     if q in ((d.commander if p is None else p.name).lower() + " " +
                              ((d.lead if p is None else p.row) or {}).get("ltype", ""))]
        key = self.built_sort.currentData()
        if key and key != "deck":
            head = [x for x in shown if x[1] is None]
            rest = sorted((x for x in shown if x[1] is not None),
                          key=lambda x: _sort_key(x[1].row or {"lname": x[1].name.lower()},
                                                  key))
            shown = head + rest
            self._set_pref("built_sort", key)
        for k, p in shown:
            row = d.lead if p is None else p.row
            label = (f"★ {d.commander}" if p is None else
                     (f"{p.count}× {p.name}" if p.count > 1 else p.name))
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, k)
            it.setToolTip("The commander" if p is None else p.why)
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            pm = self._thumb(row) if row else None
            if pm is not None:
                it.setIcon(QIcon(pm))
            self.built_grid.addItem(it)
        self.built_count.setText(f"{len(shown)} shown")

    def picked(self) -> list:
        """The picks selected in the grid (not the commander)."""
        d = self.built
        if d is None:
            return []
        ks = sorted({it.data(Qt.UserRole) for it in self.built_grid.selectedItems()})
        return [d.picks[k] for k in ks if 0 <= k < len(d.picks)]

    def built_rows(self) -> list:
        """The selected cards as rows (the commander too when it's selected)."""
        d = self.built
        if d is None:
            return []
        out = []
        for it in self.built_grid.selectedItems():
            k = it.data(Qt.UserRole)
            row = d.lead if k == -1 else (d.picks[k].row if 0 <= k < len(d.picks) else None)
            if row:
                out.append(row)
        return out

    def _built_details(self):
        it = self.built_grid.currentItem()
        d = self.built
        if it is None or d is None:
            self.built_info.setHtml("")
            return
        k = it.data(Qt.UserRole)
        row = d.lead if k == -1 else d.picks[k].row
        why = "The commander" if k == -1 else d.picks[k].why
        self.built_info.setHtml(f"<p style='color:gray'>{why}</p>" + self._card_html(row)
                                if row else "")

    def _built_menu(self, pos):
        if self.built_grid.itemAt(pos) is None:
            return
        m = self._card_menu(self.built_rows())
        m.addSeparator()
        m.addAction(icons.icon("refresh"), "Another card for this job", self.swap_picked)
        a = m.addAction(icons.icon("delete"), "Take out of the deck", self.drop_picked)
        a.setShortcut(Qt.Key_Delete)
        m.exec(self.built_grid.viewport().mapToGlobal(pos))

    def _built_full(self):
        rows = self.built_rows()
        if rows:
            self.view_full(rows[0])

    def swap_picked(self):
        d = self.built
        picks = self.picked()
        if d is None or not picks:
            return
        done = [p for p in picks if p.why != "Basic land" and d.swap(p) is not None]
        self._show_built(d)
        self.build_lbl.setText(f"Swapped {len(done)} card(s)." if done else
                               "No other card does that job here.")

    def drop_picked(self):
        d = self.built
        picks = self.picked()
        if d is None or not picks:
            return
        gone = {id(p) for p in picks}
        d.picks = [p for p in d.picks if id(p) not in gone]
        self._show_built(d)

    def save_built(self):
        d = self.built
        if d is None:
            return
        self.save_list([], f"{d.commander} – built", d.entries())

    def new_deck_from_build(self):
        """A new MSE Studio deck with every card of the build (real cards)."""
        d = self.built
        if d is None:
            return
        before = self.main.project
        try:
            p = self.main.new_deck(name=d.commander)        # MSE Studio 0.18
        except TypeError:
            self.main.new_deck()
            p = self.main.project if self.main.project is not before else None
        if p is None:
            return
        entries = [e for e in d.entries() if e.found]
        n = dl.add_to_project(p, entries)
        p.save_config()
        self.main.record(f"Card database · new deck around {d.commander} · {n} real card(s)")
        self.main.update_title()
        self.main.statusBar().showMessage(f"{p.name}: {n} real cards with {d.commander} – "
                                          "they're on the Order page", 10000)
        self.main.order_tab.real_pictures(entries)

    def add_built(self):
        """Every card of the build into the open deck (as before 1.1)."""
        d = self.built
        p = self.main.project
        if d is None or p is None:
            return
        entries = [e for e in d.entries() if e.found]
        n = dl.add_to_project(p, entries)
        self.main.record(f"Card database · built deck · {n} real card(s)")
        self.main.update_title()
        self.main.order_tab.real_pictures(entries)
