"""MPCFill: mpcfill.com in a browser inside MSE Studio – it opens on Explore
and stays on MPCFill. Pictures you download there (*Download Image*) show
up beside it, ready to go in your deck like a decklist's or a proxy deck's
cards: as real cards printed with the picture (the Order page) or as cards
to edit with its art. An order (*Download → XML*) comes here too, and its
cards become real cards printed with the pictures you picked (and its card
back your deck's back).

Network: mpcfill.com in the browser (only while the page is open), and the
pictures of an order when you add them (MPCFill's image server set in MSE
Studio, else Google Drive); Scryfall for the text of cards to edit."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QListView, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QSplitter, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from mse_studio.core import addons, mpcfill
from mse_studio.core import decklists as dl
from mse_studio.gui import icons
from mse_studio.gui.common import Job, error, forget, start
from mse_studio.gui.nav import page_header

from . import order as mo

ADDON_ID = "mpcfill"
SITE = "https://mpcfill.com/explore"        # it opens on Explore
EDITOR = "https://mpcfill.com/editor"
STAY_ON = ("mpcfill.com",)                   # the browser doesn't leave MPCFill
CREDIT = "Picture from MPCFill (mpcfill.com)"
PICS = (".png", ".jpg", ".jpeg", ".webp")
REAL_HINT = ("<b>Add to my order</b>: real cards, straight to the Order page – printed with "
             "this picture. <b>Add to my deck to edit</b>: your own cards on the Cards page, "
             "with the card's text and this picture's art.")


class MpcfillPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._jobs: list = []
        self.order: mo.Order | None = None
        self.order_file = ""
        self.pictures: list = []       # pictures downloaded on MPCFill (paths)
        lay = QVBoxLayout(self)
        lay.addWidget(page_header(
            "MPCFill", "mpcfill.com right here: import your decklist there and pick the "
                       "pictures, then Download → XML – the order comes to this page, and its "
                       "cards are added to your deck as real cards printed with those "
                       "pictures."))
        split = QSplitter(Qt.Horizontal)
        self.split = split
        self.web = None                # the browser: made when the page is first opened
        from mse_studio.gui import web_window
        if web_window.available():
            self.placeholder = QLabel("Opening MPCFill…")
            self.placeholder.setAlignment(Qt.AlignCenter)
            split.addWidget(self.placeholder)
        else:                          # an MSE Studio without the browser
            self.placeholder = None
            box = QWidget()
            bv = QVBoxLayout(box)
            msg = QLabel("This copy of MSE Studio can't show web pages – update it, or use "
                         "MPCFill in your browser and open the order file it gives you here.")
            msg.setWordWrap(True)
            bv.addWidget(msg)
            b = QPushButton("Open MPCFill in my browser")
            icons.set_icon(b, "open_in_new")
            b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(SITE)))
            bv.addWidget(b)
            bv.addStretch(1)
            split.addWidget(box)

        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        for label, url, tip in (("Explore", SITE, "Look through MPCFill's pictures"),
                                ("Editor", EDITOR, "Make an order: import a decklist, pick the "
                                                   "pictures")):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, u=url: self.web is not None and self.web.go(u))
            row.addWidget(b)
        row.addStretch(1)
        sv.addLayout(row)
        self.side_tabs = QTabWidget()
        sv.addWidget(self.side_tabs, 1)

        # pictures downloaded on MPCFill (Download Image)
        pics = QWidget()
        pv = QVBoxLayout(pics)
        pv.setContentsMargins(0, 4, 0, 0)
        self.pics_hint = QLabel("On MPCFill, <b>Download Image</b> on a card: it shows up here. "
                                "Right-click a picture (Ctrl/Shift+click for several).")
        self.pics_hint.setWordWrap(True)
        self.pics_hint.setObjectName("Hint")
        pv.addWidget(self.pics_hint)
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setIconSize(QSize(130, 182))
        self.grid.setGridSize(QSize(146, 222))
        self.grid.setWordWrap(True)
        self.grid.setSpacing(4)
        self.grid.setSelectionMode(QListWidget.ExtendedSelection)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._grid_menu)
        self.grid.itemDoubleClicked.connect(lambda it: self.view_full(it.data(Qt.UserRole)))
        self.grid.itemSelectionChanged.connect(self._buttons)
        try:                                   # MSE Studio 0.17: the Delete key
            from mse_studio.gui.common import delete_key
            delete_key(self.grid, self.remove_pictures)
        except ImportError:
            pass
        pv.addWidget(self.grid, 1)
        hint = QLabel(REAL_HINT)
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        pv.addWidget(hint)
        self.real_btn = QPushButton("Add to my order")
        icons.set_icon(self.real_btn, "shopping_cart")
        self.real_btn.setToolTip("Real cards printed with these pictures – on the Order page")
        self.real_btn.clicked.connect(lambda: self.add_real(self._picked()))
        pv.addWidget(self.real_btn)
        self.edit_btn = QToolButton()
        self.edit_btn.setText("Add to my deck to edit")
        self.edit_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.edit_btn.setIcon(icons.icon("edit"))
        self.edit_btn.setPopupMode(QToolButton.InstantPopup)
        self.edit_btn.setToolTip("Your own cards on the Cards page: the card's text (from "
                                 "Scryfall) and this picture's art")
        em = QMenu(self.edit_btn)
        self._fill_edit_menu(em, None)
        self.edit_btn.setMenu(em)
        pv.addWidget(self.edit_btn)
        self.side_tabs.addTab(pics, "Downloaded pictures")

        # an order (Download → XML)
        orders = QWidget()
        ov = QVBoxLayout(orders)
        ov.setContentsMargins(0, 4, 0, 0)
        self.head = QLabel("<b>Your order</b>")
        ov.addWidget(self.head)
        self.hint = QLabel("On MPCFill's Editor: <b>Import</b> your decklist (or search cards), "
                           "pick a picture for each, then <b>Download → XML</b>. The order shows "
                           "up here.")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("Hint")
        ov.addWidget(self.hint)
        self.list = QListWidget()
        self.list.setToolTip("The cards of the order and how many of each – Delete takes the "
                             "selected out of it")
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        try:                                   # MSE Studio 0.17: the Delete key
            from mse_studio.gui.common import delete_key
            delete_key(self.list, self.drop_selected)
        except ImportError:
            pass
        ov.addWidget(self.list, 1)
        self.add_btn = QPushButton("Add them to my deck")
        self.add_btn.setProperty("kind", "primary")
        icons.set_icon(self.add_btn, "add")
        self.add_btn.setToolTip("As real cards printed with the pictures you picked on "
                                "MPCFill – on the Order page and in Print at home")
        self.add_btn.clicked.connect(self.add_to_deck)
        ov.addWidget(self.add_btn)
        self.back_btn = QPushButton("Use its card back")
        self.back_btn.clicked.connect(self.use_back)
        ov.addWidget(self.back_btn)
        row = QHBoxLayout()
        b = QPushButton("Open an order file…")
        icons.set_icon(b, "folder_open")
        b.setToolTip("An .xml order MPCFill gave you before")
        b.clicked.connect(self.open_file)
        row.addWidget(b)
        b = QPushButton("Picture server…")
        b.setToolTip("MPCFill's picture server makes downloads faster and sharper")
        b.clicked.connect(self.settings)
        row.addWidget(b)
        ov.addLayout(row)
        self.side_tabs.addTab(orders, "Order (XML)")
        self.status = QLabel()
        self.status.setWordWrap(True)
        sv.addWidget(self.status)
        split.addWidget(side)
        split.setSizes([860, 360])
        lay.addWidget(split, 1)
        self._load_last()
        self._buttons()

    # ------------------------------------------------------------ MSE Studio calls these
    def load(self):
        self._buttons()

    def refresh(self):
        """The page was opened: mpcfill.com is loaded the first time."""
        if self.web is None and self.placeholder is not None:
            from mse_studio.gui import web_window
            try:                         # MSE Studio 0.18: it stays on MPCFill
                self.web = web_window.WebPanel(self, SITE, on_download=self._downloaded,
                                               stay_on=STAY_ON)
            except TypeError:
                self.web = web_window.WebPanel(self, SITE, on_download=self._downloaded)
            self.split.replaceWidget(0, self.web)
            self.placeholder.deleteLater()
            self.placeholder = None
            self.split.setSizes([860, 360])
        self._buttons()

    def shutdown(self):
        forget(self._jobs)
        if self.web is not None:
            self.web.close_browser()

    # ------------------------------------------------------------ the order
    def _downloaded(self, path: Path, _page: str):
        try:
            if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                self._picture_downloaded(path)
                return
            if path.suffix.lower() != ".xml":
                self.status.setText(f"Saved {path.name}")
                return
            keep = addons.data_dir(ADDON_ID) / "orders"
            keep.mkdir(parents=True, exist_ok=True)
            dst = keep / path.name
            dst.write_bytes(path.read_bytes())
            self.show_order(dst)
        except RuntimeError:
            return

    def _picture_downloaded(self, path: Path):
        """Download Image on MPCFill: the picture shows up beside it, ready to
        go in the deck."""
        keep = addons.data_dir(ADDON_ID) / "pictures"
        keep.mkdir(parents=True, exist_ok=True)
        dst = keep / path.name
        dst.write_bytes(path.read_bytes())
        self.pictures = [p for p in self.pictures if Path(p).name != dst.name] + [str(dst)]
        self._keep_pictures()
        self._show_pictures(select=str(dst))
        self.side_tabs.setCurrentIndex(0)
        self.status.setText(f"Got {mo.card_name(dst.name)} – right-click it to add it to your "
                            "deck.")

    # ------------------------------------------------------------ the downloaded pictures
    def _show_pictures(self, select: str = ""):
        keep_sel = {it.data(Qt.UserRole) for it in self.grid.selectedItems()}
        if select:
            keep_sel = {select}
        self.grid.blockSignals(True)
        self.grid.clear()
        for f in reversed(self.pictures):              # the newest first
            it = QListWidgetItem(mo.card_name(Path(f).name))
            it.setData(Qt.UserRole, f)
            it.setToolTip(Path(f).name)
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            pm = QPixmap(f)
            if not pm.isNull():
                it.setIcon(QIcon(pm.scaled(130, 182, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            self.grid.addItem(it)
            it.setSelected(f in keep_sel)
        self.grid.blockSignals(False)
        self.pics_hint.setVisible(not self.pictures)
        self.side_tabs.setTabText(0, f"Downloaded pictures ({len(self.pictures)})"
                                  if self.pictures else "Downloaded pictures")
        self._buttons()

    def _picked(self, path: str = "") -> list:
        """The pictures to act on: the selected ones (or the one right-clicked)."""
        sel = [it.data(Qt.UserRole) for it in self.grid.selectedItems()]
        if path and path not in sel:
            return [path]
        return sel

    def _grid_menu(self, pos):
        it = self.grid.itemAt(pos)
        if it is None:
            return
        f = it.data(Qt.UserRole)
        picked = self._picked(f)
        n = len(picked)
        m = QMenu(self)
        m.addAction(icons.icon("zoom_in"), "See it full size", lambda: self.view_full(f))
        m.addSeparator()
        a = m.addAction(icons.icon("shopping_cart"),
                        "Add to my order (a real card, printed with this picture)" if n == 1 else
                        f"Add the {n} to my order (real cards, printed with these pictures)",
                        lambda: self.add_real(picked))
        a.setEnabled(self.main.project is not None)
        edit = m.addMenu(icons.icon("edit"), "Add to my deck to edit" if n == 1 else
                         f"Add the {n} to my deck to edit")
        edit.setEnabled(self.main.project is not None)
        self._fill_edit_menu(edit, picked)
        self._tools_menu(m, f)
        m.addSeparator()
        m.addAction(icons.icon("save"), "Save the picture…" if n == 1 else
                    f"Save the {n} pictures…", lambda: self.save_pictures(picked))
        a = m.addAction(icons.icon("delete"), "Remove from this list" if n == 1 else
                        f"Remove the {n} from this list", lambda: self.remove_pictures(picked))
        a.setShortcut(Qt.Key_Delete)
        m.exec(self.grid.viewport().mapToGlobal(pos))

    def _fill_edit_menu(self, menu: QMenu, picked):
        """picked None: the selected pictures, when the menu is used."""
        for label, frame, tip in (
                ("With its art, in my frame", "mine",
                 "Your deck's frame (a planeswalker, saga… gets the matching one)"),
                ("With its art, in a frame like the real card", "real",
                 "The MSE frame closest to the real card's")):
            a = menu.addAction(label, lambda fr=frame: self.edit_cards(
                picked if picked is not None else self._picked(), fr))
            a.setToolTip(tip)

    def _tools_menu(self, menu: QMenu, path: str):
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
        info = {"name": mo.card_name(Path(path).name), "card": {}, "kind": "mpcfill",
                "credit": CREDIT, "maker": "MPCFill", "page": "https://mpcfill.com"}
        for t in tools:
            a = menu.addAction(icons.icon("brush"), t.label,
                               lambda t=t: picture_tools.run(t, self, Path(path), dict(info)))
            a.setToolTip(t.tooltip)

    def view_full(self, path: str):
        from mse_studio.gui.image_viewer import ImageViewer
        files = [Path(f) for f in reversed(self.pictures)]
        try:
            i = files.index(Path(path))
        except ValueError:
            i = 0
        ImageViewer(self, files, i).exec()

    def remove_pictures(self, picked=None):
        """Out of this list (the files go too – they're MSE Studio's copies)."""
        picked = picked if picked else self._picked()
        if not picked:
            return
        try:
            from mse_studio.gui.common import ask_delete
            if not ask_delete(self, f"Take {len(picked)} picture(s) out of the list?"):
                return
        except ImportError:
            pass
        gone = set(picked)
        self.pictures = [f for f in self.pictures if f not in gone]
        keep = addons.data_dir(ADDON_ID) / "pictures"
        for f in gone:
            fp = Path(f)
            try:
                if fp.parent == keep and fp.is_file():
                    fp.unlink()
            except OSError:
                pass
        self._keep_pictures()
        self._show_pictures()

    def save_pictures(self, picked: list):
        import shutil
        if not picked:
            return
        if len(picked) == 1:
            dst, _ = QFileDialog.getSaveFileName(self, "Save the picture", Path(picked[0]).name)
            if dst:
                shutil.copyfile(picked[0], dst)
            return
        folder = QFileDialog.getExistingDirectory(self, "Save the pictures in")
        if folder:
            for f in picked:
                shutil.copyfile(f, Path(folder) / Path(f).name)
            self.status.setText(f"Saved {len(picked)} picture(s) in {folder}.")

    def add_real(self, picked: list):
        """Real cards printed with these pictures (the Order page)."""
        p = self.main.project
        if p is None or not picked:
            return
        cards, folder = [mo.from_picture(Path(f)) for f in picked], str(p.folder)

        def work(progress=None, cancel=None):
            entries = [dl.Entry(name=c.name, count=1) for c in cards]
            dl.resolve(entries, progress, cancel)        # card data (Scryfall), if it's real
            return folder, [(e, [(0, c.file)]) for c, e in zip(cards, entries)]

        self.status.setText("Adding them…")
        job = Job(work, label="Adding MPCFill pictures to the order")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(self._added)
        job.signals.failed.connect(self._failed)
        self._jobs.append(start(job))

    def edit_cards(self, picked: list, frame: str):
        """Your own cards to edit: the card's text (Scryfall) and the
        picture's art (its art window, fitted like Force to fit)."""
        p = self.main.project
        if p is None or not picked:
            return
        names, folder = [mo.card_name(Path(f).name) for f in picked], str(p.folder)

        def work(progress=None, cancel=None):
            from PIL import Image
            entries = [dl.Entry(name=n) for n in names]
            dl.resolve(entries, progress, cancel)
            pics = []
            for f in picked:
                with Image.open(f) as im:
                    pics.append((f, art_window(im.size)))
            return folder, entries, pics

        self.status.setText("Looking the cards up…")
        job = Job(work, label="Cards to edit from MPCFill")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(lambda res, fr=frame: self._edit_ready(res, fr))
        job.signals.failed.connect(self._failed)
        self._jobs.append(start(job))

    def _edit_ready(self, res, frame: str):
        try:
            from mse_studio.core import art_import
            folder, entries, pics = res
            p = self.main.project
            if p is None or str(p.folder) != folder:
                self.status.setText("The deck was closed – nothing was added.")
                return
            keep = []                          # the art goes in the deck's art folder
            target = art_import.default_folder(p)
            for e, (path, crop) in zip(entries, pics):
                dst = art_import.save_image_bytes(Path(path).read_bytes(), target,
                                                  f"{e.display_name} (MPCFill)")
                art_import.set_credit(p, dst, "MPCFill", CREDIT, "https://mpcfill.com")
                keep.append((dst, crop))
            try:
                n = self.main.decklists_tab.add_custom(entries, "MPCFill", frame=frame,
                                                       pictures=keep, keep_unknown=True)
            except TypeError:                  # an MSE Studio before 0.17
                error(self, "MPCFill", "Update MSE Studio (0.17 or newer) to add cards to edit.")
                return
            if n:
                self.status.setText(f"Added {n} card(s) to edit – they're on the Cards page, "
                                    "with their art.")
        except RuntimeError:
            return

    def drop_selected(self):
        """The selected cards out of the order (not out of your deck)."""
        if self.order is None:
            return
        rows = sorted({self.list.row(it) for it in self.list.selectedItems()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self.order.cards):
                del self.order.cards[r]
        self._show_list()

    def _keep_pictures(self):
        import json
        (addons.data_dir(ADDON_ID) / "pictures.json").write_text(json.dumps(self.pictures),
                                                                  encoding="utf-8")

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "An MPCFill order", "",
                                              "MPCFill orders (*.xml)")
        if path:
            self.show_order(Path(path))

    def show_order(self, path: Path):
        try:
            self.order = mo.read(path)
        except ValueError as e:
            error(self, "MPCFill", str(e))
            return
        self.order_file = str(path)
        (addons.data_dir(ADDON_ID) / "last.txt").write_text(str(path), encoding="utf-8")
        self._show_list()
        self.side_tabs.setCurrentIndex(1)
        self.status.setText(f"From {path.name}")

    def _show_list(self):
        self.list.clear()
        for c in self.order.cards:
            it = QListWidgetItem(f"{c.count}×  {c.name}" + ("   (two faces)" if c.back else "")
                                 + ("   (downloaded picture)" if c.file else ""))
            it.setToolTip(c.picture)
            self.list.addItem(it)
        self.head.setText(f"<b>Your order</b> – {len(self.order.cards)} different cards, "
                          f"{self.order.total} in all")
        self._buttons()

    def _load_last(self):
        import json
        try:
            files = json.loads((addons.data_dir(ADDON_ID) / "pictures.json")
                               .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            files = []
        self.pictures = [str(f) for f in files if Path(f).is_file()]
        try:
            last = Path((addons.data_dir(ADDON_ID) / "last.txt").read_text(encoding="utf-8")
                        .strip())
            if last.is_file():
                self.show_order(last)
        except OSError:
            pass
        self._show_pictures()
        if self.pictures:
            self.side_tabs.setCurrentIndex(0)

    def _buttons(self):
        has = self.order is not None and bool(self.order.cards)
        p = self.main.project
        n = len(self.grid.selectedItems())
        for b in (self.real_btn, self.edit_btn):
            b.setEnabled(p is not None and n > 0)
        self.real_btn.setText(f"Add the {n} selected to my order" if n > 1 else "Add to my order")
        self.edit_btn.setText(f"Add the {n} selected to my deck to edit" if n > 1 else
                              "Add to my deck to edit")
        self.add_btn.setEnabled(has and p is not None)
        self.add_btn.setText(f"Add {self.order.total} cards to my deck" if has else
                             "Add them to my deck")
        self.back_btn.setVisible(self.order is not None and bool(self.order.cardback))
        self.back_btn.setEnabled(p is not None)

    def settings(self):
        from mse_studio.gui.mpcfill_dialog import MpcfillDialog
        MpcfillDialog(self, self.main.settings).exec()

    def _images(self) -> str:
        return getattr(self.main.settings, "mpcfill_images", "")

    # ------------------------------------------------------------ into the deck
    def add_to_deck(self):
        p, o = self.main.project, self.order
        if p is None or o is None or not o.cards:
            return
        from mse_studio.core import addons as _a
        tmp = _a.data_dir(ADDON_ID) / "pictures"
        tmp.mkdir(parents=True, exist_ok=True)
        cards, images, folder = list(o.cards), self._images(), str(p.folder)

        def work(progress=None, cancel=None):
            entries = [dl.Entry(name=c.name, count=c.count) for c in cards]
            dl.resolve(entries, progress, cancel)        # card data (Scryfall), if it's real
            out = []
            for k, (c, e) in enumerate(zip(cards, entries)):
                if cancel is not None and cancel.cancelled:
                    break
                progress(k, len(cards), f"Pictures: {c.name}")
                files = []
                if c.file and Path(c.file).is_file():          # Download Image: have it
                    files.append((0, c.file))
                for side, pid in enumerate((c.front, c.back)):
                    if not pid or (side == 0 and files):
                        continue
                    data = mpcfill.download(pid, images)
                    f = tmp / f"{_safe(pid)}{_ext(data)}"
                    f.write_bytes(data)
                    files.append((side, str(f)))
                out.append((e, files))
            return folder, out

        self.status.setText("Getting the pictures…")
        job = Job(work, label="Adding the MPCFill order")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(self._added)
        job.signals.failed.connect(self._failed)
        self._jobs.append(start(job))

    def _progress(self, _d, _t, msg):
        try:
            self.status.setText(msg)
        except RuntimeError:
            return

    def _failed(self, msg: str):
        try:
            self.status.setText("")
            error(self, "MPCFill", msg.splitlines()[0])
        except RuntimeError:
            return

    def _added(self, res):
        from mse_studio.pipeline import real_cards as rc
        try:
            folder, out = res
            p = self.main.project
            if p is None or str(p.folder) != folder:
                return
            ok = [e for e, files in out if files]
            dl.add_to_project(p, ok)
            for e, files in out:
                for side, f in files:
                    rc.use_picture(p, e, Path(f), side, CREDIT)
            p.save_config()
            n = sum(e.count for e in ok)
            self.main.record(f"MPCFill · {n} real card(s)")
            self.main.update_title()
            self.status.setText(f"Added {n} card(s) – they're on the Order page.")
            self.main.order_tab.real_pictures(ok)
        except RuntimeError:
            return

    def use_back(self):
        p, o = self.main.project, self.order
        if p is None or o is None or not o.cardback:
            return
        pid, images, folder = o.cardback, self._images(), str(p.folder)
        tmp = addons.data_dir(ADDON_ID) / "pictures"
        tmp.mkdir(parents=True, exist_ok=True)

        def work(progress=None, cancel=None):
            data = mpcfill.download(pid, images)
            f = tmp / f"card back {_safe(pid)}{_ext(data)}"
            f.write_bytes(data)
            return folder, str(f)

        job = Job(work, label="Getting the card back")
        job.signals.finished.connect(self._back_ready)
        job.signals.failed.connect(self._failed)
        self._jobs.append(start(job))

    def _back_ready(self, res):
        from mse_studio.core import card_backs
        try:
            folder, path = res
            p = self.main.project
            if p is None or str(p.folder) != folder:
                return
            card_backs.use_for_deck(p, Path(path))
            self.main.order_tab.refresh()
            self.status.setText("The order's card back is your deck's card back now.")
        except RuntimeError:
            return


ART_BOX = (29 / 375, 60 / 523, 317 / 375, 233 / 523)


def art_window(size: tuple) -> list:
    """Where a card picture's art is: [x, y, width, height] (with or without
    MPC's margin; a sideways card is left whole)."""
    w, h = size
    if w > h:
        return [0, 0, w, h]
    bx = by = 0.0
    if abs(w / h - 2.75 / 3.75) < abs(w / h - 2.5 / 3.5):     # MPC's margin around it
        bx, by = w * 0.125 / 2.75, h * 0.125 / 3.75
    cw, ch = w - 2 * bx, h - 2 * by
    x, y, aw, ah = ART_BOX
    return [round(bx + x * cw), round(by + y * ch), round(aw * cw), round(ah * ch)]


def _safe(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name)[:80] or "picture"


def _ext(data: bytes) -> str:
    return ".png" if data[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
