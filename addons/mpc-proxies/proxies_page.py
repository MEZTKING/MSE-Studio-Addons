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

from PySide6.QtCore import QItemSelectionModel, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QSlider, QSplitter, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QTabWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from mse_studio.core import decklists as dl
from mse_studio.gui import icons, thumbs
from mse_studio.gui.common import Job, error, forget, start
from mse_studio.gui.nav import page_header

from . import gdrive, local
from . import proxies as px

BIG = 200                          # wider than this: the large thumbnails (MSE Studio 0.16)
GROUPS = [("free", "Free"), ("paid", "Paid – on Ko-fi"), ("mine", "Added by you"),
          ("pc", "On this PC")]
SORTS = [("deck", "Deck order"), ("name", "Name"), ("folder", "Folder (card type)"),
         ("count", "Copies")]


NO_TEXT = "__no_text__"            # the type filter's "no text at all on the picture"
NO_RULES = "__no_rules__"          # "no rules text on the picture"
REAL_HINT = ("<b>Add to my order</b>: real cards, straight into your deck – printed as they "
             "are, with the maker's credit. <b>Add to my deck to edit</b>: your own cards on the "
             "Cards page, with the card's text and its art – in this deck's own frame when it has "
             "one (right-click the deck → This deck's frame).")


def _real_pictures(main, entries):
    """The real cards' pictures (MSE Studio 0.25: main.real_pictures; before,
    the Order page did it)."""
    fn = getattr(main, "real_pictures", None) or main.order_tab.real_pictures
    fn(entries)


def _pages_changed(main):
    """The page that's open shows the change (the Order page before 0.25)."""
    fn = getattr(main, "refresh_shown_page", None)
    if fn is not None:
        fn()
    elif getattr(main, "order_tab", None) is not None:
        main.order_tab.refresh()


def _ask_delete(parent, text: str) -> bool:
    """MSE Studio 0.17's "Ask before deleting" (Settings) – else ask."""
    try:
        from mse_studio.gui.common import ask_delete
        return ask_delete(parent, text)
    except ImportError:
        return QMessageBox.question(parent, "Proxy decks", text) == QMessageBox.Yes


