"""Playtest page: goldfish opening hands and turns, and the odds of drawing
what the deck needs – for your deck or a decklist (Decklists → Playtest).

Until MSE Studio 0.25 this page came with the app (mse_studio.gui.playtest_tab)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QMenu,
                               QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter, QTabWidget,
                               QVBoxLayout, QWidget)

from mse_studio.core import decklists, deck_stats, markup
from mse_studio.gui import icons, theme, thumbs
from mse_studio.gui.common import Job, forget, start
from mse_studio.gui.nav import page_header
from mse_studio.gui.stats_view import BarChart, Panel

from . import game as playtest

RATIO = 744 / 1039          # card width / height
HAND_H = 300                # default card height in the hand (slider: 160–460)
FIELD_SCALE = 0.62          # battlefield / graveyard cards, relative to the hand


class CardList(QListWidget):
    """A zone of the game, drawn as card pictures."""

    def __init__(self, height: int, wrap: bool):
        super().__init__()
        self.wrap = wrap
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(wrap)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        if not wrap:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.set_height(height)

    def set_height(self, height: int):
        self.card_h = height
        # tapped cards turn sideways, so a square cell fits both
        self.setIconSize(QSize(height, height) if self.wrap else
                         QSize(round(height * RATIO), height))
        if self.wrap:
            self.setMinimumHeight(height + 16)
        else:
            self.setFixedHeight(height + 30)

    def cards(self) -> list[int]:
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]


class PlaytestPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.game: Optional[playtest.Game] = None
        self.rows: list[int] = []            # non-token cards (indices into the set)
        self._sig: tuple = ()
        self._pix: dict[tuple, QPixmap] = {}
        self._flags: dict[str, list[bool]] = {}
        self._matchers: dict = {}
        self._commander_name: Optional[str] = None
        self._just_bottomed = False
        self._card_list: list = []           # the deck's cards; real cards once per copy
        self._n_custom = 0                   # the first ones are the set's own cards
        self._jobs: list = []
        self._fetching = False
        self._export_ok: dict[int, Path] = {}    # rows whose export is up to date
        self._drawn: dict[int, Path] = {}        # rows MSE drew for the playtest
        self._drawing = False
        self._draw_again = False
        lay = QVBoxLayout(self)
        lay.addWidget(page_header(
            "Playtest", "Goldfish the deck: draw an opening hand, mulligan (London rule), play "
                        "turn by turn, and see the odds of drawing what you need. Card pictures "
                        "come from 1 Exported (cards that changed since are drawn by MSE first) and "
                        "Scryfall for real cards. Imported decklists can be played too."))

        row = QHBoxLayout()
        row.addWidget(QLabel("Deck"))
        self.source = QComboBox()
        self.source.setMinimumWidth(160)
        self.source.setToolTip("This deck (with any real cards added to it), or a real deck "
                               "imported on the Decklists page")
        self.source.activated.connect(lambda *_: self._source_changed())
        row.addWidget(self.source)
        row.addWidget(QLabel("Commander"))
        self.commander = QComboBox()
        self.commander.setMinimumWidth(180)
        self.commander.setToolTip("Starts in the command zone, so it's never drawn")
        self.commander.activated.connect(self._commander_changed)
        row.addWidget(self.commander)
        self.on_play = QComboBox()
        self.on_play.addItems(["On the play", "On the draw"])
        self.on_play.setToolTip("On the play you skip the draw on your first turn")
        self.on_play.currentIndexChanged.connect(self._update_odds)
        row.addWidget(self.on_play)
        self.free_mull = QCheckBox("First mulligan free")
        self.free_mull.setChecked(True)
        self.free_mull.setToolTip("Multiplayer Commander: the first mulligan doesn't make you "
                                  "put a card on the bottom")
        self.free_mull.toggled.connect(self._free_mull_changed)
        row.addWidget(self.free_mull)
        row.addSpacing(12)
        self.new_btn = self._button(row, "New game", "restart_alt", self.new_game,
                                    "Shuffle and draw seven")
        self.mull_btn = self._button(row, "Mulligan", "refresh", self.mulligan,
                                     "Shuffle the hand back and draw seven (London rule)")
        self.draw_btn = self._button(row, "Draw", "add", self.draw, "Draw a card")
        self.turn_btn = self._button(row, "Next turn", "play_arrow", self.next_turn,
                                     "Start the next turn (and draw for it)")
        self.turn_btn.setProperty("kind", "primary")
        row.addSpacing(12)
        self.life = self._counter(row, "Life", 40, "Your life total (Commander starts at 40)")
        self.poison = self._counter(row, "Poison", 0, "Poison counters (10 and you lose)")
        row.addStretch(1)
        row.addWidget(QLabel("Card size"))
        self.size = QSlider(Qt.Horizontal)
        self.size.setRange(160, 460)
        self.size.setValue(HAND_H)
        self.size.setFixedWidth(150)
        self.size.valueChanged.connect(self._resize_cards)
        row.addWidget(self.size)
        lay.addLayout(row)
        self.status = QLabel()
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self.views = QTabWidget()
        lay.addWidget(self.views, 1)
        game = QWidget()
        g = QVBoxLayout(game)
        g.setContentsMargins(6, 6, 6, 6)
        self.hand_label = QLabel("Hand")
        g.addWidget(self.hand_label)
        self.hand = CardList(HAND_H, wrap=False)
        self.hand.itemEntered.connect(self._hover)
        self.hand.setToolTip("Double-click a card to play it · right-click for more")
        self.hand.itemClicked.connect(self._hand_clicked)
        self.hand.itemDoubleClicked.connect(self._hand_double)
        self.hand.customContextMenuRequested.connect(self._hand_menu)
        g.addWidget(self.hand)
        zones = QSplitter(Qt.Horizontal)
        zones.setChildrenCollapsible(False)
        fh = round(HAND_H * FIELD_SCALE)
        self.field = CardList(fh, wrap=True)
        self.field.setToolTip("Double-click to tap / untap · right-click for more")
        self.field.itemDoubleClicked.connect(
            lambda it: self._move(self.game.tap, it.data(Qt.UserRole)))
        self.field.customContextMenuRequested.connect(self._field_menu)
        self.field.itemEntered.connect(self._hover)
        self.grave = CardList(fh, wrap=True)
        self.grave.itemEntered.connect(self._hover)
        self.grave.setToolTip("Double-click to return a card to your hand")
        self.grave.itemDoubleClicked.connect(
            lambda it: self._move(self.game.to_hand, it.data(Qt.UserRole)))
        self.field_label = QLabel("Battlefield")
        self.grave_label = QLabel("Graveyard")
        zones.addWidget(self._zone(self.field_label, self.field))
        zones.addWidget(self._zone(self.grave_label, self.grave))
        zones.setSizes([700, 260])
        g.addWidget(zones, 1)
        # the card under the mouse, big
        side = QSplitter(Qt.Horizontal)
        side.setChildrenCollapsible(False)
        side.addWidget(game)
        prev = QWidget()
        pv = QVBoxLayout(prev)
        pv.setContentsMargins(6, 6, 6, 6)
        self.preview = QLabel("Point at a card to see it here")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setObjectName("Hint")
        self.preview.setWordWrap(True)
        self.preview.setMinimumWidth(220)
        pv.addWidget(self.preview, 1)
        side.addWidget(prev)
        side.setStretchFactor(0, 1)
        side.setStretchFactor(1, 0)
        side.setSizes([1300, 380])
        self.views.addTab(side, icons.icon("playing_cards"), "Game")

        # ---- odds + opening hand simulation
        tools = QWidget()
        h = QHBoxLayout(tools)
        h.setContentsMargins(6, 6, 6, 6)
        body = QWidget()
        b = QVBoxLayout(body)
        b.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.odds_what = QComboBox()
        self.odds_what.currentIndexChanged.connect(self._update_odds)
        form.addRow("Looking for", self.odds_what)
        nums = QHBoxLayout()
        self.odds_k = QSpinBox()
        self.odds_k.setRange(1, 20)
        self.odds_k.setValue(3)
        self.odds_k.setPrefix("at least ")
        self.odds_k.valueChanged.connect(self._update_odds)
        nums.addWidget(self.odds_k)
        self.odds_turn = QSpinBox()
        self.odds_turn.setRange(0, 20)
        self.odds_turn.setValue(3)
        self.odds_turn.setPrefix("by turn ")
        self.odds_turn.setSpecialValueText("in the opening hand")
        self.odds_turn.valueChanged.connect(self._update_odds)
        nums.addWidget(self.odds_turn)
        nums.addStretch(1)
        form.addRow("", nums)
        b.addLayout(form)
        self.odds_result = QLabel("–")
        f = QFont(self.odds_result.font())
        f.setPointSizeF(f.pointSizeF() * 2)
        f.setBold(True)
        self.odds_result.setFont(f)
        b.addWidget(self.odds_result)
        self.odds_chart = BarChart(unit=" %")
        b.addWidget(self.odds_chart, 1)
        self.odds_panel = Panel("Odds", body)
        h.addWidget(self.odds_panel, 1)

        body = QWidget()
        b = QVBoxLayout(body)
        b.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.sim_what = QComboBox()
        self.sim_what.currentIndexChanged.connect(self._update_sim)
        form.addRow("Count", self.sim_what)
        b.addLayout(form)
        self.sim_chart = BarChart(unit=" % of hands")
        b.addWidget(self.sim_chart, 1)
        self.sim_panel = Panel("Opening hands · 10,000 shuffles", body)
        h.addWidget(self.sim_panel, 1)
        scroll = QScrollArea()             # keeps the page from forcing a tall window
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(tools)
        self.views.addTab(scroll, icons.icon("casino"), "Odds && opening hands")
        thumbs.cache().ready.connect(self._thumb_ready)

    # ------------------------------------------------------------- helpers
    def _button(self, row: QHBoxLayout, text: str, icon: str, slot, tip: str) -> QPushButton:
        b = QPushButton(text)
        icons.set_icon(b, icon)
        b.setToolTip(tip)
        b.clicked.connect(slot)
        row.addWidget(b)
        return b

    @staticmethod
    def _zone(label: QLabel, lst: QWidget) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(label)
        v.addWidget(lst, 1)
        return w

    def _cards(self):
        return self._card_list

    def _build_cards(self):
        """This deck (its cards, then real cards once per copy) or a decklist."""
        p = self.main.project
        src = self.source.currentData() or ""
        dl = next((d for d in decklists.saved() if d.id == src), None) if src else None
        if dl is not None:
            self._n_custom = 0
            self._card_list = [rc for e in dl.deck for rc in [decklists.RealCard(e)] * e.count]
            self._real_commanders = {decklists.RealCard(e).name for e in dl.commanders}
        else:
            self._n_custom = len(p.set.cards)
            self._card_list = list(p.set.cards) + decklists.real_cards(p)
            self._real_commanders = {decklists.RealCard(e).name
                                     for e in decklists.project_real(p) if e.section == "commander"}

    def _fill_sources(self):
        keep = self.source.currentData() or ""
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItem("This deck", "")
        for d in decklists.saved():
            self.source.addItem(f"{d.name} ({d.size})", d.id)
        self.source.setCurrentIndex(max(0, self.source.findData(keep)))
        self.source.blockSignals(False)

    def _source_changed(self):
        self._commander_name = None
        self.refresh()

    def shutdown(self):
        """The page is going (pages rebuilt, the deck closed): its jobs stop and
        don't call it back."""
        forget(self._jobs)

    def _bottomed_done(self):
        self._just_bottomed = False

    def play_decklist(self, deck_id: str):
        """Show the page with an imported decklist."""
        self._fill_sources()
        self.source.setCurrentIndex(max(0, self.source.findData(deck_id)))
        self._commander_name = None
        self.refresh()

    def population(self) -> list[int]:
        cmd = self._commander_row()
        return [i for i in self.rows if i != cmd]

    def _commander_row(self) -> Optional[int]:
        d = self.commander.currentData()
        return d if isinstance(d, int) and d >= 0 else None

    # ------------------------------------------------------------- refresh
    def refresh(self):
        """Called when the page is shown: picks up changes to the deck."""
        self._fill_sources()
        self._build_cards()
        cards = self._cards()
        from mse_studio.pipeline import order
        backs = order.back_of(self.main.project) if self._n_custom else {}
        self.rows = [i for i, c in enumerate(cards)      # back cards travel with their front
                     if not deck_stats.is_token(c) and i not in backs]
        self._pix.clear()
        self._flags.clear()
        self.commander.blockSignals(True)
        self.commander.clear()
        self.commander.addItem("No commander", -1)
        named = set()
        for i in self.rows:
            if deck_stats.can_be_commander(cards[i]) and cards[i].name not in named:
                named.add(cards[i].name)
                self.commander.addItem(cards[i].name or "(untitled)", i)
        if self._commander_name:
            pick = self.commander.findText(self._commander_name)
        elif self._real_commanders and not any(
                deck_stats.can_be_commander(c) for c in cards[:self._n_custom]):
            pick = next((n for n in range(1, self.commander.count())
                         if self.commander.itemText(n) in self._real_commanders), 0)
        else:
            pick = 1 if self.commander.count() > 1 else 0
        self.commander.setCurrentIndex(max(0, pick))
        self.commander.blockSignals(False)
        self._matchers = dict(playtest.matchers(self.main.project))
        names = sorted({cards[i].name for i in self.rows if cards[i].name})
        for n in names:
            self._matchers[f"Card: {n}"] = (lambda n: lambda c: c.name == n)(n)
        self._fill_combo(self.odds_what, "Lands")
        self._fill_combo(self.sim_what, "Lands")
        self._fetch_pictures()
        self._draw_cards()
        sig = (self.source.currentData(),) + tuple(cards[i].name for i in self.rows) + \
            (self._commander_row(),)
        if sig != self._sig or self.game is None:
            self._sig = sig
            self.new_game()
        else:
            self._show()
        self._update_odds()
        self._update_sim()

    def _fill_combo(self, combo: QComboBox, default: str):
        keep = combo.currentData() or default
        combo.blockSignals(True)
        combo.clear()
        pop = self.population()
        cards = self._cards()
        for key in self._matchers:
            n = sum(self._flags_for(key, pop, cards))
            if n or key in ("Lands", "Creatures"):
                combo.addItem(f"{key}  ({n})", key)
        combo.setCurrentIndex(max(0, combo.findData(keep)))
        combo.blockSignals(False)

    def _flags_for(self, key: str, pop=None, cards=None) -> list[bool]:
        if key not in self._flags:
            pop = pop if pop is not None else self.population()
            cards = cards if cards is not None else self._cards()
            fn = self._matchers.get(key)
            self._flags[key] = [bool(fn and fn(cards[i])) for i in pop]
        return self._flags[key]

    # ------------------------------------------------------------- the game
    def new_game(self):
        self.game = playtest.Game(self.population(), free_mulligan=self.free_mull.isChecked())
        for sb, v in ((self.life, 40), (self.poison, 0)):
            sb.blockSignals(True)
            sb.setValue(v)
            sb.blockSignals(False)
        self._counters_changed()
        self._show()

    def mulligan(self):
        if self.game and self.game.turn == 0:
            self.game.mulligan()
            self._show()

    def draw(self):
        if self.game:
            self.game.draw(1)
            self._show()

    def next_turn(self):
        if self.game and not self.game.to_bottom:
            self.game.next_turn(self.on_play.currentIndex() == 0)
            self._show()

    def _commander_changed(self, _i: int):
        self._commander_name = self.commander.currentText() if self._commander_row() is not None \
            else ""
        self._flags.clear()
        self._sig = self._sig[:-1] + (self._commander_row(),)
        self._fill_combo(self.odds_what, "Lands")
        self._fill_combo(self.sim_what, "Lands")
        self.new_game()
        self._update_odds()
        self._update_sim()

    def _free_mull_changed(self, on: bool):
        if self.game:
            self.game.free_mulligan = on

    def _move(self, fn, card: int):
        if self.game:
            fn(card)
            self._show()

    def _hand_clicked(self, it: QListWidgetItem):
        g = self.game
        if g and g.to_bottom > 0:
            g.bottom(it.data(Qt.UserRole))
            self._just_bottomed = True
            QTimer.singleShot(QApplication.doubleClickInterval(), self, self._bottomed_done)
            self._show()

    def _hand_double(self, it: QListWidgetItem):
        if self.game and not self.game.to_bottom and not self._just_bottomed:
            self._move(self.game.play, it.data(Qt.UserRole))

    def _hand_menu(self, pos):
        it = self.hand.itemAt(pos)
        if not it or not self.game:
            return
        card, g = it.data(Qt.UserRole), self.game
        m = QMenu(self)
        if g.to_bottom:
            m.addAction(f"Put on the bottom ({g.to_bottom} to go)",
                        lambda: self._hand_clicked(it))
        else:
            m.addAction(icons.icon("play_arrow"), "Play", lambda: self._move(g.play, card))
            m.addAction("Discard", lambda: self._move(g.discard, card))
            m.addSeparator()
            m.addAction(icons.icon("arrow_upward"), "Put on top of the library",
                        lambda: self._move(g.to_top, card))
            m.addAction(icons.icon("arrow_downward"), "Put on the bottom of the library",
                        lambda: self._move(g.to_library_bottom, card))
        m.exec(self.hand.viewport().mapToGlobal(pos))

    def _counter(self, row, label: str, value: int, tip: str) -> QSpinBox:
        row.addWidget(QLabel(label))
        sb = QSpinBox()
        sb.setRange(-99, 999)
        sb.setValue(value)
        sb.setToolTip(tip)
        sb.valueChanged.connect(self._counters_changed)
        row.addWidget(sb)
        return sb

    def _counters_changed(self, *_):
        if self.game:
            self.game.life, self.game.poison = self.life.value(), self.poison.value()
            t = theme.current()
            self.poison.setStyleSheet(f"color: {t.error};" if self.game.poison >= 10 else "")
            self.life.setStyleSheet(f"color: {t.error};" if self.game.life <= 0 else "")

    def _resize_cards(self, h: int):
        self.hand.set_height(h)
        fh = round(h * FIELD_SCALE)
        self.field.set_height(fh)
        self.grave.set_height(fh)
        self._show()

    def _hover(self, it: QListWidgetItem):
        i = it.data(Qt.UserRole)
        if i is None:
            return
        h = max(200, min(self.preview.height() - 10,
                         round((self.preview.width() - 10) / RATIO)))
        self.preview.setPixmap(self.card_pixmap(i, h))

    def _field_menu(self, pos):
        it = self.field.itemAt(pos)
        if not it or not self.game:
            return
        card, g = it.data(Qt.UserRole), self.game
        m = QMenu(self)
        m.addAction("Untap" if card in g.tapped else "Tap", lambda: self._move(g.tap, card))
        m.addAction(icons.icon("undo"), "Return to hand", lambda: self._move(g.to_hand, card))
        m.addAction(icons.icon("delete"), "To the graveyard", lambda: self._move(g.discard, card))
        m.exec(self.field.viewport().mapToGlobal(pos))

    def _show(self):
        g = self.game
        if g is None:
            return
        cards = self._cards()
        for lst, zone in ((self.hand, g.hand), (self.field, g.battlefield),
                          (self.grave, g.graveyard)):
            lst.clear()
            for i in zone:
                c = cards[i]
                pm = self.card_pixmap(i, lst.card_h)
                if i in g.tapped and lst is self.field:
                    pm = pm.transformed(QTransform().rotate(90), Qt.SmoothTransformation)
                it = QListWidgetItem(QIcon(pm), "")
                it.setData(Qt.UserRole, i)
                it.setToolTip(f"{c.name}\n{c.type_line}")
                lst.addItem(it)
        lands = sum(1 for i in g.battlefield if "land" in deck_stats.card_types(cards[i]))
        mana = sum(1 for i in g.battlefield if deck_stats.produces(cards[i]))
        self.hand_label.setText(f"Hand ({len(g.hand)})")
        self.field_label.setText(f"Battlefield ({len(g.battlefield)} · {lands} land"
                                 f"{'' if lands == 1 else 's'}, {mana} mana source"
                                 f"{'' if mana == 1 else 's'})")
        self.grave_label.setText(f"Graveyard ({len(g.graveyard)})")
        turn = "Opening hand" if g.turn == 0 else f"Turn {g.turn}"
        msg = [turn, f"{len(g.library)} in library"]
        if g.mulligans:
            msg.append(f"{g.mulligans} mulligan{'' if g.mulligans == 1 else 's'}")
        text = " · ".join(msg)
        if g.to_bottom:
            text += (f"  —  click {g.to_bottom} card{'' if g.to_bottom == 1 else 's'} in your "
                     f"hand to put on the bottom of the library")
        elif g.turn == 0:
            text += "  —  keep it with Next turn, or Mulligan"
        self.status.setText(text)
        self.mull_btn.setEnabled(g.turn == 0 and not g.to_bottom and len(self.population()) >= 7)
        self.draw_btn.setEnabled(bool(g.library) and not g.to_bottom)
        self.turn_btn.setEnabled(not g.to_bottom)
        self.turn_btn.setText("Keep" if g.turn == 0 else "Next turn")

    # ------------------------------------------------------------- pictures
    def _fetch_pictures(self):
        """Download the pictures of real cards that aren't cached yet."""
        data = [c.data for c in self._card_list[self._n_custom:] if c.data.get("image")]
        if self._fetching or not data:
            return
        missing = [d for d in data if not decklists.image_path(d).exists()]
        if not missing:
            return
        self._fetching = True
        job = Job(decklists.fetch_images, missing, label="Card pictures for the playtest")
        job.signals.progress.connect(self._pictures_progress)
        job.signals.finished.connect(self._pictures_done)
        job.signals.failed.connect(self._pictures_failed)
        self._jobs.append(start(job))

    def _pictures_progress(self, *_):
        self._pictures_arrived()

    def _pictures_done(self, *_):
        self._pictures_arrived(done=True)

    def _pictures_failed(self, *_):
        self._fetching = False

    def _pictures_arrived(self, done: bool = False):
        if done:
            self._fetching = False
        for k in [k for k in self._pix if k[0] >= self._n_custom]:
            del self._pix[k]
        try:
            if self.isVisible() and self.game is not None:
                self._show()
        except RuntimeError:            # the page is gone
            return

    def _draw_cards(self):
        """Your cards as they really look: the export when it's up to date,
        otherwise MSE draws them in the background (shown as text meanwhile)."""
        from mse_studio.pipeline import card_pictures as cp
        from mse_studio.pipeline import stages
        p = self.main.project
        if p is None or not self._n_custom:
            return
        if self._drawing:
            self._draw_again = True
            return
        try:
            st = stages.status(p)["exported"]
        except OSError:
            st = []
        self._export_ok = {i: Path(s.path) for i, s in enumerate(st)
                           if s.state == "ok" and s.path is not None and i < self._n_custom}
        shown = set(self.game.hand + self.game.battlefield + self.game.graveyard) \
            if self.game is not None else set()
        order = sorted((r for r in self.rows if r < self._n_custom and r not in self._export_ok),
                       key=lambda r: (r not in shown, r))
        if not order:
            return
        renderer = self.main.previewer("playtest") if self.main.settings.mse_path else None
        results: dict[int, Path] = {}
        self._draw_results = results

        def work(progress=None, cancel=None):
            for k, row in enumerate(order):
                if cancel is not None and cancel.cancelled:
                    break
                try:
                    path, text, files = cp.request(p, row)
                except Exception:  # noqa: BLE001 - shown as text
                    continue
                if not path.exists():
                    if renderer is None or not cp.draw(renderer, [(row, path, text, files)]):
                        continue
                results[row] = path
                progress(k + 1, len(order), "Drawing cards for the playtest")
            return results

        self._drawing = True
        job = Job(work, label="Drawing cards for the playtest")
        job.signals.progress.connect(self._drawn_some)
        job.signals.finished.connect(self._drawing_done)
        job.signals.failed.connect(self._drawing_done)
        self._jobs.append(start(job))

    def _drawn_some(self, *_):
        try:
            new = {r: pth for r, pth in dict(self._draw_results).items()
                   if self._drawn.get(r) != pth}
            if not new:
                return
            self._drawn.update(new)
            for k in [k for k in self._pix if k[0] in new]:
                del self._pix[k]
            if self.isVisible() and self.game is not None:
                self._show()
        except RuntimeError:
            return

    def _drawing_done(self, *_):
        try:
            self._drawing = False
            self._drawn_some()
            if self._draw_again:
                self._draw_again = False
                self._draw_cards()
        except RuntimeError:
            return

    def card_pixmap(self, row: int, h: int) -> QPixmap:
        key = (row, h)
        if key in self._pix:
            return self._pix[key]
        pm = None
        if row >= self._n_custom:              # a real card: its Scryfall picture
            data = self._card_list[row].data
            path = decklists.image_path(data) if data else None
            path = path if path is not None and path.exists() else None
            if path is None:
                pm, _ = self._text_card(row, h)
                return pm                      # the picture may still come
        else:               # the up-to-date export, or MSE's drawing of the card as it is now
            path = self._export_ok.get(row) or self._drawn.get(row)
            if path is not None and not path.exists():
                path = None
        if path is not None:
            img = QPixmap(str(path))
            if not img.isNull():
                pm = img.scaledToHeight(h, Qt.SmoothTransformation)
        if pm is None:
            pm, final = self._text_card(row, h)
            if not final:
                return pm          # art thumbnail still loading – don't keep this one
        self._pix[key] = pm
        return pm

    def _text_card(self, row: int, h: int) -> tuple[QPixmap, bool]:
        """A plain card face for cards that aren't exported yet."""
        t = theme.current()
        c = self._cards()[row]
        w = round(h * RATIO)
        pm = QPixmap(w, h)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(t.outline))
        p.setBrush(QColor(t.surface_high))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 8, 8)
        pad = max(4, h // 30)
        f = QFont(p.font())
        f.setPixelSize(max(9, h // 16))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(t.on_surface))
        line = f.pixelSize() + 4
        cost = markup.untag(c.raw("casting_cost"))
        p.drawText(QRectF(pad, pad, w - 2 * pad, line), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(c.name or "(untitled)", Qt.ElideRight,
                                              w - 2 * pad - p.fontMetrics().horizontalAdvance(
                                                  cost) - 4))
        p.drawText(QRectF(pad, pad, w - 2 * pad, line), Qt.AlignRight | Qt.AlignVCenter, cost)
        art = QRectF(pad, pad + line + 2, w - 2 * pad, h * 0.38)
        final = True
        s = self.main.project.set
        thumb = None
        if row < self._n_custom and c.image and s.has_file(c.image):
            thumb = thumbs.cache().get(f"{self.main.project.set_path}:{c.image}", c.image,
                                       lambda n=c.image, s=s: s.read_file(n))
            final = thumb is not None
        if thumb is not None:
            src = thumb.rect()
            scale = max(art.width() / src.width(), art.height() / src.height())
            sw, sh = art.width() / scale, art.height() / scale
            p.drawPixmap(art, thumb, QRectF((src.width() - sw) / 2, (src.height() - sh) / 2,
                                            sw, sh))
        else:
            p.fillRect(art, QColor(t.surface_low))
        f.setBold(False)
        f.setPixelSize(max(8, h // 20))
        p.setFont(f)
        y = art.bottom() + 3
        p.drawText(QRectF(pad, y, w - 2 * pad, line), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(c.type_line, Qt.ElideRight, w - 2 * pad))
        y += line + 2
        f.setPixelSize(max(7, h // 24))
        p.setFont(f)
        p.setPen(QColor(t.on_surface_variant))
        rules = markup.rules_to_editor(c.raw("rule_text"))
        p.drawText(QRectF(pad, y, w - 2 * pad, h - y - pad - line),
                   Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, rules)
        pt = "/".join(x for x in (markup.untag(c.raw("power")), markup.untag(c.raw("toughness")))
                      if x)
        if pt:
            p.setPen(QColor(t.on_surface))
            p.drawText(QRectF(pad, h - pad - line, w - 2 * pad, line),
                       Qt.AlignRight | Qt.AlignVCenter, pt)
        p.end()
        return pm, final

    def _thumb_ready(self, _source_id: str):
        try:
            if self.isVisible() and self.game is not None:
                self._show()
        except RuntimeError:            # the page is gone
            return

    # ------------------------------------------------------------- odds
    def _update_odds(self, *_):
        key = self.odds_what.currentData()
        if not key:
            self.odds_result.setText("–")
            self.odds_chart.set_data([], [])
            return
        pop = len(self.population())
        hits = sum(self._flags_for(key))
        k, turn = self.odds_k.value(), self.odds_turn.value()
        on_play = self.on_play.currentIndex() == 0
        seen = playtest.cards_seen(turn, on_play) if turn else playtest.HAND
        chance = playtest.at_least(pop, hits, seen, k)
        self.odds_result.setText(f"{chance * 100:.1f} %")
        what = key.split(": ", 1)[-1]
        when = "in the opening hand" if not turn else f"by turn {turn}"
        self.odds_panel.set_note(
            f"Chance of at least {k} × {what} {when} – {hits} of the {pop} cards in the "
            f"library match, and you'll have seen {seen} cards "
            f"({'on the play' if on_play else 'on the draw'}, no mulligans).")
        turns = max(10, turn)
        vals = playtest.by_turn(pop, hits, k, turns, on_play)
        self.odds_chart.set_data([f"T{t}" for t in range(1, turns + 1)],
                                 [("Chance", [round(v * 100, 1) for v in vals])])

    def _update_sim(self, *_):
        key = self.sim_what.currentData()
        if not key:
            self.sim_chart.set_data([], [])
            self.sim_panel.set_note("")
            return
        flags = self._flags_for(key)
        trials = 10000
        r = playtest.simulate(flags, trials)
        if not any(r["counts"]):
            self.sim_chart.set_data([], [])
            self.sim_panel.set_note("The deck needs at least seven cards.")
            return
        pct = [round(c * 100 / trials, 1) for c in r["counts"]]
        self.sim_chart.set_data([str(i) for i in range(len(pct))], [("Hands", pct)])
        none = pct[0]
        note = (f"Average {r['average']:g} per opening hand · none in {none:g} % of hands")
        if key == "Lands":
            note += f" · 2–5 lands (an easy keep) in {r['keepable']:g} %"
        self.sim_panel.set_note(note + ".")
