"""Proxy decks: decks people share on r/mpcproxies, Ko-fi and Discord (real
Magic cards with new art and frames), straight from their public Google Drive
folders – and proxy folders or zips on your own PC. Import a deck to see its
cards, tick the ones you want and add them to your deck as real cards printed
with those pictures (every picture keeps its maker's credit), save them as a
decklist, or save the pictures.

Network: Google Drive (a deck's folder, thumbnails and pictures) when you
import a deck or use its pictures; Reddit and Ko-fi only when you search
them or read a link you pasted; Scryfall to look the cards up when you add
them to your deck. Decks on this PC are read from the folder or zip you
picked."""
from __future__ import annotations

import copy
import re
import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from mse_studio.core import decklists as dl
from mse_studio.gui import icons, thumbs
from mse_studio.gui.common import Job, error, forget, start
from mse_studio.gui.nav import page_header

from . import gdrive, local
from . import proxies as px

THUMB = QSize(126, 176)
GROUPS = [("free", "Free"), ("paid", "Paid – on Ko-fi"), ("mine", "Added by you"),
          ("pc", "On this PC")]
SORTS = [("deck", "Deck order"), ("name", "Name"), ("folder", "Folder (card type)"),
         ("count", "Copies")]


def _group(d: px.Deck) -> str:
    return "pc" if d.on_pc else "mine" if d.mine else ("paid" if d.price == "paid" else "free")


def _label(d: px.Deck) -> str:
    marks = []
    if d.price == "paid" and d.bought_link:
        marks.append("✓ yours")
    if px.is_imported(d.id):
        marks.append("imported")
    return d.title + (f"  · {', '.join(marks)}" if marks else "")


class ProxiesPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._jobs: list = []
        self._decks: dict[str, px.Deck] = {}
        self.deck: px.Deck | None = None
        self.cards: list[px.Card] = []
        self.backs: list[gdrive.Item] = []
        self.text = ""
        self._by_key: dict[str, px.Card] = {}
        self._ticked: set[str] = set()
        self._thumb_for: dict[str, list[str]] = {}
        self._importing = ""
        lay = QVBoxLayout(self)
        lay.addWidget(page_header(
            "Proxy decks", "Decks people share on r/mpcproxies, Ko-fi and Discord – real Magic "
                           "cards with new art and frames – from their Google Drive, or proxy "
                           "folders on this PC. Import a deck, tick the cards you want and add "
                           "them to your deck: they're printed with those pictures, and every "
                           "picture keeps its maker's credit."))
        split = QSplitter(Qt.Horizontal)

        # ---------------------------------------------------------------- the decks
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.list = QTreeWidget()
        self.list.setHeaderHidden(True)
        self.list.currentItemChanged.connect(self._picked)
        lv.addWidget(self.list, 1)
        row = QHBoxLayout()
        b = QPushButton("Add a link or post…")
        icons.set_icon(b, "link")
        b.setToolTip("A Google Drive folder, a Reddit post or a Ko-fi page – or a whole post "
                     "copied from Reddit or Discord. The name and maker are found for you.")
        b.clicked.connect(self.add_link)
        row.addWidget(b)
        b = QPushButton("Add from this PC")
        icons.set_icon(b, "folder_open")
        b.setToolTip("Proxies you downloaded: a deck's folder, a folder of decks, or a zip")
        m = QMenu(b)
        m.addAction(icons.icon("folder_open"), "A folder (one deck, or a folder of decks)…",
                    self.add_folder)
        m.addAction(icons.icon("layers"), "A zip file…", self.add_zip)
        b.setMenu(m)
        row.addWidget(b)
        lv.addLayout(row)
        row = QHBoxLayout()
        b = QPushButton("Find on r/mpcproxies…")
        icons.set_icon(b, "search")
        b.setToolTip("Search r/mpcproxies (e.g. \"EDH deck\") and add the decks you like")
        b.clicked.connect(self.find_on_reddit)
        row.addWidget(b)
        self.remove_btn = QPushButton("Remove from my list")
        icons.set_icon(self.remove_btn, "delete")
        self.remove_btn.setToolTip("Decks on this PC: the files stay where they are")
        self.remove_btn.clicked.connect(self.remove)
        row.addWidget(self.remove_btn)
        lv.addLayout(row)
        split.addWidget(left)

        # ---------------------------------------------------------------- one deck
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.RichText)
        self.title.setOpenExternalLinks(True)
        rv.addWidget(self.title)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setObjectName("Hint")
        rv.addWidget(self.notes)
        row = QHBoxLayout()
        self.import_btn = QPushButton("Import the deck")
        self.import_btn.setProperty("kind", "primary")
        icons.set_icon(self.import_btn, "download")
        self.import_btn.setToolTip("Read the deck's cards from its folder; they stay here until "
                                   "you import it again")
        self.import_btn.clicked.connect(self.import_deck)
        row.addWidget(self.import_btn)
        self.buy_btn = QPushButton("Buy on Ko-fi")
        icons.set_icon(self.buy_btn, "open_in_new")
        self.buy_btn.clicked.connect(self._open_page)
        row.addWidget(self.buy_btn)
        self.bought_btn = QPushButton("I bought it – add my download link…")
        self.bought_btn.setToolTip("After buying, Ko-fi gives you a Google Drive link: paste it "
                                   "here and the deck opens here like the free ones")
        self.bought_btn.clicked.connect(self.add_bought_link)
        row.addWidget(self.bought_btn)
        self.source_btn = QPushButton("Google Drive")
        icons.set_icon(self.source_btn, "open_in_new")
        self.source_btn.clicked.connect(self._open_source)
        row.addWidget(self.source_btn)
        self.maker_btn = QPushButton("Who made it…")
        icons.set_icon(self.maker_btn, "edit")
        self.maker_btn.setToolTip("The maker's name and page, for the credit on every card")
        self.maker_btn.clicked.connect(self.edit_maker)
        row.addWidget(self.maker_btn)
        row.addStretch(1)
        rv.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        rv.addWidget(self.status)

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a card…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill_grid)
        row.addWidget(self.search, 1)
        row.addWidget(QLabel("Sort by"))
        self.sort = QComboBox()
        for k, label in SORTS:
            self.sort.addItem(label, k)
        self.sort.setToolTip("Deck order: the commander first, then by name. Folder: as the "
                             "maker sorted them (Creature, Land…)")
        self.sort.currentIndexChanged.connect(self._fill_grid)
        row.addWidget(self.sort)
        self.show_extra = QCheckBox("Show tokens and extras")
        self.show_extra.setChecked(True)
        self.show_extra.setToolTip("Tokens, extras and cards that aren't on the deck's own list "
                                   "(they start unticked)")
        self.show_extra.toggled.connect(self._fill_grid)
        row.addWidget(self.show_extra)
        self.tick_all = QPushButton("Tick all")
        self.tick_all.setToolTip("Tick every card shown (with the search and filter)")
        self.tick_all.clicked.connect(lambda: self._tick_shown(True))
        row.addWidget(self.tick_all)
        self.tick_none = QPushButton("Untick all")
        self.tick_none.clicked.connect(lambda: self._tick_shown(False))
        row.addWidget(self.tick_none)
        rv.addLayout(row)

        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setIconSize(THUMB)
        self.grid.setGridSize(QSize(THUMB.width() + 22, THUMB.height() + 58))
        self.grid.setWordWrap(True)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.setToolTip("Tick the cards to add. Double-click a card to see it full size; "
                             "right-click for more")
        self.grid.itemChanged.connect(self._tick_changed)
        self.grid.itemDoubleClicked.connect(self._double_clicked)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._grid_menu)
        rv.addWidget(self.grid, 1)

        row = QHBoxLayout()
        self.add_btn = QPushButton("Add the ticked to my deck")
        self.add_btn.setProperty("kind", "primary")
        icons.set_icon(self.add_btn, "add")
        self.add_btn.clicked.connect(lambda: self.add_to_deck())
        row.addWidget(self.add_btn)
        self.list_btn = QPushButton("Save as a decklist")
        self.list_btn.setToolTip("The deck's card list on the Decklists page (to view or "
                                 "playtest); tokens and extras go in its sideboard")
        self.list_btn.clicked.connect(self.save_decklist)
        row.addWidget(self.list_btn)
        self.save_btn = QPushButton("Save the pictures…")
        self.save_btn.setToolTip("The ticked cards' pictures (all of them when none is ticked) "
                                 "in a folder you choose")
        self.save_btn.clicked.connect(self.save_pictures)
        row.addWidget(self.save_btn)
        self.back_btn = QPushButton("Use its card back")
        self.back_btn.clicked.connect(self.use_back)
        row.addWidget(self.back_btn)
        b = QPushButton("Copy the credit")
        b.clicked.connect(self.copy_credit)
        row.addWidget(b)
        row.addStretch(1)
        rv.addLayout(row)
        split.addWidget(right)
        split.setSizes([320, 900])
        lay.addWidget(split, 1)
        thumbs.cache().ready.connect(self._thumb_ready)
        px.clear_scratch()
        self.fill_list()

    # ------------------------------------------------------------ MSE Studio calls these
    def load(self):
        self._buttons()

    def refresh(self):
        self._buttons()

    def shutdown(self):
        forget(self._jobs)

    # ------------------------------------------------------------ the list of decks
    def fill_list(self, keep: str = ""):
        keep = keep or (self.deck.id if self.deck else "") or px.last_deck()
        self._decks = {d.id: d for d in px.decks()}
        self.list.blockSignals(True)
        self.list.clear()
        groups = {}
        for key, label in GROUPS:
            g = QTreeWidgetItem(self.list, [label])
            g.setFlags(Qt.ItemIsEnabled)
            f = g.font(0)
            f.setBold(True)
            g.setFont(0, f)
            groups[key] = g
        pick = None
        for d in self._decks.values():
            it = QTreeWidgetItem(groups[_group(d)], [_label(d)])
            it.setData(0, Qt.UserRole, d.id)
            it.setToolTip(0, d.credit())
            if d.id == keep:
                pick = it
        for g in groups.values():
            g.setHidden(g.childCount() == 0)
        self.list.expandAll()
        self.list.blockSignals(False)
        if pick is None:
            pick = next((groups[k].child(0) for k, _l in GROUPS if groups[k].childCount()), None)
        self.deck = None
        if pick is not None:
            self.list.setCurrentItem(pick)
            if self.deck is None:                 # it was current already
                self._picked(pick, None)
        else:
            self._picked(None, None)

    def _tree_item(self, deck_id: str):
        for i in range(self.list.topLevelItemCount()):
            g = self.list.topLevelItem(i)
            for k in range(g.childCount()):
                if g.child(k).data(0, Qt.UserRole) == deck_id:
                    return g.child(k)
        return None

    def _picked(self, cur, _prev):
        did = cur.data(0, Qt.UserRole) if cur is not None else None
        self.deck = self._decks.get(did) if did else None
        self.cards, self.backs, self.text = [], [], ""
        self._by_key, self._ticked = {}, set()
        self.grid.clear()
        self.status.clear()
        d = self.deck
        if d is None:
            self.title.clear()
            self.notes.clear()
            self._buttons()
            return
        px.set_last_deck(d.id)
        links = " · ".join(f'<a href="{u}">{n}</a>' for n, u in (
            ("Ko-fi page", d.page), ("Reddit post", d.reddit),
            ("the maker", d.creator_link)) if u)
        who = d.creator or ("unknown – Who made it… adds it" if d.on_pc or d.mine else "unknown")
        where = (" · <b>On this PC</b>" if d.on_pc else
                 " · <b>Free</b>" if d.price == "free" else
                 " · <b>Paid</b>" + (" – you added your link" if d.bought_link else ""))
        self.title.setText(f"<b style='font-size:15px'>{d.title}</b><br>By {who}"
                           + (f" · {links}" if links else "") + where)
        self.notes.setText(d.notes or "")
        saved = px.load_listing(d.id)
        if saved is not None:
            items, text, when = saved
            self._show_cards(items, text, "imported " + time.strftime("%d %b %Y",
                                                                      time.localtime(when)))
        elif d.can_open:
            self.status.setText("Import the deck to see its cards.")
        else:
            self.status.setText("A paid deck: buy it on Ko-fi, then add the download link you "
                                "got – it opens here like the free ones.")
        self._buttons()

    def _buttons(self):
        d = self.deck
        locked = d is not None and not d.can_open
        self.import_btn.setVisible(d is not None and not locked)
        self.import_btn.setEnabled(d is not None and d.can_open and not self._importing)
        self.import_btn.setText("Import again" if d is not None and px.is_imported(d.id)
                                else "Import the deck")
        self.buy_btn.setVisible(d is not None and not d.on_pc and d.price == "paid"
                                and bool(d.page))
        self.bought_btn.setVisible(d is not None and not d.on_pc and d.price == "paid")
        self.bought_btn.setText("Change my download link…" if d is not None and d.bought_link
                                else "I bought it – add my download link…")
        self.source_btn.setVisible(d is not None and d.can_open)
        self.source_btn.setText("Open the folder" if d is not None and d.on_pc
                                else "Google Drive")
        self.maker_btn.setVisible(d is not None and (d.on_pc or d.mine))
        self.remove_btn.setEnabled(d is not None and (d.mine or d.on_pc))
        has = bool(self.cards)
        p = self.main.project
        for b in (self.list_btn, self.save_btn, self.tick_all, self.tick_none, self.search,
                  self.sort, self.show_extra):
            b.setEnabled(has)
        n = self._ticked_count()
        self.add_btn.setEnabled(n > 0 and p is not None)
        self.add_btn.setText(f"Add the {n} ticked to my deck" if n else
                             "Add the ticked to my deck")
        self.add_btn.setToolTip(
            "Open a deck first" if p is None else
            "As real cards printed with these pictures (on the Order page and in Print at "
            "home); the maker's credit stays with each")
        self.back_btn.setVisible(bool(self.backs))
        self.back_btn.setEnabled(p is not None)

    def _ticked_count(self) -> int:
        return sum(c.count for c in self.cards if c.key in self._ticked)

    # ------------------------------------------------------------ importing a deck
    def import_deck(self):
        d = self.deck
        if d is None or not d.can_open or self._importing:
            return
        deck = copy.copy(d)

        def work(progress=None, cancel=None):
            items, text = px.list_deck(deck, progress=lambda m: progress(0, 0, m),
                                       cancel=cancel)
            return deck.id, items, text

        self._importing = d.id
        self.status.setText("Reading the deck's files…" if d.on_pc else
                            "Reading the deck's Google Drive folder…")
        job = Job(work, label=f"Importing {d.title}")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(self._imported)
        job.signals.failed.connect(self._import_failed)
        self._jobs.append(start(job))
        self._buttons()

    def _progress(self, _d, _t, msg):
        try:
            self.status.setText(msg)
        except RuntimeError:
            return

    def _import_failed(self, msg: str):
        try:
            self._importing = ""
            self.status.setText(msg.splitlines()[0])
            self._buttons()
        except RuntimeError:
            return

    def _imported(self, res):
        try:
            did, items, text = res
            self._importing = ""
            px.save_listing(did, items, text)
            it = self._tree_item(did)
            if it is not None and did in self._decks:
                it.setText(0, _label(self._decks[did]))
            if self.deck is not None and self.deck.id == did:
                self._show_cards(items, text, "imported just now")
            self._buttons()
        except RuntimeError:
            return

    def _show_cards(self, items: list, text: str, when: str):
        d = self.deck
        self.text = text
        self.cards, self.backs = px.cards_in(items, text, d.id if d else "")
        self._by_key = {c.key: c for c in self.cards}
        self._ticked = {c.key for c in self.cards if not c.extra}
        self._fill_grid()
        deck = [c for c in self.cards if not c.extra]
        extra = len(self.cards) - len(deck)
        self.status.setText(
            (f"{len(deck)} different cards, {sum(c.count for c in deck)} in all" +
             (" (counts from the deck's own list)" if text else "") +
             (f" · {extra} tokens and extras, unticked" if extra else "") +
             (f" · {len(self.backs)} card back(s)" if self.backs else "") +
             f" · {when}") if self.cards else
            "No card pictures in that folder.")

    # ------------------------------------------------------------ the cards
    def _fill_grid(self, *_):
        q = self.search.text().strip().lower()
        sort = self.sort.currentData()
        cards = [c for c in self.cards if (self.show_extra.isChecked() or not c.extra) and
                 (not q or q in c.name.lower() or q in c.category.lower()
                  or q in c.front.name.lower())]
        if sort == "name":
            cards.sort(key=lambda c: c.name.lower())
        elif sort == "folder":
            cards.sort(key=lambda c: (c.category.lower() or "~", c.name.lower()))
        elif sort == "count":
            cards.sort(key=lambda c: (-c.count, c.name.lower()))
        self.grid.blockSignals(True)
        self.grid.clear()
        self._thumb_for = {}
        for c in cards:
            label = c.name + (f"  ×{c.count}" if c.count > 1 else "") + \
                ("\n★ commander" if c.section == "commander" else "") + \
                ("\n(two faces)" if c.back else "") + \
                (("\ntoken" if c.token else "\nextra") if c.extra else "")
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, c.key)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if c.key in self._ticked else Qt.Unchecked)
            tip = [c.front.name]
            if c.category:
                tip.append(f"Folder: {c.category}")
            if c.variants:
                tip.append(f"{len(c.variants) + 1} pictures – right-click to choose")
            if c.extra:
                tip.append("Not part of the deck itself: tick it to add it")
            it.setToolTip("\n".join(tip))
            it.setSizeHint(QSize(THUMB.width() + 16, THUMB.height() + 54))
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            pm = self._thumb(c)
            if pm is not None:
                it.setIcon(QIcon(pm))
            self.grid.addItem(it)
        self.grid.blockSignals(False)
        self._buttons()

    def _thumb(self, c: px.Card):
        item = c.front
        if item.kind == "drive":
            sid, stamp = f"gdrive:{item.id}", "1"
            fid = item.id

            def loader(fid=fid):
                return gdrive.thumbnail(fid)
        else:
            sid, stamp = f"proxypc:{item.id}", local.stamp(item)
            copy_of = gdrive.Item(item.id, item.name, False, item.path, item.kind)

            def loader(it=copy_of):
                return local.read(it)
        self._thumb_for.setdefault(sid, []).append(c.key)
        return thumbs.cache().get(sid, stamp, loader)

    def _thumb_ready(self, source_id: str):
        try:
            keys = self._thumb_for.get(source_id)
            if not keys:
                return
            for i in range(self.grid.count()):
                it = self.grid.item(i)
                c = self._by_key.get(it.data(Qt.UserRole))
                if c is not None and c.key in keys:
                    pm = self._thumb(c)
                    if pm is not None:
                        self.grid.blockSignals(True)
                        it.setIcon(QIcon(pm))
                        self.grid.blockSignals(False)
        except RuntimeError:
            return

    def _tick_changed(self, item):
        try:
            key = item.data(Qt.UserRole)
            if item.checkState() == Qt.Checked:
                self._ticked.add(key)
            else:
                self._ticked.discard(key)
            self._buttons()
        except RuntimeError:
            return

    def _tick_shown(self, on: bool):
        self.grid.blockSignals(True)
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            it.setCheckState(Qt.Checked if on else Qt.Unchecked)
            (self._ticked.add if on else self._ticked.discard)(it.data(Qt.UserRole))
        self.grid.blockSignals(False)
        self._buttons()

    def _tick_keys(self, keys: list, on: bool):
        for k in keys:
            (self._ticked.add if on else self._ticked.discard)(k)
        self._fill_grid()

    def _selected_keys(self) -> list:
        return [it.data(Qt.UserRole) for it in self.grid.selectedItems()]

    def _double_clicked(self, item):
        self.view_card(item.data(Qt.UserRole))

    def _grid_menu(self, pos):
        it = self.grid.itemAt(pos)
        if it is None:
            return
        key = it.data(Qt.UserRole)
        keys = self._selected_keys()
        if key not in keys:
            keys = [key]
        c = self._by_key.get(key)
        if c is None:
            return
        menu = QMenu(self)
        menu.addAction(icons.icon("zoom_in"), "See it full size", lambda: self.view_card(key))
        n = len(keys)
        add = menu.addAction(icons.icon("add"), "Add this card to my deck" if n == 1 else
                             f"Add the {n} selected to my deck",
                             lambda: self.add_to_deck(keys))
        add.setEnabled(self.main.project is not None)
        menu.addAction("Tick" + (" them" if n > 1 else " it"), lambda: self._tick_keys(keys, True))
        menu.addAction("Untick" + (" them" if n > 1 else " it"),
                       lambda: self._tick_keys(keys, False))
        if c.variants:
            sub = menu.addMenu(f"Print it with ({len(c.variants) + 1} pictures)")
            a = sub.addAction(f"{c.front.name} (now)")
            a.setEnabled(False)
            for i, v in enumerate(c.variants):
                sub.addAction(v.name, lambda i=i: self._use_variant(key, i))
        menu.addAction(icons.icon("save"), "Save its picture…", lambda: self.save_pictures(keys))
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    def _use_variant(self, key: str, i: int):
        c = self._by_key.get(key)
        if c is None or i >= len(c.variants):
            return
        c.front, c.variants[i] = c.variants[i], c.front
        self._fill_grid()

    def view_card(self, key: str):
        """The card's pictures at full size (front, back, other pictures)."""
        c = self._by_key.get(key)
        if c is None:
            return
        pics = [i for i in (c.front, c.back) if i is not None] + list(c.variants)
        folder = px.scratch("view-")

        def work(progress=None, cancel=None):
            out = []
            for k, item in enumerate(pics):
                if item.kind == "file":
                    out.append(item.id)
                    continue
                progress(k, len(pics), f"Getting {item.name}")
                f = folder / f"{k + 1} - {Path(item.name).name}"
                f.write_bytes(px.fetch(item))
                out.append(str(f))
            return out

        self.status.setText(f"Getting {c.name} at full size…")
        job = Job(work, label=f"Showing {c.name}")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(self._show_viewer)
        job.signals.failed.connect(self._failed_box)
        self._jobs.append(start(job))

    def _show_viewer(self, paths: list):
        try:
            self.status.clear()
            from mse_studio.gui.image_viewer import ImageViewer
            ImageViewer(self, [Path(p) for p in paths]).exec()
        except RuntimeError:
            return

    def _failed_box(self, msg: str):
        try:
            self.status.clear()
            error(self, "Proxy decks", msg.splitlines()[0])
        except RuntimeError:
            return

    # ------------------------------------------------------------ using it
    def add_to_deck(self, keys: list | None = None):
        """The cards as real cards of the open deck, printed with these pictures."""
        p, d = self.main.project, self.deck
        cards = [self._by_key[k] for k in keys if k in self._by_key] if keys else \
            [c for c in self.cards if c.key in self._ticked]
        if p is None or not cards or d is None:
            return
        if d.on_pc and not d.creator:
            name, ok = QInputDialog.getText(
                self, "Who made these proxies?", "Who made them – kept with every card for the "
                "credit (leave it empty if you don't know):")
            if not ok:
                return
            if name.strip():
                px.set_maker(d.id, name.strip())
                d.creator = name.strip()
        credit, folder = d.credit(), str(p.folder)
        tmp = px.scratch("add-")
        cards = [copy.copy(c) for c in cards]
        pool = [copy.copy(c) for c in self.cards]       # a back face may be unticked

        def work(progress=None, cancel=None):
            entries = [dl.Entry(name=c.name, count=c.count, section=c.section) for c in cards]
            dl.resolve(entries, progress, cancel)        # card data (Scryfall), if it's real
            both, entries = px.pair_faces(cards, entries, pool)
            out = []
            for k, (c, e) in enumerate(zip(both, entries)):
                if cancel is not None and cancel.cancelled:
                    break
                progress(k, len(both), f"Pictures: {c.name}")
                files = []
                for side, item in enumerate((c.front, c.back)):
                    if item is None:
                        continue
                    f = tmp / f"{k}-{side}{Path(item.name).suffix.lower() or '.png'}"
                    f.write_bytes(px.fetch(item))
                    files.append((side, str(f)))
                out.append((e, files))
            return folder, credit, d.title, out

        self.status.setText("Getting the pictures…")
        job = Job(work, label=f"Adding {d.title}")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(self._added)
        job.signals.failed.connect(self._failed_box)
        self._jobs.append(start(job))

    def _added(self, res):
        from mse_studio.pipeline import real_cards as rc
        try:
            folder, credit, title, out = res
            p = self.main.project
            if p is None or str(p.folder) != folder:
                self.status.setText("The deck was closed – nothing was added.")
                return
            ok = [e for e, files in out if files]
            dl.add_to_project(p, ok)
            for e, files in out:
                for side, f in files:
                    rc.use_picture(p, e, Path(f), side, credit)
            p.save_config()
            n = sum(e.count for e in ok)
            self.main.record(f"Proxy decks · {n} real card(s) from {title}")
            self.main.update_title()
            self.status.setText(f"Added {n} card(s) to your deck – they're on the Order page.")
            self.main.statusBar().showMessage(
                f"Added {n} card(s) from {title} – making their print files; they're on the "
                "Order page", 10000)
            self.main.order_tab.real_pictures(ok)
            unknown = [e.name for e in ok if not e.found]
            if unknown:
                QMessageBox.information(
                    self, "Proxy decks", "Printed with their pictures, but Scryfall doesn't "
                    "know these names, so they don't count in the Guide or Playtest: "
                    + ", ".join(unknown[:12]) + ("…" if len(unknown) > 12 else ""))
        except RuntimeError:
            return

    def save_decklist(self):
        d = self.deck
        if d is None or not self.cards:
            return
        deck = dl.Decklist(d.title, [dl.Entry(name=c.name, count=c.count,
                                              section="side" if c.extra else c.section)
                                     for c in self.cards],
                           d.page or d.reddit or (gdrive.folder_link(d.folder) if d.folder
                                                  else "; ".join(d.local)))
        dl.save(deck)
        try:
            self.main.decklists_tab.refresh()
        except Exception:  # noqa: BLE001
            pass
        self.main.statusBar().showMessage(
            f"Saved {d.title} on the Decklists page (Look up missing cards there fills in the "
            "card details)", 8000)

    def save_pictures(self, keys: list | None = None):
        cards = [self._by_key[k] for k in keys if k in self._by_key] if keys else \
            ([c for c in self.cards if c.key in self._ticked] or list(self.cards))
        if not cards:
            return
        folder = QFileDialog.getExistingDirectory(self, "Save the pictures in")
        if not folder:
            return
        items = [i for c in cards for i in (c.front, c.back) if i is not None] + \
            ([] if keys else self.backs)

        def work(progress=None, cancel=None):
            for k, it in enumerate(items):
                if cancel is not None and cancel.cancelled:
                    break
                progress(k, len(items), f"Saving {it.name}")
                (Path(folder) / Path(it.name).name).write_bytes(px.fetch(it))
            return f"Saved {len(items)} picture(s)"

        job = Job(work, label="Saving proxy pictures")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(self._done_text)
        job.signals.failed.connect(self._failed_box)
        self._jobs.append(start(job))

    def _done_text(self, text: str):
        try:
            self.status.setText(text)
        except RuntimeError:
            return

    def use_back(self):
        p = self.main.project
        if p is None or not self.backs:
            return
        item = self.backs[0]
        folder = str(p.folder)

        def work(progress=None, cancel=None):
            path = px.scratch("add-") / Path(item.name).name
            path.write_bytes(px.fetch(item))
            return folder, str(path)

        job = Job(work, label="Getting the card back")
        job.signals.finished.connect(self._back_ready)
        job.signals.failed.connect(self._failed_box)
        self._jobs.append(start(job))

    def _back_ready(self, res):
        from mse_studio.core import card_backs
        try:
            folder, path = res
            p = self.main.project
            if p is None or str(p.folder) != folder:
                return
            card_backs.use_for_deck(p, Path(path))          # copied into the deck
            self.main.order_tab.refresh()
            self.main.statusBar().showMessage(f"{Path(path).name} is your deck's card back now",
                                              8000)
        except RuntimeError:
            return

    def copy_credit(self):
        if self.deck is not None:
            QApplication.clipboard().setText(self.deck.credit())
            self.main.statusBar().showMessage("Copied: " + self.deck.credit(), 6000)

    def _open_page(self):
        if self.deck is not None and self.deck.page:
            QDesktopServices.openUrl(QUrl(self.deck.page))

    def _open_source(self):
        d = self.deck
        if d is None:
            return
        if d.on_pc:
            src = Path(d.local[0])
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(src if src.is_dir() else src.parent)))
        elif d.folder:
            QDesktopServices.openUrl(QUrl(gdrive.folder_link(d.folder)))

    # ------------------------------------------------------------ your own list
    def add_link(self):
        dlg = AddLinkDialog(self)
        if not dlg.exec() or dlg.deck is None:
            return
        deck = dlg.deck
        px.add_mine(deck)
        self.fill_list(deck.id)
        if deck.can_open:
            self.import_deck()

    def add_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "A folder of proxies – one deck, or a folder of decks")
        if path:
            self._add_from_pc(path)

    def add_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "A zip of proxies", "", "Zip files (*.zip)")
        if path:
            self._add_from_pc(path)

    def _add_from_pc(self, path: str):
        found = local.scan(path)
        if not found:
            error(self, "Proxy decks", "No card pictures in there. Pick the deck's own folder, "
                                       "a folder with decks in it, or a deck's zip.")
            return
        px.add_root(path)
        self.fill_list(px.local_id(found[0]))
        self.main.statusBar().showMessage(
            f"{len(found)} deck(s) from {Path(path).name} – under On this PC", 8000)
        if self.deck is not None and not px.is_imported(self.deck.id):
            self.import_deck()

    def add_bought_link(self):
        d = self.deck
        if d is None:
            return
        link, ok = QInputDialog.getText(
            self, "My download link", f"The Google Drive link you got for {d.title} "
            "(it stays on this PC):", text=d.bought_link)
        if not ok:
            return
        try:
            px.set_bought(d.id, link.strip())
        except ValueError as e:
            error(self, "Proxy decks", str(e))
            return
        self.fill_list(d.id)

    def edit_maker(self):
        d = self.deck
        if d is None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Who made it")
        f = QFormLayout(dlg)
        name = QLineEdit(d.creator)
        name.setPlaceholderText("Their name, e.g. White Rabbit MTG")
        f.addRow("Made by", name)
        link = QLineEdit(d.creator_link)
        link.setPlaceholderText("Their Ko-fi, Reddit or website (optional)")
        f.addRow("Their page", link)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        dlg.resize(480, 0)
        if dlg.exec():
            px.set_maker(d.id, name.text(), link.text())
            self.fill_list(d.id)

    def remove(self):
        d = self.deck
        if d is None:
            return
        if d.on_pc:
            same = [x for x in self._decks.values() if x.on_pc and x.root == d.root]
            if QMessageBox.question(
                    self, "Proxy decks",
                    f"Take {d.root} off the list ({len(same)} deck(s))? The files stay on "
                    "your PC.") != QMessageBox.Yes:
                return
            px.remove_root(d.root)
            for x in same:
                px.forget_listing(x.id)
        elif d.mine:
            px.remove_mine(d.id)
        else:
            return
        self.deck = None
        self.fill_list()

    def find_on_reddit(self):
        dlg = RedditDialog(self)
        if dlg.exec():
            added = dlg.chosen()
            for post in added:
                px.add_mine(px.deck_from_post(post))
            if added:
                self.fill_list(px.deck_from_post(added[0]).id)


