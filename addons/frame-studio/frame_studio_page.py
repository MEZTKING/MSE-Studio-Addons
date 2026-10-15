"""Frame studio: make a Magic Set Editor frame from a frame template – the blank frames
a proxy maker shares or sells (one picture per colour), or your own – and
your cards can use it like any other frame. Proxy decks sends a deck's
templates here (right-click a deck → This deck's frame).

Network: none. Files: the pictures you pick (read), the add-on's data folder,
and MSE's data folder – through MSE Studio's frame-pack installer."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFontComboBox,
                               QFormLayout,
                               QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsView, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QProgressBar,
                               QPushButton, QRadioButton, QScrollArea, QSplitter, QTabWidget,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from mse_studio.gui import icons
from mse_studio.gui.common import Job, error, forget, start
from mse_studio.gui.nav import page_header

from . import framegen as fg

BOX_COLOURS = {"name": "#e8b923", "cost": "#e8b923", "art": "#3fa9f5", "type": "#7ed957",
               "rarity": "#7ed957", "text": "#ff7a59", "pt": "#c07cff", "ptbox": "#c07cff",
               "artist": "#9aa0a6", "credit": "#9aa0a6"}
COLOUR_LABELS = [("name", "Name"), ("type", "Type line"), ("text", "Rules text"),
                 ("pt", "Power / toughness"), ("artist", "Artist and credit lines"),
                 ("mana", "Numbers on the mana symbols")]
FONT_LABELS = [("title", "Name and type line"), ("text", "Rules text"),
               ("italic", "Rules text (italic)"), ("pt", "Power / toughness"),
               ("info", "Artist and credit lines"), ("mana", "Numbers on the mana symbols")]
MANA_FLOWS = [("", "As the box is (tall: one under the other)"), ("row", "In a row"),
              ("down", "One under the other, from the top"),
              ("up", "One under the other, from the bottom (colours on top)")]


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

    def __init__(self, key: str, rect: QRectF, bounds: QRectF, on_change, sample=None):
        super().__init__(rect)
        self.key, self.bounds, self.on_change = key, bounds, on_change
        self.sample = sample          # (text, font, size in MSE points, colour, bold) or None
        self.quiet = False            # sample text is shown on the other boxes
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
        if self.sample:
            self._paint_sample(qp, r)
            return
        if self.quiet and self.key not in ("art", "rarity"):
            return                               # sample text shown: no labels in its way
        f = QFont(qp.font())
        f.setPixelSize(max(8, int(self.bounds.width() / 32)))
        f.setBold(True)
        qp.setFont(f)
        qp.setPen(QColor("#ffffff"))
        qp.drawText(r.adjusted(4, 2, -4, -2), Qt.AlignLeft | Qt.AlignTop,
                    fg.BOX_NAMES[self.key])

    def _paint_sample(self, qp, r: QRectF):
        """The sample text as MSE would place it (roughly: MSE draws the real one)."""
        text, family, size, colour, bold, align = self.sample[:6]
        scale = self.bounds.height() / fg.CARD_H        # the card's units → this picture
        px = max(4, int(round(size / fg.PT_PER_UNIT * scale)))   # MSE's points → units
        if self.key == "cost":                          # mana symbols
            mana, flow = (self.sample[6] if len(self.sample) > 6 else ({}, ""))
            d = px * 0.95
            syms = [t for t in text.replace("}", "").split("{") if t]
            vertical = flow in ("down", "up") or (flow != "row" and
                                                  r.height() > 1.8 * r.width())
            spots = []
            if vertical and flow == "up":               # from the bottom: colours on top
                x, y = r.center().x() - d / 2, r.bottom() - 2 - d
                for _sym in syms:
                    spots.append((x, y))
                    y -= d * 1.08
            elif vertical:                              # one under the other, from the top
                x, y = r.center().x() - d / 2, r.top() + 2
                for _sym in syms:
                    spots.append((x, y))
                    y += d * 1.08
            else:                                       # in a row, from the right
                x, y = r.right() - 2, r.center().y() - d / 2
                for _sym in syms:
                    x -= d
                    spots.insert(0, (x, y))
                    x -= d * 0.08
            for sym, (x, y) in zip(syms, spots):
                box = QRectF(x, y, d, d)
                own = mana.get("mana-n" if sym[:1].isdigit() or sym in "XYZ" else
                               "mana-" + sym.lower())
                if own is not None:                     # the frame's own symbol
                    qp.drawPixmap(box.toRect(), own)
                    if sym[:1].isdigit() or sym in "XYZ":
                        f = QFont(mana.get("font") or "Arial")
                        f.setPixelSize(max(4, int(d * 0.62)))
                        qp.setFont(f)
                        qp.setPen(QColor(mana.get("colour") or "#000000"))
                        qp.drawText(box, Qt.AlignCenter, sym)
                    continue
                qp.setBrush(QColor("#cac5c0" if sym.isdigit() else "#f8f6d8"))
                qp.setPen(QPen(QColor("#000000"), max(1.0, d / 14)))
                qp.drawEllipse(box)
                f = QFont("Arial")
                f.setPixelSize(max(4, int(d * 0.7)))
                f.setBold(True)
                qp.setFont(f)
                qp.drawText(box, Qt.AlignCenter, sym)
            return
        f = QFont(family)
        f.setPixelSize(px)
        f.setBold(bold)
        qp.setFont(f)
        qp.setPen(QColor(colour))
        across = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter,
                  "right": Qt.AlignRight}.get(align, Qt.AlignLeft)
        align = {"pt": Qt.AlignCenter, "name": across | Qt.AlignBottom,
                 "text": across | Qt.AlignVCenter}.get(self.key, across | Qt.AlignTop)
        pad = 6 * scale if self.key == "text" else 2 * scale
        qp.drawText(r.adjusted(pad, 0, -pad, 0), align | Qt.TextWordWrap, text)

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

    def show_frame(self, picture: Optional[QPixmap], boxes: dict, keys: list,
                   samples: Optional[dict] = None):
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
                         b, self.on_change, (samples or {}).get(k))
            it.quiet = bool(samples)
            sc.addItem(it)
            self.items_by_key[k] = it
        sc.setSceneRect(b)
        self.fitInView(b, Qt.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fitInView(self.bounds, Qt.KeepAspectRatio)


# ------------------------------------------------------------------ a new frame
class NewFrameDialog(QDialog):
    """Pictures in (and Photoshop files, put together colour by colour), a
    colour for each (guessed from their names), the fonts that came with
    them, a name."""

    def __init__(self, parent, files: Optional[list] = None, name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("New frame from a template")
        self.resize(820, 700)
        self.rows: list = []           # (label, source, combo): a path, or (psd key, PsdPick)
        self._psds: dict = {}          # psd key → the file read (up to PSD_W wide)
        self._jobs: list = []
        self._ready: Optional[dict] = None
        self._queue: list = []         # Photoshop files still to read
        self.fonts: list = []          # font files found
        self._layouts: list = []       # what each Photoshop file's text layers say
        self._row_imgs: list = []      # each row's small picture (or its file)
        self._row_kinds: list = []
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("e.g. Death Note – Vibrant")
        f.addRow("Name of the frame", self.name)
        lay.addLayout(f)
        hint = QLabel("Add the frame template – a Photoshop file, or the blank frames as "
                      "files (one per colour: White, Blue, Black, Red, Green, Gold, Artifact, "
                      "Colourless, Land) – and its fonts. Each colour's frame, P/T box and mana "
                      "symbol is matched for you: check the choices below, or press Match "
                      "automatically. A Photoshop file's groups and single layers are there "
                      "too, to pick by hand.")
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        lay.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Layer or file", "Use it as"])
        self.tree.setIconSize(QSize(42, 58))
        self.tree.setColumnWidth(0, 470)
        lay.addWidget(self.tree, 3)
        row = QHBoxLayout()
        self.add_btns = []
        for label, fn, icon, tip in (
                ("Add files…", self.add_files, "add_photo_alternate",
                 "Frame pictures, Photoshop files or fonts"),
                ("Add a folder…", self.add_folder, "folder_open",
                 "Everything in a folder and the folders in it: pictures, Photoshop files and "
                 "a Fonts folder"),
                ("Add a Photoshop file…", self.add_psd, "layers", ""),
                ("Add fonts…", self.add_fonts, "font_download",
                 "Font files (.ttf, .otf) or a .zip of them that came with the frame")):
            b = QPushButton(label)
            icons.set_icon(b, icon)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.add_btns.append(b)
        row.addStretch(1)
        self.match_btn = QPushButton("Match automatically")
        icons.set_icon(self.match_btn, "auto_fix_high")
        self.match_btn.setToolTip("Choose what each layer or file is for, from their names and "
                                  "colours (only the ones not chosen yet)")
        self.match_btn.clicked.connect(self.match_all)
        row.addWidget(self.match_btn)
        self.ai_match_btn = QPushButton("Ask AI to match them")
        icons.set_icon(self.ai_match_btn, "auto_fix_high")
        self.ai_match_btn.clicked.connect(self.ai_match)
        from .designer_dialog import ai_module, ai_on
        ai = ai_module()
        self.ai_match_btn.setVisible(hasattr(parent, "main") and ai_on(parent.main.settings))
        why = "Needs MSE Studio 0.20.0 or newer." if ai is None else \
            ai.not_ready(parent.main.settings) if hasattr(parent, "main") else "No AI."
        self.ai_match_btn.setEnabled(not why)
        self.ai_match_btn.setToolTip(why or "Sends small pictures of the frames, groups and "
                                     f"symbols to {ai.service(parent.main.settings)} (Settings → "
                                     "AI), which says what each is for – one request")
        row.addWidget(self.ai_match_btn)
        lay.addLayout(row)
        # fonts that came with the frame
        self.font_box = QWidget()
        fl = QVBoxLayout(self.font_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(QLabel("<b>Fonts that came with it</b> – kept with the frame, and installed "
                            "for MSE when you add the frame to MSE (ticked ones)"))
        self.font_list = QListWidget()
        self.font_list.setMaximumHeight(110)
        fl.addWidget(self.font_list)
        ff = QFormLayout()
        self.title_font = QComboBox()
        self.text_font = QComboBox()
        ff.addRow("Name and type line in", self.title_font)
        ff.addRow("Rules text in", self.text_font)
        fl.addLayout(ff)
        self.font_box.setVisible(False)
        lay.addWidget(self.font_box)
        # where the name, type line… go, from a template's text and guide layers
        self.layout_cb = QCheckBox()
        self.layout_cb.setChecked(True)
        self.layout_cb.setVisible(False)
        self.layout_cb.setToolTip("The file's own text layers (Card Name, Typeline, Rules "
                                  "Text…) and guides (Art Frame, Textbox Reference…) say where "
                                  "each text goes, how big, in which colour and font")
        lay.addWidget(self.layout_cb)
        self.layout_hint = QLabel()
        self.layout_hint.setObjectName("Hint")
        self.layout_hint.setWordWrap(True)
        self.layout_hint.setVisible(False)
        lay.addWidget(self.layout_hint)
        prog = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(True)
        prog.addWidget(self.progress, 1)
        self.stop_btn = QPushButton("Stop")
        icons.set_icon(self.stop_btn, "stop")
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self._stop)
        prog.addWidget(self.stop_btn)
        lay.addLayout(prog)
        self.status = QLabel()
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.button(QDialogButtonBox.Ok).setText("Make the frame")
        self.bb.accepted.connect(self._ok)
        self.bb.rejected.connect(self.reject)
        lay.addWidget(self.bb)
        self.add_paths([Path(p) for p in files or []])

    def done(self, r):
        forget(self._jobs)
        super().done(r)

    # ------------------------------------------------------------ pictures in
    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Frame pictures", "", "Pictures and fonts (*.png *.jpg *.jpeg *.webp *.bmp "
                                        "*.tif *.tiff *.psd *.psb *.ttf *.otf *.ttc *.zip);;"
                                        "All files (*)")
        self.add_paths([Path(p) for p in paths])

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "A folder of frame pictures")
        if folder:
            if not self.name.text().strip():
                self.name.setText(Path(folder).name)
            self.add_paths([Path(folder)])

    def add_psd(self):
        path, _ = QFileDialog.getOpenFileName(self, "A Photoshop file", "",
                                              "Photoshop files (*.psd *.psb)")
        if path:
            self.add_paths([Path(path)])

    def add_fonts(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Fonts that came with the frame", "",
                                                "Fonts (*.ttf *.otf *.ttc *.zip)")
        self.add_paths([Path(p) for p in paths])

    def add_paths(self, paths: list):
        self.sources = getattr(self, "sources", []) + [str(p) for p in paths]
        if not self.name.text().strip():                  # named after the template
            first = next((Path(p) for p in paths if Path(p).is_dir() or
                          Path(p).suffix.lower() in (".psd", ".psb")), None)
            if first is not None:
                self.name.setText(first.stem.replace("_", " ").strip())
        found_fonts = fg.fonts_in(paths)
        for p in paths:
            p = Path(p)
            files = fg.pictures_in(p) if p.is_dir() else [p]
            for f in files:
                low = f.suffix.lower()
                if low in (".psd", ".psb"):
                    self._queue.append(f)
                elif low in fg.PICTURES and f.is_file():
                    self._add_row(None, f.name, f, f.name, None)
        self._add_fonts(found_fonts)
        self._count()
        self._next_psd()

    # ------------------------------------------------------------ Photoshop files, one by one
    def _next_psd(self):
        if not self._queue or any(not j.cancel.cancelled for j in self._jobs):
            return
        path = self._queue.pop(0)

        def work(progress=None, cancel=None):
            from mse_studio.pipeline.common import Cancelled
            from . import psdread
            try:
                psd = fg.read_psd(path, progress, cancel)
                picks = fg.psd_picks(psd)
                try:
                    layout = fg.psd_layout(psd)
                except Exception:  # noqa: BLE001 - a file whose layers say nothing usable
                    layout = None
                small = psd.scaled(160)
                thumbs = []
                for k, pk in enumerate(picks):
                    progress(k, len(picks), f"Putting {path.name} together: {pk.label}")
                    try:
                        thumbs.append(fg.psd_picture(small, pk, cancel))
                    except psdread.Stopped:
                        raise
                    except Exception:  # noqa: BLE001 - no small picture for this one
                        thumbs.append(None)
            except psdread.Stopped:
                raise Cancelled() from None
            return path, psd, picks, thumbs, layout

        self._busy(True, f"Reading {path.name}…")
        job = Job(work, label=f"Reading {path.name}")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(self._psd_read)
        job.signals.failed.connect(lambda msg, p=path.name: self._psd_failed(p, msg))
        job.signals.cancelled.connect(self._psd_stopped)
        self._jobs = [j for j in self._jobs if not j.cancel.cancelled]
        self._jobs.append(start(job))

    def _progress(self, done: int, total: int, text: str):
        try:
            self.progress.setRange(0, max(1, total))
            self.progress.setValue(done)
            self.progress.setFormat(text[:90])
        except RuntimeError:
            return

    def _psd_read(self, result):
        try:
            path, psd, picks, thumbs, layout = result
        except (TypeError, ValueError):
            return
        try:
            self._jobs.clear()
            key = str(path)
            self._psds[key] = psd
            top = QTreeWidgetItem(self.tree, [path.name, ""])
            top.setFirstColumnSpanned(True)
            top.setExpanded(True)
            single = None
            put_together = any(pk.guess and "put together" in pk.label for pk in picks)
            for pk, th in zip(picks, thumbs):
                guess = pk.guess
                if pk.label.startswith("The whole frame") and not put_together:
                    guess = fg.guess_slot(path.name) or ""   # one file per colour
                if pk.label.startswith(("Group:", "Layer:")):
                    guess = ""                               # chosen by hand
                parent = top
                if pk.label.startswith("Layer:"):
                    if single is None:
                        single = QTreeWidgetItem(top, ["Single layers"])
                        single.setFirstColumnSpanned(True)
                    parent = single
                kind = "mana" if pk.label.startswith("Mana symbol") else \
                    "frame" if pk.guess or pk.label.startswith(("The whole", "All layers")) \
                    else "any"
                self._add_row(parent, pk.label, (key, pk), "", th, guess, kind)
            if single is not None:
                single.setText(0, f"Single layers ({single.childCount()})")
            if layout and layout.get("found"):
                self._layouts.append((path.name, layout))
                self._show_layout()
            n = sum(1 for pk in picks if "put together" in pk.label)
            self.status.setText(f"{path.name}: " + (f"{n} picture(s) put together from its "
                                                    "colour layers – check them below." if n else
                                                    "pick the picture for each colour below."))
        except RuntimeError:
            return
        self._busy(False)
        self._count()
        self._next_psd()

    def _psd_failed(self, name: str, msg: str):
        try:
            self._jobs.clear()
            self._busy(False)
            self.status.setText(f"Couldn't read {name}: {msg.splitlines()[0] if msg else ''}")
        except RuntimeError:
            return
        self._next_psd()

    def _psd_stopped(self):
        try:
            self._jobs.clear()
            self._queue.clear()
            self._busy(False)
            self.status.setText("Stopped.")
        except RuntimeError:
            return

    def _stop(self):
        for j in self._jobs:
            j.cancel.cancel()

    def _busy(self, on: bool, text: str = ""):
        self.progress.setVisible(on)
        self.stop_btn.setVisible(on)
        if on:
            self.progress.setRange(0, 0)
            self.progress.setFormat(text)
        for b in self.add_btns:
            b.setEnabled(not on)
        self.bb.button(QDialogButtonBox.Ok).setEnabled(not on)

    # ------------------------------------------------------------ rows
    def _add_row(self, parent, label: str, source, guess_from: str, img, guess: str = None,
                 kind: str = "any"):
        """A layer or file and what it's used as. ``kind``: "frame" (a colour's
        frame or P/T box), "mana" (a mana symbol) or "any"."""
        it = QTreeWidgetItem(parent if parent is not None else self.tree, [label, ""])
        try:
            pm = QPixmap.fromImage(_qimage(img)) if img is not None else (
                _pixmap(source) if isinstance(source, Path) else QPixmap())
            if not pm.isNull():
                it.setIcon(0, QIcon(pm.scaledToHeight(58, Qt.SmoothTransformation)))
                if not fg.is_card_shaped((pm.width(), pm.height())):
                    it.setToolTip(0, "Not card-shaped – probably not a frame")
        except Exception:  # noqa: BLE001
            pass
        combo = QComboBox()
        combo.addItem("– not used –", "")
        if kind != "mana":
            for k, v in fg.SLOTS:
                combo.addItem(f"{v} frame", k)
            for k, v in fg.PT_SLOTS:
                combo.addItem(f"P/T box – {v}", k)
        if kind != "frame":
            for k, v in fg.MANA_SLOTS:
                combo.addItem(f"Mana symbol – {v}", k)
        combo.setProperty("guess", guess if guess is not None else
                          (fg.guess_slot(guess_from) or ""))
        if guess is None:
            guess = fg.guess_slot(guess_from) or ""
        if guess and any(r[2].currentData() == guess for r in self.rows):
            guess = ""                         # one picture per colour
        combo.setCurrentIndex(max(0, combo.findData(guess)))
        combo.currentIndexChanged.connect(self._count)
        self.tree.setItemWidget(it, 1, combo)
        self.rows.append((label, source, combo))
        self._row_imgs.append(img if img is not None else source)
        self._row_kinds.append(kind)

    def match_all(self):
        """Fill every unused choice with its best guess: the names, then the
        colours of frame files whose names say nothing."""
        used = {r[2].currentData() for r in self.rows if r[2].currentData()}
        done = 0
        for label, src, combo in self.rows:
            if combo.currentData():
                continue
            guess = combo.property("guess") or ""
            if not guess and isinstance(src, Path):
                try:
                    guess = fg.guess_frame_colour(fg.card_picture(src)) if \
                        fg.is_card_shaped(Image.open(src).size) else \
                        fg.guess_mana_colour(fg.open_picture(src))
                except Exception:  # noqa: BLE001 - not a picture we can read
                    guess = ""
            elif not guess and isinstance(src, tuple) and src[1].label.startswith("Mana symbol"):
                try:
                    guess = fg.guess_mana_colour(fg.psd_picture(self._psds[src[0]].scaled(400),
                                                                src[1]))
                except Exception:  # noqa: BLE001
                    guess = ""
            if guess and guess not in used and combo.findData(guess) >= 0:
                combo.setCurrentIndex(combo.findData(guess))
                used.add(guess)
                done += 1
        self._count()
        if not self._jobs:
            self.status.setText(self.status.text() + (f" – {done} more matched." if done else
                                                      " – nothing more to match."))

    def ai_match(self):
        """Ask the AI what the frames, groups and symbols are for (one contact
        sheet of numbered pictures), then fill the choices still empty."""
        from PIL import ImageDraw, ImageFont
        from .designer_dialog import ai_module
        ai = ai_module()
        if ai is None:
            return
        settings = self.parent().main.settings
        cands = []
        for i, (label, src, combo) in enumerate(self.rows):
            if label.startswith("Layer:") or combo.currentData():
                continue
            img = self._row_imgs[i]
            try:
                if isinstance(img, Path):
                    img = fg.open_picture(img)
                if img is None or img.getbbox() is None:
                    continue
            except Exception:  # noqa: BLE001 - not a picture we can show
                continue
            cands.append((i, label, img))
        cands = cands[:48]
        if not cands:
            self.status.setText("Nothing left to match.")
            return
        cw, ch, cols = 150, 210, 8
        sheet = Image.new("RGB", (cols * cw, ((len(cands) + cols - 1) // cols) * ch),
                          (128, 128, 128))
        dr = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.truetype("arial.ttf", 26)
        except OSError:
            font = ImageFont.load_default()
        for n, (_i, _label, img) in enumerate(cands):
            im = img.convert("RGBA")
            im = im.crop(im.getbbox())
            im.thumbnail((cw - 10, ch - 40))
            x, y = (n % cols) * cw, (n // cols) * ch
            sheet.paste(im, (x + (cw - im.width) // 2, y + 34), im)
            dr.rectangle([x, y, x + 34, y + 30], fill=(255, 255, 255))
            dr.text((x + 4, y + 2), str(n + 1), fill=(0, 0, 0), font=font)
        import io
        buf = io.BytesIO()
        sheet.save(buf, format="PNG")
        codes = [k for k, _ in fg.SLOTS] + [k for k, _ in fg.PT_SLOTS] + \
            [k for k, _ in fg.MANA_SLOTS]
        names = {**{k: f"{v} frame" for k, v in fg.SLOTS},
                 **{k: f"P/T box – {v}" for k, v in fg.PT_SLOTS},
                 **{k: f"mana symbol – {v}" for k, v in fg.MANA_SLOTS}}
        system = ("You sort the parts of a trading card frame template (Magic: The Gathering "
                  "style). Each numbered picture is a layer, group or file from it. Say what "
                  "each is for, with one of these codes (each code at most once; leave out "
                  "what's none of them – sample art, text, symbols of the set, single pieces):\n" +
                  "\n".join(f"{c}: {names[c]}" for c in codes) +
                  '\nAnswer {"choices": {"<number>": "<code>"}}.')
        prompt = "The pictures' names:\n" + "\n".join(
            f"{n + 1}: {label}" for n, (_i, label, _img) in enumerate(cands))
        png = buf.getvalue()

        def work(progress=None, cancel=None):
            progress(0, 0, "Asking the AI…")
            return ai.ask_json(settings, system, prompt, images=[png])

        self._busy(True, "Asking the AI what each picture is for…")
        job = Job(work, label="Matching with AI")
        job.signals.finished.connect(lambda data, c=cands: self._ai_matched(data, c))
        job.signals.failed.connect(lambda msg: self._psd_failed("the AI's answer", msg))
        self._jobs.append(start(job))

    def _ai_matched(self, data, cands):
        try:
            self._jobs.clear()
            self._busy(False)
            choices = data.get("choices", {}) if isinstance(data, dict) else {}
            used = {r[2].currentData() for r in self.rows if r[2].currentData()}
            done = 0
            for key, code in choices.items():
                try:
                    i = cands[int(key) - 1][0]
                except (ValueError, IndexError, TypeError):
                    continue
                combo = self.rows[i][2]
                if code in used or combo.currentData() or combo.findData(code) < 0:
                    continue
                combo.setCurrentIndex(combo.findData(code))
                used.add(code)
                done += 1
            self._count()
            self.status.setText(f"The AI matched {done} – check them below.")
        except RuntimeError:
            return

    def _count(self, *_):
        n = sum(1 for r in self.rows if r[2].currentData())
        if not self._jobs:
            self.status.setText(f"{len(self.rows)} layers and files, {n} used" if self.rows else
                                "Add the frame template: a Photoshop file, a folder or files.")

    # ------------------------------------------------------------ fonts
    def _add_fonts(self, files: list):
        have = {Path(f).name.lower() for f in self.fonts}
        for f in files:
            if Path(f).name.lower() in have:
                continue
            self.fonts.append(Path(f))
            it = QListWidgetItem(f"{fg.font_name(f)}  ({Path(f).name})")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, str(f))
            self.font_list.addItem(it)
        if not self.fonts:
            return
        self.font_box.setVisible(True)
        names = sorted({fg.font_name(f) for f in self.fonts}, key=str.lower)
        guess = fg.guess_fonts(self.fonts)
        for combo, key, usual in ((self.title_font, "title", "Beleren Bold"),
                                  (self.text_font, "text", "MPlantin")):
            keep = combo.currentData()
            combo.clear()
            combo.addItem(f"MSE's usual font ({usual})", "")
            for n in names:
                combo.addItem(n, n)
            pick = keep if keep is not None and combo.findData(keep) >= 0 else guess.get(key, "")
            combo.setCurrentIndex(max(0, combo.findData(pick)))
        self._show_layout()

    def _show_layout(self):
        if not self._layouts:
            return
        name, lay = self._layouts[0]
        self.layout_cb.setText(f"Place the text where {name} has it – with its sizes, "
                               "colours and fonts")
        self.layout_cb.setVisible(True)
        missing = fg.missing_fonts(lay, self.fonts)
        text = "Found in its layers: " + ", ".join(lay["found"]) + "."
        if missing:
            text += (" It uses fonts that didn't come with it: " + ", ".join(missing) +
                     " – add their font files (Add fonts…), else MSE draws those texts in its "
                     "usual fonts.")
        self.layout_hint.setText(text)
        self.layout_hint.setVisible(True)
        for combo, key in ((self.title_font, "title"), (self.text_font, "text")):
            fam = fg.resolve_font(lay["fonts"].get(key, ""), self.fonts)
            if fam and combo.findData(fam) >= 0:
                combo.setCurrentIndex(combo.findData(fam))

    def layout(self) -> Optional[dict]:
        """What the Photoshop file's text layers say (if it's to be used)."""
        if self._layouts and self.layout_cb.isChecked():
            return self._layouts[0][1]
        return None

    def chosen_fonts(self) -> list:
        return [Path(self.font_list.item(i).data(Qt.UserRole))
                for i in range(self.font_list.count())
                if self.font_list.item(i).checkState() == Qt.Checked]

    def font_names(self) -> dict:
        out = {}
        if self.title_font.currentData():
            out["title"] = self.title_font.currentData()
        if self.text_font.currentData():
            out["text"] = self.text_font.currentData()
        return out

    # ------------------------------------------------------------ done
    def _wanted(self) -> dict:
        out = {}
        for _label, src, combo in self.rows:
            slot = combo.currentData()
            if slot and slot not in out:
                out[slot] = src
        return out

    def chosen(self) -> dict:
        """{slot: path or PIL image} (Photoshop pictures already put together)."""
        if self._ready is not None:
            return dict(self._ready)
        return {k: v for k, v in self._wanted().items() if isinstance(v, Path)}

    def _ok(self):
        want = self._wanted()
        if not any(k in want for k in fg.BASE + ["l"]) and self.windowTitle() != "Pick the layer":
            error(self, "Frame studio", "Pick which picture is which colour (at least one).")
            return
        if not want:
            error(self, "Frame studio", "Pick a picture.")
            return
        if not self.name.text().strip():
            error(self, "Frame studio", "Give the frame a name.")
            return
        psds = dict(self._psds)

        def work(progress=None, cancel=None):
            from mse_studio.pipeline.common import Cancelled
            from . import psdread
            out = {}
            todo = list(want.items())
            for k, (slot, src) in enumerate(todo):
                if isinstance(src, tuple):
                    key, pick = src
                    progress(k, len(todo), f"Putting together: {pick.label}")
                    try:
                        out[slot] = fg.psd_picture(psds[key], pick, cancel)
                    except psdread.Stopped:
                        raise Cancelled() from None
                else:
                    out[slot] = src
            return out

        self._busy(True, "Putting the pictures together…")
        job = Job(work, label="Putting the frame pictures together")
        job.signals.progress.connect(self._progress)
        job.signals.finished.connect(self._made)
        job.signals.failed.connect(lambda msg: self._psd_failed("the pictures", msg))
        job.signals.cancelled.connect(self._psd_stopped)
        self._jobs.append(start(job))

    def _made(self, result: dict):
        try:
            self._jobs.clear()
            self._busy(False)
            self._ready = result
            self.accept()
        except RuntimeError:
            return


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
            "Frame studio", "Make an MSE frame from a frame template – a Photoshop file or the "
                            "blank frames a proxy maker shares or sells – or design your own. "
                            "Place the name, mana cost, art and text on it, and your cards can "
                            "use it like any other frame."))
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
        lv.addLayout(row)
        row = QHBoxLayout()
        b = QPushButton("Design a frame…")
        icons.set_icon(b, "palette")
        b.setToolTip("The Frame designer: a whole frame drawn for you – every colour, P/T boxes "
                     "and mana symbols – from lots of settings (or a description, when AI is "
                     "switched on)")
        b.clicked.connect(lambda: self.design_frame())
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
        for k, label in fg.SLOTS + fg.PT_SLOTS + fg.MANA_SLOTS:
            if k == "mana-w":
                r += 1
                lab = QLabel("<b>Mana symbols</b> – the frame's own designs for the mana cost "
                             "(from a template's Mana group, or pictures of yours). The ones "
                             "without a picture are MSE's usual symbols; numbers and X are "
                             "written on the Numbers tile.")
                lab.setWordWrap(True)
                self.slot_grid.addWidget(lab, r, 0, 1, 4)
                r += 1
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
            self.slot_grid.addWidget(QLabel(f"P/T box – {label}" if k.startswith("pt-") else
                                            f"Mana – {label}" if k.startswith("mana-") else
                                            label), r, 1)
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
        self.empty_hint = QLabel()
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setVisible(False)
        v.addWidget(self.empty_hint)
        row = QHBoxLayout()
        self.remake_btn = QPushButton("Pictures from the files again…")
        icons.set_icon(self.remake_btn, "refresh")
        self.remake_btn.setToolTip("Open the maker's files again (a folder, pictures or a "
                                   "Photoshop file) and pick the colours anew – where things go, "
                                   "the text colours and fonts stay")
        self.remake_btn.clicked.connect(self.remake_pictures)
        row.addWidget(self.remake_btn)
        self.edit_design_btn = QPushButton("Edit the design…")
        icons.set_icon(self.edit_design_btn, "palette")
        self.edit_design_btn.setToolTip("Change this frame's settings in the Frame designer and "
                                        "draw it again")
        self.edit_design_btn.clicked.connect(lambda: self.design_frame(self.frame))
        self.edit_design_btn.setVisible(False)
        row.addWidget(self.edit_design_btn)
        row.addStretch(1)
        v.addLayout(row)
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
        self.sample_cb = QCheckBox("Show sample text (in the frame's fonts, colours and sizes)")
        self.sample_cb.setChecked(True)
        self.sample_cb.setToolTip("How the name, mana cost, type line, rules text and P/T will "
                                  "sit on the frame – a quick look; MSE draws the real card "
                                  "(Try it on a card)")
        self.sample_cb.toggled.connect(lambda *_: self._draw_layout())
        v.addWidget(self.sample_cb)
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
        self.size_boxes: dict = {}
        for key, label in fg.SIZE_NAMES:
            sb = QDoubleSpinBox()
            sb.setRange(0, 60)
            sb.setDecimals(1)
            sb.setSingleStep(0.5)
            sb.setSpecialValueText("automatic")
            sb.setToolTip("0 = automatic: fits the box, never bigger than a real frame's")
            sb.valueChanged.connect(lambda v, k=key: self._size(k, v))
            f.addRow(f"{label} size", sb)
            self.size_boxes[key] = sb
        self.mana_flow = QComboBox()
        for key, label in MANA_FLOWS:
            self.mana_flow.addItem(label, key)
        self.mana_flow.setToolTip("How MSE puts the mana cost's symbols: in a row, or one "
                                  "under the other (cards with the cost down the side)")
        self.mana_flow.currentIndexChanged.connect(self._mana_flow)
        f.addRow("Mana symbols go", self.mana_flow)
        self.shadow_cb = QCheckBox("Text shadows, as the Photoshop file has them")
        self.shadow_cb.setToolTip("The Drop Shadow effects of the template's text layers, for "
                                  "MSE to draw under the same texts")
        self.shadow_cb.toggled.connect(self._shadows)
        f.addRow(self.shadow_cb)
        self.align_boxes: dict = {}
        for key, label in fg.ALIGN_NAMES:
            cb = QComboBox()
            for a, text in (("left", "Left"), ("center", "Centre"), ("right", "Right")):
                cb.addItem(text, a)
            cb.currentIndexChanged.connect(lambda _i, k=key: self._align(k))
            f.addRow(f"{label} sits", cb)
            self.align_boxes[key] = cb
        hint = QLabel("MSE's own Magic fonts (Beleren, MPlantin) come with the Full Magic Pack "
                      "– Advanced → Fonts shows which are installed. MSE only draws fonts "
                      "installed in Windows.")
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        f.addRow(hint)
        f.addRow(QLabel("<b>Fonts that came with this frame</b>"))
        self.frame_fonts = QListWidget()
        self.frame_fonts.setMaximumHeight(120)
        f.addRow(self.frame_fonts)
        row = QHBoxLayout()
        self.install_fonts_btn = QPushButton("Install them for MSE")
        icons.set_icon(self.install_fonts_btn, "download")
        self.install_fonts_btn.setToolTip("Installs the fonts for your Windows user (no "
                                          "administrator needed), so MSE can draw them")
        self.install_fonts_btn.clicked.connect(lambda: self.install_fonts(ask=False))
        row.addWidget(self.install_fonts_btn)
        b = QPushButton("Add fonts…")
        icons.set_icon(b, "add")
        b.setToolTip("Font files (.ttf, .otf) or a .zip of them that came with the frame")
        b.clicked.connect(self.add_fonts)
        row.addWidget(b)
        row.addStretch(1)
        f.addRow(row)
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
            col = (fg.mana_number_colour(fr) if k == "mana" else fr.colour(k)) if fr else \
                "#000000"
            b.setText(col)
            b.setStyleSheet(f"QPushButton {{ background: {col}; color: "
                            f"{'#000' if QColor(col).lightness() > 128 else '#fff'}; }}")
        for k, fb in self.font_boxes.items():
            fb.setCurrentText((fr.font(k) or fr.font("title")) if fr else
                              (fg.DEFAULT_FONTS[k] or fg.DEFAULT_FONTS["title"]))
        for k, cb in self.align_boxes.items():
            cb.setCurrentIndex(max(0, cb.findData(fr.align(k) if fr else "left")))
        self.mana_flow.setCurrentIndex(max(0, self.mana_flow.findData(fr.mana_flow if fr
                                                                      else "")))
        has_shadows = bool(fr) and any(k != "_off" for k in fr.shadows)
        self.shadow_cb.setVisible(has_shadows)
        self.shadow_cb.setChecked(has_shadows and not fr.shadows.get("_off"))
        for k, sb in self.size_boxes.items():
            sb.setValue(float(fr.sizes.get(k) or 0) if fr else 0)
            sb.setSpecialValueText(f"automatic ({fr.size(k):g})" if fr else "automatic")
        self.edit_design_btn.setVisible(bool(fr and fr.design))
        self.remake_btn.setVisible(not (fr and fr.design))
        self._load_fonts()
        self._check_pictures()
        self._show_fonts()
        self._loading = False
        self._draw_layout()
        self._buttons()

    def _missing_fonts(self) -> list:
        """The frame's font files whose fonts Windows hasn't got."""
        fr = self.frame
        if fr is None or not fr.font_files:
            return []
        try:
            from mse_studio.core import fonts as fonts_mod
            from mse_studio.gui.advanced import qt_installed_fonts
            have = qt_installed_fonts()
            return [f for f in fg.frame_fonts(fr)
                    if not fonts_mod.is_installed(fg.font_name(f), have)]
        except Exception:  # noqa: BLE001 - can't tell: offer them all
            return fg.frame_fonts(fr)

    def _show_fonts(self):
        self.frame_fonts.clear()
        fr = self.frame
        files = fg.frame_fonts(fr) if fr else []
        missing = {str(f) for f in self._missing_fonts()}
        for f in files:
            ok = str(f) not in missing
            it = QListWidgetItem(f"{fg.font_name(f)}  –  " + ("installed" if ok else
                                                             "not installed yet"))
            it.setIcon(icons.icon("check_circle" if ok else "error"))
            it.setToolTip(f.name)
            self.frame_fonts.addItem(it)
        if not files:
            self.frame_fonts.addItem("None – add the maker's font files if the frame came "
                                     "with some")
        self.install_fonts_btn.setEnabled(bool(missing))

    def add_fonts(self):
        if self.frame is None:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Fonts that came with the frame", "",
                                                "Fonts (*.ttf *.otf *.ttc *.zip)")
        files = fg.fonts_in([Path(p) for p in paths])
        if not files:
            return
        fg.keep_fonts(self.frame, files)
        self._changed()
        self._show_frame()

    def install_fonts(self, ask: bool = True) -> bool:
        """Install the frame's fonts that Windows hasn't got (MSE Studio's own
        font installer, for your Windows user). Returns False if you said no."""
        missing = self._missing_fonts()
        if not missing:
            return True
        if ask:
            from PySide6.QtWidgets import QMessageBox
            names = "\n".join(f"• {fg.font_name(f)}" for f in missing[:12])
            r = QMessageBox.question(
                self, "Frame studio", f"The frame uses fonts that aren't installed:\n{names}\n\n"
                "Install them for your Windows user so MSE can draw them?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
            if r == QMessageBox.Cancel:
                return False
            if r == QMessageBox.No:
                return True
        try:
            from mse_studio.gui.advanced import install_font_files
            done = install_font_files(self, missing)
        except Exception as e:  # noqa: BLE001
            error(self, "Frame studio", f"Couldn't install the fonts: {e}")
            return True
        self._show_fonts()
        if done:                 # MSE Studio 0.18 starts MSE again for the next preview
            self.status.setText(f"Installed {len(done)} font(s) – MSE uses them from the next "
                                "card it draws." if hasattr(self.main, "fonts_changed") else
                                f"Installed {len(done)} font(s) – restart MSE Studio so MSE "
                                "draws them.")
        return True

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
        samples = self._samples(fr) if self.sample_cb.isChecked() else {}
        self.view.show_frame(pm, {k: fr.box(k) for k in keys}, keys, samples)

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

    def _size(self, key: str, value: float):
        if self.frame is None or self._loading:
            return
        if value:
            self.frame.sizes[key] = round(value, 1)
        else:
            self.frame.sizes.pop(key, None)
        self._changed()
        self.size_boxes[key].setSpecialValueText(f"automatic ({self.frame.size(key):g})")
        self._draw_layout()

    def _mana_flow(self, *_):
        if self.frame is None or self._loading:
            return
        self.frame.mana_flow = self.mana_flow.currentData() or ""
        self._changed()
        self._draw_layout()

    def _shadows(self, on: bool):
        if self.frame is None or self._loading:
            return
        if on:
            self.frame.shadows.pop("_off", None)
        else:
            self.frame.shadows["_off"] = True
        self._changed()

    def _align(self, key: str):
        if self.frame is None or self._loading:
            return
        self.frame.aligns[key] = self.align_boxes[key].currentData()
        self._changed()
        self._draw_layout()

    def _samples(self, fr) -> dict:
        """box → (text, font family, size, colour, bold) for the sample text."""
        return {"name": ("Card Name", fr.font("title"), fr.size("title"), fr.colour("name"),
                         False, fr.align("name")),
                "cost": ("{2}{B}{R}" if fr.vertical_cost() else "{2}{W}", fr.font("text"),
                         fr.size("cost"), "#000000", False, "", (self._mana_pixmaps(fr),
                                                                fr.mana_flow)),
                "type": ("Creature — Human Wizard", fr.font("title"), fr.size("type"),
                         fr.colour("type"), False, fr.align("type")),
                "text": ("Flying\nWhen this creature enters, draw a card, then discard a "
                         "card.", fr.font("text"), fr.size("text"), fr.colour("text"), False,
                         fr.align("text")),
                "pt": ("2/3", fr.font("pt"), fr.size("pt"), fr.colour("pt"), False, "center"),
                "artist": ("Illus. Artist Name", fr.font("info"), fr.size("info"),
                           fr.colour("artist"), False, fr.align("artist")),
                "credit": ("Your credit line", fr.font("info"), fr.size("info"),
                           fr.colour("artist"), False, fr.align("credit"))}

    def _mana_pixmaps(self, fr) -> dict:
        """The frame's own mana symbols for the sample text (and the numbers' look)."""
        out: dict = {"font": fr.font("mana") or fr.font("title"),
                     "colour": fg.mana_number_colour(fr)}
        for k, _label in fg.MANA_SLOTS:
            pic = fr.pictures.get(k)
            if pic:
                try:
                    out[k] = QPixmap.fromImage(_qimage(fg.mana_picture(fg.frame_dir(fr.slug) /
                                                                       pic)))
                except Exception:  # noqa: BLE001 - drawn as MSE's usual symbol
                    pass
        return out

    def _load_fonts(self):
        """The frame's own fonts, for the sample text (only inside MSE Studio –
        MSE needs them installed: Install them for MSE)."""
        from PySide6.QtGui import QFontDatabase
        done = getattr(self, "_loaded_fonts", set())
        for f in fg.frame_fonts(self.frame) if self.frame else []:
            if str(f) not in done:
                QFontDatabase.addApplicationFont(str(f))
                done.add(str(f))
        self._loaded_fonts = done

    def _check_pictures(self):
        """Pictures that are almost empty: single layers of a Photoshop file
        (Frame studio 1.0) – say how to put each colour together."""
        fr = self.frame
        if fr is None:
            self.empty_hint.setVisible(False)
            return
        covers = []
        for k in fg.BASE + ["l"]:
            pic = fr.pictures.get(k)
            if pic:
                try:
                    covers.append(fg.coverage(fg.frame_dir(fr.slug) / pic))
                except Exception:  # noqa: BLE001
                    pass
        empty = bool(covers) and max(covers) < 0.12
        self.empty_hint.setVisible(empty)
        if empty:
            self.empty_hint.setText(
                "<b>These pictures are almost empty</b> – most likely single layers of a "
                "Photoshop file. Press <b>Pictures from the files again…</b> and add the "
                "Photoshop file: each colour is put together from its layers now.")

    def remake_pictures(self):
        """New pictures for this frame from the maker's files – the boxes,
        colours and fonts stay."""
        fr = self.frame
        if fr is None:
            return
        files = [Path(f) for f in (fr.sources or ([fr.made_from] if fr.made_from else []))
                 if f and Path(f).exists()]
        dlg = NewFrameDialog(self, files, fr.name)
        dlg.setWindowTitle(f"{fr.name} – pictures from the files again")
        if not dlg.exec():
            return
        chosen, fonts, names = dlg.chosen(), dlg.chosen_fonts(), dlg.font_names()
        layout = dlg.layout()
        frame = fr

        def work(progress=None, cancel=None):
            progress(0, 0, f"Putting {frame.name} together…")
            fg.set_pictures(frame, chosen)
            if fonts:
                fg.keep_fonts(frame, fonts)
            if layout:
                fg.apply_layout(frame, layout)
            frame.fonts.update(names)
            frame.sources = list(dict.fromkeys(frame.sources + getattr(dlg, "sources", [])))
            fg.save_frame(frame)
            return frame.slug

        def done(slug):
            try:
                self.fill(slug)
                self.status.setText("New pictures – Save and add to MSE to update the frame "
                                    "in MSE.")
            except RuntimeError:
                return
        job = Job(work, label=f"New pictures for {fr.name}")
        job.signals.finished.connect(done)
        job.signals.failed.connect(self._failed)
        self._jobs.append(start(job))

    def _font(self, key: str, family: str):
        if self.frame is not None and not self._loading and family.strip():
            self.frame.fonts[key] = family.strip()
            self._changed()

    def choose_picture(self, slot: str):
        if self.frame is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, f"The frame for {dict(fg.SLOTS + fg.PT_SLOTS).get(slot, slot)}", "",
            "Pictures (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.psd *.psb)")
        if not path:
            return
        src = Path(path)
        if src.suffix.lower() in (".psd", ".psb"):
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
                   proxy_deck: str = "", done=None) -> None:
        """A new frame from pictures, Photoshop files and fonts (Proxy decks
        sends a deck's templates here). ``done(frame)`` is called once it's
        made (in the background – big pictures take a moment)."""
        dlg = NewFrameDialog(self, files, name)
        if not dlg.exec():
            return None
        chosen, fonts, names = dlg.chosen(), dlg.chosen_fonts(), dlg.font_names()
        layout = dlg.layout()
        title = dlg.name.text()
        sources = list(dict.fromkeys(getattr(dlg, "sources", [])))
        first = Path(sources[0]) if sources else None
        made_from = str(first if first.is_dir() else first.parent) if first else ""

        def work(progress=None, cancel=None):
            progress(0, 0, f"Making {title}…")
            frame = fg.new_frame(title, chosen, made_from=made_from, fonts=fonts,
                                 font_names=names, layout=layout)
            frame.proxy_deck = proxy_deck
            frame.sources = sources
            fg.save_frame(frame)
            return frame

        def made(frame):
            try:
                self.fill(frame.slug)
                self.tabs.setCurrentIndex(1)
                self.status.setText(
                    ("The boxes, sizes, colours and fonts come from the Photoshop file – "
                     "check them, " if layout else
                     "Check where the name, art and text go (drag the boxes), ") +
                    "then Save and add to MSE.")
            except RuntimeError:
                return
            if callable(done):
                done(frame)

        self.status.setText(f"Making {title}…")
        job = Job(work, label=f"Making the frame {title}")
        job.signals.finished.connect(made)
        job.signals.failed.connect(self._failed)
        self._jobs.append(start(job))
        return None

    def design_frame(self, frame: Optional[fg.Frame] = None) -> None:
        """The Frame designer: a new frame, or ``frame`` drawn again."""
        from . import designer as ds
        from .designer_dialog import DesignerDialog
        design = ds.Design.from_dict(frame.design) if frame is not None and frame.design \
            else None
        dlg = DesignerDialog(self, self.main, design, frame.name if frame else "")
        if not dlg.exec():
            return
        d, title = dlg.design, dlg.name.text().strip()
        slug = frame.slug if frame is not None else ""

        def work(progress=None, cancel=None):
            from mse_studio.pipeline.common import Cancelled
            from . import psdread
            try:
                pics = ds.render_all(d, fg.MAX_W, progress, cancel)
            except psdread.Stopped:
                raise Cancelled() from None
            progress(0, 0, f"Saving {title}…")
            if slug:
                fr = next((f for f in fg.load_frames() if f.slug == slug), None)
                if fr is None:
                    raise fg.FrameError("The frame isn't there any more.")
                fr.name = title or fr.name
                gone = {k: None for k in fr.pictures if k not in pics}
                fg.set_pictures(fr, {**gone, **pics})
            else:
                fr = fg.new_frame(title, pics)
            ds.apply_to_frame(fr, d)
            fg.save_frame(fr)
            return fr.slug

        def made(s):
            try:
                self.fill(s)
                self.tabs.setCurrentIndex(1)
                self.status.setText("Drawn – check it on Where things go, then Save and add to "
                                    "MSE." if not slug else "Drawn again – Save and add to MSE to "
                                    "update it in MSE.")
            except RuntimeError:
                return
        self.status.setText(f"Drawing {title}…")
        job = Job(work, label=f"Drawing the frame {title}")
        job.signals.finished.connect(made)
        job.signals.failed.connect(self._failed)
        self._jobs.append(start(job))

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
        if not self.install_fonts(ask=True):
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
