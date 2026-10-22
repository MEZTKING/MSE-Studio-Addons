"""Art extensions: one picture across several cards, so the art carries on
from a card to the cards beside it (a panorama, a scene split over a card and
its art cards). The cards are kept in groups – which cards, in which order,
the picture and how they lie on it – in the deck's ``art_extensions.json``;
*Put the art on the cards* gives each card its part of the picture."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QPushButton, QSizePolicy, QSlider, QSpinBox, QSplitter,
                               QVBoxLayout, QWidget)

from mse_studio.gui.common import Job, error, forget, start
from mse_studio.gui.icons import set_icon
from mse_studio.gui.nav import page_header

try:
    from . import extend
except ImportError:                     # loaded on its own
    import extend

ZONE = "Art extensions"                 # the zone new extension cards start in
PREVIEW_MAX = 1600                      # the preview's picture, at most this many pixels
PICTURES = "Pictures (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"
NO_TEXT = ("casting_cost", "super_type", "sub_type", "rule_text", "flavor_text", "power",
           "toughness", "loyalty")


def _zones_here() -> bool:
    """MSE Studio has zones of the deck's own (0.25.0, later builds)."""
    from mse_studio.core import versions
    return hasattr(versions, "add_zone")


def read_preview(path: str, progress=None, cancel=None):
    """For a worker thread: (small picture as a QImage, (width, height) of the
    picture itself – upright, as the crops are made)."""
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        try:
            from mse_studio.core.art import upright
            im = upright(im)
        except ImportError:
            im = ImageOps.exif_transpose(im)
        size = im.size
        im = im.convert("RGBA")
        im.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
        data = im.tobytes("raw", "RGBA")
        img = QImage(data, im.width, im.height, im.width * 4, QImage.Format_RGBA8888).copy()
    return img, size


def cut_parts(source: str, crops: list, name: str, progress=None, cancel=None) -> tuple:
    """For a worker thread: each card's part of the picture as card art bytes
    – (source, name, [(card id, crop, bytes)])."""
    from mse_studio.core.art import crop_image
    out = []
    for k, (cid, crop) in enumerate(crops):
        if progress:
            progress(k, len(crops), "Cutting the picture")
        out.append((cid, crop, crop_image(Path(source), crop)))
    return source, name, out