class TickDelegate(QStyledItemDelegate):
    """A card with a big tick box at its top-left; ticked cards get a frame."""
    BOX = 28

    def paint(self, qp, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        ticked = bool(opt.state & QStyle.State_Selected)
        opt.state &= ~QStyle.State_Selected            # no blue over the picture
        opt.state &= ~QStyle.State_HasFocus
        w = opt.widget
        style = w.style() if w is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, qp, w)
        try:
            from mse_studio.gui import theme
            accent = QColor(theme.current().primary)
        except Exception:  # noqa: BLE001
            accent = QColor("#5b8def")
        icon = style.subElementRect(QStyle.SE_ItemViewItemDecoration, opt, w)
        qp.save()
        qp.setRenderHint(QPainter.Antialiasing)
        if ticked:
            qp.setPen(QPen(accent, 3))
            qp.setBrush(Qt.NoBrush)
            qp.drawRoundedRect(QRectF(opt.rect).adjusted(2, 2, -2, -2), 8, 8)
        b = QRectF(icon.left() + 6, icon.top() + 6, self.BOX, self.BOX)
        qp.setPen(QPen(QColor(0, 0, 0, 160), 1.5))
        qp.setBrush(accent if ticked else QColor(255, 255, 255, 225))
        qp.drawRoundedRect(b, 6, 6)
        if ticked:
            path = QPainterPath()
            path.moveTo(b.left() + b.width() * 0.22, b.top() + b.height() * 0.52)
            path.lineTo(b.left() + b.width() * 0.43, b.top() + b.height() * 0.72)
            path.lineTo(b.left() + b.width() * 0.78, b.top() + b.height() * 0.30)
            qp.setPen(QPen(QColor("#ffffff"), 3.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            qp.setBrush(Qt.NoBrush)
            qp.drawPath(path)
        qp.restore()


class TickGrid(QListWidget):
    """Cards to tick: click (or Ctrl+click) a card to tick or untick it, drag
    across cards to tick several, Shift+click to tick everything up to it,
    Ctrl+A for all. Right-click doesn't change the ticks."""

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.MultiSelection)
        self.setItemDelegate(TickDelegate(self))
        self._anchor = -1

    def mousePressEvent(self, e):
        it = self.itemAt(e.position().toPoint())
        if e.button() == Qt.RightButton:
            if it is not None:
                self.setCurrentItem(it, QItemSelectionModel.NoUpdate)
            e.accept()
            return
        if it is not None and e.button() == Qt.LeftButton and \
                e.modifiers() & Qt.ShiftModifier and self._anchor >= 0:
            a, b = sorted((self._anchor, self.row(it)))
            sm = self.selectionModel()
            for r in range(a, b + 1):
                sm.select(self.model().index(r, 0), QItemSelectionModel.Select)
            e.accept()
            return
        super().mousePressEvent(e)
        if it is not None:
            self._anchor = self.row(it)


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
        self._importing: set = set()       # decks being imported
        self.types: dict = {}              # name → type line, from Scryfall
        self.texts: dict = {}              # name → has rules text, from Scryfall
        self.templates: list = []          # the maker's frame templates in the deck
        self._looking: set = set()         # decks being looked up
        lay = QVBoxLayout(self)
        self.header = page_header(
            "Proxy decks", "Decks people share on r/mpcproxies, Ko-fi and Discord – real Magic "
                           "cards with new art and frames – from their Google Drive, or proxy "
                           "folders on this PC. Import a deck, tick the cards you want and add "
                           "them to your deck: they're printed with those pictures, and every "
                           "picture keeps its maker's credit.")
        lay.addWidget(self.header)
        split = QSplitter(Qt.Horizontal)
        self.split = split

        # ---------------------------------------------------------------- the decks
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.list = QTreeWidget()
        self.list.setHeaderHidden(True)
        self.list.currentItemChanged.connect(self._picked)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)
        self.list.setToolTip("Right-click a deck for more – Delete takes it off your list")
        try:
            from mse_studio.gui.common import delete_key
            delete_key(self.list, self.remove)
        except ImportError:
            pass
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
        self.remove_btn.setToolTip("Take the deck off your list (files on your PC stay where they "
                                   "are). Right-click the list → Bring back removed decks")
        self.remove_btn.clicked.connect(self.remove)
        row.addWidget(self.remove_btn)
        lv.addLayout(row)
        split.addWidget(left)
        self.left = left

        # ---------------------------------------------------------------- one deck
        self.tabs = QTabWidget()
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 4, 0, 0)
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
        row = QHBoxLayout()
        row.addWidget(QLabel("Type"))
        self.type_filter = QComboBox()
        self.type_filter.addItem("All types", "")
        for t in px.TYPES:
            self.type_filter.addItem({"Sorcery": "Sorceries"}.get(t, t + "s"), t)
        self.type_filter.addItem("No text at all on the picture", NO_TEXT)
        self.type_filter.addItem("No rules text on the picture (full art…)", NO_RULES)
        self.type_filter.setToolTip("Types come from Scryfall when the cards are looked up, "
                                    "else from the deck's folders (Creature, Land…). The last "
                                    "two look at the pictures themselves for lines of letters "
                                    "(the name, type line and rules text) – once per deck, it "
                                    "takes a moment; very busy art can fool it now and then")
        self.type_filter.currentIndexChanged.connect(self._fill_grid)
        row.addWidget(self.type_filter)
        row.addSpacing(12)
        row.addWidget(QLabel("Size"))
        self.size = QSlider(Qt.Horizontal)
        self.size.setRange(110, 360)
        self.size.setValue(int(px.pref("size") or 180))
        self.size.setFixedWidth(170)
        self.size.setToolTip("How big the cards are shown")
        self.size.sliderReleased.connect(self._size_changed)
        self.size.valueChanged.connect(self._size_moved)
        row.addWidget(self.size)
        row.addSpacing(12)
        self.lookup = QCheckBox("Look the cards up on Scryfall")
        self.lookup.setChecked(bool(px.pref("lookup")))
        self.lookup.setToolTip("For their types (the filter), both faces of double-faced cards "
                               "and the card details in your deck. Untick it for custom cards "
                               "Scryfall doesn't know – nothing is looked up then")
        self.lookup.toggled.connect(self._lookup_toggled)
        row.addWidget(self.lookup)
        row.addStretch(1)
        self.big_btn = QPushButton("Bigger view")
        self.big_btn.setCheckable(True)
        icons.set_icon(self.big_btn, "fullscreen")
        self.big_btn.setToolTip("Hide the list of decks and the page's title: more room for "
                                "the cards")
        self.big_btn.toggled.connect(self._big_view)
        row.addWidget(self.big_btn)
        rv.addLayout(row)

        self.grid = TickGrid()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self._apply_size()
        self.grid.setWordWrap(True)
        self.grid.setToolTip("Click a card to tick or untick it (drag across cards to tick "
                             "several, Shift+click for all up to it, Ctrl+A for all). "
                             "Double-click to see it full size; right-click for more")
        self.grid.itemSelectionChanged.connect(self._ticks_changed)
        self.grid.itemDoubleClicked.connect(self._double_clicked)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._grid_menu)
        rv.addWidget(self.grid, 1)

        row = QHBoxLayout()
        self.add_btn = QPushButton("Add the ticked to my order")
        self.add_btn.setProperty("kind", "primary")
        icons.set_icon(self.add_btn, "shopping_cart")
        self.add_btn.clicked.connect(lambda: self.add_to_deck())
        row.addWidget(self.add_btn)
        self.edit_btn = QPushButton("Add the ticked to my deck to edit")
        icons.set_icon(self.edit_btn, "edit")
        self.edit_btn.setToolTip("Your own cards with the card's text and this art – in the "
                                 "deck's own frame, or a frame like the real card")
        self.edit_menu = QMenu(self.edit_btn)
        self.edit_menu.aboutToShow.connect(lambda: self._fill_edit_menu(self.edit_menu, None))
        self.edit_btn.setMenu(self.edit_menu)
        row.addWidget(self.edit_btn)
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
        self.hint = QLabel(REAL_HINT)
        self.hint.setWordWrap(True)
        self.hint.setObjectName("Hint")
        rv.addWidget(self.hint)
        self.tabs.addTab(right, "Cards")
        self.tabs.addTab(self._mine_tab(), "In my deck")
        self.tabs.currentChanged.connect(lambda i: self.fill_mine() if i == 1 else None)
        split.addWidget(self.tabs)
        split.setSizes([320, 900])
        lay.addWidget(split, 1)
        thumbs.cache().ready.connect(self._thumb_ready)
        if hasattr(thumbs, "large"):
            thumbs.large().ready.connect(self._thumb_ready)
        px.clear_scratch()
        # nothing is read (your proxy folders, the last deck's pictures) until the
        # page is opened – not when MSE Studio starts or a deck opens
        self._listed = False
        if px.pref("big_view"):
            self.big_btn.setChecked(True)

    # ------------------------------------------------------------ MSE Studio calls these
    def load(self):
        if not self._listed:
            return
        self._buttons()
        if self.tabs.currentIndex() == 1:
            self.fill_mine()

    def refresh(self):
        if not self._listed:
            self.fill_list()
            if self.tabs.currentIndex() == 1:
                self.fill_mine()
        self._buttons()

    def shutdown(self):
        forget(self._jobs)

    # ------------------------------------------------------------ the list of decks
    def fill_list(self, keep: str = ""):
        self._listed = True
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
        self.import_btn.setEnabled(d is not None and d.can_open and d.id not in self._importing)
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
        self.remove_btn.setEnabled(d is not None)
        has = bool(self.cards)
        p = self.main.project
        for b in (self.list_btn, self.save_btn, self.tick_all, self.tick_none, self.search,
                  self.sort, self.show_extra):
            b.setEnabled(has)
        n = self._ticked_count()
        self.add_btn.setEnabled(n > 0 and p is not None)
        self.add_btn.setText(f"Add the {n} ticked to my order" if n else
                             "Add the ticked to my order")
        self.add_btn.setToolTip(
            "Open a deck first" if p is None else
            "Real cards, straight into your deck: printed with these pictures as they are "
            "(and in Print at home); the maker's credit stays with each")
        self.edit_btn.setEnabled(n > 0 and p is not None)
        self.edit_btn.setText(f"Add the {n} ticked to my deck to edit" if n else
                              "Add the ticked to my deck to edit")
        self.back_btn.setVisible(bool(self.backs))
        self.back_btn.setEnabled(p is not None)

    def _ticked_count(self) -> int:
        return sum(c.count for c in self.cards if c.key in self._ticked)

    def _ticked_keys(self) -> list:
        return [c.key for c in self.cards if c.key in self._ticked]

    # ------------------------------------------------------------ importing a deck
    def import_deck(self):
        d = self.deck
        if d is None or not d.can_open or d.id in self._importing:
            return
        deck = copy.copy(d)

        def work(progress=None, cancel=None):
            items, text = px.list_deck(deck, progress=lambda m: progress(0, 0, m),
                                       cancel=cancel)
            return deck.id, items, text

        self._importing.add(d.id)
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
            self._importing.clear()
            self.status.setText(msg.splitlines()[0])
            self._buttons()
        except RuntimeError:
            return

    def _imported(self, res):
        try:
            did, items, text = res
            self._importing.discard(did)
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
        self.templates = px.templates_in(items)
        self.fonts = px.fonts_in(items)
        self._by_key = {c.key: c for c in self.cards}
        self.types = px.load_types(d.id) if d else {}
        self.texts = px.load_texts(d.id) if d else {}
        self.scans = px.load_scans(d.id) if d else {}
        if d is not None and self.lookup.isChecked() and not self.types and self.cards:
            self._look_up(d.id)
        self._ticked = {c.key for c in self.cards if not c.extra}
        self._fill_grid()
        deck = [c for c in self.cards if not c.extra]
        extra = len(self.cards) - len(deck)
        self.status.setText(
            (f"{len(deck)} different cards, {sum(c.count for c in deck)} in all" +
             (" (counts from the deck's own list)" if text else "") +
             (f" · {extra} tokens and extras, unticked" if extra else "") +
             (f" · {len(self.backs)} card back(s)" if self.backs else "") +
             (f" · {len(self.templates)} frame template(s) – right-click the deck → This "
              "deck's frame" if self.templates else "") +
             f" · {when}") if self.cards else
            "No card pictures in that folder.")

    # ------------------------------------------------------------ looking cards up
    def _look_up(self, deck_id: str):
        """The cards' types from Scryfall (or the Card database add-on), kept with
        the import; the type filter uses them."""
        if deck_id in self._looking:
            return
        cards = [c for c in self.cards if not c.token]

        def work(progress=None, cancel=None):
            types, texts = px.lookup_cards(cards, progress, cancel)
            return deck_id, types, texts

        self._looking.add(deck_id)
        job = Job(work, label="Looking the proxy cards up")
        job.signals.finished.connect(self._looked_up)
        job.signals.failed.connect(self._look_failed)
        self._jobs.append(start(job))

    def _looked_up(self, res):
        try:
            did, types, texts = res
            self._looking.discard(did)
            px.set_types(did, types)
            px.set_texts(did, texts)
            if self.deck is not None and self.deck.id == did:
                self.types, self.texts = types, texts
                self._fill_grid()
        except RuntimeError:
            return

    def _look_failed(self, msg: str):
        try:
            self._looking.clear()
            self.status.setText("Couldn't look the cards up: " + msg.splitlines()[0])
        except RuntimeError:
            return

    def _scan_pictures(self, deck_id: str):
        """Look for text on every card's picture (once per deck; kept with the
        import). Stopping keeps what was looked at already."""
        if deck_id in getattr(self, "_scanning", set()):
            return
        self._scanning = getattr(self, "_scanning", set()) | {deck_id}
        done = dict(getattr(self, "scans", {}))
        todo = [c.front for c in self.cards if c.front is not None and c.front.id not in done]
        todo = list({it.id: it for it in todo}.values())

        def work(progress=None, cancel=None):
            from mse_studio.pipeline.common import Cancelled
            out = dict(done)
            try:
                for k, it in enumerate(todo):
                    progress(k, len(todo), f"Looking for text on the pictures: {it.name}")
                    try:
                        r = px.scan_picture(it)
                    except Cancelled:
                        raise
                    except Exception:  # noqa: BLE001 - this picture can't be read
                        r = None
                    if r is not None:
                        out[it.id] = r
                    if k % 20 == 19:
                        px.set_scans(deck_id, out)       # kept as it goes
            except Cancelled:
                pass
            return deck_id, out

        job = Job(work, label="Looking for text on the pictures")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(self._scanned)
        job.signals.failed.connect(self._scan_failed)
        self._jobs.append(start(job))
        self.status.setText(f"Looking for text on {len(todo)} picture(s)… the cards show up "
                            "when it's done (Stop keeps what's checked so far).")

    def _scanned(self, res):
        try:
            did, scans = res
            self._scanning.discard(did)
            px.set_scans(did, scans)
            if self.deck is not None and self.deck.id == did:
                self.scans = scans
                self._fill_grid()
        except RuntimeError:
            return

    def _scan_failed(self, msg: str):
        try:
            self._scanning = set()
            self.status.setText("Couldn't look at the pictures: " + msg.splitlines()[0])
        except RuntimeError:
            return

    def _lookup_toggled(self, on: bool):
        px.set_pref("lookup", on)
        if on and self.deck is not None and self.cards and (not self.types or not self.texts):
            self._look_up(self.deck.id)

    # ------------------------------------------------------------ size
    def _thumb_size(self) -> QSize:
        w = self.size.value()
        return QSize(w, round(w * 1.4))

    def _apply_size(self):
        t = self._thumb_size()
        self.grid.setIconSize(t)
        self.grid.setGridSize(QSize(t.width() + 22, t.height() + 58))

    def _size_moved(self, _v):
        if not self.size.isSliderDown():          # keys, wheel: right away
            self._size_changed()

    def _size_changed(self):
        px.set_pref("size", self.size.value())
        self._apply_size()
        self._fill_grid()

    # ------------------------------------------------------------ the cards
    def _fill_grid(self, *_):
        q = self.search.text().strip().lower()
        sort = self.sort.currentData()
        want = self.type_filter.currentData() or ""
        scans = getattr(self, "scans", {})
        if want in (NO_TEXT, NO_RULES) and self.deck is not None and self.cards and \
                any(c.front is not None and c.front.id not in scans for c in self.cards):
            self._scan_pictures(self.deck.id)    # what's written on each picture

        def kind_ok(c) -> bool:
            if not want:
                return True
            if want in (NO_TEXT, NO_RULES):
                has = px.text_on_picture(c, scans, "any" if want == NO_TEXT else "rules")
                return has is False              # not looked at yet: not shown yet
            return want in px.card_types(c, self.types)
        cards = [c for c in self.cards if (self.show_extra.isChecked() or not c.extra) and
                 (not q or q in c.name.lower() or q in c.category.lower()
                  or q in c.front.name.lower()) and kind_ok(c)]
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
            tip = [c.front.name]
            line = self.types.get(c.name.lower())
            if line:
                tip.append(line)
            if c.category:
                tip.append(f"Folder: {c.category}")
            if c.variants:
                tip.append(f"{len(c.variants) + 1} pictures – right-click to choose")
            if c.extra:
                tip.append("Not part of the deck itself: tick it to add it")
            it.setToolTip("\n".join(tip))
            size = self._thumb_size()
            it.setSizeHint(QSize(size.width() + 16, size.height() + 54))
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            pm = self._thumb(c)
            if pm is not None:
                it.setIcon(QIcon(pm))
            self.grid.addItem(it)
            if c.key in self._ticked:
                it.setSelected(True)
        self.grid.blockSignals(False)
        self._buttons()
        if want in (NO_TEXT, NO_RULES) and not getattr(self, "_scanning", set()):
            self.status.setText(f"{len(cards)} card(s) with " +
                                ("no text at all" if want == NO_TEXT else "no rules text") +
                                " on the picture.")

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
        if self.size.value() > BIG and hasattr(thumbs, "large"):
            big = thumbs.large().get(sid, stamp, loader)
            if big is not None:
                return big
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

    def _ticks_changed(self):
        """Ticking is selecting: the cards shown follow what's selected (cards
        hidden by the search or filter keep their ticks)."""
        try:
            shown = {self.grid.item(i).data(Qt.UserRole) for i in range(self.grid.count())}
            sel = {it.data(Qt.UserRole) for it in self.grid.selectedItems()}
            self._ticked = (self._ticked - shown) | sel
            self._buttons()
        except RuntimeError:
            return

    def _tick_shown(self, on: bool):
        self.grid.blockSignals(True)
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            it.setSelected(on)
            (self._ticked.add if on else self._ticked.discard)(it.data(Qt.UserRole))
        self.grid.blockSignals(False)
        self.grid.viewport().update()
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
        c = self._by_key.get(key)
        if c is None:
            return
        ticked = self._ticked_keys()
        keys = ticked if key in self._ticked and len(ticked) > 1 else [key]
        n = len(keys)
        p = self.main.project
        menu = QMenu(self)
        menu.addAction(icons.icon("zoom_in"), "See it full size", lambda: self.view_card(key))
        add = menu.addAction(icons.icon("shopping_cart"),
                             "Add it to my order (printed as it is)" if n == 1 else
                             f"Add the {n} ticked to my order (printed as they are)",
                             lambda: self.add_to_deck(keys))
        add.setToolTip("Real cards, straight into your deck, printed with this picture")
        add.setEnabled(p is not None)
        edit = menu.addMenu(icons.icon("edit"), "Add it to my deck to edit" if n == 1 else
                            f"Add the {n} ticked to my deck to edit")
        edit.setEnabled(p is not None)
        self._fill_edit_menu(edit, keys)
        a = menu.addAction(icons.icon("brush"), "Use its art on the card I'm editing…",
                           lambda: self.use_art(key, False))
        a.setEnabled(p is not None and
                     getattr(self.main.cards_tab.editor, "card", None) is not None)
        self._tools_menu(menu, key)
        menu.addSeparator()
        if key in self._ticked:
            menu.addAction("Untick" + (" them" if n > 1 else " it"),
                           lambda: self._tick_keys(keys, False))
        else:
            menu.addAction("Tick it", lambda: self._tick_keys([key], True))
        if c.variants:
            sub = menu.addMenu(f"Print it with ({len(c.variants) + 1} pictures)")
            a = sub.addAction(f"{c.front.name} (now)")
            a.setEnabled(False)
            for i, v in enumerate(c.variants):
                sub.addAction(v.name, lambda i=i: self._use_variant(key, i))
        menu.addAction(icons.icon("save"), "Save its picture…" if n == 1 else
                       f"Save the {n} pictures…", lambda: self.save_pictures(keys))
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    def _fill_edit_menu(self, menu: QMenu, keys):
        """Add to my deck to edit ▸ which frame."""
        menu.clear()
        d = self.deck
        own = px.deck_frame(d.id) if d else ""
        if own:
            menu.addAction(icons.icon("palette"), f"In this deck's frame ({own})",
                           lambda: self.edit_cards(keys, own))
        menu.addAction("In a frame like the real card", lambda: self.edit_cards(keys, "real"))
        menu.addAction("In my deck's frame", lambda: self.edit_cards(keys, "same"))
        menu.addSeparator()
        menu.addAction(icons.icon("palette"), "Choose this deck's frame…", self.choose_frame)

    def _tools_menu(self, menu: QMenu, key: str):
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
        for t in tools:
            a = menu.addAction(icons.icon("brush"), t.label,
                               lambda t=t: self._run_tool(t, key))
            a.setToolTip(t.tooltip)

    def _run_tool(self, tool, key: str):
        c, d = self._by_key.get(key), self.deck
        if c is None:
            return
        item = c.front
        folder = px.scratch("tool-")
        info = {"name": c.name, "card": {}, "kind": "proxy", "credit": d.credit() if d else "",
                "maker": d.creator if d else "", "page": d.page if d else ""}

        def work(progress=None, cancel=None):
            if item.kind == "file":
                return item.id
            progress(0, 0, f"Getting {c.name}…")
            f = folder / Path(item.name).name
            f.write_bytes(px.fetch(item))
            return str(f)

        def done(path):
            from mse_studio.core import picture_tools
            try:
                picture_tools.run(tool, self, Path(path), info)
            except RuntimeError:
                return
        job = Job(work, label=f"Getting {c.name}")
        job.signals.finished.connect(done)
        job.signals.failed.connect(self._failed_box)
        self._jobs.append(start(job))

    # ------------------------------------------------------------ cards to edit
    def edit_cards(self, keys, frame: str):
        """The cards as your own cards to edit: Scryfall's text (when they're
        looked up), the picture's art in the art box (all of it, like MSE's
        Force to fit) – in ``frame``: this deck's own frame, "real" (like the
        real card) or "same" (your deck's frame)."""
        p, d = self.main.project, self.deck
        keys = keys or self._ticked_keys()
        cards = [copy.copy(self._by_key[k]) for k in keys if k in self._by_key]
        if p is None or d is None or not cards:
            return
        lookup, folder = self.lookup.isChecked(), str(p.folder)
        tmp = px.scratch("edit-")

        def work(progress=None, cancel=None):
            from PIL import Image
            entries = [dl.Entry(name=c.name, count=c.count, section=c.section) for c in cards]
            if lookup:
                px.resolve(entries, progress, cancel)
            pics = []
            for k, c in enumerate(cards):
                if cancel is not None and cancel.cancelled:
                    break
                progress(k, len(cards), f"Art: {c.name}")
                f = tmp / f"{k}{Path(c.front.name).suffix.lower() or '.png'}"
                f.write_bytes(px.fetch(c.front))
                with Image.open(f) as im:
                    pics.append((str(f), px.art_window(im.size)))
            return folder, entries[:len(pics)], pics

        def done(res):
            try:
                self._edit_ready(res, frame, d)
            except RuntimeError:
                return
        self.status.setText("Getting the art…")
        job = Job(work, label=f"Cards to edit from {d.title}")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(done)
        job.signals.failed.connect(self._failed_box)
        self._jobs.append(start(job))

    def _edit_ready(self, res, frame: str, deck: px.Deck):
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
                                              f"{e.display_name} (proxy)")
            art_import.set_credit(p, dst, deck.creator, deck.credit(), deck.page)
            keep.append((dst, crop))
        tab = self.main.decklists_tab
        try:
            n = tab.add_custom(entries, deck.title, frame=frame, pictures=keep,
                               keep_unknown=True)
        except TypeError:                  # an MSE Studio before 0.17
            error(self, "Proxy decks", "Update MSE Studio (0.17 or newer) to add cards to edit.")
            return
        if n:
            px.log_added(p.folder, deck, [e.display_name for e in entries], "edit")
            self.status.setText(f"Added {n} card(s) to edit – they're on the Cards page, with "
                                "their art.")
            self.fill_mine()

    # ------------------------------------------------------------ this deck's frame
    def choose_frame(self):
        d = self.deck
        if d is None:
            return
        dlg = FrameDialog(self, d, self.templates + getattr(self, "fonts", []))
        if dlg.exec():
            px.set_deck_frame(d.id, dlg.frame)
            self.status.setText(f"{d.title}'s cards are edited in {dlg.frame} now." if dlg.frame
                                else f"{d.title} has no frame of its own now.")

    def make_frame(self, deck: px.Deck, templates: list):
        """Frame studio (an add-on) makes a frame from the deck's templates."""
        page = (getattr(self.main, "addon_pages", {}) or {}).get("frame-studio", (None, None))[1]
        if page is None:
            error(self, "Proxy decks", "Frame studio makes a frame from the maker's templates: "
                                       "get it in Manage → Add-ons → Store.")
            return
        folder = px.scratch("templates-")

        def work(progress=None, cancel=None):
            out = []
            for k, it in enumerate(templates):
                if cancel is not None and cancel.cancelled:
                    break
                if it.kind == "file":
                    out.append(it.id)
                    continue
                progress(k, len(templates), f"Getting {it.name}")
                f = folder / f"{k:03d} {Path(it.name).name}"
                f.write_bytes(px.fetch(it))
                out.append(str(f))
            return out

        def made(frame):
            px.set_deck_frame(deck.id, frame.style_name)

        def done(files):
            try:
                self.main.tabs.setCurrentWidget(page)
                try:                   # Frame studio 1.1 makes it in the background
                    fr = page.start_from([Path(f) for f in files], deck.title,
                                         proxy_deck=deck.id, done=made)
                except TypeError:
                    fr = page.start_from([Path(f) for f in files], deck.title,
                                         proxy_deck=deck.id)
                if fr is not None:
                    made(fr)
            except RuntimeError:
                return
        job = Job(work, label=f"Getting {deck.title}'s templates")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(done)
        job.signals.failed.connect(self._failed_box)
        self._jobs.append(start(job))

    # ------------------------------------------------------------ bigger view
    def _big_view(self, on: bool):
        self.left.setVisible(not on)
        self.header.setVisible(not on)
        self.title.setVisible(not on)
        self.notes.setVisible(not on and bool(self.notes.text()))
        self.big_btn.setText("Normal view" if on else "Bigger view")
        icons.set_icon(self.big_btn, "fullscreen_exit" if on else "fullscreen")
        px.set_pref("big_view", on)

    def use_art(self, key: str, new_card: bool):
        """A proxy's art on your own card: its picture goes in the deck's art
        folder (with the maker's credit), and the art editor opens on it with the
        art window already picked."""
        c, d, p = self._by_key.get(key), self.deck, self.main.project
        if c is None or p is None:
            return
        item, credit, maker = c.front, (d.credit() if d else ""), (d.creator if d else "")
        lookup, name, folder = self.lookup.isChecked(), c.name, str(p.folder)

        def work(progress=None, cancel=None):
            from PIL import Image
            from mse_studio.core import art_import
            target = art_import.default_folder(p)
            target.mkdir(parents=True, exist_ok=True)
            path = art_import.save_image_bytes(px.fetch(item), target, f"{name} (proxy)")
            with Image.open(path) as im:
                crop = px.art_window(im.size)
            entry = None
            if new_card and lookup:
                entry = dl.Entry(name=name)
                try:
                    px.resolve([entry], progress, cancel)
                except Exception:  # noqa: BLE001 - the card gets just its name
                    entry = None
            return folder, str(path), crop, credit, maker, new_card, name, entry

        job = Job(work, label=f"Getting the art of {name}")
        job.signals.finished.connect(self._art_ready)
        job.signals.failed.connect(self._failed_box)
        self._jobs.append(start(job))

    def _art_ready(self, res):
        from mse_studio.core import art_import
        try:
            folder, path, crop, credit, maker, new_card, name, entry = res
            p = self.main.project
            if p is None or str(p.folder) != folder:
                return
            art_import.set_credit(p, Path(path), maker, credit, self.deck.page if self.deck
                                  else "")
            tab = self.main.cards_tab
            tab.editor.commit()
            if new_card:
                card = p.new_card()
                if entry is not None and entry.found:
                    for f, val in dl.as_custom(entry).items():
                        card.set_text(f, val)
                else:
                    card.set_text("name", name)
                row = len(p.set.cards) - 1
                self.main.record(f"Proxy decks · new card {name} with its art", row=row)
                tab.reload(row)
            self.main.tabs.setCurrentWidget(tab)
            if new_card:
                tab.select_row(len(p.set.cards) - 1)
            tab.editor.open_editor(Path(path), crop=crop, original=path)
        except RuntimeError:
            return

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
        lookup = self.lookup.isChecked()

        def work(progress=None, cancel=None):
            entries = [dl.Entry(name=c.name, count=c.count, section=c.section) for c in cards]
            both = cards
            if lookup:                                   # card data (Scryfall), if it's real
                px.resolve(entries, progress, cancel)
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
            return folder, credit, d.title, out, lookup

        self.status.setText("Getting the pictures…")
        job = Job(work, label=f"Adding {d.title}")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(self._added)
        job.signals.failed.connect(self._failed_box)
        self._jobs.append(start(job))

    def _added(self, res):
        from mse_studio.pipeline import real_cards as rc
        try:
            folder, credit, title, out, lookup = res
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
            if self.deck is not None and self.deck.title == title:
                px.log_added(p.folder, self.deck, [e.display_name for e in ok], "real")
            self.main.record(f"Proxy decks · {n} real card(s) from {title}")
            self.main.update_title()
            self.status.setText(f"Added {n} real card(s) to your deck, printed as they are.")
            self.main.statusBar().showMessage(
                f"Added {n} card(s) from {title} – making their print files", 10000)
            _real_pictures(self.main, ok)
            self.fill_mine()
            unknown = [e.name for e in ok if not e.found] if lookup else []
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
            _pages_changed(self.main)
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
        paths, _ = QFileDialog.getOpenFileNames(self, "Zips of proxies (pick several if you "
                                                "like)", "", "Zip files (*.zip)")
        for path in paths:
            self._add_from_pc(path, quiet=len(paths) > 1)

    def _add_from_pc(self, path: str, quiet: bool = False):
        found = local.scan(path)
        if not found:
            if not quiet:
                error(self, "Proxy decks", "No card pictures in there. Pick the deck's own "
                                           "folder, a folder with decks in it, or a deck's zip.")
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
        """Take the deck off your list: yours are forgotten, the store's and the
        ones on this PC are hidden (Bring back removed decks… shows them)."""
        d = self.deck
        if d is None:
            return
        if not _ask_delete(self, f"Take {d.title} off your list?" +
                           (" The files stay on your PC." if d.on_pc else "")):
            return
        if d.mine:
            px.remove_mine(d.id)
        else:
            px.hide(d.id)
        if d.on_pc:
            px.forget_listing(d.id)
        self.deck = None
        self.fill_list()

    def remove_folder(self):
        """A folder you added (with all the decks in it) off the list."""
        d = self.deck
        if d is None or not d.on_pc:
            return
        same = [x for x in self._decks.values() if x.on_pc and x.root == d.root]
        if not _ask_delete(self, f"Take the folder {d.root} off the list ({len(same)} "
                                 "deck(s))? The files stay on your PC."):
            return
        px.remove_root(d.root)
        for x in same:
            px.forget_listing(x.id)
        self.deck = None
        self.fill_list()

    def bring_back(self):
        n = len(px.hidden())
        px.unhide()
        self.fill_list()
        self.main.statusBar().showMessage(f"{n} deck(s) back on your list", 6000)

    def _list_menu(self, pos):
        it = self.list.itemAt(pos)
        m = QMenu(self)
        if it is not None and it.data(0, Qt.UserRole):
            self.list.setCurrentItem(it)
            d = self.deck
            if d is not None:
                if d.can_open:
                    m.addAction(icons.icon("download"), "Import again" if px.is_imported(d.id)
                                else "Import the deck", self.import_deck)
                    m.addAction(icons.icon("open_in_new"), "Open the folder" if d.on_pc else
                                "Open its Google Drive", self._open_source)
                if d.page:
                    m.addAction(icons.icon("open_in_new"), "Open its Ko-fi page", self._open_page)
                if d.on_pc or d.mine:
                    m.addAction(icons.icon("edit"), "Who made it…", self.edit_maker)
                frame = px.deck_frame(d.id)
                m.addAction(icons.icon("palette"), "This deck's frame…" +
                            (f" ({frame})" if frame else ""), self.choose_frame)
                if self.cards:
                    m.addAction("Save as a decklist", self.save_decklist)
                m.addAction("Copy the credit", self.copy_credit)
                m.addSeparator()
                a = m.addAction(icons.icon("delete"), "Remove from my list", self.remove)
                a.setShortcut(Qt.Key_Delete)
                if d.on_pc:
                    m.addAction("Remove the whole folder from my list", self.remove_folder)
        n = len(px.hidden())
        if n:
            m.addSeparator()
            m.addAction(f"Bring back removed decks ({n})", self.bring_back)
        if not m.isEmpty():
            m.exec(self.list.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ what's in my deck
    def _mine_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 0)
        hint = QLabel("The cards of your open deck that came from proxy decks, by deck: real "
                      "cards and cards to edit are on the Cards page. "
                      "Double-click one to go to it; Delete takes it out of your deck.")
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        v.addWidget(hint)
        self.mine = QTreeWidget()
        self.mine.setHeaderLabels(["Card", "As", "Copies"])
        self.mine.setColumnWidth(0, 360)
        self.mine.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.mine.itemDoubleClicked.connect(self._mine_open)
        self.mine.setContextMenuPolicy(Qt.CustomContextMenu)
        self.mine.customContextMenuRequested.connect(self._mine_menu)
        try:
            from mse_studio.gui.common import delete_key
            delete_key(self.mine, self.remove_from_deck)
        except ImportError:
            pass
        v.addWidget(self.mine, 1)
        row = QHBoxLayout()
        b = QPushButton("Take the selected out of my deck")
        icons.set_icon(b, "delete")
        b.clicked.connect(self.remove_from_deck)
        row.addWidget(b)
        row.addStretch(1)
        self.mine_count = QLabel()
        self.mine_count.setObjectName("Hint")
        row.addWidget(self.mine_count)
        v.addLayout(row)
        return w

    def fill_mine(self):
        """Real cards (credited to a proxy deck) and cards to edit (from the
        deck's log), grouped by the proxy deck they came from."""
        self.mine.clear()
        p = self.main.project
        if p is None:
            self.mine_count.setText("Open a deck first.")
            return
        log = px.added_log(p.folder)
        decks = {d.id: d for d in px.decks(with_hidden=True)}
        by_credit = {d.credit(): d.id for d in decks.values()}
        groups: dict = {}

        def group(deck_id: str, title: str):
            if deck_id not in groups:
                g = QTreeWidgetItem(self.mine, [title, "", ""])
                f = g.font(0)
                f.setBold(True)
                g.setFont(0, f)
                g.setFlags(Qt.ItemIsEnabled)
                groups[deck_id] = g
            return groups[deck_id]

        real_from = {(d.get("card") or "").lower(): d for d in log if d.get("as") == "real"}
        n = 0
        for e in dl.project_real(p):
            pr = e.printing or {}
            credit = pr.get("credit") or ""
            hit = real_from.get(e.display_name.lower()) or real_from.get(e.name.lower())
            did = (hit or {}).get("deck") or by_credit.get(credit)
            if not did and not credit:
                continue
            title = decks[did].title if did in decks else (hit or {}).get("title") or credit
            it = QTreeWidgetItem(group(did or credit, title),
                                 [e.display_name, "Real card", str(e.count)])
            it.setData(0, Qt.UserRole, ("real", e.name, e.section))
            it.setToolTip(0, credit)
            n += 1
        names = {c.name.lower(): i for i, c in enumerate(p.set.cards)}
        for d in log:
            if d.get("as") != "edit":
                continue
            row = names.get((d.get("card") or "").lower())
            if row is None:
                continue
            did = d.get("deck") or ""
            title = decks[did].title if did in decks else d.get("title") or did
            it = QTreeWidgetItem(group(did, title), [p.set.cards[row].name,
                                                     "To edit (Cards page)", ""])
            it.setData(0, Qt.UserRole, ("edit", p.set.cards[row].name, ""))
            n += 1
        for g in groups.values():
            g.setText(2, str(g.childCount()))
        self.mine.expandAll()
        self.mine_count.setText(f"{n} card(s) from {len(groups)} proxy deck(s)" if n else
                                "No cards from proxy decks in this deck yet.")

    def _mine_selected(self) -> list:
        return [it.data(0, Qt.UserRole) for it in self.mine.selectedItems()
                if it.data(0, Qt.UserRole)]

    def _mine_open(self, it, _col=0):
        data = it.data(0, Qt.UserRole)
        p = self.main.project
        if not data or p is None:
            return
        kind, name, _section = data
        if kind == "real":
            show = getattr(self.main.cards_tab, "show_real", None)
            if show is not None:                     # MSE Studio 0.25: on the Cards page
                self.main.tabs.setCurrentWidget(self.main.cards_tab)
                show(name)
            elif getattr(self.main, "order_tab", None) is not None:
                self.main.tabs.setCurrentWidget(self.main.order_tab)
            return
        rows = [i for i, c in enumerate(p.set.cards) if c.name == name]
        if rows:
            self.main.tabs.setCurrentWidget(self.main.cards_tab)
            self.main.cards_tab.select_row(rows[0])

    def _mine_menu(self, pos):
        it = self.mine.itemAt(pos)
        if it is None or not it.data(0, Qt.UserRole):
            return
        if not it.isSelected():
            self.mine.clearSelection()
            it.setSelected(True)
        m = QMenu(self)
        m.addAction("Go to it", lambda: self._mine_open(it))
        a = m.addAction(icons.icon("delete"), "Take it out of my deck", self.remove_from_deck)
        a.setShortcut(Qt.Key_Delete)
        m.exec(self.mine.viewport().mapToGlobal(pos))

    def remove_from_deck(self):
        """The selected cards out of your deck (Undo brings them back)."""
        sel = self._mine_selected()
        p = self.main.project
        if not sel or p is None:
            return
        names = sorted({name for _k, name, _s in sel})
        if not _ask_delete(self, f"Take {', '.join(names[:5])}" + ("…" if len(names) > 5 else "")
                           + " out of your deck?"):
            return
        self.main.cards_tab.editor.commit()
        real = {(name.lower(), section) for kind, name, section in sel if kind == "real"}
        if real:
            dl.set_project_real(p, [e for e in dl.project_real(p)
                                    if (e.name.lower(), e.section) not in real])
            p.save_config()
        edit = {name for kind, name, _s in sel if kind == "edit"}
        for c in [c for c in p.set.cards if c.name in edit]:
            p.set.remove_card(c)
            p.dirty = True
        px.forget_added(p.folder, names)
        self.main.record(f"Proxy decks · took {len(sel)} card(s) out")
        self.main.cards_tab.reload()
        self.main.update_title()
        self.fill_mine()

    def find_on_reddit(self):
        dlg = RedditDialog(self)
        if dlg.exec():
            added = dlg.chosen()
            for post in added:
                px.add_mine(px.deck_from_post(post))
            if added:
                self.fill_list(px.deck_from_post(added[0]).id)


