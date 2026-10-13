"""Deck sharing: share decks with friends through a folder you all can see –
a shared OneDrive, Google Drive or Dropbox folder – or send one as a file.
Your friends' decks show up here; open one and it's unpacked into your decks
folder (never over a deck of yours).

Network: none of its own – the folder is kept in step by OneDrive, Google
Drive or Dropbox."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMenu, QMessageBox, QPushButton, QSplitter,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from mse_studio import __version__
from mse_studio.gui import icons
from mse_studio.gui.common import Job, error, forget, start
from mse_studio.gui.nav import page_header

from . import sharing as sh


def _size(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 1e5 else f"{max(1, n // 1000)} KB"


class SharingPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._jobs: list = []
        self.shared: list[sh.Shared] = []
        lay = QVBoxLayout(self)
        lay.addWidget(page_header(
            "Deck sharing", "Share decks with friends through a folder you all can see – a "
                            "shared OneDrive, Google Drive or Dropbox folder – or send a deck "
                            "as a file. Your friends' decks show up here; open one and it's "
                            "added to your decks."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Your name"))
        self.name = QLineEdit(sh.prefs().get("name", ""))
        self.name.setPlaceholderText("So friends see who shared it")
        self.name.setMaximumWidth(220)
        self.name.editingFinished.connect(lambda: sh.set_pref("name", self.name.text().strip()))
        row.addWidget(self.name)
        row.addSpacing(16)
        row.addWidget(QLabel("Shared folder"))
        self.folder = QLineEdit(sh.prefs().get("folder", ""))
        self.folder.setPlaceholderText("A folder you share with your friends")
        self.folder.setReadOnly(True)
        row.addWidget(self.folder, 1)
        b = QPushButton("Choose…")
        icons.set_icon(b, "folder_open")
        b.setToolTip("A folder on your PC that OneDrive, Google Drive or Dropbox shares with "
                     "your friends (share it with them there first)")
        m = QMenu(b)
        m.addAction("Pick a folder…", self.pick_folder)
        self.cloud_menu = m.addMenu("In my cloud folders")
        self.cloud_menu.aboutToShow.connect(self._fill_cloud)
        b.setMenu(m)
        row.addWidget(b)
        b = QPushButton("Open it")
        icons.set_icon(b, "open_in_new")
        b.setToolTip("Show the shared folder in Windows")
        b.clicked.connect(self._open_folder)
        row.addWidget(b)
        lay.addLayout(row)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Deck", "Shared by", "When", "Cards", "Size"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setRootIsDecorated(False)
        self.tree.itemDoubleClicked.connect(lambda *_: self.open_shared())
        self.tree.currentItemChanged.connect(self._picked)
        lv.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.open_btn = QPushButton("Open this deck")
        self.open_btn.setProperty("kind", "primary")
        icons.set_icon(self.open_btn, "download")
        self.open_btn.setToolTip("Unpack it into your decks folder and open it – a deck of "
                                 "yours is never replaced")
        self.open_btn.clicked.connect(self.open_shared)
        row.addWidget(self.open_btn)
        self.remove_btn = QPushButton("Stop sharing it")
        icons.set_icon(self.remove_btn, "delete")
        self.remove_btn.setToolTip("Take a deck you shared out of the shared folder")
        self.remove_btn.clicked.connect(self.remove)
        row.addWidget(self.remove_btn)
        b = QPushButton("Refresh")
        icons.set_icon(b, "refresh")
        b.clicked.connect(self.fill)
        row.addWidget(b)
        row.addStretch(1)
        lv.addLayout(row)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(220, 300)
        rv.addWidget(self.preview)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        rv.addWidget(self.info)
        rv.addStretch(1)
        split.addWidget(right)
        split.setSizes([760, 300])
        lay.addWidget(split, 1)

        box = QHBoxLayout()
        self.share_btn = QPushButton("Share this deck")
        self.share_btn.setProperty("kind", "primary")
        icons.set_icon(self.share_btn, "upload")
        self.share_btn.setToolTip("Put the open deck in the shared folder (sharing it again "
                                  "updates your earlier one)")
        self.share_btn.clicked.connect(self.share)
        box.addWidget(self.share_btn)
        self.note = QLineEdit()
        self.note.setPlaceholderText("A note for your friends (optional)")
        box.addWidget(self.note, 1)
        self.renders = QCheckBox("With its card pictures")
        self.renders.setToolTip("The exported, upscaled and print-ready pictures too – friends "
                                "can print straight away, but the file is much bigger")
        box.addWidget(self.renders)
        self.art = QCheckBox("With its art folder")
        self.art.setToolTip("Your art library for this deck (screenshots and pictures), so "
                            "friends can re-crop the art")
        box.addWidget(self.art)
        lay.addLayout(box)
        row = QHBoxLayout()
        b = QPushButton("Send as a file…")
        icons.set_icon(b, "save")
        b.setToolTip("Save the open deck as one file to send on Discord, by e-mail…")
        b.clicked.connect(self.send_file)
        row.addWidget(b)
        b = QPushButton("Open a deck file…")
        icons.set_icon(b, "folder_open")
        b.setToolTip("A deck file a friend sent you (.msedeck)")
        b.clicked.connect(self.open_file)
        row.addWidget(b)
        row.addStretch(1)
        self.status = QLabel()
        self.status.setObjectName("Hint")
        row.addWidget(self.status)
        lay.addLayout(row)
        self.fill()

    # ------------------------------------------------------------ MSE Studio calls these
    def load(self):
        self._buttons()

    def refresh(self):
        self.fill()

    def shutdown(self):
        forget(self._jobs)

    # ------------------------------------------------------------ the shared folder
    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "The folder you share with your friends",
                                                self.folder.text())
        if path:
            self._set_folder(path)

    def _fill_cloud(self):
        from mse_studio.core import backup
        self.cloud_menu.clear()
        found = backup.detect_cloud_folders()
        if not found:
            a = self.cloud_menu.addAction("No OneDrive, Google Drive or Dropbox folder found")
            a.setEnabled(False)
        for name, path in found:
            self.cloud_menu.addAction(f"{name}: {path}", lambda p=path: self._pick_in(p))

    def _pick_in(self, start_in: Path):
        path = QFileDialog.getExistingDirectory(
            self, "The folder you share with your friends (make one here if you like)",
            str(start_in))
        if path:
            self._set_folder(path)

    def _set_folder(self, path: str):
        sh.set_pref("folder", path)
        self.folder.setText(path)
        self.fill()

    def _open_folder(self):
        if self.folder.text():
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder.text()))

    def fill(self):
        folder = self.folder.text()
        self.shared = sh.shared_in(Path(folder)) if folder else []
        self.tree.clear()
        me = self.name.text().strip().lower()
        for k, s in enumerate(self.shared):
            it = QTreeWidgetItem([s.deck, s.by + ("  (you)" if me and s.by.lower() == me else ""),
                                  s.when.replace("T", " ")[:16], str(s.cards), _size(s.size)])
            it.setData(0, Qt.UserRole, k)
            it.setToolTip(0, s.note or s.path.name)
            self.tree.addTopLevelItem(it)
        self.status.setText(
            "Choose the folder you share with your friends first." if not folder else
            f"{len(self.shared)} deck(s) in the shared folder" if self.shared else
            "No shared decks there yet – share one, or wait for your friends' to sync.")
        if self.shared:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        else:
            self._picked(None, None)
        self._buttons()

    def _current(self):
        it = self.tree.currentItem()
        k = it.data(0, Qt.UserRole) if it is not None else None
        return self.shared[k] if k is not None and 0 <= k < len(self.shared) else None

    def _picked(self, *_):
        s = self._current()
        self.preview.clear()
        if s is None:
            self.info.clear()
            self._buttons()
            return
        data = sh.preview(s.path)
        if data:
            pm = QPixmap()
            pm.loadFromData(data)
            self.preview.setPixmap(pm.scaled(220, 308, Qt.KeepAspectRatio,
                                             Qt.SmoothTransformation))
        extras = [x for x, on in (("card pictures", s.renders), ("art folder", s.art)) if on]
        self.info.setText(f"<b>{s.deck}</b><br>Shared by {s.by or 'someone'} on {s.day} · "
                          f"{s.cards} cards · {_size(s.size)}"
                          + (f"<br>With its {' and '.join(extras)}" if extras else "")
                          + (f"<br><br>{s.note}" if s.note else ""))
        self._buttons()

    def _buttons(self):
        s = self._current()
        me = self.name.text().strip().lower()
        self.open_btn.setEnabled(s is not None)
        self.remove_btn.setEnabled(s is not None and bool(me) and s.by.lower() == me)
        self.share_btn.setEnabled(self.main.project is not None and bool(self.folder.text()))

    # ------------------------------------------------------------ sharing
    def _pack(self, out: Path, label: str):
        p = self.main.project
        if p is None:
            return
        self.main.cards_tab.editor.commit()
        if p.dirty and not self.main.save():          # what friends get is what's saved
            return
        by, note = self.name.text().strip(), self.note.text().strip()
        renders, art = self.renders.isChecked(), self.art.isChecked()
        if not by:
            error(self, "Deck sharing", "Type your name first, so your friends see who shared "
                                        "the deck.")
            return

        def work(progress=None, cancel=None):
            return str(sh.pack(p, out, by, note, renders, art, __version__, progress, cancel))

        self.status.setText(f"{label}…")
        job = Job(work, label=label)
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(self._packed)
        job.signals.failed.connect(self._failed)
        self._jobs.append(start(job))

    def share(self):
        p = self.main.project
        if p is None or not self.folder.text():
            return
        out = Path(self.folder.text()) / sh.file_name(p.name, self.name.text().strip())
        self._pack(out, f"Sharing {p.name}")

    def send_file(self):
        p = self.main.project
        if p is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the deck as a file",
            str(Path.home() / sh.file_name(p.name, self.name.text().strip() or "me")),
            f"Shared decks (*{sh.SUFFIX})")
        if path:
            if not path.endswith(sh.SUFFIX):
                path += sh.SUFFIX
            self._pack(Path(path), f"Saving {p.name}")

    def _progress(self, _d, _t, msg):
        try:
            self.status.setText(msg)
        except RuntimeError:
            return

    def _failed(self, msg: str):
        try:
            self.status.setText("")
            error(self, "Deck sharing", msg.splitlines()[0])
        except RuntimeError:
            return

    def _packed(self, path: str):
        try:
            self.fill()
            self.status.setText(f"Done: {Path(path).name}")
        except RuntimeError:
            return

    def remove(self):
        s = self._current()
        if s is None:
            return
        if QMessageBox.question(self, "Deck sharing",
                                f"Take {s.deck} out of the shared folder? Friends who opened "
                                "it keep their copy.") != QMessageBox.Yes:
            return
        try:
            s.path.unlink()
        except OSError as e:
            error(self, "Deck sharing", f"Couldn't remove it: {e}")
        self.fill()

    # ------------------------------------------------------------ opening a friend's deck
    def open_shared(self):
        s = self._current()
        if s is not None:
            self._unpack(s)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "A shared deck", "",
                                              f"Shared decks (*{sh.SUFFIX} *.zip)")
        if not path:
            return
        try:
            self._unpack(sh.read(Path(path)))
        except sh.ShareError as e:
            error(self, "Deck sharing", str(e))

    def _unpack(self, s: sh.Shared):
        decks = Path(getattr(self.main.settings, "decks_dir", "") or Path.home() / "MSE decks")
        target = sh.target_for(decks, s)

        def work(progress=None, cancel=None):
            progress(0, 0, f"Unpacking {s.deck}…")
            return str(sh.unpack(s.path, target))

        job = Job(work, label=f"Opening {s.deck}")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(self._unpacked)
        job.signals.failed.connect(self._failed)
        self._jobs.append(start(job))

    def _unpacked(self, folder: str):
        try:
            self.status.setText(f"Added to your decks: {Path(folder).name}")
            self.main.open_project(Path(folder))
        except RuntimeError:
            return
