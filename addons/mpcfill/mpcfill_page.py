"""MPCFill: mpcfill.com in a browser inside MSE Studio. Make your order there
– import a decklist, pick the pictures – then *Download → XML*: the order
comes straight here, and its cards become real cards of your deck printed
with the pictures you picked (and its card back your deck's back).

Network: mpcfill.com in the browser (only while the page is open), and the
pictures of an order when you add them (MPCFill's image server set in MSE
Studio, else Google Drive)."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QSplitter, QVBoxLayout, QWidget)

from mse_studio.core import addons, mpcfill
from mse_studio.core import decklists as dl
from mse_studio.gui import icons
from mse_studio.gui.common import Job, error, forget, start
from mse_studio.gui.nav import page_header

from . import order as mo

ADDON_ID = "mpcfill"
SITE = "https://mpcfill.com/editor"
CREDIT = "Picture from MPCFill (mpcfill.com)"


class MpcfillPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._jobs: list = []
        self.order: mo.Order | None = None
        self.order_file = ""
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
        self.head = QLabel("<b>Your order</b>")
        sv.addWidget(self.head)
        self.hint = QLabel("On MPCFill: <b>Import</b> your decklist (or search cards), pick a "
                           "picture for each, then <b>Download → XML</b>. The order shows up "
                           "here.")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("Hint")
        sv.addWidget(self.hint)
        self.list = QListWidget()
        self.list.setToolTip("The cards of the order and how many of each – Delete takes the "
                             "selected out of it")
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        try:                                   # MSE Studio 0.17: the Delete key
            from mse_studio.gui.common import delete_key
            delete_key(self.list, self.drop_selected)
        except ImportError:
            pass
        sv.addWidget(self.list, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        sv.addWidget(self.status)
        self.add_btn = QPushButton("Add them to my deck")
        self.add_btn.setProperty("kind", "primary")
        icons.set_icon(self.add_btn, "add")
        self.add_btn.setToolTip("As real cards printed with the pictures you picked on "
                                "MPCFill – on the Order page and in Print at home")
        self.add_btn.clicked.connect(self.add_to_deck)
        sv.addWidget(self.add_btn)
        self.back_btn = QPushButton("Use its card back")
        self.back_btn.clicked.connect(self.use_back)
        sv.addWidget(self.back_btn)
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
        sv.addLayout(row)
        split.addWidget(side)
        split.setSizes([900, 320])
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
            self.web = web_window.WebPanel(self, SITE, on_download=self._downloaded)
            self.split.replaceWidget(0, self.web)
            self.placeholder.deleteLater()
            self.placeholder = None
            self.split.setSizes([900, 320])
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
        """Download Image on MPCFill: the card joins the order list, printed
        with that picture."""
        keep = addons.data_dir(ADDON_ID) / "pictures"
        keep.mkdir(parents=True, exist_ok=True)
        dst = keep / path.name
        dst.write_bytes(path.read_bytes())
        card = mo.from_picture(dst)
        if self.order is None:
            self.order = mo.Order()
            self.order_file = ""
        same = next((c for c in self.order.cards if c.file and Path(c.file).name == dst.name),
                    None)
        if same is None:
            self.order.cards.append(card)
        self._keep_pictures()
        self._show_list()
        self.status.setText(f"{card.name} is in the order list – Add them to my deck prints it "
                            "with that picture.")

    def drop_selected(self):
        """The selected cards out of the order (not out of your deck)."""
        if self.order is None:
            return
        rows = sorted({self.list.row(it) for it in self.list.selectedItems()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self.order.cards):
                del self.order.cards[r]
        self._keep_pictures()
        self._show_list()

    def _keep_pictures(self):
        import json
        files = [c.file for c in (self.order.cards if self.order else []) if c.file]
        (addons.data_dir(ADDON_ID) / "pictures.json").write_text(json.dumps(files),
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
        self._keep_pictures()                    # a new order: downloaded pictures start over
        self._show_list()
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
        try:                                     # read first: opening the order resets it
            files = json.loads((addons.data_dir(ADDON_ID) / "pictures.json")
                               .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            files = []
        try:
            last = Path((addons.data_dir(ADDON_ID) / "last.txt").read_text(encoding="utf-8")
                        .strip())
            if last.is_file():
                self.show_order(last)
        except OSError:
            pass
        pics = [mo.from_picture(Path(f)) for f in files if Path(f).is_file()]
        if pics:
            if self.order is None:
                self.order = mo.Order()
            self.order.cards += pics
            self._keep_pictures()
            self._show_list()

    def _buttons(self):
        has = self.order is not None and bool(self.order.cards)
        p = self.main.project
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


def _safe(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name)[:80] or "picture"


def _ext(data: bytes) -> str:
    return ".png" if data[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
