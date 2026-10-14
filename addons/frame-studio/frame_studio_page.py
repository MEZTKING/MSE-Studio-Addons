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
    """Pictures in (and Photoshop files, put together colour by colour), a
    colour for each (guessed from their names), the fonts that came with
    them, a name."""

    def __init__(self, parent, files: Optional[list] = None, name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("A new frame from pictures")
        self.resize(820, 700)
        self.rows: list = []           # (label, source, combo): a path, or (psd key, PsdPick)
        self._psds: dict = {}          # psd key → the file read (up to PSD_W wide)
        self._jobs: list = []
        self._ready: Optional[dict] = None
        self._queue: list = []         # Photoshop files still to read
        self.fonts: list = []          # font files found
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("e.g. Death Note – Vibrant")
        f.addRow("Name of the frame", self.name)
        lay.addLayout(f)
        hint = QLabel("The blank frames: one picture per colour (White, Blue, Black, Red, Green, "
                      "Gold, Artifact, Colourless, and Land if there is one). Their names "
                      "usually say which is which – check the guesses below. A Photoshop file's "
                      "colours are put together from its layers (each colour's own layers, "
                      "without the sample text and art); its groups and single layers are "
                      "there too.")
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        lay.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Picture", "It's the frame for"])
        self.tree.setIconSize(QSize(42, 58))
        self.tree.setColumnWidth(0, 470)
        lay.addWidget(self.tree, 3)
        row = QHBoxLayout()
        self.add_btns = []
        for label, fn, icon, tip in (
                ("Add pictures…", self.add_files, "add_photo_alternate",
                 "Picture files, Photoshop files or fonts"),
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
            return path, psd, picks, thumbs

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
            path, psd, picks, thumbs = result
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
                self._add_row(parent, pk.label, (key, pk), "", th, guess)
            if single is not None:
                single.setText(0, f"Single layers ({single.childCount()})")
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
    def _add_row(self, parent, label: str, source, guess_from: str, img, guess: str = None):
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
        for k, v in fg.SLOTS:
            combo.addItem(v, k)
        for k, v in fg.PT_SLOTS:
            combo.addItem(f"P/T box – {v}", k)
        if guess is None:
            guess = fg.guess_slot(guess_from) or ""
        if guess and any(r[2].currentData() == guess for r in self.rows):
            guess = ""                         # one picture per colour
        combo.setCurrentIndex(max(0, combo.findData(guess)))
        combo.currentIndexChanged.connect(self._count)
        self.tree.setItemWidget(it, 1, combo)
        self.rows.append((label, source, combo))

    def _count(self, *_):
        n = sum(1 for r in self.rows if r[2].currentData())
        if not self._jobs:
            self.status.setText(f"{len(self.rows)} picture(s), {n} used" if self.rows else
                                "Add the frame pictures (or a Photoshop file).")

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
            col = fr.colour(k) if fr else "#000000"
            b.setText(col)
            b.setStyleSheet(f"QPushButton {{ background: {col}; color: "
                            f"{'#000' if QColor(col).lightness() > 128 else '#fff'}; }}")
        for k, fb in self.font_boxes.items():
            fb.setCurrentText(fr.font(k) if fr else fg.DEFAULT_FONTS[k])
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
        title = dlg.name.text()
        made_from = str(Path(files[0]).parent) if files else ""

        def work(progress=None, cancel=None):
            progress(0, 0, f"Making {title}…")
            frame = fg.new_frame(title, chosen, made_from=made_from, fonts=fonts,
                                 font_names=names)
            frame.proxy_deck = proxy_deck
            fg.save_frame(frame)
            return frame

        def made(frame):
            try:
                self.fill(frame.slug)
                self.tabs.setCurrentIndex(1)
                self.status.setText("Check where the name, art and text go (drag the boxes), "
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