class Preview(QWidget):
    """The picture with the cards on it: each card's outline, its art box
    clear, the rest dimmed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap: QPixmap | None = None
        self.size_px = (0, 0)
        self.places: list = []
        self.note = ""
        self.setMinimumSize(320, 260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def show_plan(self, pixmap, size_px, places, note: str = "") -> None:
        self.pixmap, self.size_px, self.places, self.note = pixmap, size_px, places, note
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, self.palette().base())
        pw, ph = self.size_px
        if self.pixmap is None or not pw or not ph:
            p.setPen(self.palette().text().color())
            p.drawText(r.adjusted(16, 16, -16, -16), Qt.AlignCenter | Qt.TextWordWrap,
                       self.note or "Choose a picture to see the cards on it.")
            return
        k = min((r.width() - 8) / pw, (r.height() - 8) / ph)
        ox, oy = (r.width() - pw * k) / 2, (r.height() - ph * k) / 2
        whole = QRectF(ox, oy, pw * k, ph * k)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawPixmap(whole, self.pixmap, QRectF(self.pixmap.rect()))

        def at(b):
            return QRectF(ox + b[0] * k, oy + b[1] * k, b[2] * k, b[3] * k)
        shade = QPainterPath()
        shade.addRect(whole)
        for pl in self.places:
            hole = QPainterPath()
            hole.addRect(at(pl["art"]))
            shade = shade.subtracted(hole)
        p.fillPath(shade, QColor(0, 0, 0, 150))
        accent = self.palette().highlight().color()
        for n, pl in enumerate(self.places, 1):
            card = at(pl["card"])
            p.setPen(QPen(QColor(255, 255, 255, 220), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(card, 4, 4)
            p.setPen(QPen(accent, 2))
            p.drawRect(at(pl["art"]))
            badge = QRectF(card.left() + 4, card.top() + 4, 22, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(badge, 4, 4)
            p.setPen(QColor(255, 255, 255))
            p.drawText(badge, Qt.AlignCenter, str(n))


class ArtExtensionsPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.groups: list = []
        self.g = None                       # the group shown
        self.boxes: list = []               # its cards' art boxes (mm), in order
        self.rows: list = []                # its cards' places in the deck (-1: gone)
        self.picture = None                 # (path, QPixmap, (w, h)) of the preview
        self._jobs: list = []
        self._filling = False
        lay = QVBoxLayout(self)
        lay.addWidget(page_header(
            "Extend art",
            "Art extensions – one picture across several cards: the art carries on from one "
            "card to the next when they lie side by side, like a scene split over a card and "
            "its art cards, or a row of lands."))
        split = QSplitter(Qt.Horizontal)

        # ---- the deck's art extensions
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("<b>This deck's art extensions</b>"))
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._pick)
        lv.addWidget(self.list, 1)
        self.new_btn = QPushButton("New, from the open card")
        set_icon(self.new_btn, "add")
        self.new_btn.setToolTip("Start an art extension with the card open on the Cards page – "
                                "its art's picture is used, and more cards carry it on")
        self.new_btn.clicked.connect(self.new_group)
        lv.addWidget(self.new_btn)
        self.del_btn = QPushButton("Forget this one")
        set_icon(self.del_btn, "delete")
        self.del_btn.setToolTip("Take it off this list – the cards and their art stay as they are")
        self.del_btn.clicked.connect(self.delete_group)
        lv.addWidget(self.del_btn)
        if hasattr(self.main, "card_kinds"):          # MSE Studio's explanation (0.25.0)
            self.kinds_btn = QPushButton("What's the difference?")
            set_icon(self.kinds_btn, "info")
            self.kinds_btn.setToolTip("Art extensions, art cards, alternates and zones – what "
                                      "each one is")
            self.kinds_btn.clicked.connect(self.explain)
            lv.addWidget(self.kinds_btn)
        split.addWidget(left)

        # ---- the one picked
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        f = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("A name for it")
        self.name.editingFinished.connect(self._renamed)
        f.addRow("Name", self.name)
        prow = QHBoxLayout()
        self.pic_label = QLabel("No picture yet")
        self.pic_label.setObjectName("Hint")
        self.pic_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        prow.addWidget(self.pic_label, 1)
        self.pic_btn = QPushButton("Choose…")
        set_icon(self.pic_btn, "folder_open")
        self.pic_btn.setToolTip("The picture to spread over the cards – it's copied into the "
                                "deck's folder, so it goes with the deck")
        self.pic_btn.clicked.connect(self.choose_picture)
        prow.addWidget(self.pic_btn)
        self.card_pic_btn = QPushButton("The first card's art")
        self.card_pic_btn.setToolTip("The whole picture the first card's art was cut from (as "
                                     "you edited it)")
        self.card_pic_btn.clicked.connect(self.picture_from_card)
        prow.addWidget(self.card_pic_btn)
        f.addRow("Picture", prow)
        mv.addLayout(f)

        box = QGroupBox("The cards, in order")
        bv = QVBoxLayout(box)
        hint = QLabel("Left to right, then the next row. Double-click one to open it.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        bv.addWidget(hint)
        self.cards = QListWidget()
        self.cards.setMinimumHeight(120)
        self.cards.itemDoubleClicked.connect(self._open_card)
        bv.addWidget(self.cards, 1)
        row = QHBoxLayout()
        self.add_open_btn = QPushButton("Add the open card")
        self.add_open_btn.setToolTip("The card open on the Cards page")
        self.add_open_btn.clicked.connect(self.add_open_card)
        row.addWidget(self.add_open_btn)
        self.add_pick_btn = QPushButton("Add a card…")
        self.add_pick_btn.setToolTip("A card from the deck – a land, another card or an art card")
        self.add_pick_btn.clicked.connect(self.add_picked_card)
        row.addWidget(self.add_pick_btn)
        bv.addLayout(row)
        row = QHBoxLayout()
        self.make_btn = QPushButton("Make an extension card")
        set_icon(self.make_btn, "add_photo_alternate")
        self.make_btn.setToolTip("A new art card of the first card (never played, not counted) "
                                 "that carries its art on")
        self.make_btn.clicked.connect(self.make_card)
        row.addWidget(self.make_btn)
        self.up_btn = QPushButton()
        set_icon(self.up_btn, "arrow_upward")
        self.up_btn.setToolTip("Earlier in the row")
        self.up_btn.clicked.connect(self.move_up)
        row.addWidget(self.up_btn)
        self.down_btn = QPushButton()
        set_icon(self.down_btn, "arrow_downward")
        self.down_btn.setToolTip("Later in the row")
        self.down_btn.clicked.connect(self.move_down)
        row.addWidget(self.down_btn)
        self.out_btn = QPushButton("Take out")
        self.out_btn.setToolTip("Out of this art extension – the card stays in the deck")
        self.out_btn.clicked.connect(self.take_out)
        row.addWidget(self.out_btn)
        bv.addLayout(row)
        row = QHBoxLayout()
        self.cut_btn = QPushButton("Add the cards cut from this picture")
        self.cut_btn.setToolTip("Every card of the deck whose art was cut from this picture, put "
                                "in order: left to right, as they were cut")
        self.cut_btn.clicked.connect(self.add_cut_cards)
        row.addWidget(self.cut_btn)
        self.link_btn = QPushButton("Link them…")
        set_icon(self.link_btn, "link")
        self.link_btn.setToolTip("The selected card is the card you play; the others become its "
                                 "art cards – printed with it, never played or counted")
        self.link_btn.clicked.connect(self.link_cards)
        row.addWidget(self.link_btn)
        bv.addLayout(row)
        nf = QFormLayout()
        self.frame = QComboBox()
        self.frame.setToolTip("The frame new extension cards get – a full-art or borderless "
                              "frame shows the most of the picture")
        nf.addRow("New ones' frame", self.frame)
        self.no_text = QCheckBox("Without rules text (the name stays)")
        self.no_text.setChecked(True)
        self.no_text.setToolTip("New extension cards are pictures: their cost, type line, "
                                "rules, flavour text and P/T are left empty")
        nf.addRow("", self.no_text)
        self.in_zone = QCheckBox(f"Together in the zone “{ZONE}” on the Cards page")
        self.in_zone.setChecked(True)
        self.in_zone.setToolTip("New extension cards start in a zone of the deck's own: grouped "
                                "together in the Cards list (Group by → Where they start), never "
                                "counted in the deck")
        self.in_zone.setVisible(_zones_here())
        nf.addRow("", self.in_zone)
        bv.addLayout(nf)
        mv.addWidget(box, 1)

        lbox = QGroupBox("How they lie on the picture")
        lf = QFormLayout(lbox)
        self.mode = QComboBox()
        for key, label in extend.MODES.items():
            self.mode.addItem(label, key)
        self.mode.setToolTip("Side by side: as if the card frames were windows onto one "
                             "picture. Art box to art box: each art box carries straight on "
                             "from the one before.")
        self.mode.currentIndexChanged.connect(self._layout_changed)
        lf.addRow("The art", self.mode)
        self.cols = QSpinBox()
        self.cols.setRange(1, 12)
        self.cols.setToolTip("How many cards lie in a row")
        self.cols.valueChanged.connect(self._layout_changed)
        lf.addRow("Cards a row", self.cols)
        self.gap = QDoubleSpinBox()
        self.gap.setRange(0, 20)
        self.gap.setSingleStep(0.5)
        self.gap.setSuffix(" mm")
        self.gap.setToolTip("The space between the cards as you'll lay them out")
        self.gap.valueChanged.connect(self._layout_changed)
        lf.addRow("Gap", self.gap)
        self.zoom = self._slider(100, 400, "Bigger: the cards cover less of the picture")
        lf.addRow("Zoom", self.zoom)
        self.dx = self._slider(-100, 100, "Move the cards left or right on the picture")
        lf.addRow("Left – right", self.dx)
        self.dy = self._slider(-100, 100, "Move the cards up or down on the picture")
        lf.addRow("Up – down", self.dy)
        self.centre_btn = QPushButton("Centre and fit")
        self.centre_btn.clicked.connect(self.centre)
        lf.addRow("", self.centre_btn)
        mv.addWidget(lbox)
        split.addWidget(mid)

        # ---- the preview
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.preview = Preview()
        rv.addWidget(self.preview, 1)
        self.status = QLabel("")
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        rv.addWidget(self.status)
        self.put_btn = QPushButton("Put the art on the cards")
        self.put_btn.setProperty("kind", "primary")
        set_icon(self.put_btn, "crop")
        self.put_btn.setToolTip("Each card gets its part of the picture as its art (Undo takes "
                                "it back)")
        self.put_btn.clicked.connect(self.put_art)
        rv.addWidget(self.put_btn)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        split.setStretchFactor(2, 3)
        split.setSizes([220, 380, 520])
        lay.addWidget(split, 1)
        self._editors = [self.name, self.pic_btn, self.card_pic_btn, self.cards,
                         self.add_open_btn, self.add_pick_btn, self.make_btn, self.up_btn,
                         self.down_btn, self.out_btn, self.cut_btn, self.link_btn, self.frame,
                         self.no_text, self.in_zone,
                         self.mode,
                         self.cols, self.gap, self.zoom, self.dx, self.dy, self.centre_btn,
                         self.put_btn, self.del_btn]
        self.load()

    def explain(self) -> None:
        self.main.card_kinds("versions")

    def _slider(self, lo: int, hi: int, tip: str) -> QSlider:
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setToolTip(tip)
        s.valueChanged.connect(self._layout_changed)
        s.sliderReleased.connect(self._save)
        return s

    # ------------------------------------------------------------ the page
    def load(self):
        """A deck was opened (or Settings changed)."""
        p = self.main.project
        self.groups = extend.load(p.folder) if p is not None else []
        self.picture = None
        self._fill_groups(0)
        self.new_btn.setEnabled(p is not None)
        if p is None:
            self.status.setText("Open a deck first.")

    def refresh(self):
        """The page was opened: the deck's cards may have changed."""
        self._fill_frames()
        self._show_group()

    def shutdown(self):
        self._save()
        forget(self._jobs)

    def _fill_frames(self) -> None:
        keep = self.frame.currentData() or ""
        self.frame.blockSignals(True)
        self.frame.clear()
        self.frame.addItem("The first card's own frame", "")
        try:
            frames = self.main.known_frames() if self.main.project is not None else []
        except Exception:  # noqa: BLE001 - no MSE yet
            frames = []
        for name in frames:
            self.frame.addItem(name, name)
        self.frame.setCurrentIndex(max(0, self.frame.findData(keep)))
        self.frame.blockSignals(False)

    def _fill_groups(self, select: int) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for g in self.groups:
            self.list.addItem(f"{g.name} · {len(g.cards)} card{'s' if len(g.cards) != 1 else ''}")
        self.list.blockSignals(False)
        if self.groups:
            self.list.setCurrentRow(max(0, min(select, len(self.groups) - 1)))
        self._pick(self.list.currentRow())

    def _pick(self, row: int) -> None:
        self.g = self.groups[row] if 0 <= row < len(self.groups) else None
        self._show_group()

    def _save(self) -> None:
        p = self.main.project
        if p is None:
            return
        try:
            extend.save(p.folder, self.groups)
        except OSError as e:
            self.status.setText(f"Couldn't keep the art extensions: {e}")

    def _label_group(self) -> None:
        row = self.list.currentRow()
        if self.g is not None and 0 <= row < self.list.count():
            n = len(self.g.cards)
            self.list.item(row).setText(f"{self.g.name} · {n} card{'s' if n != 1 else ''}")

    # ------------------------------------------------------------ the group shown
    def _show_group(self) -> None:
        g, p = self.g, self.main.project
        on = g is not None and p is not None
        for w in self._editors:
            w.setEnabled(on)
        self._filling = True
        try:
            if not on:
                self.name.clear()
                self.cards.clear()
                self.pic_label.setText("No picture yet")
                self.boxes, self.rows = [], []
                self.preview.show_plan(None, (0, 0), [], "Open a deck first." if p is None else
                                       "Open a card on the Cards page, then press New, from "
                                       "the open card.")
                return
            self.name.setText(g.name)
            self.mode.setCurrentIndex(max(0, self.mode.findData(g.mode)))
            self.cols.setValue(g.cols)
            self.gap.setValue(g.gap)
            self.zoom.setValue(round(g.zoom * 100))
            self.dx.setValue(round(g.dx * 100))
            self.dy.setValue(round(g.dy * 100))
        finally:
            self._filling = False
        self._fill_cards()
        self._load_picture()

    def _fill_cards(self, select: int = -1) -> None:
        """The group's cards: their names, places in the deck and art boxes."""
        from mse_studio.core import versions
        from mse_studio.pipeline import regions
        p, g = self.main.project, self.g
        self.cards.clear()
        self.boxes, self.rows = [], []
        if p is None or g is None:
            return
        where = {cid: i for i, cid in enumerate(versions.ids(p))}
        inf = versions.info(p)
        for n, cid in enumerate(g.cards, 1):
            i = where.get(cid, -1)
            self.rows.append(i)
            if i < 0:
                self.cards.addItem(f"{n}. (no longer in the deck)")
                self.boxes.append(extend.art_box(regions.DEFAULT["image"][1:5]))
                continue
            card = p.set.cards[i]
            what = versions.label(p, i, inf)
            self.cards.addItem(f"{n}. {card.name or '(untitled)'}" + (f" – {what}" if what else ""))
            regs, calibrated = regions.regions_for(card)
            frac = (regs.get("image") or regions.DEFAULT["image"])[1:5]
            aspect = 0.0
            if not calibrated:                  # a guess: the art's own shape is surer
                bw, bh = p.art_box_for(card)
                aspect = bw / bh if bh else 0.0
            self.boxes.append(extend.art_box(frac, aspect))
        if 0 <= select < self.cards.count():
            self.cards.setCurrentRow(select)
        self._label_group()
        self._draw()

    def _layout_changed(self, *_args) -> None:
        if self._filling or self.g is None:
            return
        g = self.g
        g.mode = self.mode.currentData() or "cards"
        g.cols, g.gap = self.cols.value(), float(self.gap.value())
        g.zoom, g.dx, g.dy = self.zoom.value() / 100, self.dx.value() / 100, self.dy.value() / 100
        self._draw()
        if not any(s.isSliderDown() for s in (self.zoom, self.dx, self.dy)):
            self._save()

    def centre(self) -> None:
        self._filling = True
        self.zoom.setValue(100)
        self.dx.setValue(0)
        self._filling = False
        self.dy.setValue(0)

    def _renamed(self) -> None:
        if self.g is None or self._filling:
            return
        name = self.name.text().strip()
        if name and name != self.g.name:
            self.g.name = name
            self._label_group()
            self._save()

    # ------------------------------------------------------------ the picture
    def _picture_path(self):
        p, g = self.main.project, self.g
        if p is None or g is None or not g.picture:
            return None
        return extend.picture_path(p.folder, g)

    def _load_picture(self) -> None:
        path = self._picture_path()
        if path is None:
            self.picture = None
            self.pic_label.setText("No picture yet – choose one, or use the first card's art.")
            self._draw()
            return
        self.pic_label.setText(self.g.picture)
        self.pic_label.setToolTip(str(path))
        if self.picture is not None and self.picture[0] == str(path):
            self._draw()
            return
        if not path.is_file():
            self.picture = None
            self._draw(f"The picture isn't there any more:\n{path}")
            return
        self.picture = None
        self._draw("Reading the picture…")
        job = Job(read_preview, str(path))
        job.signals.finished.connect(self._picture_read)
        job.signals.failed.connect(self._picture_failed)
        self._jobs.append(start(job))

    def _picture_read(self, result) -> None:
        try:
            img, size = result
            path = self._picture_path()
            if path is None:
                return
            self.picture = (str(path), QPixmap.fromImage(img), size)
            self._draw()
        except RuntimeError:
            return

    def _picture_failed(self, text: str) -> None:
        try:
            self.picture = None
            self._draw("Couldn't read the picture: " + ((text or "").splitlines() or [""])[0])
        except RuntimeError:
            return

    def _plan(self) -> list:
        if self.picture is None or self.g is None or not self.boxes:
            return []
        return extend.plan(self.picture[2], self.g, self.boxes)

    def _draw(self, note: str = "") -> None:
        if self.picture is None:
            self.preview.show_plan(None, (0, 0), [], note)
            self.put_btn.setEnabled(False)
            return
        _path, pix, size = self.picture
        places = self._plan()
        self.preview.show_plan(pix, size, places, note)
        self.put_btn.setEnabled(bool(places) and any(r >= 0 for r in self.rows))
        if places:
            w = min(round(pl["art"][2]) for pl in places)
            self.status.setText(f"{len(places)} card{'s' if len(places) != 1 else ''} · each "
                                f"card's art about {w} pixels wide" +
                                (" – small: upscale the picture first for sharp prints"
                                 if w < 500 else "") + ".")

    def choose_picture(self) -> None:
        p = self.main.project
        if p is None or self.g is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "The picture to spread over the cards",
                                              str(p.folder), PICTURES)
        if path:
            self._set_picture(path)

    def picture_from_card(self) -> None:
        from mse_studio.core import art
        p = self.main.project
        first = next((r for r in self.rows if r >= 0), -1)
        if p is None or first < 0:
            self.status.setText("Add a card first.")
            return
        info = art.source_for(p, p.set.cards[first])
        if not info or not Path(info.get("source", "")).is_file():
            self.status.setText("The first card has no art yet – choose a picture instead.")
            return
        self._set_picture(info["source"])

    def _set_picture(self, path) -> None:
        p = self.main.project
        try:
            self.g.picture = extend.keep_picture(p.folder, path)
        except OSError as e:
            error(self, "Art extensions", f"Couldn't copy the picture into the deck's folder:\n{e}")
            return
        self._save()
        self._load_picture()

    # ------------------------------------------------------------ groups
    def _open_row(self) -> int:
        """The card open on the Cards page (-1: none)."""
        tab = getattr(self.main, "cards_tab", None)
        editor = getattr(tab, "editor", None)
        if editor is None or getattr(editor, "card", None) is None:
            return -1
        try:
            editor.commit()
        except Exception:  # noqa: BLE001 - nothing to keep
            pass
        row = getattr(editor, "row", -1)
        p = self.main.project
        return row if p is not None and 0 <= row < len(p.set.cards) else -1

    def new_group(self) -> None:
        from mse_studio.core import art, versions
        p = self.main.project
        row = self._open_row()
        if p is None:
            return
        if row < 0:
            self.status.setText("Open a card on the Cards page first – the one whose art "
                                "carries on.")
            return
        card = p.set.cards[row]
        g = extend.Group(card.name or "Art extension", cards=[versions.ids(p)[row]])
        info = art.source_for(p, card) or {}
        ids, cols, picture = self._cut_from(extend.picture_key(info))
        if len(ids) > 1:                        # the deck's cards cut from the same picture
            g.cards, g.cols = ids, max(1, min(12, cols))
        src = picture or info.get("source") or ""
        if src and Path(src).is_file():
            try:
                g.picture = extend.keep_picture(p.folder, src)
            except OSError:
                pass
        self.groups.append(g)
        self._save()
        self._fill_groups(len(self.groups) - 1)
        if len(ids) > 1:
            self.status.setText(f"{len(ids)} cards were cut from this picture – they're in the "
                                f"order they were cut, left to right. Put the art on them, or "
                                f"Link them so only the card you play counts.")
        else:
            self.status.setText("Now add the cards the art carries on to – or make extension "
                                "cards – and place them on the picture.")

    def _cut_from(self, key: str) -> tuple[list, int, str]:
        """The deck's cards whose art was cut from the picture ``key`` names:
        (their ids in order, cards in the longest row, the picture to use)."""
        from mse_studio.core import versions
        p = self.main.project
        if p is None or not key:
            return [], 1, ""
        sources = p.config.get("art_sources") or {}
        ids = versions.ids(p)
        found, infos = [], []
        for i, c in enumerate(p.set.cards):
            info = sources.get(c.image) if c.image else None
            if info and extend.picture_key(info) == key:
                found.append((ids[i], info.get("crop")))
                infos.append(info)
        order, cols = extend.in_order(found)
        return order, cols, extend.best_picture(infos)

    def add_cut_cards(self) -> None:
        """The deck's cards cut from this group's picture, in the order they
        were cut; cards that weren't stay after them."""
        p, g = self.main.project, self.g
        if p is None or g is None:
            return
        key = ""
        sources = p.config.get("art_sources") or {}
        for row in self.rows:
            if row >= 0 and p.set.cards[row].image in sources:
                key = extend.picture_key(sources[p.set.cards[row].image])
                if key:
                    break
        if not key and g.picture:
            key = extend.picture_key({"source": str(extend.picture_path(p.folder, g))})
        ids, cols, _pic = self._cut_from(key)
        if len(ids) < 2:
            self.status.setText("No other card of the deck was cut from this picture.")
            return
        rest = [c for c in g.cards if c not in ids]
        added = len([c for c in ids if c not in g.cards])
        g.cards = ids + rest
        g.cols = max(1, min(12, cols))
        self._save()
        self._show_group()
        self.status.setText(f"{len(ids)} cards cut from this picture, in order"
                            + (f" ({added} added)." if added else "."))

    def link_cards(self) -> None:
        """The selected card is the one you play; the group's other cards
        become its art cards (not counted)."""
        from mse_studio.core import versions
        from mse_studio.gui.common import confirm
        p, g = self.main.project, self.g
        if p is None or g is None:
            return
        rows = [r for r in self.rows if r >= 0]
        i = self.cards.currentRow()
        main_row = self.rows[i] if 0 <= i < len(self.rows) else -1
        if main_row < 0:                        # none picked: the one with the most rules
            main_row = max(rows, key=lambda r: len(p.set.cards[r].text("rule_text")),
                           default=-1)
        others = [r for r in rows if r != main_row]
        if main_row < 0 or not others:
            self.status.setText("Add the cards first – at least two.")
            return
        inf = versions.info(p)
        main_card = inf.card_of(main_row)
        todo = [r for r in others if not (inf.kind[r] == versions.ART and inf.of[r] == main_card)]
        name = p.set.cards[main_card].name or "the card"
        if not todo:
            self.status.setText(f"They're art cards of {name} already.")
            return
        names = ", ".join(p.set.cards[r].name or "untitled" for r in todo)
        if not confirm(self, "Link them", f"{name} is the card you play. These become its art "
                                          f"cards – printed with it, never played or counted:"
                                          f"\n\n{names}"):
            return
        tab = getattr(self.main, "cards_tab", None)
        if tab is not None:
            try:
                tab.editor.commit()
            except Exception:  # noqa: BLE001
                pass
        cids = versions.ids(p)
        main_id = cids[main_card]
        zone = versions.add_zone(p, ZONE) if self.in_zone.isChecked() and _zones_here() else ""
        for cid in [cids[r] for r in todo]:     # by id: rows stay put, but be safe
            ids_now = versions.ids(p)
            r, m = ids_now.index(cid), ids_now.index(main_id)
            versions.set_version(p, r, versions.ART, m)
            if zone:
                versions.set_zone(p, r, zone)
        p.dirty = True
        self.main.record(f"Art extension · art cards of {name}", row=main_card)
        self._reload_cards()
        self._fill_cards(i)
        self.status.setText(f"{len(todo)} card(s) are art cards of {name} now – only {name} "
                            f"counts in the deck.")

    def delete_group(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.groups):
            del self.groups[row]
            self._save()
            self._fill_groups(row)

    # ------------------------------------------------------------ cards
    def _add_id(self, row: int) -> None:
        from mse_studio.core import versions
        p, g = self.main.project, self.g
        cid = versions.ids(p)[row]
        if cid in g.cards:
            self.status.setText("That card is in it already.")
            return
        g.cards.append(cid)
        self._save()
        self._fill_cards(len(g.cards) - 1)

    def add_open_card(self) -> None:
        row = self._open_row()
        if self.g is None:
            return
        if row < 0:
            self.status.setText("Open a card on the Cards page first.")
            return
        self._add_id(row)

    def add_picked_card(self) -> None:
        p, g = self.main.project, self.g
        if p is None or g is None:
            return
        try:
            from mse_studio.gui.card_picker import pick_card
        except ImportError:
            self.status.setText("Open the card on the Cards page and press Add the open card.")
            return
        have = set(self.rows)
        choices = [i for i in range(len(p.set.cards)) if i not in have]
        if not choices:
            self.status.setText("Every card of the deck is in it already.")
            return
        row = pick_card(self, p, "Add a card", "The art carries on to:", choices)
        if row is not None:
            self._add_id(row)

    def make_card(self) -> None:
        from mse_studio.core import versions
        p, g = self.main.project, self.g
        first = next((r for r in self.rows if r >= 0), -1)
        if p is None or g is None:
            return
        if first < 0:
            self.status.setText("Add the card whose art carries on first.")
            return
        tab = getattr(self.main, "cards_tab", None)
        if tab is not None:
            try:
                tab.editor.commit()
            except Exception:  # noqa: BLE001
                pass
        new = versions.add_version(p, first, versions.ART)
        card = p.set.cards[new]
        frame = self.frame.currentData() or ""
        if frame:
            card.set_raw("stylesheet", frame)
        if self.no_text.isChecked():
            for key in NO_TEXT + tuple(k + "_2" for k in NO_TEXT):
                if card.raw(key):
                    card.set_raw(key, "")
        if self.in_zone.isChecked() and _zones_here():
            versions.set_zone(p, new, versions.add_zone(p, ZONE))
        g.cards.append(versions.ids(p)[new])
        p.dirty = True
        self.main.record(f"Art extension · a new art card of {p.set.cards[first].name or 'a card'}",
                         row=new)
        self._reload_cards(new)
        self._save()
        self._fill_cards(len(g.cards) - 1)

    def _move(self, step: int) -> None:
        g = self.g
        i = self.cards.currentRow()
        j = i + step
        if g is None or not (0 <= i < len(g.cards) and 0 <= j < len(g.cards)):
            return
        g.cards[i], g.cards[j] = g.cards[j], g.cards[i]
        self._save()
        self._fill_cards(j)

    def move_up(self) -> None:
        self._move(-1)

    def move_down(self) -> None:
        self._move(1)

    def take_out(self) -> None:
        g = self.g
        i = self.cards.currentRow()
        if g is None or not 0 <= i < len(g.cards):
            return
        del g.cards[i]
        self._save()
        self._fill_cards(min(i, len(g.cards) - 1))

    def _open_card(self, _item) -> None:
        i = self.cards.currentRow()
        row = self.rows[i] if 0 <= i < len(self.rows) else -1
        tab = getattr(self.main, "cards_tab", None)
        if row < 0 or tab is None:
            return
        self.main.tabs.setCurrentWidget(tab)
        tab.select_row(row)

    def _reload_cards(self, row: int = -1) -> None:
        tab = getattr(self.main, "cards_tab", None)
        if tab is None:
            return
        try:
            tab.reload(row if row >= 0 else None)
        except RuntimeError:
            return
        try:
            self.main.update_title()
        except Exception:  # noqa: BLE001 - older MSE Studio
            pass

    # ------------------------------------------------------------ the art
    def put_art(self) -> None:
        p, g = self.main.project, self.g
        places = self._plan()
        if p is None or g is None or not places or self.picture is None:
            return
        size = self.picture[2]
        crops = [(cid, extend.crop_of(pl["art"], size))
                 for cid, row, pl in zip(g.cards, self.rows, places) if row >= 0]
        if not crops:
            return
        source = str(self._picture_path())
        self.put_btn.setEnabled(False)
        self.status.setText("Cutting the picture…")
        job = Job(cut_parts, source, crops, g.name, label="Art extension: cutting the picture")
        job.signals.finished.connect(self._cut)
        job.signals.failed.connect(self._cut_failed)
        job.signals.cancelled.connect(self._cut_stopped)
        self._jobs.append(start(job))

    def _cut(self, result) -> None:
        try:
            self.put_btn.setEnabled(True)
        except RuntimeError:
            return
        from mse_studio.core import art, versions
        source, name, parts = result
        p = self.main.project
        if p is None:
            return
        tab = getattr(self.main, "cards_tab", None)
        if tab is not None:
            try:
                tab.editor.commit()
            except Exception:  # noqa: BLE001
                pass
        source = Path(source)
        where = {cid: i for i, cid in enumerate(versions.ids(p))}
        ext = getattr(art, "art_ext", None)
        done, first = 0, -1
        for cid, crop, data in parts:
            i = where.get(cid, -1)
            if i < 0:
                continue
            card = p.set.cards[i]
            suffix = ext(data) if ext else ".png"
            name = p.set.add_file(data, f"art_{source.stem}{suffix}")
            card.set_raw("image", name)
            p.config.setdefault("art_sources", {})[name] = {
                "source": str(source), "crop": list(crop), "flip": False, "adjust": {}}
            done += 1
            first = i if first < 0 else first
        if not done:
            self.status.setText("None of its cards are in the deck any more.")
            return
        p.dirty = True
        self.main.record(f"Art extension · {name}", row=first)
        self._reload_cards()
        self.status.setText(f"The art is on {done} card{'s' if done != 1 else ''} – Undo takes "
                            f"it back. Double-click a card above to see it.")

    def _cut_failed(self, text: str) -> None:
        try:
            self.put_btn.setEnabled(True)
            self.status.setText("Couldn't cut the picture: " + ((text or "").splitlines() or [""])[0])
        except RuntimeError:
            return

    def _cut_stopped(self) -> None:
        try:
            self.put_btn.setEnabled(True)
            self.status.setText("Stopped – no card was changed.")
        except RuntimeError:
            return