class FrameDialog(QDialog):
    """The MSE frame a proxy deck's cards are edited in."""

    def __init__(self, parent, deck: px.Deck, templates: list):
        super().__init__(parent)
        self.page, self.deck, self.templates = parent, deck, templates
        self.frame = px.deck_frame(deck.id)
        self.setWindowTitle(f"{deck.title} – its frame")
        self.resize(520, 520)
        lay = QVBoxLayout(self)
        hint = QLabel("Makers often sell their frame templates with a deck (a deluxe edition). "
                      "Frame studio (an add-on) turns them into an MSE frame; pick it here and "
                      "Add to my deck to edit puts this deck's cards in it.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.list = QListWidget()
        it = QListWidgetItem("No frame of its own (choose when adding)")
        it.setData(Qt.UserRole, "")
        self.list.addItem(it)
        frames = []
        try:
            frames = parent.main.known_frames()
        except Exception:  # noqa: BLE001
            pass
        made = [f for f in frames if f.startswith("fs-")]
        for f in made + [f for f in frames if not f.startswith("fs-")]:
            it = QListWidgetItem(("★ " if f in made else "") + f)
            it.setData(Qt.UserRole, f)
            it.setToolTip("Made with Frame studio" if f in made else "")
            self.list.addItem(it)
            if f == self.frame:
                self.list.setCurrentItem(it)
        if self.list.currentItem() is None:
            self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda *_: self._ok())
        lay.addWidget(self.list, 1)
        fonts = px.fonts_in(templates)
        n = len(templates) - len(fonts)
        extra = f" and {len(fonts)} font file(s)" if fonts else ""
        b = QPushButton(f"Make one from the deck's {n} template(s){extra} with Frame studio…"
                        if n else "Make one with Frame studio (pick the maker's pictures)…")
        icons.set_icon(b, "palette")
        b.clicked.connect(self._make)
        lay.addWidget(b)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self):
        it = self.list.currentItem()
        self.frame = it.data(Qt.UserRole) if it is not None else ""
        self.accept()

    def _make(self):
        self.reject()
        self.page.make_frame(self.deck, self.templates)


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
