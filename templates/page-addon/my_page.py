"""A page add-on for MSE Studio: a QWidget that gets the main window.

- section: Create, Produce, Review or Manage (where it goes in the side rail)
- icon:    an icon name from MSE Studio's resources/icons (without .svg)
- Your other files: "from . import helpers" (or "import helpers").
- Everything in MSE Studio can be used: main.project (the open deck),
  main.settings, mse_studio.core.*, mse_studio.pipeline.*, and PySide6,
  Pillow, NumPy and OpenCV, which come with MSE Studio.
"""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget

from mse_studio.gui.nav import page_header      # the title every page has


class MyPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        lay = QVBoxLayout(self)
        lay.addWidget(page_header("My page", "What this page is for."))
        self.summary = QLabel()
        lay.addWidget(self.summary)
        self.cards = QListWidget()
        lay.addWidget(self.cards, 1)
        b = QPushButton("Open the first card")
        b.clicked.connect(self.open_first)
        lay.addWidget(b)

    # --- MSE Studio calls these (all optional) -------------------------
    def load(self):
        """A deck was opened, or Settings were changed."""
        self.refresh()

    def refresh(self):
        """The page was opened."""
        p = self.main.project
        self.cards.clear()
        if p is None:
            self.summary.setText("No deck open.")
            return
        self.summary.setText(f"{p.name}: {len(p.set.cards)} cards")
        for card in p.set.cards:
            self.cards.addItem(f"{card.name}  —  {card.text('casting_cost')}")

    def shutdown(self):
        """The deck is closing or MSE Studio is quitting: save what you need to."""

    # --------------------------------------------------------------------
    def open_first(self):
        if self.main.project and self.main.project.set.cards:
            self.main.tabs.setCurrentWidget(self.main.cards_tab)
            self.main.cards_tab.select_row(0)
