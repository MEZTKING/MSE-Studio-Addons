"""Card prices: what the real cards of your deck, or a decklist, cost at
TCGplayer and Cardmarket – the cheapest printing of each, totals per store
and the cheapest mix – in your currency, with links to buy them.

Network: Scryfall (prices, unless the Card database add-on has them) and
frankfurter.app (exchange rates), only when you press Get prices."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from mse_studio.core import decklists as dl
from mse_studio.gui import icons, theme
from mse_studio.gui.common import error, forget, Job, start
from mse_studio.gui.nav import page_header

from . import prices as pr

COLS = ["Copies", "Card", "TCGplayer", "Cardmarket", "Cheapest at"]
DECK = "__deck__"


class CardPricesPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._jobs: list = []
        self.prices: list[pr.Price] = []
        self.fx: dict = {"USD": 1.0}
        lay = QVBoxLayout(self)
        lay.addWidget(page_header(
            "Card prices", "What the real cards of your deck – or a decklist – cost at TCGplayer "
                           "and Cardmarket: the cheapest printing of each, totals per store and "
                           "the cheapest mix, in your currency."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Cards"))
        self.which = QComboBox()
        self.which.setMinimumWidth(260)
        row.addWidget(self.which)
        row.addWidget(QLabel("Currency"))
        self.currency = QComboBox()
        for code in pr.CURRENCIES:
            self.currency.addItem(code, code)
        self.currency.currentIndexChanged.connect(self._fill)
        row.addWidget(self.currency)
        self.cheapest = QCheckBox("Cheapest printing")
        self.cheapest.setChecked(True)
        self.cheapest.setToolTip("Every printing of each card is compared (slower without the "
                                 "Card database add-on with every printing); off: the usual "
                                 "printing")
        row.addWidget(self.cheapest)
        self.foil = QCheckBox("Foil")
        row.addWidget(self.foil)
        self.skip_basics = QCheckBox("Leave out basic lands")
        self.skip_basics.setChecked(True)
        row.addWidget(self.skip_basics)
        b = QPushButton("Get prices")
        b.setProperty("kind", "primary")
        icons.set_icon(b, "payments")
        b.clicked.connect(self.get_prices)
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        lay.addWidget(self.summary)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.cellDoubleClicked.connect(self._open_store)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        b = QPushButton("Buy at TCGplayer…")
        b.setToolTip("Opens TCGplayer's Mass Entry with every card filled in")
        b.clicked.connect(self.tcgplayer)
        row.addWidget(b)
        b = QPushButton("Copy for Cardmarket")
        b.setToolTip("Copies \"1 Sol Ring\" lines: paste them into a Cardmarket Wants list "
                     "(Wants → Create list → paste)")
        b.clicked.connect(self.cardmarket)
        row.addWidget(b)
        b = QPushButton("Save as CSV…")
        b.clicked.connect(self.save_csv)
        row.addWidget(b)
        row.addStretch(1)
        note = QLabel("Prices: Scryfall (TCGplayer market, Cardmarket trend; once a day). "
                      "Double-click a card to open it at a store.")
        note.setObjectName("Hint")
        row.addWidget(note)
        lay.addLayout(row)

    # ------------------------------------------------------------ MSE Studio calls these
    def load(self):
        self._fill_sources()

    def refresh(self):
        self._fill_sources()

    def shutdown(self):
        forget(self._jobs)                # the page is going: nothing may call it back

    # ------------------------------------------------------------ which cards
    def _fill_sources(self):
        keep = self.which.currentData()
        self.which.blockSignals(True)
        self.which.clear()
        p = self.main.project
        if p is not None:
            self.which.addItem(f"Real cards in {p.name}", DECK)
        for d in dl.saved():
            self.which.addItem(f"Decklist: {d.name}", d.id)
        i = self.which.findData(keep)
        self.which.setCurrentIndex(max(0, i))
        self.which.blockSignals(False)

    def _cards(self) -> list[tuple[str, int]]:
        key = self.which.currentData()
        if key == DECK and self.main.project is not None:
            entries = dl.project_real(self.main.project)
        else:
            d = next((x for x in dl.saved() if x.id == key), None)
            entries = [e for e in d.entries if e.section != "side"] if d else []
        out = []
        for e in entries:
            if self.skip_basics.isChecked() and \
                    "basic land" in ((e.card or {}).get("type_line", "").lower()):
                continue
            out.append((e.display_name, e.count))
        return out

    # ------------------------------------------------------------ prices
    def get_prices(self):
        cards = self._cards()
        if not cards:
            self.summary.setText("No real cards there yet – add some from Decklists, the Mana "
                                 "base or the Card database.")
            return
        cheapest, foil = self.cheapest.isChecked(), self.foil.isChecked()

        def work(progress=None, cancel=None):
            found = pr.look_up(cards, cheapest, foil, progress, cancel)
            return found, pr.rates()

        self.summary.setText("Getting prices…")
        job = Job(work, label="Getting card prices")
        job.signals.progress.connect(lambda d, t, m: self.summary.setText(m))
        job.signals.finished.connect(self._got)
        job.signals.failed.connect(lambda m: error(self, "Card prices", m.splitlines()[0]))
        self._jobs.append(start(job))

    def _got(self, res):
        try:
            self.prices, self.fx = res
            self._fill()
        except RuntimeError:
            pass

    def _fill(self, *_):
        cur = self.currency.currentData() or "USD"
        t = pr.totals(self.prices, cur, self.fx)
        th = theme.current()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.prices))
        for r, p in enumerate(self.prices):
            u = pr.convert(p.usd, "USD", cur, self.fx)
            e = pr.convert(p.eur, "EUR", cur, self.fx)
            best = t.cheapest_store.get(p.name)
            items = [_num_item(p.count, str(p.count)), QTableWidgetItem(p.name),
                     _num_item(u, pr.money(u, cur), p.usd_set),
                     _num_item(e, pr.money(e, cur), p.eur_set),
                     QTableWidgetItem(pr.STORES.get(best, "not found"))]
            items[1].setData(Qt.UserRole, r)
            if best:
                col = 2 if best == "tcgplayer" else 3
                items[col].setForeground(QColor(th.success))
                f = items[col].font()
                f.setBold(True)
                items[col].setFont(f)
            if not p.found:
                items[1].setForeground(QColor(th.error))
            for c, it in enumerate(items):
                self.table.setItem(r, c, it)
        self.table.setSortingEnabled(True)
        n = sum(p.count for p in self.prices)
        miss = f" · {t.missing_both} card(s) without a price" if t.missing_both else ""
        compare = ""
        if t.both:
            diff = t.both_tcgplayer - t.both_cardmarket
            cheaper = "Cardmarket" if diff > 0 else "TCGplayer"
            compare = (f"<br>The {t.both} card(s) both stores have: TCGplayer "
                       f"{pr.money(t.both_tcgplayer, cur)}, Cardmarket "
                       f"{pr.money(t.both_cardmarket, cur)}"
                       + (f" – {cheaper} is <b>{pr.money(abs(diff), cur)}</b> cheaper"
                          if abs(diff) >= 0.005 else " – the same"))
        self.summary.setText(
            f"<b>{n} card(s)</b>{miss}<br>"
            f"All at TCGplayer: <b>{pr.money(t.tcgplayer, cur)}</b>"
            + (f" ({t.missing_tcg} without a price)" if t.missing_tcg else "")
            + f" · All at Cardmarket: <b>{pr.money(t.cardmarket, cur)}</b>"
            + (f" ({t.missing_cm} without a price)" if t.missing_cm else "")
            + f" · Cheapest mix (each card where it costs least): "
              f"<b>{pr.money(t.cheapest, cur)}</b>"
            + compare
            + ("" if cur in ("USD", "EUR") else " · rates: European Central Bank")
            + ("" if {"EUR", cur} <= set(self.fx) else
               "<br>Couldn't get exchange rates (no internet?), so prices in another "
               "currency are missing – try again, or pick US dollars or euros."))

    def _open_store(self, row: int, col: int):
        it = self.table.item(row, 1)
        if it is None:
            return
        p = self.prices[it.data(Qt.UserRole)]
        url = p.cardmarket if col == 3 else p.tcgplayer or p.cardmarket
        if url:
            QDesktopServices.openUrl(QUrl(url))

    # ------------------------------------------------------------ buying
    def tcgplayer(self):
        if self.prices:
            QDesktopServices.openUrl(QUrl(pr.tcgplayer_mass_entry(self.prices)))

    def cardmarket(self):
        if self.prices:
            QApplication.clipboard().setText(pr.wants_list(self.prices))
            self.main.statusBar().showMessage(
                f"Copied {len(self.prices)} card(s) – paste them into a Cardmarket Wants list",
                8000)

    def save_csv(self):
        if not self.prices:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save prices", "card prices.csv", "CSV (*.csv)")
        if path:
            Path(path).write_text(pr.csv_text(self.prices, self.currency.currentData(), self.fx),
                                  encoding="utf-8")


class _NumItem(QTableWidgetItem):
    """Sorts by the number, shows the text."""

    def __lt__(self, other):
        a, b = self.data(Qt.UserRole + 1), other.data(Qt.UserRole + 1)
        a = a if a is not None else float("inf")
        b = b if b is not None else float("inf")
        return a < b


def _num_item(value, text: str, tip: str = "") -> QTableWidgetItem:
    it = _NumItem(text)
    it.setData(Qt.UserRole + 1, value)
    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if tip:
        it.setToolTip(tip)
    return it
