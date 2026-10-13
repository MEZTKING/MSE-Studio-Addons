"""Proxy decks: decks people share on r/mpcproxies and Ko-fi (real Magic
cards with new art and frames), browsed straight from their public Google
Drive folders. Print them as real cards of your deck – every picture keeps
its maker's credit – save them as a decklist, or save the pictures.

Network: Google Drive (a deck's folder, thumbnails and pictures) when you
open or add a deck, Reddit only when you search it, Scryfall to look the
cards up when you add them to your deck."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListView, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from mse_studio.core import decklists as dl
from mse_studio.gui import icons, thumbs
from mse_studio.gui.common import Job, error, forget, start
from mse_studio.gui.nav import page_header

from . import gdrive
from . import proxies as px

THUMB = QSize(126, 176)
GROUPS = [("free", "Free"), ("paid", "Paid – on Ko-fi"), ("mine", "Added by you")]


class ProxiesPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._jobs: list = []
        self.deck: px.Deck | None = None
        self.cards: list[px.Card] = []
        self.backs: list[gdrive.Item] = []
        lay = QVBoxLayout(self)
        lay.addWidget(page_header(
            "Proxy decks", "Decks people share on r/mpcproxies and Ko-fi – real Magic cards "
                           "with new art and frames – straight from their Google Drive. Print "
                           "them as real cards of your deck (every picture keeps its maker's "
                           "credit), save them as a decklist, or save the pictures."))
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.list = QTreeWidget()
        self.list.setHeaderHidden(True)
        self.list.currentItemChanged.connect(self._picked)
        lv.addWidget(self.list, 1)
        row = QHBoxLayout()
        b = QPushButton("Add a link…")
        icons.set_icon(b, "link")
        b.setToolTip("A Google Drive folder someone shared (on Reddit, Ko-fi, Discord…), or a "
                     "Ko-fi page of a paid deck")
        b.clicked.connect(self.add_link)
        row.addWidget(b)
        b = QPushButton("Find on r/mpcproxies…")
        icons.set_icon(b, "search")
        b.setToolTip("Search r/mpcproxies (e.g. \"EDH deck\") and add the decks you like")
        b.clicked.connect(self.find_on_reddit)
        row.addWidget(b)
        lv.addLayout(row)
        self.remove_btn = QPushButton("Remove from my list")
        self.remove_btn.clicked.connect(self.remove)
        lv.addWidget(self.remove_btn)
        split.addWidget(left)

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
        self.open_btn = QPushButton("Open the deck")
        self.open_btn.setProperty("kind", "primary")
        icons.set_icon(self.open_btn, "folder_open")
        self.open_btn.clicked.connect(self.open_deck)
        row.addWidget(self.open_btn)
        self.buy_btn = QPushButton("Buy on Ko-fi")
        icons.set_icon(self.buy_btn, "open_in_new")
        self.buy_btn.clicked.connect(lambda: self._open_url(self.deck.page if self.deck else ""))
        row.addWidget(self.buy_btn)
        self.bought_btn = QPushButton("I bought it – add my download link…")
        self.bought_btn.setToolTip("After buying, Ko-fi gives you a Google Drive link: paste it "
                                   "here and the deck opens here like the free ones")
        self.bought_btn.clicked.connect(self.add_bought_link)
        row.addWidget(self.bought_btn)
        self.drive_btn = QPushButton("Google Drive")
        icons.set_icon(self.drive_btn, "open_in_new")
        self.drive_btn.clicked.connect(
            lambda: self._open_url(gdrive.folder_link(self.deck.folder) if self.deck else ""))
        row.addWidget(self.drive_btn)
        row.addStretch(1)
        rv.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        rv.addWidget(self.status)
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setIconSize(THUMB)
        self.grid.setGridSize(QSize(THUMB.width() + 22, THUMB.height() + 46))
        self.grid.setWordWrap(True)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.itemSelectionChanged.connect(self._selection)
        rv.addWidget(self.grid, 1)
        row = QHBoxLayout()
        self.add_btn = QPushButton("Add all to my deck")
        self.add_btn.setProperty("kind", "primary")
        icons.set_icon(self.add_btn, "add")
        self.add_btn.setToolTip("As real cards printed with these pictures (they go in your MPC "
                                "order and Print at home); the maker's credit stays with each")
        self.add_btn.clicked.connect(self.add_to_deck)
        row.addWidget(self.add_btn)
        b = QPushButton("Save as a decklist")
        b.setToolTip("The card list on the Decklists page (to view or playtest)")
        b.clicked.connect(self.save_decklist)
        row.addWidget(b)
        self.list_btn = b
        b = QPushButton("Save the pictures…")
        b.clicked.connect(self.save_pictures)
        row.addWidget(b)
        self.save_btn = b
        self.back_btn = QPushButton("Use its card back")
        self.back_btn.clicked.connect(self.use_back)
        row.addWidget(self.back_btn)
        b = QPushButton("Copy the credit")
        b.clicked.connect(self.copy_credit)
        row.addWidget(b)
        row.addStretch(1)
        rv.addLayout(row)
        split.addWidget(right)
        split.setSizes([300, 900])
        lay.addWidget(split, 1)
        thumbs.cache().ready.connect(self._thumb_ready)
        self.fill_list()

    # ------------------------------------------------------------ MSE Studio calls these
    def load(self):
        self._buttons()

    def shutdown(self):
        forget(self._jobs)

    # ------------------------------------------------------------ the list of decks
    def fill_list(self, keep: str = ""):
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
        for d in px.decks():
            g = groups["mine" if d.mine else ("paid" if d.price == "paid" else "free")]
            mark = "  ✓ yours" if d.price == "paid" and d.bought_link else ""
            it = QTreeWidgetItem(g, [d.title + mark])
            it.setData(0, Qt.UserRole, d.id)
            it.setToolTip(0, d.credit())
            if d.id == keep:
                pick = it
        for g in groups.values():
            g.setHidden(g.childCount() == 0)
        self.list.expandAll()
        if pick is not None:
            self.list.setCurrentItem(pick)
        else:
            first = next((groups[k].child(0) for k, _l in GROUPS if groups[k].childCount()), None)
            if first is not None:
                self.list.setCurrentItem(first)
        self._buttons()

    def _picked(self, cur, _prev):
        did = cur.data(0, Qt.UserRole) if cur is not None else None
        self.deck = next((d for d in px.decks() if d.id == did), None) if did else None
        self.cards, self.backs = [], []
        self.grid.clear()
        self.status.clear()
        d = self.deck
        if d is None:
            self.title.clear()
            self.notes.clear()
        else:
            links = " · ".join(f'<a href="{u}">{n}</a>' for n, u in (
                ("Ko-fi page", d.page), ("Reddit post", d.reddit),
                ("the maker", d.creator_link)) if u)
            who = d.creator or "unknown"
            self.title.setText(f"<b style='font-size:15px'>{d.title}</b><br>By {who}"
                               + (f" · {links}" if links else "")
                               + (" · <b>Free</b>" if d.price == "free" else
                                  " · <b>Paid</b>" + (" – you added your link" if d.bought_link
                                                      else "")))
            self.notes.setText(d.notes or "")
        self._buttons()

    def _buttons(self):
        d = self.deck
        paid_locked = d is not None and d.price == "paid" and not d.bought_link and not d.drive
        self.open_btn.setVisible(d is not None and not paid_locked)
        self.open_btn.setEnabled(d is not None and d.can_open)
        self.buy_btn.setVisible(d is not None and d.price == "paid" and bool(d.page))
        self.bought_btn.setVisible(d is not None and d.price == "paid")
        self.bought_btn.setText("Change my download link…" if d is not None and d.bought_link
                                else "I bought it – add my download link…")
        self.drive_btn.setVisible(d is not None and d.can_open)
        self.remove_btn.setEnabled(d is not None and d.mine)
        has = bool(self.cards)
        p = self.main.project
        for b in (self.list_btn, self.save_btn):
            b.setEnabled(has)
        self.add_btn.setEnabled(has and p is not None)
        self.add_btn.setToolTip("" if p is not None else "Open a deck first")
        self.back_btn.setVisible(bool(self.backs))
        self.back_btn.setEnabled(p is not None)
        self._selection()

    def _selection(self):
        n = len(self.grid.selectedItems())
        total = sum(c.count for c in self.cards if not c.extra)
        self.add_btn.setText(f"Add the {n} selected to my deck" if n else
                             f"Add all {total} to my deck" if total else "Add all to my deck")

    # ------------------------------------------------------------ opening a deck
    def open_deck(self):
        d = self.deck
        if d is None or not d.can_open:
            return
        fid = d.folder

        def work(progress=None, cancel=None):
            title, items = gdrive.list_folder(fid, progress=lambda m: progress(0, 0, m),
                                              cancel=cancel)
            text = ""
            lists = [i for i in items if i.text and "list" in i.name.lower()] or \
                [i for i in items if i.text]
            if lists:
                try:
                    text = gdrive.download(lists[0].id).decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001 - counts of 1 instead
                    text = ""
            return items, text

        self.status.setText("Reading the deck's Google Drive folder…")
        job = Job(work, label="Opening a proxy deck")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(lambda res, did=d.id: self._opened(did, *res))
        job.signals.failed.connect(self._failed)
        self._jobs.append(start(job))

    def _progress(self, _d, _t, msg):
        try:
            self.status.setText(msg)
        except RuntimeError:
            return

    def _failed(self, msg: str):
        try:
            self.status.setText(msg.splitlines()[0])
        except RuntimeError:
            return

    def _opened(self, deck_id: str, items: list, text: str):
        try:
            if self.deck is None or self.deck.id != deck_id:
                return
            self.cards, self.backs = px.cards_in(items, text)
            self.grid.clear()
            for c in self.cards:
                label = c.name + (f"  ×{c.count}" if c.count > 1 else "") + \
                    ("\n★ commander" if c.section == "commander" else "") + \
                    ("\n(two faces)" if c.back else "") + \
                    (("\ntoken" if c.token else "\nnot in the deck's list") if c.extra else "")
                it = QListWidgetItem(label)
                if c.extra:
                    it.setToolTip("Not part of the deck itself: added only when you select it")
                it.setData(Qt.UserRole, c.front.id)
                it.setSizeHint(QSize(THUMB.width() + 16, THUMB.height() + 42))
                it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
                pm = self._thumb(c.front.id)
                if pm is not None:
                    it.setIcon(QIcon(pm))
                self.grid.addItem(it)
            deck = [c for c in self.cards if not c.extra]
            n, extra = sum(c.count for c in deck), len(self.cards) - len(deck)
            self.status.setText(
                f"{len(deck)} different cards, {n} in all" +
                (" (counts from the deck's own list)" if text else "") +
                (f" · {extra} extra (tokens, cards not on its list)" if extra else "") +
                (f" · {len(self.backs)} card back(s)" if self.backs else "") +
                " · select cards to add only those" if self.cards else
                "No card pictures in that folder.")
            self._buttons()
        except RuntimeError:
            return

    def _thumb(self, file_id: str):
        return thumbs.cache().get(f"gdrive:{file_id}", "1",
                                  lambda fid=file_id: gdrive._http(gdrive.thumbnail_url(fid)))

    def _thumb_ready(self, source_id: str):
        try:
            if not source_id.startswith("gdrive:"):
                return
            fid = source_id.split(":", 1)[1]
            for i in range(self.grid.count()):
                it = self.grid.item(i)
                if it.data(Qt.UserRole) == fid:
                    pm = self._thumb(fid)
                    if pm is not None:
                        it.setIcon(QIcon(pm))
        except RuntimeError:
            return

    def _chosen(self, extras: bool = False) -> list[px.Card]:
        """The selected cards, else the deck's (with the extras, ``extras``)."""
        ids = {it.data(Qt.UserRole) for it in self.grid.selectedItems()}
        return [c for c in self.cards if c.front.id in ids] if ids else \
            [c for c in self.cards if extras or not c.extra]

    # ------------------------------------------------------------ using it
    def add_to_deck(self):
        """The cards as real cards of the open deck, printed with these pictures."""
        from mse_studio.pipeline import real_cards as rc
        p = self.main.project
        cards, d = self._chosen(), self.deck
        if p is None or not cards or d is None:
            return
        credit = d.credit()
        tmp = Path(tempfile.mkdtemp(prefix="mse_proxies_"))

        def work(progress=None, cancel=None):
            entries = [dl.Entry(name=c.name, count=c.count, section=c.section) for c in cards]
            dl.resolve(entries, progress, cancel)        # card data (Scryfall), if it's real
            out = []
            for k, (c, e) in enumerate(zip(cards, entries)):
                if cancel is not None and cancel.cancelled:
                    break
                progress(k, len(cards), f"Pictures: {c.name}")
                files = []
                for side, item in enumerate((c.front, c.back)):
                    if item is None:
                        continue
                    f = tmp / f"{k}-{side}{Path(item.name).suffix.lower() or '.png'}"
                    f.write_bytes(gdrive.download(item.id))
                    files.append((side, f))
                out.append((e, files))
            return out

        def done(res):
            try:
                ok = [e for e, files in res if files]
                dl.add_to_project(p, ok)
                for e, files in res:
                    for side, f in files:
                        rc.use_picture(p, e, f, side, credit)
                p.save_config()
                n = sum(e.count for e in ok)
                self.main.record(f"Proxy decks · {n} real card(s) from {d.title}")
                self.main.update_title()
                self.main.statusBar().showMessage(
                    f"Added {n} card(s) from {d.title} – making their print files; they're on "
                    "the Order page", 10000)
                self.main.order_tab.real_pictures(ok)
                unknown = [e.name for e in ok if not e.found]
                if unknown:
                    QMessageBox.information(
                        self, "Proxy decks", "Printed with their pictures, but Scryfall doesn't "
                        "know these names, so they don't count in the Guide or Playtest: "
                        + ", ".join(unknown[:12]) + ("…" if len(unknown) > 12 else ""))
            except RuntimeError:
                return

        self.status.setText("Getting the pictures…")
        job = Job(work, label=f"Adding {d.title}")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(done)
        job.signals.failed.connect(lambda m: error(self, "Proxy decks", m.splitlines()[0]))
        self._jobs.append(start(job))

    def save_decklist(self):
        d = self.deck
        if d is None or not self.cards:
            return
        deck = dl.Decklist(d.title, [dl.Entry(name=c.name, count=c.count,
                                              section="side" if c.extra else c.section)
                                     for c in self.cards], d.page or d.reddit or
                           gdrive.folder_link(d.folder))
        dl.save(deck)
        try:
            self.main.decklists_tab.refresh()
        except Exception:  # noqa: BLE001
            pass
        self.main.statusBar().showMessage(
            f"Saved {d.title} on the Decklists page (Look up missing cards there fills in the "
            "card details)", 8000)

    def save_pictures(self):
        cards = self._chosen(extras=True)
        if not cards:
            return
        folder = QFileDialog.getExistingDirectory(self, "Save the pictures in")
        if not folder:
            return
        items = [i for c in cards for i in (c.front, c.back) if i is not None] + self.backs

        def work(progress=None, cancel=None):
            for k, it in enumerate(items):
                if cancel is not None and cancel.cancelled:
                    break
                progress(k, len(items), f"Saving {it.name}")
                (Path(folder) / Path(it.name).name).write_bytes(gdrive.download(it.id))
            return len(items)

        job = Job(work, label="Saving proxy pictures")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(lambda n: self._progress(0, 0, f"Saved {n} picture(s)"))
        job.signals.failed.connect(lambda m: error(self, "Proxy decks", m.splitlines()[0]))
        self._jobs.append(start(job))

    def use_back(self):
        from mse_studio.core import card_backs
        p = self.main.project
        if p is None or not self.backs:
            return
        item = self.backs[0]

        def work(progress=None, cancel=None):
            return gdrive.download(item.id)

        def done(data):
            try:
                path = Path(tempfile.mkdtemp(prefix="mse_proxies_")) / Path(item.name).name
                path.write_bytes(data)
                card_backs.use_for_deck(p, path)          # copied into the deck
                self.main.order_tab.refresh()
                self.main.statusBar().showMessage(f"{item.name} is your deck's card back now",
                                                  8000)
            except RuntimeError:
                return

        job = Job(work, label="Getting the card back")
        job.signals.finished.connect(done)
        job.signals.failed.connect(lambda m: error(self, "Proxy decks", m.splitlines()[0]))
        self._jobs.append(start(job))

    def copy_credit(self):
        if self.deck is not None:
            QApplication.clipboard().setText(self.deck.credit())
            self.main.statusBar().showMessage("Copied: " + self.deck.credit(), 6000)

    def _open_url(self, url: str):
        if url:
            QDesktopServices.openUrl(QUrl(url))

    # ------------------------------------------------------------ your own list
    def add_link(self):
        dlg = AddLinkDialog(self)
        if not dlg.exec():
            return
        try:
            deck = px.deck_from_link(dlg.link.text(), dlg.name.text().strip(),
                                     dlg.creator.text().strip(), dlg.page.text().strip(),
                                     "paid" if dlg.paid.isChecked() else "free")
        except ValueError as e:
            error(self, "Proxy decks", str(e))
            return
        deck.notes = dlg.notes.text().strip()
        px.add_mine(deck)
        self.fill_list(deck.id)

    def add_bought_link(self):
        d = self.deck
        if d is None:
            return
        from PySide6.QtWidgets import QInputDialog
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

    def remove(self):
        if self.deck is not None and self.deck.mine:
            px.remove_mine(self.deck.id)
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
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Add a proxy deck")
        f = QFormLayout(self)
        self.link = QLineEdit()
        self.link.setPlaceholderText("https://drive.google.com/drive/folders/…  or a Ko-fi page")
        f.addRow("Link", self.link)
        self.name = QLineEdit()
        f.addRow("Name", self.name)
        self.creator = QLineEdit()
        self.creator.setPlaceholderText("Who made it (for the credit)")
        f.addRow("Made by", self.creator)
        self.page = QLineEdit()
        self.page.setPlaceholderText("Where it's from: the Reddit post or Ko-fi page")
        f.addRow("From", self.page)
        self.notes = QLineEdit()
        f.addRow("Notes", self.notes)
        self.paid = QCheckBox("It's paid (Ko-fi)")
        f.addRow(self.paid)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.resize(560, 0)


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
        v.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Post", "By", "Pictures"])
        self.tree.setColumnWidth(0, 480)
        self.tree.itemDoubleClicked.connect(
            lambda it, _c: QDesktopServices.openUrl(QUrl(self.posts[it.data(0, Qt.UserRole)]
                                                         .link)))
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
            self.status.setText(f"{len(self.posts)} post(s) with decks to download"
                                if self.posts else "No posts with a Google Drive or Ko-fi link.")
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
