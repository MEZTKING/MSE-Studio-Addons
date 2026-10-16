"""MPCFill… : the server (searching) and the image server (full-size
pictures) – found from mpcfill.com, or typed in. Saved in the add-on's
preferences."""
from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout)

from mse_studio.gui import icons
from mse_studio.gui.common import Job, forget, start

from . import mpcfill_api as mpcfill
from . import prefs as prefs_file


class ServerDialog(QDialog):
    def __init__(self, parent, prefs: dict):
        super().__init__(parent)
        self.prefs = prefs
        self._jobs: list = []
        self.setWindowTitle("MPCFill")
        self.resize(640, 320)
        lay = QVBoxLayout(self)
        about = QLabel(
            "Real cards are printed with <b>MPCFill</b>'s print-ready pictures when it has "
            "them, Scryfall's otherwise. MPCFill's page (<a href='https://mpcfill.com/explore'>"
            "mpcfill.com</a>) finds them through a <b>server</b>, and full-size pictures come "
            "from an <b>image server</b>. <b>Find them from mpcfill.com</b> reads both "
            "addresses from the page – or paste them, or a shared link with "
            "<i>?server=…</i>.<br><br>When a deck's real cards get their pictures, their names "
            "are sent to that server.")
        about.setWordWrap(True)
        about.setOpenExternalLinks(True)
        lay.addWidget(about)
        f = QFormLayout()
        self.server = QLineEdit(prefs.get("mpcfill_server", ""))
        self.server.setPlaceholderText("e.g. https://… (empty: real cards use Scryfall's pictures)")
        f.addRow("Server", self.server)
        self.images = QLineEdit(prefs.get("mpcfill_images", ""))
        self.images.setPlaceholderText("for full-size pictures (empty: straight from Google Drive)")
        f.addRow("Image server", self.images)
        lay.addLayout(f)
        row = QHBoxLayout()
        self.find_btn = QPushButton("Find them from mpcfill.com")
        icons.set_icon(self.find_btn, "search")
        self.find_btn.clicked.connect(self.find)
        row.addWidget(self.find_btn)
        self.test_btn = QPushButton("Test")
        self.test_btn.setToolTip("Ask the server which drives it searches")
        self.test_btn.clicked.connect(self.test)
        row.addWidget(self.test_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.status = QLabel()
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        lay.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _server_text(self) -> str:
        text = self.server.text().strip()
        return mpcfill.server_from_link(text) or mpcfill.clean_url(text)

    def _say(self, text: str):
        try:
            self.status.setText(text)
        except RuntimeError:          # the window is closed
            return

    def find(self):
        self.find_btn.setEnabled(False)
        self._say("Reading mpcfill.com…")
        site = self.server.text().strip() if "server=" in self.server.text() else mpcfill.SITE

        def work(progress=None, cancel=None):
            return mpcfill.discover(site, lambda m: progress(0, 0, m))

        job = Job(work, label="Finding MPCFill's server")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(self._found)
        job.signals.failed.connect(self._find_failed)
        self._jobs.append(start(job))

    def _progress(self, _done, _total, text):
        self._say(text)

    def _found(self, found):
        try:
            self.find_btn.setEnabled(True)
            if found.server:
                self.server.setText(found.server)
                if found.images:
                    self.images.setText(found.images)
                self.status.setText("Found the server" + (
                    " and the image server." if found.images else
                    " (not the image server – pictures come from Google Drive)."))
            else:
                self.status.setText(
                    "No server found on the page. Open mpcfill.com in your browser, find the "
                    "server it uses in its settings, and paste it here.")
        except RuntimeError:
            return

    def _find_failed(self, msg: str):
        try:
            self.find_btn.setEnabled(True)
        except RuntimeError:
            return
        self._say(msg.splitlines()[0][:300])

    def test(self):
        server = self._server_text()
        if not server:
            self._say("Type or find a server first.")
            return
        self._say(f"Asking {server}…")
        job = Job(lambda progress=None, cancel=None: len(mpcfill.sources(server)),
                  label="Testing the MPCFill server")
        job.signals.finished.connect(self._tested)
        job.signals.failed.connect(self._test_failed)
        self._jobs.append(start(job))

    def _tested(self, n: int):
        self._say(f"✓ The server answers: {n} source(s) (drives).")

    def _test_failed(self, msg: str):
        self._say(f"✗ That isn't an MPCFill server: {msg.splitlines()[0][:200]}")

    def accept(self):
        self.prefs["mpcfill_server"] = self._server_text()
        self.prefs["mpcfill_images"] = mpcfill.clean_url(self.images.text())
        prefs_file.save(self.prefs)
        super().accept()

    def done(self, r):
        forget(self._jobs)
        super().done(r)
