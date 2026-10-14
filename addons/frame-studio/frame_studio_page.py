"""Frame studio: make a Magic Set Editor frame from pictures – the blank frames
a proxy maker shares or sells (one picture per colour), or your own – and
your cards can use it like any other frame. Proxy decks sends a deck's
templates here (right-click a deck → This deck's frame).

Network: none. Files: the pictures you pick (read), the add-on's data folder,
and MSE's data folder – through MSE Studio's frame-pack installer."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QColorDialog, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFontComboBox, QFormLayout,
                               QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsView, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton,
                               QRadioButton, QScrollArea, QSplitter, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from mse_studio.gui import icons
from mse_studio.gui.common import Job, error, forget, start
from mse_studio.gui.nav import page_header

from . import framegen as fg

BOX_COLOURS = {"name": "#e8b923", "cost": "#e8b923", "art": "#3fa9f5", "type": "#7ed957",
               "rarity": "#7ed957", "text": "#ff7a59", "pt": "#c07cff", "ptbox": "#c07cff",
               "artist": "#9aa0a6", "credit": "#9aa0a6"}
COLOUR_LABELS = [("name", "Name"), ("type", "Type line"), ("text", "Rules text"),
                 ("pt", "Power / toughness"), ("artist", "Artist and credit lines")]
FONT_LABELS = [("title", "Name and type line"), ("text", "Rules text"),
               ("italic", "Rules text (italic)"), ("pt", "Power / toughness"),
               ("info", "Artist and credit lines")]


def _qimage(img) -> QImage:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    return QImage(data, img.width, img.height, img.width * 4, QImage.Format_RGBA8888).copy()


def _pixmap(path: Path, h: int = 0) -> QPixmap:
    pm = QPixmap(str(path))
    if pm.isNull():
        try:
            pm = QPixmap.fromImage(_qimage(fg.open_picture(path)))
        except Exception:  # noqa: BLE001
            return QPixmap()
    return pm.scaledToHeight(h, Qt.SmoothTransformation) if h and not pm.isNull() else pm


# ------------------------------------------------------------------ boxes on the frame
class BoxItem(QGraphicsRectItem):
    """A box you can move (drag it) and size (drag its bottom-right corner)."""
    HANDLE = 0.035          # of the card's width

    def __init__(self, key: str, rect: QRectF, bounds: QRectF, on_change):
        super().__init__(rect)
        self.key, self.bounds, self.on_change = key, bounds, on_change
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(2 if key != "art" else 1)
        self._drag = None
        col = QColor(BOX_COLOURS.get(key, "#ffffff"))
        self.pen_col = col
        fill = QColor(col)
        fill.setAlpha(40 if key != "art" else 22)
        self.setBrush(QBrush(fill))
        self.setToolTip(f"{fg.BOX_NAMES[key]} – drag to move, drag the corner to size")

    def _handle(self) -> float:
        return self.bounds.width() * self.HANDLE

    def paint(self, qp, option, widget=None):
        r = self.rect()
        pen = QPen(self.pen_col, max(2.0, self.bounds.width() / 300))
        if self.isSelected():
            pen.setStyle(Qt.DashLine)
        qp.setPen(pen)
        qp.setBrush(self.brush())
        qp.drawRect(r)
        h = self._handle()
        qp.fillRect(QRectF(r.right() - h, r.bottom() - h, h, h), self.pen_col)
        f = QFont(qp.font())
        f.setPixelSize(max(8, int(self.bounds.width() / 32)))
        f.setBold(True)
        qp.setFont(f)
        qp.setPen(QColor("#ffffff"))
        qp.drawText(r.adjusted(4, 2, -4, -2), Qt.AlignLeft | Qt.AlignTop,
                    fg.BOX_NAMES[self.key])

    def hoverMoveEvent(self, e):
        r, h = self.rect(), self._handle() * 1.6
        near = e.pos().x() > r.right() - h and e.pos().y() > r.bottom() - h
        self.setCursor(Qt.SizeFDiagCursor if near else Qt.SizeAllCursor)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        r, h = self.rect(), self._handle() * 1.6
        size = e.pos().x() > r.right() - h and e.pos().y() > r.bottom() - h
        self._drag = ("size" if size else "move", e.scenePos(), QRectF(r))
        self.setSelected(True)
        e.accept()

    def mouseMoveEvent(self, e):
        if not self._drag:
            return super().mouseMoveEvent(e)
        kind, p0, r0 = self._drag
        d = e.scenePos() - p0
        b = self.bounds
        if kind == "move":
            r = r0.translated(d)
            dx = max(b.left() - r.left(), 0) + min(b.right() - r.right(), 0)
            dy = max(b.top() - r.top(), 0) + min(b.bottom() - r.bottom(), 0)
            r.translate(dx, dy)
        else:
            mn = b.width() * 0.02
            w = min(max(mn, r0.width() + d.x()), b.right() - r0.left())
            h = min(max(mn, r0.height() + d.y()), b.bottom() - r0.top())
            r = QRectF(r0.left(), r0.top(), w, h)
        self.prepareGeometryChange()
        self.setRect(r)

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = None
            b, r = self.bounds, self.rect()
            self.on_change(self.key, [round(r.left() / b.width(), 5),
                                      round(r.top() / b.height(), 5),
                                      round(r.width() / b.width(), 5),
                                      round(r.height() / b.height(), 5)])
        super().mouseReleaseEvent(e)


class LayoutView(QGraphicsView):
    """A frame picture with the boxes where the text and art go."""

    def __init__(self, on_change):
        super().__init__()
        self.on_change = on_change
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#2b2b2b"))
        self.items_by_key: dict = {}
        self.bounds = QRectF(0, 0, 375, 523)

    def show_frame(self, picture: Optional[QPixmap], boxes: dict, keys: list):
        sc = self.scene()
        sc.clear()
        self.items_by_key = {}
        if picture is not None and not picture.isNull():
            pix = QGraphicsPixmapItem(picture)
            pix.setTransformationMode(Qt.SmoothTransformation)
            pix.setZValue(0)
            sc.addItem(pix)
            self.bounds = QRectF(0, 0, picture.width(), picture.height())
        else:
            self.bounds = QRectF(0, 0, 750, 1046)
            sc.addRect(self.bounds, QPen(QColor("#666")), QBrush(QColor("#3a3a3a")))
        b = self.bounds
        for k in keys:
            x, y, w, h = boxes[k]
            it = BoxItem(k, QRectF(x * b.width(), y * b.height(), w * b.width(), h * b.height()),
                         b, self.on_change)
            sc.addItem(it)
            self.items_by_key[k] = it
        sc.setSceneRect(b)
        self.fitInView(b, Qt.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fitInView(self.bounds, Qt.KeepAspectRatio)


# ------------------------------------------------------------------ a new frame
class NewFrameDialog(QDialog):
    """Pictures in, a colour for each (guessed from their names), a name."""

    def __init__(self, parent, files: Optional[list] = None, name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("A new frame from pictures")
        self.resize(760, 620)
        self.rows: list = []           # (label, source: Path or (Path, layer index))
        self._layers: dict = {}        # psd path → [(name, image)]
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("e.g. Death Note – Vibrant")
        f.addRow("Name of the frame", self.name)
        lay.addLayout(f)
        hint = QLabel("The blank frames: one picture per colour (White, Blue, Black, Red, Green, "
                      "Gold, Artifact, Colourless, and Land if there is one). Their names "
                      "usually say which is which – check the guesses below. Photoshop files "
                      "are opened layer by layer.")
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        lay.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Picture", "It's the frame for"])
        self.tree.setIconSize(QSize(42, 58))
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 420)
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        for label, fn, icon in (("Add pictures…", self.add_files, "add_photo_alternate"),
                                ("Add a folder…", self.add_folder, "folder_open"),
                                ("Add a Photoshop file…", self.add_psd, "layers")):
            b = QPushButton(label)
            icons.set_icon(b, icon)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.status = QLabel()
        self.status.setObjectName("Hint")
        lay.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Make the frame")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.add_paths([Path(p) for p in files or []])

    # pictures in
    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Frame pictures", "", "Pictures (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff "
                                        "*.psd);;All files (*)")
        self.add_paths([Path(p) for p in paths])

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "A folder of frame pictures")
        if folder:
            self.add_paths(fg.pictures_in(Path(folder)))
            if not self.name.text().strip():
                self.name.setText(Path(folder).name)

    def add_psd(self):
        path, _ = QFileDialog.getOpenFileName(self, "A Photoshop file", "",
                                              "Photoshop files (*.psd)")
        if path:
            self.add_paths([Path(path)])

    def add_paths(self, paths: list):
        for p in paths:
            if p.suffix.lower() == ".psd":
                try:
                    layers = fg.psd_layers(p)
                except Exception as e:  # noqa: BLE001
                    self.status.setText(f"Couldn't read {p.name}: {e}")
                    continue
                self._layers[str(p)] = layers
                for i, (lname, img) in enumerate(layers):
                    self._add_row(f"{p.name} › {lname}", (p, i), lname, img)
            elif p.is_file():
                self._add_row(p.name, p, p.name, None)
        self._count()

    def _add_row(self, label: str, source, guess_from: str, img):
        it = QTreeWidgetItem(self.tree, [label, ""])
        try:
            pm = QPixmap.fromImage(_qimage(img)) if img is not None else _pixmap(source)
            if not pm.isNull():
                it.setIcon(0, QIcon(pm.scaledToHeight(58, Qt.SmoothTransformation)))
                if not fg.is_card_shaped((pm.width(), pm.height())):
                    it.setToolTip(0, "Not card-shaped – probably not a frame")
        except Exception:  # noqa: BLE001
            pass
        combo = QComboBox()
        combo.addItem("– not used –", "")
        for k, v in fg.SLOTS:
            combo.addItem(v, k)
        for k, v in fg.PT_SLOTS:
            combo.addItem(f"P/T box – {v}", k)
        guess = fg.guess_slot(guess_from) or ""
        if guess and any(r[2].currentData() == guess for r in self.rows):
            guess = ""                         # one picture per colour
        combo.setCurrentIndex(max(0, combo.findData(guess)))
        combo.currentIndexChanged.connect(self._count)
        self.tree.setItemWidget(it, 1, combo)
        self.rows.append((label, source, combo))

    def _count(self, *_):
        n = sum(1 for r in self.rows if r[2].currentData())
        self.status.setText(f"{len(self.rows)} picture(s), {n} used" if self.rows else
                            "Add the frame pictures.")

    def chosen(self) -> dict:
        """{slot: path or PIL image}"""
        out = {}
        for _label, src, combo in self.rows:
            slot = combo.currentData()
            if not slot or slot in out:
                continue
            if isinstance(src, tuple):
                path, i = src
                out[slot] = self._layers[str(path)][i][1]
            else:
                out[slot] = src
        return out

    def _ok(self):
        ch = self.chosen()
        if not any(k in ch for k in fg.BASE + ["l"]):
            error(self, "Frame studio", "Pick which picture is which colour (at least one).")
            return
        if not self.name.text().strip():
            error(self, "Frame studio", "Give the frame a name.")
            return
        self.accept()


# ------------------------------------------------------------------ the page
class FrameStudioPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._jobs: list = []
        self.frame: Optional[fg.Frame] = None
        self._loading = False
        lay = QVBoxLayout(self)
        lay.addWidget(page_header(
            "Frame studio", "Make an MSE frame from pictures – the blank frames a proxy maker "
                            "shares or sells (one per colour), or your own. Place the name, "
                            "mana cost, art and text on it, and your cards can use it like any "
                            "other frame."))
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("<b>Frames you made</b>"))
        self.list = QListWidget()
        self.list.setIconSize(QSize(54, 75))
        self.list.currentItemChanged.connect(self._picked)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)
        lv.addWidget(self.list, 1)
        row = QHBoxLayout()
        b = QPushButton("New frame…")
        b.setProperty("kind", "primary")
        icons.set_icon(b, "add")
        b.setToolTip("From the blank frame pictures (a folder, picture files or a Photoshop "
                     "file)")
        b.clicked.connect(lambda: self.start_from())
        row.addWidget(b)
        self.remove_btn = QPushButton("Remove")
        icons.set_icon(self.remove_btn, "delete")
        self.remove_btn.setToolTip("Take the frame out of MSE and out of this list (cards "
                                   "using it then need another frame)")
        self.remove_btn.clicked.connect(self.remove)
        row.addWidget(self.remove_btn)
        lv.addLayout(row)
        try:
            from mse_studio.gui.common import delete_key
            delete_key(self.list, self.remove)
        except ImportError:
            pass
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Name"))
        self.name = QLineEdit()
        self.name.editingFinished.connect(self._renamed)
        row.addWidget(self.name, 1)
        self.state = QLabel()
        self.state.setObjectName("Hint")
        row.addWidget(self.state)
        rv.addLayout(row)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._pictures_tab(), "Pictures")
        self.tabs.addTab(self._layout_tab(), "Where things go")
        self.tabs.addTab(self._text_tab(), "Text")
        rv.addWidget(self.tabs, 1)
        row = QHBoxLayout()
        self.install_btn = QPushButton("Save and add to MSE")
        self.install_btn.setProperty("kind", "primary")
        icons.set_icon(self.install_btn, "save")
        self.install_btn.setToolTip("Puts the frame in MSE's frames – the Cards page's frame "
                                    "list has it then")
        self.install_btn.clicked.connect(self.install)
        row.addWidget(self.install_btn)
        self.try_btn = QPushButton("Try it on a card")
        icons.set_icon(self.try_btn, "visibility")
        self.try_btn.setToolTip("MSE draws the card you're editing in this frame (your card "
                                "isn't changed)")
        self.try_btn.clicked.connect(self.try_it)
        row.addWidget(self.try_btn)
        self.use_btn = QPushButton("Use it on my selected cards")
        icons.set_icon(self.use_btn, "style")
        self.use_btn.setToolTip("The cards selected on the Cards page get this frame (Undo "
                                "brings their old one back)")
        self.use_btn.clicked.connect(self.use_on_selected)
        row.addWidget(self.use_btn)
        row.addStretch(1)
        rv.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        rv.addWidget(self.status)
        split.addWidget(right)
        split.setSizes([260, 900])
        lay.addWidget(split, 1)
        self.fill()

    # ------------------------------------------------------------ MSE Studio calls these
    def load(self):
        self._buttons()

    def refresh(self):
        self._buttons()

    def shutdown(self):
        forget(self._jobs)

    # ------------------------------------------------------------ tabs
    def _pictures_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel("The frame's picture for each colour. A colour without one uses the "
                      "Colourless picture (or the first one there is); lands use the Land "
                      "picture, else their colour's.")
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        v.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.slot_grid = QGridLayout(inner)
        self.slot_widgets: dict = {}
        r = 0
        for k, label in fg.SLOTS + fg.PT_SLOTS:
            if k == "pt-w":
                r += 1
                self.pt_label = QLabel("<b>P/T boxes</b> – only if the maker has them as separate "
                                       "pictures (most frames have the box in the picture)")
                self.pt_label.setWordWrap(True)
                self.slot_grid.addWidget(self.pt_label, r, 0, 1, 4)
                r += 1
            thumb = QLabel()
            thumb.setFixedSize(54, 75)
            thumb.setAlignment(Qt.AlignCenter)
            thumb.setStyleSheet("QLabel { border: 1px solid palette(mid); }")
            self.slot_grid.addWidget(thumb, r, 0)
            self.slot_grid.addWidget(QLabel(label if not k.startswith("pt-") else
                                            f"P/T box – {label}"), r, 1)
            b = QPushButton("Choose…")
            b.clicked.connect(lambda _c=False, k=k: self.choose_picture(k))
            self.slot_grid.addWidget(b, r, 2)
            c = QPushButton("Clear")
            c.setProperty("kind", "text")
            c.clicked.connect(lambda _c=False, k=k: self.set_picture(k, None))
            self.slot_grid.addWidget(c, r, 3)
            self.slot_widgets[k] = thumb
            r += 1
        self.slot_grid.setColumnStretch(1, 1)
        scroll.setWidget(inner)
        v.addWidget(scroll, 1)
        return w

    def _layout_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("Show the"))
        self.show_slot = QComboBox()
        self.show_slot.currentIndexChanged.connect(lambda *_: self._draw_layout())
        row.addWidget(self.show_slot)
        row.addWidget(QLabel("frame"))
        row.addStretch(1)
        b = QPushButton("The art fills the whole card")
        b.setToolTip("For full-art frames: the art goes under the whole frame")
        b.clicked.connect(self._full_art)
        row.addWidget(b)
        b = QPushButton("Put the boxes back")
        b.setToolTip("Where a modern (M15) frame has them")
        b.clicked.connect(self._reset_boxes)
        row.addWidget(b)
        v.addLayout(row)
        self.view = LayoutView(self._box_moved)
        v.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("The art goes"))
        self.art_group = QButtonGroup(self)
        for key, label in fg.ART_MODES.items():
            rb = QRadioButton(label)
            rb.setProperty("mode", key)
            self.art_group.addButton(rb)
            row.addWidget(rb)
        self.art_group.buttonToggled.connect(self._art_mode)
        row.addStretch(1)
        v.addLayout(row)
        hint = QLabel("Drag a box to move it, drag its corner to size it. Most frames have a "
                      "see-through art window – the art goes under the frame then.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        return w

    def _text_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.colour_btns: dict = {}
        for key, label in COLOUR_LABELS:
            b = QPushButton()
            b.setFixedWidth(120)
            b.clicked.connect(lambda _c=False, k=key: self._pick_colour(k))
            f.addRow(f"{label} colour", b)
            self.colour_btns[key] = b
        self.font_boxes: dict = {}
        for key, label in FONT_LABELS:
            fb = QFontComboBox()
            fb.setEditable(True)
            fb.currentTextChanged.connect(lambda t, k=key: self._font(k, t))
            f.addRow(f"{label} font", fb)
            self.font_boxes[key] = fb
        hint = QLabel("MSE's own Magic fonts (Beleren, MPlantin) come with the Full Magic Pack "
                      "– Advanced → Fonts shows which are installed.")
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        f.addRow(hint)
        return w

    # ------------------------------------------------------------ the list
    def fill(self, keep: str = ""):
        keep = keep or (self.frame.slug if self.frame else "")
        self.list.blockSignals(True)
        self.list.clear()
        data = self._data_dir()
        pick = None
        for fr in fg.load_frames():
            it = QListWidgetItem(fr.name + ("" if fg.is_installed(fr, data) else
                                            "\n(not in MSE yet)"))
            it.setData(Qt.UserRole, fr.slug)
            first = next((fr.pictures[k] for k in fg.BASE + ["l"] if fr.pictures.get(k)), None)
            if first:
                it.setIcon(QIcon(_pixmap(fg.frame_dir(fr.slug) / first, 75)))
            it.setToolTip(f"Cards use it as {fr.style_name}" +
                          (f"\nFrom {fr.made_from}" if fr.made_from else ""))
            self.list.addItem(it)
            if fr.slug == keep:
                pick = it
        self.list.blockSignals(False)
        if pick is None and self.list.count():
            pick = self.list.item(0)
        if pick is not None:
            self.list.setCurrentItem(pick)
            self._picked(pick, None)
        else:
            self._picked(None, None)

    def _data_dir(self) -> Optional[Path]:
        from mse_studio.core import styles
        return styles.data_dir(getattr(self.main.settings, "mse_path", "") or "")

    def _picked(self, cur, _prev):
        slug = cur.data(Qt.UserRole) if cur is not None else None
        self.frame = next((f for f in fg.load_frames() if f.slug == slug), None) if slug else None
        self._show_frame()

    def _show_frame(self):
        fr = self.frame
        self._loading = True
        self.name.setText(fr.name if fr else "")
        for k, thumb in self.slot_widgets.items():
            pic = fr.pictures.get(k) if fr else None
            thumb.setPixmap(_pixmap(fg.frame_dir(fr.slug) / pic, 73) if pic else QPixmap())
        self.show_slot.blockSignals(True)
        self.show_slot.clear()
        if fr:
            for k, label in fg.SLOTS:
                if fr.pictures.get(k):
                    self.show_slot.addItem(label, k)
        self.show_slot.blockSignals(False)
        for b in self.art_group.buttons():
            b.setChecked(bool(fr) and b.property("mode") == fr.art)
        for k, b in self.colour_btns.items():
            col = fr.colour(k) if fr else "#000000"
            b.setText(col)
            b.setStyleSheet(f"QPushButton {{ background: {col}; color: "
                            f"{'#000' if QColor(col).lightness() > 128 else '#fff'}; }}")
        for k, fb in self.font_boxes.items():
            fb.setCurrentText(fr.font(k) if fr else fg.DEFAULT_FONTS[k])
        self._loading = False
        self._draw_layout()
        self._buttons()

    def _draw_layout(self):
        fr = self.frame
        if fr is None:
            self.view.scene().clear()
            return
        slot = self.show_slot.currentData() or next(
            (k for k in fg.BASE + ["l"] if fr.pictures.get(k)), None)
        pm = None
        if slot and fr.pictures.get(slot):
            try:
                pm = QPixmap.fromImage(_qimage(fg.card_picture(fg.frame_dir(fr.slug) /
                                                               fr.pictures[slot])))
            except Exception:  # noqa: BLE001
                pm = None
        keys = [k for k, _ in fg.BOXES
                if k != "ptbox" or any(p.startswith("pt-") for p in fr.pictures)]
        self.view.show_frame(pm, {k: fr.box(k) for k in keys}, keys)

    def _buttons(self):
        fr = self.frame
        data = self._data_dir()
        has = fr is not None
        for w in (self.name, self.tabs, self.install_btn, self.remove_btn):
            w.setEnabled(has)
        installed = has and fg.is_installed(fr, data)
        p = self.main.project
        self.try_btn.setEnabled(installed and p is not None and bool(p.set.cards))
        self.use_btn.setEnabled(installed and p is not None)
        if not has:
            self.state.setText("")
            self.status.setText("Make a frame from its pictures: New frame…" if
                                not self.list.count() else "")
        else:
            self.state.setText(("In MSE as " + fr.style_name) if installed else
                               "Not in MSE yet – Save and add to MSE")
        if data is None:
            self.status.setText("MSE wasn't found – set where it is in Settings, then frames can "
                                "be added to it.")

    # ------------------------------------------------------------ changes
    def _changed(self):
        if self.frame is None or self._loading:
            return
        fg.save_frame(self.frame)
        if fg.is_installed(self.frame, self._data_dir()):
            self.state.setText("Changed – Save and add to MSE again to update it")

    def _renamed(self):
        if self.frame is not None and self.name.text().strip() and \
                self.name.text().strip() != self.frame.name:
            self.frame.name = self.name.text().strip()
            self._changed()
            self.fill(self.frame.slug)

    def _box_moved(self, key: str, box: list):
        if self.frame is not None:
            self.frame.boxes[key] = box
            self._changed()

    def _full_art(self):
        if self.frame is None:
            return
        self.frame.boxes["art"] = list(fg.FULL_ART["art"])
        self.frame.art = "under"
        self._changed()
        self._show_frame()

    def _reset_boxes(self):
        if self.frame is None:
            return
        self.frame.boxes = {}
        self._changed()
        self._draw_layout()

    def _art_mode(self, button, on: bool):
        if on and self.frame is not None and not self._loading:
            self.frame.art = button.property("mode")
            self._changed()

    def _pick_colour(self, key: str):
        if self.frame is None:
            return
        col = QColorDialog.getColor(QColor(self.frame.colour(key)), self, "Text colour")
        if col.isValid():
            self.frame.colours[key] = col.name()
            if key == "artist":
                self.frame.colours["credit"] = col.name()
            self._changed()
            self._show_frame()

    def _font(self, key: str, family: str):
        if self.frame is not None and not self._loading and family.strip():
            self.frame.fonts[key] = family.strip()
            self._changed()

    def choose_picture(self, slot: str):
        if self.frame is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, f"The frame for {dict(fg.SLOTS + fg.PT_SLOTS).get(slot, slot)}", "",
            "Pictures (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.psd)")
        if not path:
            return
        src = Path(path)
        if src.suffix.lower() == ".psd":
            dlg = NewFrameDialog(self, [src], self.frame.name)
            dlg.setWindowTitle("Pick the layer")
            if not dlg.exec():
                return
            picked = list(dlg.chosen().values()) or [None]
            self.set_picture(slot, picked[0])
            return
        self.set_picture(slot, src)

    def set_picture(self, slot: str, src):
        if self.frame is None:
            return
        try:
            fg.set_pictures(self.frame, {slot: src})
        except Exception as e:  # noqa: BLE001
            error(self, "Frame studio", f"Couldn't use that picture: {e}")
            return
        self._changed()
        self._show_frame()

    # ------------------------------------------------------------ new and removing
    def start_from(self, files: Optional[list] = None, name: str = "",
                   proxy_deck: str = "") -> Optional[fg.Frame]:
        """A new frame from pictures (Proxy decks sends a deck's templates
        here). Returns it, or None if you cancelled."""
        dlg = NewFrameDialog(self, files, name)
        if not dlg.exec():
            return None
        frame = fg.new_frame(dlg.name.text(), dlg.chosen(),
                             made_from=str(Path(files[0]).parent) if files else "")
        frame.proxy_deck = proxy_deck
        fg.save_frame(frame)
        self.fill(frame.slug)
        self.tabs.setCurrentIndex(1)
        self.status.setText("Check where the name, art and text go (drag the boxes), then "
                            "Save and add to MSE.")
        return frame

    def _list_menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        self.list.setCurrentItem(it)
        m = QMenu(self)
        m.addAction(icons.icon("save"), "Save and add to MSE", self.install)
        m.addAction(icons.icon("content_copy"), "Make a copy", self.copy_frame)
        a = m.addAction(icons.icon("delete"), "Remove", self.remove)
        a.setShortcut(Qt.Key_Delete)
        m.exec(self.list.viewport().mapToGlobal(pos))

    def copy_frame(self):
        import shutil
        fr = self.frame
        if fr is None:
            return
        taken = {f.slug for f in fg.load_frames()}
        new = fg.Frame(**{**fr.__dict__})
        new.name = fr.name + " (copy)"
        new.slug = fg.slug_for(new.name, taken)
        shutil.copytree(fg.frame_dir(fr.slug), fg.frame_dir(new.slug))
        fg.save_frame(new)
        self.fill(new.slug)

    def remove(self):
        fr = self.frame
        if fr is None:
            return
        try:
            from mse_studio.gui.common import ask_delete
        except ImportError:
            def ask_delete(_p, _t, _title=""):
                return True
        if not ask_delete(self, f"Remove the frame {fr.name}? It's taken out of MSE too (kept "
                                "in the add-on's folder); cards using it need another frame."):
            return
        try:
            fg.uninstall(fr, self._data_dir())
        except Exception as e:  # noqa: BLE001
            error(self, "Frame studio", f"Couldn't take it out of MSE: {e}")
            return
        fg.delete_frame(fr.slug)
        self.frame = None
        self.fill()
        self._frames_changed()

    # ------------------------------------------------------------ into MSE
    def install(self):
        fr = self.frame
        data = self._data_dir()
        if fr is None:
            return
        if data is None:
            error(self, "Frame studio", "MSE wasn't found – set where it is in Settings first.")
            return
        fg.save_frame(fr)
        frame = fg.Frame(**{**fr.__dict__})

        def work(progress=None, cancel=None):
            progress(0, 0, f"Making {frame.name}…")
            return fg.install(frame, data)

        self.status.setText("Making the frame…")
        job = Job(work, label=f"Adding {fr.name} to MSE")
        job.signals.finished.connect(self._installed)
        job.signals.failed.connect(self._failed)
        self._jobs.append(start(job))

    def _installed(self, style: str):
        try:
            self.status.setText(f"Added to MSE – cards can use it: pick “{self.frame.name}” "
                                "in the Cards page's frame list, or Use it on my selected cards.")
            self.fill()
            self._frames_changed()
        except RuntimeError:
            return

    def _failed(self, msg: str):
        try:
            self.status.setText("")
            error(self, "Frame studio", msg.splitlines()[0])
        except RuntimeError:
            return

    def _frames_changed(self):
        fn = getattr(self.main, "frames_changed", None)
        if callable(fn):
            fn()

    def use_on_selected(self):
        fr, p = self.frame, self.main.project
        if fr is None or p is None:
            return
        tab = self.main.cards_tab
        rows = tab.selected_rows()
        if not rows:
            error(self, "Frame studio", "Select the cards on the Cards page first.")
            return
        tab.editor.commit()
        for r in rows:
            p.set.cards[r].set_raw("stylesheet", fr.style_name)
        p.dirty = True
        self.main.record(f"Frame studio · {len(rows)} card(s) in {fr.name}", row=rows[0])
        tab.reload(rows[0])
        self.main.update_title()
        self.status.setText(f"{len(rows)} card(s) use {fr.name} now (Undo puts their old frame "
                            "back).")

    def try_it(self):
        fr, p = self.frame, self.main.project
        if fr is None or p is None or not p.set.cards:
            return
        card = getattr(self.main.cards_tab.editor, "card", None) or p.set.cards[0]
        from mse_studio.pipeline.preview import mini_set, variant_set
        text, files = mini_set(p.set, card)
        text = variant_set(text, stylesheet=fr.style_name)
        renderer = self.main.previewer("frame-studio")

        def work(progress=None, cancel=None):
            progress(0, 0, "MSE is drawing the card…")
            return str(renderer.render(text, files, 200))

        job = Job(work, label="Trying the frame")
        job.signals.finished.connect(self._tried)
        job.signals.failed.connect(self._failed)
        self._jobs.append(start(job))

    def _tried(self, path: str):
        try:
            import shutil
            keep = fg._data() / "tried.png"
            shutil.copyfile(path, keep)
            from mse_studio.gui.image_viewer import ImageViewer
            ImageViewer(self, [keep]).exec()
        except RuntimeError:
            return