class AddLinkDialog(QDialog):
    """Paste a link or a whole post; the details are found for you."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Add a proxy deck")
        self.deck: px.Deck | None = None
        self._jobs: list = []
        v = QVBoxLayout(self)
        hint = QLabel("Paste a Google Drive folder link, a Reddit post or a Ko-fi page – or a "
                      "whole post copied from Reddit or Discord: its links and decklist are "
                      "found in it.")
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        v.addWidget(hint)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("https://drive.google.com/drive/folders/…")
        self.text.setMaximumHeight(130)
        v.addWidget(self.text)
        row = QHBoxLayout()
        self.auto = QCheckBox("Find the name and maker online (Reddit, Ko-fi, Google Drive)")
        self.auto.setChecked(True)
        self.auto.setToolTip("Untick to fill everything in yourself – nothing is asked online")
        row.addWidget(self.auto, 1)
        self.read_btn = QPushButton("Find the details")
        self.read_btn.setProperty("kind", "primary")
        icons.set_icon(self.read_btn, "travel_explore")
        self.read_btn.clicked.connect(self.read)
        row.addWidget(self.read_btn)
        v.addLayout(row)
        self.found = QLabel()
        self.found.setWordWrap(True)
        v.addWidget(self.found)
        f = QFormLayout()
        self.name = QLineEdit()
        f.addRow("Name", self.name)
        self.creator = QLineEdit()
        self.creator.setPlaceholderText("Who made it (for the credit)")
        f.addRow("Made by", self.creator)
        self.creator_link = QLineEdit()
        self.creator_link.setPlaceholderText("Their Ko-fi, Reddit or website")
        f.addRow("Their page", self.creator_link)
        self.drive = QLineEdit()
        self.drive.setPlaceholderText("The Google Drive folder with the pictures")
        f.addRow("Google Drive", self.drive)
        self.page = QLineEdit()
        self.page.setPlaceholderText("The Ko-fi page (where you buy or download it)")
        f.addRow("Ko-fi", self.page)
        self.reddit = QLineEdit()
        f.addRow("Reddit post", self.reddit)
        self.notes = QLineEdit()
        f.addRow("Notes", self.notes)
        self.paid = QCheckBox("It's paid (Ko-fi)")
        f.addRow(self.paid)
        v.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Add to my list")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(620, 0)

    def read(self):
        text, online = self.text.toPlainText(), self.auto.isChecked()

        def work(progress=None, cancel=None):
            return px.describe(text, progress=lambda m: progress(0, 0, m), online=online)

        self.read_btn.setEnabled(False)
        self.found.setText("Finding the details…" if online else "")
        job = Job(work, label="Reading the link")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(self._read_done)
        job.signals.failed.connect(self._read_failed)
        self._jobs.append(start(job))

    def _progress(self, _d, _t, msg):
        try:
            self.found.setText(msg)
        except RuntimeError:
            return

    def _read_failed(self, msg: str):
        try:
            self.read_btn.setEnabled(True)
            self.found.setText(msg.splitlines()[0])
        except RuntimeError:
            return

    def _read_done(self, deck):
        try:
            self.read_btn.setEnabled(True)
            self._fill(deck)
        except RuntimeError:
            return

    def _fill(self, deck: px.Deck):
        self.deck = deck
        self.name.setText(deck.title)
        self.creator.setText(deck.creator)
        self.creator_link.setText(deck.creator_link)
        self.drive.setText(gdrive.folder_link(deck.drive) if deck.drive else "")
        self.page.setText(deck.page)
        self.reddit.setText(deck.reddit)
        self.notes.setText(deck.notes)
        self.paid.setChecked(deck.price == "paid")
        drive, _k = px.links_in(self.text.toPlainText())
        found = []
        if deck.drive:
            found.append("a Google Drive folder")
        if deck.decklist:
            found.append(f"a decklist ({len(deck.decklist.splitlines())} lines)")
        msg = ("Found " + " and ".join(found) + "." if found else
               "No Google Drive folder yet – after buying or downloading it on Ko-fi, add "
               "the link you get.") + \
            (f" {len(drive)} Google Drive folders in it: the first is used – add the others "
             "one by one." if len(drive) > 1 else "") + " Check the details, then Add to my list."
        self.found.setText(msg)

    def accept(self):
        if self.deck is None:                    # not read yet: what's in it, without asking
            try:
                self._fill(px.describe(self.text.toPlainText(), online=False))
            except ValueError as e:
                if not self.drive.text().strip() and not self.page.text().strip():
                    error(self, "Proxy decks", str(e))
                    return
                self.deck = px.Deck("", "", mine=True)
        d = self.deck
        d.title = self.name.text().strip() or d.title or "My proxy deck"
        d.creator = self.creator.text().strip()
        d.creator_link = self.creator_link.text().strip()
        d.drive = gdrive.folder_id(self.drive.text())
        d.page = self.page.text().strip()
        d.reddit = self.reddit.text().strip()
        d.notes = self.notes.text().strip()
        d.price = "paid" if self.paid.isChecked() and not d.drive else "free"
        if self.drive.text().strip() and not d.drive:
            error(self, "Proxy decks", "That isn't a Google Drive folder link.")
            return
        if not d.drive and not d.page:
            error(self, "Proxy decks", "Add a Google Drive folder link or a Ko-fi page.")
            return
        d.id = re.sub(r"[^a-z0-9]+", "-", d.title.lower()).strip("-")[:60] or \
            f"deck-{int(time.time())}"
        d.mine = True
        super().accept()

    def done(self, r):
        forget(self._jobs)
        super().done(r)


class RedditDialog(QDialog):
    """Search r/mpcproxies and pick decks to add to your list."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Find proxy decks on r/mpcproxies")
        self.resize(820, 560)
        self.posts: list[px.Post] = []
        self._jobs: list = []
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        self.query = QLineEdit("EDH deck")
        self.query.returnPressed.connect(self.search)
        row.addWidget(self.query, 1)
        self.sort = QComboBox()
        for k, label in (("relevance", "Best match"), ("new", "Newest"), ("top", "Most liked")):
            self.sort.addItem(label, k)
        row.addWidget(self.sort)
        b = QPushButton("Search")
        icons.set_icon(b, "search")
        b.clicked.connect(self.search)
        row.addWidget(b)
        b = QPushButton("Search in my browser")
        icons.set_icon(b, "open_in_new")
        b.setToolTip("When Reddit won't answer MSE Studio: search there, then paste a post's "
                     "link (or the whole post) with Add a link or post")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(px.search_in_browser(
            self.query.text().strip() or "EDH deck", self.sort.currentData()))))
        row.addWidget(b)
        v.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Post", "By", "Pictures"])
        self.tree.setColumnWidth(0, 480)
        self.tree.itemDoubleClicked.connect(self._open_post)
        v.addWidget(self.tree, 1)
        self.status = QLabel("Free: the post has a Google Drive link. Ko-fi: only a Ko-fi link "
                             "(usually paid). Double-click a post to read it.")
        self.status.setWordWrap(True)
        self.status.setObjectName("Hint")
        v.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Add the ticked to my list")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.search()

    def _open_post(self, it, _col):
        k = it.data(0, Qt.UserRole)
        if k is not None and 0 <= k < len(self.posts):
            QDesktopServices.openUrl(QUrl(self.posts[k].link))

    def search(self):
        q, sort = self.query.text().strip() or "EDH deck", self.sort.currentData()

        def work(progress=None, cancel=None):
            return px.search_reddit(q, sort)

        self.status.setText("Searching r/mpcproxies…")
        job = Job(work, label="Searching r/mpcproxies")
        job.signals.finished.connect(self._found)
        job.signals.failed.connect(self._failed)
        self._jobs.append(start(job))

    def _failed(self, msg: str):
        try:
            self.status.setText(msg.splitlines()[0])
        except RuntimeError:
            return

    def _found(self, posts: list):
        try:
            self.posts = [p for p in posts if p.drive or p.kofi]
            self.tree.clear()
            for k, p in enumerate(self.posts):
                it = QTreeWidgetItem(self.tree, [p.title, f"u/{p.author}",
                                                 "Free (Google Drive)" if p.drive else "Ko-fi"])
                it.setData(0, Qt.UserRole, k)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Unchecked)
                it.setToolTip(0, p.link)
            self.status.setText(
                f"{len(self.posts)} post(s) with decks to download" if self.posts else
                "No posts with a Google Drive or Ko-fi link in the results – the links may be "
                "in the comments: open a post, then paste its link with Add a link or post.")
        except RuntimeError:
            return

    def chosen(self) -> list:
        out = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.checkState(0) == Qt.Checked:
                out.append(self.posts[it.data(0, Qt.UserRole)])
        return out

    def done(self, r):
        forget(self._jobs)
        super().done(r)
