"""Deck notes: a notes page for each deck, saved as notes.md in the deck's
folder (so it travels with the deck and its backups)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

FILE = "notes.md"
START = "# {name}\n\n## Ideas\n- \n\n## To do\n- [ ] \n\n## Cards to fix\n- \n"


class NotesPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.path: Optional[Path] = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(800)
        self._timer.timeout.connect(self.save)
        lay = QVBoxLayout(self)
        # MSE Studio's own page title, so the page looks like the others
        from mse_studio.gui.nav import page_header
        lay.addWidget(page_header("Deck notes", "Ideas, to-dos and anything else about this "
                                                f"deck. Saved by itself as {FILE} in the deck's "
                                                "folder."))
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("Write anything…")
        self.edit.textChanged.connect(self._changed)
        lay.addWidget(self.edit, 1)
        row = QHBoxLayout()
        self.info = QLabel()
        self.info.setObjectName("Hint")
        row.addWidget(self.info, 1)
        b = QPushButton("Add a checklist of the cards")
        b.setToolTip("Adds every card of the deck as a \"- [ ] name\" line")
        b.clicked.connect(self.add_checklist)
        row.addWidget(b)
        b = QPushButton("Open folder")
        b.clicked.connect(self.open_folder)
        row.addWidget(b)
        lay.addLayout(row)

    # MSE Studio calls these
    def load(self):
        """A deck was opened."""
        self.save()
        p = self.main.project
        self.path = (Path(p.folder) / FILE) if p is not None else None
        text = ""
        if self.path is not None:
            try:
                text = self.path.read_text(encoding="utf-8")
            except OSError:
                text = START.format(name=p.name)
        self.edit.blockSignals(True)
        self.edit.setPlainText(text)
        self.edit.blockSignals(False)
        self._info()

    def refresh(self):
        self._info()

    def shutdown(self):
        self.save()

    # ------------------------------------------------------------------
    def _changed(self):
        self._timer.start()
        self.info.setText("Saving…")

    def _info(self):
        text = self.edit.toPlainText()
        done = text.count("- [x]") + text.count("- [X]")
        todo = text.count("- [ ]")
        parts = [f"{len(text.split())} words"]
        if done or todo:
            parts.append(f"{done} of {done + todo} ticked")
        if self.path is not None and self.path.exists():
            parts.append(f"saved in {self.path.name}")
        self.info.setText(" · ".join(parts))

    def save(self):
        self._timer.stop()
        if self.path is None:
            return
        text = self.edit.toPlainText()
        try:
            if self.path.exists() and self.path.read_text(encoding="utf-8") == text:
                return
            self.path.write_text(text, encoding="utf-8")
        except OSError as e:
            self.info.setText(f"Couldn't save: {e}")
            return
        self._info()

    def add_checklist(self):
        p = self.main.project
        if p is None:
            return
        have = self.edit.toPlainText()
        names = [c.name for c in p.set.cards if c.name and f"] {c.name}\n" not in have + "\n"]
        if not names:
            self.info.setText("Every card is in the list already")
            return
        block = "\n## Cards\n" + "".join(f"- [ ] {n}\n" for n in names)
        self.edit.moveCursor(self.edit.textCursor().MoveOperation.End)
        self.edit.insertPlainText(("" if have.endswith("\n") or not have else "\n") + block)

    def open_folder(self):
        p = self.main.project
        if p is None:
            return
        from mse_studio.pipeline.common import open_in_explorer
        open_in_explorer(Path(p.folder))
