"""MPCFill: browse print-ready card pictures from the community's drives (as on
mpcfill.com/explore), sorted by drive, name, quality or date – and print one
as a real card of your deck, use it as the card back, or save it.

Talks only to the MPCFill server and image server set in MSE Studio (MPCFill…
button), and only when you search or pick a picture."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListView, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPushButton, QSpinBox, QSplitter, QToolButton, QVBoxLayout,
                               QWidget)

from mse_studio.core import mpcfill
from mse_studio.gui import icons, thumbs
from mse_studio.gui.common import error, forget, Job, start
from mse_studio.gui.nav import page_header

THUMB = QSize(126, 176)
TYPES = [("Cards", ["CARD"]), ("Card backs", ["CARDBACK"]), ("Tokens", ["TOKEN"]),
         ("Everything", ["CARD", "CARDBACK", "TOKEN"])]
SORTS = [("By drive (source)", "source"), ("Name A–Z", "nameAscending"),
         ("Name Z–A", "nameDescending"), ("Best quality (DPI) first", "dpi"),
         ("Newest first", "dateCreatedDescending"), ("Oldest first", "dateCreatedAscending")]
HEADER = Qt.UserRole + 1


class MpcfillPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._jobs: list = []
        self.cards: list[dict] = []
        self.count = 0
        self.page = 0
        self.sources: list[dict] = []
        self.off: set[int] = set()            # drives left out of the search
        self.shown: dict[str, dict] = {}       # card id -> card, for the items
        lay = QVBoxLayout(self)
        lay.addWidget(page_header(
            "MPCFill", "Print-ready card pictures from the community's drives, as on "
                       "mpcfill.com/explore. Search, then print one as a real card in your "
                       "deck, use it as your card back, or save it."))
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Card name (empty: everything)")
        self.query.returnPressed.connect(self.search)
        row.addWidget(self.query, 2)
        self.kind = QComboBox()
        for label, types in TYPES:
            self.kind.addItem(label, types)
        row.addWidget(self.kind)
        self.sort = QComboBox()
        for label, key in SORTS:
            self.sort.addItem(label, key)
        self.sort.currentIndexChanged.connect(self._fill)
        row.addWidget(self.sort)
        row.addWidget(QLabel("Min DPI"))
        self.min_dpi = QSpinBox()
        self.min_dpi.setRange(0, 1500)
        self.min_dpi.setSingleStep(100)
        self.min_dpi.setToolTip("Only pictures at least this sharp (MPC prints at 300+; 800 "
                                "and up is very sharp)")
        row.addWidget(self.min_dpi)
        self.src_btn = QToolButton()
        self.src_btn.setText("Drives ▾")
        self.src_btn.setPopupMode(QToolButton.InstantPopup)
        self.src_btn.setToolTip("Which drives (sources) to search")
        self.src_menu = QMenu(self.src_btn)
        self.src_btn.setMenu(self.src_menu)
        row.addWidget(self.src_btn)
        b = QPushButton("Search")
        b.setProperty("kind", "primary")
        icons.set_icon(b, "search")
        b.clicked.connect(self.search)
        row.addWidget(b)
        b = QPushButton("MPCFill…")
        b.setToolTip("MPCFill's server and image server (Find them from mpcfill.com)")
        b.clicked.connect(self.settings)
        row.addWidget(b)
        lay.addLayout(row)
        self.status = QLabel()
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setWrapping(True)
        self.grid.setSpacing(6)
        self.grid.setIconSize(THUMB)
        self.grid.setWordWrap(True)
        self.grid.currentItemChanged.connect(lambda *_: self._details())
        self.grid.itemDoubleClicked.connect(lambda _it: self.print_real())
        lv.addWidget(self.grid, 1)
        self.more_btn = QPushButton("Show more")
        self.more_btn.clicked.connect(self.more)
        self.more_btn.setVisible(False)
        lv.addWidget(self.more_btn)
        split.addWidget(left)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 0, 0, 0)
        self.big = QLabel()
        self.big.setAlignment(Qt.AlignCenter)
        self.big.setMinimumSize(250, 350)
        rv.addWidget(self.big)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        self.info.setOpenExternalLinks(True)
        self.info.setMinimumHeight(110)
        self.info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        rv.addWidget(self.info)
        self.real_btn = QPushButton("Print it as a real card in my deck")
        icons.set_icon(self.real_btn, "print")
        self.real_btn.setToolTip("The real card of that name in your deck is printed with this "
                                 "picture (it's added to the deck if it isn't there yet)")
        self.real_btn.clicked.connect(self.print_real)
        rv.addWidget(self.real_btn)
        self.back_btn = QPushButton("Use as my deck's card back")
        self.back_btn.clicked.connect(self.use_back)
        rv.addWidget(self.back_btn)
        self.save_btn = QPushButton("Save the picture…")
        icons.set_icon(self.save_btn, "download")
        self.save_btn.clicked.connect(self.save_picture)
        rv.addWidget(self.save_btn)
        rv.addStretch(1)
        split.addWidget(right)
        split.setSizes([900, 320])
        lay.addWidget(split, 1)
        thumbs.cache().ready.connect(self._thumb_ready)
        self._details()

    # ------------------------------------------------------------ MSE Studio calls these
    def load(self):
        self._update_status()

    def refresh(self):
        self._update_status()
        if not self.sources and self._server():
            self._load_sources()

    def shutdown(self):
        forget(self._jobs)                # the page is going: nothing may call it back

    # ------------------------------------------------------------ settings
    def _server(self) -> str:
        return mpcfill.clean_url(getattr(self.main.settings, "mpcfill_server", ""))

    def _images(self) -> str:
        return getattr(self.main.settings, "mpcfill_images", "")

    def settings(self):
        from mse_studio.gui.mpcfill_dialog import MpcfillDialog
        if MpcfillDialog(self, self.main.settings).exec():
            self.sources = []
            self.refresh()

    def _update_status(self):
        if not self._server():
            self.status.setText("Set up MPCFill first: <b>MPCFill…</b> → <b>Find them from "
                                "mpcfill.com</b>.")
        elif self.cards:
            self.status.setText(f"{len(self.cards)} of {self.count} picture(s) · "
                                f"{len(self.sources) - len(self.off)} drive(s)")
        else:
            self.status.setText(f"MPCFill server: {self._server()}")

    def _load_sources(self):
        server = self._server()
        job = Job(lambda progress=None, cancel=None: mpcfill.sources(server))
        job.signals.finished.connect(self._got_sources)
        job.signals.failed.connect(lambda m: self.status.setText(
            "MPCFill's server didn't answer: " + m.splitlines()[0][:200]))
        self._jobs.append(start(job))

    def _got_sources(self, sources: list):
        try:
            self.sources = sources
            self.src_menu.clear()
            a = self.src_menu.addAction("All drives")
            a.triggered.connect(lambda: self._all_sources(True))
            a = self.src_menu.addAction("No drives")
            a.triggered.connect(lambda: self._all_sources(False))
            self.src_menu.addSeparator()
            for s in sources:
                a = self.src_menu.addAction(s["name"])
                a.setCheckable(True)
                a.setChecked(s["pk"] not in self.off)
                a.setData(s["pk"])
                a.toggled.connect(self._source_toggled)
            self._update_status()
        except RuntimeError:          # the page was closed meanwhile
            pass

    def _source_toggled(self, on: bool):
        a = self.sender()
        pk = a.data() if a is not None else None
        if pk is None:
            return
        (self.off.discard if on else self.off.add)(pk)

    def _all_sources(self, on: bool):
        self.off = set() if on else {s["pk"] for s in self.sources}
        for a in self.src_menu.actions():
            if a.isCheckable():
                a.blockSignals(True)
                a.setChecked(on)
                a.blockSignals(False)

    # ------------------------------------------------------------ searching
    def search(self):
        self.cards, self.count, self.page = [], 0, 0
        self._fetch()

    def more(self):
        self.page += 1
        self._fetch()

    def _fetch(self):
        server = self._server()
        if not server:
            self._update_status()
            return
        text, types = self.query.text(), self.kind.currentData()
        sort = self.sort.currentData()
        server_sort = sort if sort not in ("source", "dpi") else "nameAscending"
        pks = [s["pk"] for s in self.sources if s["pk"] not in self.off] or None
        page, min_dpi = self.page, self.min_dpi.value()

        def work(progress=None, cancel=None):
            return mpcfill.explore(server, text, page, mpcfill.PAGE_SIZE, server_sort, types,
                                   pks, min_dpi)

        self.status.setText("Searching MPCFill…")
        job = Job(work, label="Searching MPCFill")
        job.signals.finished.connect(self._got_cards)
        job.signals.failed.connect(lambda m: self.status.setText(
            "MPCFill's server didn't answer: " + m.splitlines()[0][:200]))
        self._jobs.append(start(job))

    def _got_cards(self, res):
        try:
            cards, count = res
            seen = {c["id"] for c in self.cards}
            self.cards += [c for c in cards if c["id"] not in seen]
            self.count = count
            self.more_btn.setVisible(len(self.cards) < count)
            self._fill()
            self._update_status()
        except RuntimeError:
            pass

    def _sorted(self) -> list[dict]:
        key = self.sort.currentData()
        if key == "source":
            order = {s["name"]: k for k, s in enumerate(self.sources)}
            return sorted(self.cards, key=lambda c: (order.get(c["source"], 999), c["source"],
                                                     c["name"].lower(), -c["dpi"]))
        if key == "dpi":
            return sorted(self.cards, key=lambda c: (-c["dpi"], c["name"].lower()))
        return list(self.cards)

    def _fill(self):
        """The pictures, with a heading for each drive when sorted by drive."""
        keep = self._current_id()
        self.grid.clear()
        self.shown = {}
        group = None
        by_source = self.sort.currentData() == "source"
        width = max(200, self.grid.viewport().width() - 24)
        for c in self._sorted():
            if by_source and c["source"] != group:
                group = c["source"]
                n = sum(1 for x in self.cards if x["source"] == group)
                head = QListWidgetItem(f"{group}  ·  {n}")
                head.setFlags(Qt.ItemIsEnabled)          # a heading: not picked
                head.setData(HEADER, True)
                head.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                head.setSizeHint(QSize(width, 26))
                f = head.font()
                f.setBold(True)
                head.setFont(f)
                self.grid.addItem(head)
            it = QListWidgetItem(f"{c['name']}\n{c['dpi']} DPI")
            it.setData(Qt.UserRole, c["id"])
            it.setToolTip(f"{c['name']}\n{c['source']} · {c['dpi']} DPI"
                          + (f" · {c['language']}" if c.get("language") else "")
                          + (f"\n{', '.join(c['tags'])}" if c.get("tags") else ""))
            it.setSizeHint(QSize(THUMB.width() + 12, THUMB.height() + 44))
            pm = self._thumb(c)
            if pm is not None:
                it.setIcon(QIcon(pm))
            self.shown[c["id"]] = c
            self.grid.addItem(it)
            if c["id"] == keep:
                self.grid.setCurrentItem(it)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        width = max(200, self.grid.viewport().width() - 24)
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            if it.data(HEADER):
                it.setSizeHint(QSize(width, 26))

    def _thumb(self, c: dict):
        url = c.get("thumb")
        if not url:
            return None
        return thumbs.cache().get(f"mpcfill:{c['id']}", "1",
                                  lambda url=url: mpcfill._http(url, timeout=30))

    def _thumb_ready(self, source_id: str):
        try:
            if not source_id.startswith("mpcfill:"):
                return
            cid = source_id.split(":", 1)[1]
            c = self.shown.get(cid)
            if c is None:
                return
            pm = self._thumb(c)
            for i in range(self.grid.count()):
                it = self.grid.item(i)
                if it.data(Qt.UserRole) == cid and pm is not None:
                    it.setIcon(QIcon(pm))
            if self._current_id() == cid:
                self._details()
        except RuntimeError:          # the page was closed
            return

    # ------------------------------------------------------------ the picked picture
    def _current_id(self) -> str:
        it = self.grid.currentItem()
        return it.data(Qt.UserRole) if it is not None and not it.data(HEADER) else ""

    def current(self):
        return self.shown.get(self._current_id())

    def _details(self):
        c = self.current()
        has_deck = self.main.project is not None
        self.real_btn.setEnabled(c is not None and has_deck)
        self.back_btn.setEnabled(c is not None and has_deck)
        self.save_btn.setEnabled(c is not None)
        if c is None:
            self.big.setPixmap(QPixmap())
            self.info.setText("Pick a picture.")
            return
        pm = self._thumb(c)
        if pm is not None:
            self.big.setPixmap(pm.scaled(250, 350, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        src = next((s for s in self.sources if s["name"] == c["source"]), {})
        link = f" (<a href='{src['link']}'>open</a>)" if src.get("link") else ""
        self.info.setText(
            f"<b>{c['name']}</b><br>{c['dpi']} DPI · {c['type'].lower()}"
            + (f" · {c['language']}" if c.get("language") else "")
            + f"<br>Drive: {c['source']}{link}"
            + (f"<br>Set: {c['set'].upper()}" if c.get("set") else "")
            + (f"<br>Artist: {c['artist']}" if c.get("artist") else "")
            + (f"<br>Tags: {', '.join(c['tags'])}" if c.get("tags") else ""))

    # ------------------------------------------------------------ actions
    def print_real(self):
        """Print the real card of that name with this picture."""
        from mse_studio.core import decklists as dl
        from mse_studio.pipeline import real_cards as rc
        c, p = self.current(), self.main.project
        if c is None or p is None:
            return
        entry = rc.matching_entry(p, c["name"])
        if entry is not None:
            self._use_for(entry, c)
            return
        name = c["name"].split("(")[0].strip()
        if QMessageBox.question(self, "MPCFill", f"<b>{name}</b> isn't a real card of your "
                                f"deck yet. Add it (as a real card) and print it with this "
                                f"picture?") != QMessageBox.Yes:
            return

        def work(progress=None, cancel=None):
            return dl.resolve([dl.Entry(name=name)], progress, cancel)

        def done(found):
            ok = [e for e in found if e.found]
            if not ok:
                error(self, "MPCFill", f"Scryfall doesn't know a card called {name}.")
                return
            dl.add_to_project(p, ok)
            self.main.record(f"MPCFill · real card {name}")
            self._use_for(rc.matching_entry(p, c["name"]) or ok[0], c)

        job = Job(work, label=f"Looking up {name}")
        job.signals.finished.connect(done)
        job.signals.failed.connect(lambda m: error(self, "MPCFill", m.splitlines()[0]))
        self._jobs.append(start(job))

    def _use_for(self, entry, c: dict):
        from mse_studio.pipeline import real_cards as rc
        p = self.main.project
        side = 1 if len(rc.faces(entry)) > 1 and \
            rc.query(c["name"]) == rc.query(rc.faces(entry)[1]) else 0
        rc.use_mpcfill(p, entry, c, side)
        p.save_config()
        self.main.update_title()
        self.main.statusBar().showMessage(f"{entry.display_name} will be printed with this "
                                          f"picture – making its print file…", 8000)
        self.main.order_tab.real_pictures([entry])

    def _download(self, then, label: str):
        c = self.current()
        if c is None:
            return
        images = self._images()

        def work(progress=None, cancel=None):
            return mpcfill.download(c["id"], images)

        job = Job(work, label=label)
        job.signals.finished.connect(lambda data: then(c, data))
        job.signals.failed.connect(lambda m: error(self, "MPCFill", m.splitlines()[0]))
        self._jobs.append(start(job))

    def use_back(self):
        from mse_studio.core import card_backs
        p = self.main.project
        if p is None:
            return

        def done(c, data):
            folder = Path(p.folder) / "card backs"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{_safe(c['name'])} ({c['source']}).{_ext(data)}"
            path.write_bytes(data)
            card_backs.use_for_deck(p, path)
            self.main.order_tab.refresh()
            self.main.statusBar().showMessage(f"{c['name']} is your deck's card back now", 8000)
        self._download(done, "Getting the card back")

    def save_picture(self):
        c = self.current()
        if c is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the picture", f"{_safe(c['name'])} ({c['source']}).png",
            "Pictures (*.png *.jpg)")
        if not path:
            return

        def done(_c, data):
            Path(path).write_bytes(data)
            self.main.statusBar().showMessage(f"Saved {Path(path).name}", 6000)
        self._download(done, "Downloading the picture")


def _safe(name: str) -> str:
    import re
    return re.sub(r'[<>:"/\\|?*]+', "", name).strip() or "picture"


def _ext(data: bytes) -> str:
    return "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "jpg"
