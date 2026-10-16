"""Order: every card's front and back as they'll be printed, what's still
missing, copies, a proof sheet, and Send to MPC – mpc-autofill fills your
MakePlayingCards order. Real cards get MPCFill's print-ready pictures.

Until MSE Studio 0.25 this page came with the app (mse_studio.gui.order_tab);
the printing itself (mse_studio.pipeline.order, real_cards) is still MSE
Studio's."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QListView, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from mse_studio.pipeline import order
from mse_studio.pipeline import real_cards as rc
from mse_studio.pipeline.common import open_in_explorer
from mse_studio.gui import icons, real_card_actions, theme, thumbs
from mse_studio.gui.common import delete_key, error, forget, info
from mse_studio.gui.nav import page_header

from . import mpcfill_api
from . import prefs as prefs_file

RATIO = 2.5 / 3.5
AUTOFILL_PAGE = "https://github.com/chilli-axe/mpc-autofill/releases"


def _clear(layout):
    """Remove everything from a layout (rows of widgets included)."""
    while layout.count():
        it = layout.takeAt(0)
        if it.widget() is not None:
            it.widget().deleteLater()
        elif it.layout() is not None:
            _clear(it.layout())


class OrderPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.rows: list[order.Slot] = []
        self._jobs: list = []
        self.prefs = prefs_file.load(main.settings)
        # MPCFill's servers as they're set now, for real cards' pictures (read on a
        # worker thread – a plain dict, never the page)
        self._servers = {"server": self.prefs["mpcfill_server"],
                         "images": self.prefs["mpcfill_images"]}
        servers = self._servers
        rc.add_source(mpcfill_api.make_source(lambda: dict(servers)))

        lay = QVBoxLayout(self)
        lay.addWidget(page_header(
            "Order", "Step 4 · Every card's front and back as they'll be printed, checks before "
                     "ordering, and sending the whole order to MakePlayingCards in one go. "
                     "Right-click a card to change its back or how many copies you want."))
        row = QHBoxLayout()
        self.summary = QLabel()
        row.addWidget(self.summary, 1)
        for text, icon, tip, fn in (
                ("Card back…", "style", "The back printed on every card without its own",
                 self.choose_card_back),
                ("Make backs", "refresh", "Print-ready backs for the cards with their own back "
                                          "(also done by step 3)", self.make_backs),
                ("Proof sheet (PDF)…", "fact_check", "Every card's front and back with names, "
                                                     "to check before ordering", self.proof_pdf),
                ("Print at home…", "print", "Card sheets for your own printer: paper and card "
                                            "size, crop marks, double-sided backs…",
                 self.print_home)):
            b = QPushButton(text)
            icons.set_icon(b, icon)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, fn=fn: fn())
            row.addWidget(b)
        b = QPushButton("Order folder")
        b.setProperty("kind", "text")
        b.clicked.connect(self._open_folder)
        row.addWidget(b)
        self.send_btn = QPushButton("Send to MPC")
        self.send_btn.setProperty("kind", "primary")
        icons.set_icon(self.send_btn, "shopping_cart")
        self.send_btn.setToolTip("Writes the order file and starts mpc-autofill, which uploads "
                                 "every front and back to MakePlayingCards in your browser")
        self.send_btn.clicked.connect(self.send)
        row.addWidget(self.send_btn)
        lay.addLayout(row)

        opts = QHBoxLayout()
        opts.addWidget(QLabel("Card stock"))
        self.stock = QComboBox()
        self.stock.addItems(order.STOCKS)
        self.stock.currentTextChanged.connect(self._opts_changed)
        opts.addWidget(self.stock)
        self.foil = QCheckBox("Foil")
        self.foil.toggled.connect(self._opts_changed)
        opts.addWidget(self.foil)
        opts.addSpacing(16)
        opts.addWidget(QLabel("mpc-autofill"))
        self.tool_lbl = QLabel()
        self.tool_lbl.setObjectName("Hint")
        opts.addWidget(self.tool_lbl)
        b = QPushButton("Change…")
        b.setProperty("kind", "text")
        b.clicked.connect(self.change_tool)
        opts.addWidget(b)
        self.browser = QComboBox()
        self.browser.addItems(["Browser: ask", "Chrome", "Edge", "Brave"])
        self.browser.setToolTip("The browser mpc-autofill opens MakePlayingCards in")
        self.browser.currentIndexChanged.connect(self._browser_changed)
        opts.addWidget(self.browser)
        self.mpcfill_btn = QPushButton("MPCFill ✓" if mpcfill_api.server_url(
            self._servers["server"]) else "MPCFill…")
        icons.set_icon(self.mpcfill_btn, "cloud_download")
        self.mpcfill_btn.setToolTip("Print-ready pictures for real cards from MPCFill: set up "
                                    "its server")
        self.mpcfill_btn.clicked.connect(self.mpcfill_servers)
        opts.addWidget(self.mpcfill_btn)
        opts.addStretch(1)
        opts.addWidget(QLabel("Size"))
        self.size = QSlider(Qt.Horizontal)
        full = bool(self.prefs["full_quality"])
        self.size.setRange(110, 640 if full else 320)
        self.size.setValue(190)
        self.size.setFixedWidth(160)
        self.size.valueChanged.connect(self._size_changed)
        opts.addWidget(self.size)
        self.full_quality = QCheckBox("Full quality")
        self.full_quality.setChecked(full)
        self.full_quality.setToolTip("Draw each card from its full-size picture: sharp at any "
                                     "size, and the size goes up to 640. Uses more memory and "
                                     "disk – for faster computers")
        self.full_quality.toggled.connect(self._full_quality)
        opts.addWidget(self.full_quality)
        lay.addLayout(opts)

        # what still has to be done, each with a button to the right place
        self.todo = QFrame()
        self.todo.setObjectName("OrderTodo")
        self.todo_lay = QVBoxLayout(self.todo)
        self.todo_lay.setContentsMargins(12, 8, 12, 8)
        self.todo_lay.setSpacing(4)
        lay.addWidget(self.todo)

        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setWrapping(True)
        self.grid.setSpacing(10)
        self.grid.setWordWrap(True)
        self.grid.setSelectionMode(QListWidget.ExtendedSelection)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._menu)
        self.grid.itemDoubleClicked.connect(self._view)
        delete_key(self.grid, self._delete_selected)
        lay.addWidget(self.grid, 1)
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.problems)
        thumbs.cache().ready.connect(self._thumb_ready)
        thumbs.large().ready.connect(self._thumb_ready)
        self._refill = QTimer(self)
        self._refill.setSingleShot(True)
        self._refill.setInterval(150)
        self._refill.timeout.connect(self._refill_now)

    # ------------------------------------------------------------- page
    def shutdown(self):
        """The page is going (pages rebuilt, the deck closed)."""
        self._refill.stop()
        forget(self._jobs)
        rc.remove_source(rc.MPCFILL)

    def real_pictures(self, entries: Optional[list] = None):
        """Add-ons made before MSE Studio 0.25 call main.order_tab.real_pictures()."""
        self.main.real_pictures(entries)

    def _order_dir(self) -> Path:
        d = self.main.project.folder / "order"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _open_folder(self):
        if self.main.project is not None:
            open_in_explorer(self._order_dir())

    def _autofill(self) -> Optional[Path]:
        return order.autofill_path(None, self.prefs["autofill"])

    def refresh(self):
        p = self.main.project
        if p is None:
            return
        o = p.config.get("order") or {}
        self.stock.blockSignals(True)
        self.stock.setCurrentText(o.get("stock") or order.STOCKS[0])
        self.stock.blockSignals(False)
        self.foil.blockSignals(True)
        self.foil.setChecked(bool(o.get("foil")))
        self.foil.blockSignals(False)
        exe = self._autofill()
        own = bool(self.prefs["autofill"])
        self.tool_lbl.setText(("your copy" if own else "the mpc-autofill add-on" if exe else
                               "not installed yet") + (" – not found" if own and exe and
                                                       not exe.exists() else ""))
        self.tool_lbl.setToolTip(str(exe) if exe else
                                 "Send to MPC offers to get it from the store (Change…)")
        self.browser.blockSignals(True)
        self.browser.setCurrentIndex(max(0, self.browser.findText(
            (self.prefs["browser"] or "").capitalize())))
        self.browser.blockSignals(False)
        ready = mpcfill_api.server_url(self._servers["server"])
        self.mpcfill_btn.setText("MPCFill ✓" if ready else "MPCFill…")
        self.rows = order.slots(p)
        self._fill()
        self._fill_todo()

    def _fill_todo(self):
        t = theme.current()
        _clear(self.todo_lay)
        missing = order.readiness(self.main.project)
        self.todo.setStyleSheet(
            f"#OrderTodo {{ background: {t.surface_container}; border-radius: 10px; "
            f"border-left: 4px solid {t.warning if missing else t.success}; }}")
        if not missing:
            self.todo_lay.addWidget(QLabel("✓ Ready to order: every card has a print file and "
                                           "a back."))
            return
        self.todo_lay.addWidget(QLabel("<b>Before ordering</b>"))
        actions = {"card_back": ("Choose card back…", self.choose_card_back),
                   "export": ("Go to Export", self._go_export),
                   "print": ("Go to Print", self._go_print),
                   "backs": ("Make backs", self.make_backs),
                   "real": ("Get real card pictures", self.get_real_pictures)}
        names = {s.index: s.name for s in self.rows}
        for m in missing:
            row = QHBoxLayout()
            lbl = QLabel("• " + m.text)
            lbl.setWordWrap(True)
            if m.rows:
                lbl.setToolTip("\n".join(names.get(i, "") for i in m.rows[:30]))
            row.addWidget(lbl, 1)
            text, slot = actions.get(m.kind, ("", None))
            if slot is not None:
                b = QPushButton(text)
                b.setProperty("kind", "text")
                b.clicked.connect(lambda _c=False, fn=slot: fn())
                row.addWidget(b)
            self.todo_lay.addLayout(row)

    def _go_export(self):
        self.main.tabs.setCurrentWidget(self.main.render_tab)

    def _go_print(self):
        self.main.tabs.setCurrentWidget(self.main.print_tab)

    def get_real_pictures(self):
        self.main.real_pictures()

    def choose_card_back(self):
        if self.main.choose_card_back():
            self.refresh()

    def _fill(self):
        t = theme.current()
        h = self.size.value()
        w = round(h * RATIO)
        self.grid.setIconSize(QSize(w * 2 + 6, h))
        self.grid.clear()
        deck_back = order.deck_back(self.main.project)
        total = bad = 0
        for s in self.rows:
            total += s.quantity
            label = s.name if s.quantity == 1 or s.is_back else f"{s.quantity}× {s.name}"
            if s.role:
                label += f"\n{s.role}"
            it = QListWidgetItem(QIcon(self._pair(s, deck_back, w, h)), label)
            it.setData(Qt.UserRole, s.index)
            tip = [s.name, f"Front: {s.front or 'not made yet'}",
                   f"Back: {s.back or (deck_back or 'the deck card back – not made yet')}"]
            credit = ((getattr(s.real, "printing", None) or {}).get("credit")
                      if s.real is not None else "")
            if credit:
                tip.append(f"Picture: {credit}")
            if s.problems:
                bad += 1
                it.setForeground(QColor(t.error))
                tip += ["", *s.problems]
            if s.is_back:
                it.setForeground(QColor(t.outline))
                tip.append(f"{s.role} – printed on that card's back, not on its own")
            elif not s.quantity:
                it.setForeground(QColor(t.outline))
                tip.append("Not ordered (0 copies)")
            it.setToolTip("\n".join(str(x) for x in tip))
            self.grid.addItem(it)
        self.summary.setText(
            f"<b>{total}</b> cards to print · MPC order size <b>{order.bracket(total)}</b>"
            + (f" · <span style='color:{t.error}'>{bad} need attention</span>" if bad else
               " · everything ready") + ("" if deck_back else
                                         f" · <span style='color:{t.warning}'>no card back yet "
                                         f"(step 3)</span>"))
        lines = [f"• {s.name}: {', '.join(s.problems)}" for s in self.rows if s.problems][:8]
        self.problems.setText("\n".join(lines))
        self.problems.setVisible(bool(lines))

    def _pair(self, s: order.Slot, deck_back: Optional[Path], w: int, h: int) -> QPixmap:
        """Front and back side by side."""
        t = theme.current()
        dpr = max(1.0, self.devicePixelRatioF())
        pm = QPixmap(round((w * 2 + 6) * dpr), round(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        full = self.full_quality.isChecked()
        p = QPainter(pm)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        pair = (s.front, s.back or deck_back)
        if s.is_back:          # a back card: shown as the back of the card it belongs to
            front = next((r for r in self.rows if r.back_card == s.index), None)
            pair = (front.front if front else None, s.front)
        for k, path in enumerate(pair):
            r = QRectF(k * (w + 6), 0, w, h)
            img = None
            if path and full:
                img = thumbs.large().file(path)
            if img is None and path:          # the small one while the big one is made
                img = thumbs.cache().file(path)
            if img is not None:
                p.drawPixmap(r, img, QRectF(img.rect()))
            else:
                p.setPen(QColor(t.error if not path else t.outline))
                p.setBrush(QColor(t.surface_low))
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 6, 6)
                p.drawText(r, Qt.AlignCenter | Qt.TextWordWrap,
                           ("front" if k == 0 else "back") + ("\n…" if path else "\nmissing"))
        p.end()
        return pm

    def _thumb_ready(self, _id: str):
        try:
            if self.isVisible() and self.rows:
                self._refill.start()              # many at once: drawn again once
        except RuntimeError:
            return

    def _refill_now(self):
        try:
            if self.isVisible() and self.rows:
                bar = self.grid.verticalScrollBar()
                pos = bar.value()
                self._fill()
                bar.setValue(pos)
        except RuntimeError:
            return

    def _size_changed(self, _v: int):
        if self.main.project is not None:
            self._fill()

    def _full_quality(self, on: bool):
        self.prefs["full_quality"] = on
        prefs_file.save(self.prefs)
        self.size.setRange(110, 640 if on else 320)
        if self.main.project is not None:
            self._fill()

    # ------------------------------------------------------------- options
    def _opts_changed(self, *_):
        p = self.main.project
        if p is None:
            return
        o = order.opts(p)
        o["stock"] = self.stock.currentText()
        o["foil"] = self.foil.isChecked()
        p.save_config()

    def _browser_changed(self, i: int):
        self.prefs["browser"] = "" if i == 0 else self.browser.currentText().lower()
        prefs_file.save(self.prefs)

    def change_tool(self):
        m = QMenu(self)
        if self._autofill() is None or self.prefs["autofill"]:
            m.addAction("Get the mpc-autofill add-on (from the store)", self._get_autofill)
        m.addAction("Choose another copy of mpc-autofill…", self._pick_tool)
        a = m.addAction("Use the mpc-autofill add-on", self._reset_tool)
        a.setEnabled(bool(self.prefs["autofill"]))
        m.addAction("Open its web page", self._autofill_page)
        m.exec(self.cursor().pos())
        m.deleteLater()

    def _autofill_page(self):
        import webbrowser
        webbrowser.open(AUTOFILL_PAGE)

    def _get_autofill(self, then=None):
        self.prefs["autofill"] = ""
        prefs_file.save(self.prefs)
        self.main.offer_addon("mpc-autofill", "Send to MPC needs mpc-autofill.",
                              then=then or self._autofill_installed)

    def _autofill_installed(self, _page=None):
        try:
            self.refresh()
        except RuntimeError:
            return

    def _pick_tool(self):
        path, _ = QFileDialog.getOpenFileName(self, "mpc-autofill", "",
                                              "Programs (*.exe);;All files (*)")
        if path:
            self.prefs["autofill"] = path
            prefs_file.save(self.prefs)
            self.refresh()

    def _reset_tool(self):
        self.prefs["autofill"] = ""
        prefs_file.save(self.prefs)
        self.refresh()

    def mpcfill_servers(self):
        from .server_dialog import ServerDialog
        d = ServerDialog(self, self.prefs)
        try:
            ok = d.exec()
        finally:
            d.deleteLater()
        if ok:
            self._servers.update(server=self.prefs["mpcfill_server"],
                                 images=self.prefs["mpcfill_images"])
            self.refresh()
            p = self.main.project
            if p is not None and mpcfill_api.server_url(self._servers["server"]) and \
                    any((e.printing or {}).get("source") == rc.SCRYFALL
                        for e in self._real_entries()) and QMessageBox.question(
                    self, "MPCFill", "Look for MPCFill pictures for the real cards that use "
                                     "Scryfall's now?") == QMessageBox.Yes:
                every = [e for e in self._real_entries()
                         if (e.printing or {}).get("source") == rc.SCRYFALL]
                real_card_actions.set_source(self.main, every, rc.MPCFILL)

    def _real_entries(self) -> list:
        from mse_studio.core import decklists as dl
        p = self.main.project
        return dl.project_real(p) if p is not None else []

    # ------------------------------------------------------------- per card
    def _selected(self) -> list[int]:
        return [it.data(Qt.UserRole) for it in self.grid.selectedItems()]

    def _delete_selected(self):
        """The Delete key: real cards leave the deck; your own cards stay in the
        deck but aren't printed (Print it again brings them back)."""
        rows = self._selected()
        p = self.main.project
        if p is None or not rows:
            return
        real = [s.real for s in self.rows if s.index in rows and s.real is not None]
        own = sorted({s.index for s in self.rows if s.index in rows and s.real is None
                      and not s.is_back and 0 <= s.index < len(p.set.cards)})
        if real and real_card_actions.remove(self.main, real, self):
            self.refresh()
        if own:
            self.main.set_skip(own, "print", True)
            self.main.statusBar().showMessage(
                f"{len(own)} card(s) won't be printed – right-click → Print it again", 8000)
            self.refresh()

    def _menu(self, pos):
        it = self.grid.itemAt(pos)
        if it is None:
            return
        if not it.isSelected():
            self.grid.clearSelection()
            it.setSelected(True)
        rows = self._selected()
        index = it.data(Qt.UserRole)
        real = [s.real for s in self.rows if s.index in rows and s.real is not None]
        m = QMenu(self)
        if real:
            real_card_actions.fill_menu(m, self.main, real, self, then=self.refresh,
                                        own_then=self._made_own)
        else:
            self._own_menu(m, rows)
        m.addSeparator()
        m.addAction("View front and back", lambda: self._view_index(index))
        m.exec(self.grid.viewport().mapToGlobal(pos))
        m.deleteLater()

    def _made_own(self, first_row=None):
        self.refresh()
        if first_row is not None:
            self.main.cards_tab.reload(first_row)

    def _own_menu(self, m: QMenu, rows: list[int]):
        from mse_studio.gui import back_choice
        from mse_studio.pipeline import stages
        p = self.main.project
        m.addAction("Copies…", lambda: self._set_quantity(rows))
        cards = [p.set.cards[r] for r in rows if r < len(p.set.cards)]
        if cards and all(not stages.is_printed(p, c) for c in cards):
            m.addAction("Print it again" if len(rows) == 1 else "Print them again",
                        lambda: self._skip(rows, False))
        else:
            m.addAction("Don't print it" if len(rows) == 1 else "Don't print them",
                        lambda: self._skip(rows, True))
        a = m.addAction("Its picture already has MPC's margin")
        a.setCheckable(True)
        a.setChecked(bool(cards) and all(stages.has_margin(p, c) for c in cards))
        a.toggled.connect(lambda on: self._margin(rows, on))
        back = m.addMenu("Back")
        back_choice.fill_menu(back, self, p, rows, self.make_backs)

    def _skip(self, rows: list[int], skip: bool):
        self.main.set_skip(rows, "print", skip)
        self.refresh()

    def _margin(self, rows: list[int], on: bool):
        self.main.set_margin(rows, on)
        self.refresh()

    def _set_quantity(self, rows: list[int]):
        self.main.cards_tab.set_copies(rows)
        self.refresh()

    def _view(self, it):
        self._view_index(it.data(Qt.UserRole))

    def _view_index(self, index):
        from mse_studio.gui.image_viewer import ImageViewer
        s = next((r for r in self.rows if r.index == index), None)
        if s is None:
            return
        paths = [x for x in (s.front, s.back or order.deck_back(self.main.project)) if x]
        if paths:
            v = ImageViewer(self, paths, 0)
            try:
                v.exec()
            finally:
                v.deleteLater()

    # ------------------------------------------------------------- printing
    def print_home(self):
        self.main.print_home(self._selected())

    def make_backs(self, rows: Optional[list[int]] = None):
        self.main.make_backs(rows)

    def proof_pdf(self):
        self.main.proof_sheet()

    def send(self):
        main = self.main
        if main.project is None or not main.save():
            return
        p = main.project
        exe = self._autofill()
        if exe is None:
            self._get_autofill(then=self._send_after_install)
            return
        if not exe.exists():
            error(self, "Send to MPC", f"mpc-autofill wasn't found:\n{exe}\n\nChoose a copy "
                                       f"with Change… next to mpc-autofill.")
            return
        self.refresh()
        if order.deck_back(p) is None and QMessageBox.question(
                self, "Send to MPC", "There's no card back yet, so cards without their own "
                                     "back would get MPC's default back. Send anyway?\n\n"
                                     "(Choose one with Card back…)") != QMessageBox.Yes:
            return
        bad = [s for s in self.rows if s.problems and s.quantity]
        ready = [s for s in self.rows if s.quantity and s.front]
        if not ready:
            error(self, "Send to MPC", "No print-ready cards yet – run step 3 (Print) first.")
            return
        if bad and QMessageBox.question(
                self, "Send to MPC", f"{len(bad)} card(s) need attention (see the list under "
                                     f"the cards). Send the order anyway? Cards without a print "
                                     f"file are left out.") != QMessageBox.Yes:
            return
        xml = order.order_xml(p, self._order_dir())
        total = sum(s.quantity for s in ready)
        box = QMessageBox(self)
        box.setWindowTitle("Send to MPC")
        box.setText(f"<b>{total} cards</b> (MPC order size {order.bracket(total)}) are ready "
                    f"to upload.")
        box.setInformativeText(
            "mpc-autofill opens in its own window and starts your browser. Answer its "
            "questions there (site, browser…), log in to MakePlayingCards if it asks, then let "
            "it upload every front and back. It stops before checkout so you can check the "
            "order and pay.\n\nThe order file is " + str(xml))
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        try:
            if box.exec() != QMessageBox.Ok:
                return
        finally:
            box.deleteLater()
        how = SimpleNamespace(mpc_browser=self.prefs["browser"],
                              mpc_site=getattr(main.settings, "mpc_site", ""))
        try:
            order.launch_autofill(exe, xml.parent, how)
        except OSError as e:
            error(self, "Send to MPC", f"mpc-autofill couldn't start: {e}")
            return
        main.statusBar().showMessage("mpc-autofill is running in its own window", 10000)

    def _send_after_install(self, _page=None):
        try:
            self.refresh()
        except RuntimeError:
            return
        if self._autofill() is not None:
            info(self, "Send to MPC", "mpc-autofill is installed – press Send to MPC again.")
