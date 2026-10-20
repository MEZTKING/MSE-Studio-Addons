"""Paint studio's page: the deck's paintings, new ones, and painting a
card's art (MSE Studio's "Paint this card's art" opens Paint studio too)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)

from . import files
from .doc import Document, Layer

ADDON_ID = "paint-studio"
CARD_W = 1600                 # a card's art is painted this wide (MSE scales it down)
SIZES = [("card", "A card's art (the shape of its art box)"),
         ("full", "A whole card, borderless (2.5 × 3.5)"),
         ("square", "Square (2000 × 2000)"),
         ("wide", "Wide (2400 × 1600)"),
         ("custom", "My own size")]
BACKGROUNDS = [("white", "White paper"), ("clear", "See-through"), ("colour", "The colour")]


def _safe(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name).strip(" .")
    return name[:80] or "Painting"


class NewPaintingDialog(QDialog):
    def __init__(self, parent, art_box: tuple[int, int], colour: QColor):
        super().__init__(parent)
        self.setWindowTitle("New painting")
        self.art_box = art_box
        self.colour = colour
        f = QFormLayout(self)
        self.name = QLineEdit("Painting")
        f.addRow("Name", self.name)
        self.size = QComboBox()
        for k, label in SIZES:
            self.size.addItem(label, k)
        f.addRow("Size", self.size)
        self.w, self.h = QSpinBox(), QSpinBox()
        for s in (self.w, self.h):
            s.setRange(64, 8000)
            s.setSuffix(" px")
        f.addRow("Width", self.w)
        f.addRow("Height", self.h)
        self.bg = QComboBox()
        for k, label in BACKGROUNDS:
            self.bg.addItem(label, k)
        f.addRow("Background", self.bg)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Start painting")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.size.currentIndexChanged.connect(self._preset)
        self._preset()

    def _preset(self, *_):
        k = self.size.currentData()
        bw, bh = self.art_box
        sizes = {"card": (CARD_W, round(CARD_W * bh / max(1, bw))), "full": (1500, 2100),
                 "square": (2000, 2000), "wide": (2400, 1600)}
        if k in sizes:
            self.w.setValue(sizes[k][0])
            self.h.setValue(sizes[k][1])
        for s in (self.w, self.h):
            s.setEnabled(k == "custom")

    def background(self) -> Optional[QColor]:
        k = self.bg.currentData()
        return QColor("white") if k == "white" else QColor(0, 0, 0, 0) if k == "clear" \
            else QColor(self.colour)


class PaintStudioPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.windows: dict[str, object] = {}         # painting file → its open studio
        self._overlay_for: Optional[str] = None
        try:
            from mse_studio.core import addons
            self.data_dir = Path(addons.data_dir(ADDON_ID))
        except Exception:  # noqa: BLE001 - older MSE Studio
            self.data_dir = None
        lay = QVBoxLayout(self)
        try:
            from mse_studio.gui.nav import page_header
            lay.addWidget(page_header(
                "Paint studio",
                "Paint your cards' art with layers, real-feeling brushes (pencils, inks, oils, "
                "watercolour, airbrushes…), a pen's pressure, smudging, liquify, selections "
                "and adjustments – and see the card's frame over it while you paint."))
        except ImportError:
            lay.addWidget(QLabel("Paint studio"))
        row = QHBoxLayout()
        self.card_btn = QPushButton("Paint this card's art")
        self.card_btn.setProperty("kind", "primary")
        self.card_btn.setToolTip("The card open on the Cards page: carry on with its "
                                 "painting, or start one over its art")
        self.new_btn = QPushButton("New painting…")
        self.open_btn = QPushButton("Open a picture or painting…")
        self.open_btn.setToolTip("A .ora painting (Krita, GIMP, MyPaint), a Photoshop file "
                                 "with its layers, or any picture")
        for b in (self.card_btn, self.new_btn, self.open_btn):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.hint = QLabel()
        self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListWidget.IconMode)
        self.gallery.setResizeMode(QListWidget.Adjust)
        self.gallery.setMovement(QListWidget.Static)
        self.gallery.setIconSize(QSize(180, 220))
        self.gallery.setGridSize(QSize(204, 270))
        self.gallery.setWordWrap(True)
        self.gallery.setSpacing(6)
        self.gallery.setContextMenuPolicy(Qt.CustomContextMenu)
        lay.addWidget(self.gallery, 1)
        self.card_btn.clicked.connect(self.paint_current_card)
        self.new_btn.clicked.connect(self.new_painting)
        self.open_btn.clicked.connect(self.open_file)
        self.gallery.itemDoubleClicked.connect(self._open_item)
        self.gallery.customContextMenuRequested.connect(self._menu)
        self._register()
        self.load()

    # ------------------------------------------------------------ MSE Studio's hook
    def _register(self) -> None:
        """MSE Studio's "Paint this card's art" opens Paint studio (from 0.25.0)."""
        try:
            from mse_studio.core import picture_tools
            reg = getattr(picture_tools, "register_painter", None)
            if reg is not None:
                reg("Paint studio", self._paint_hook, owner=self)
        except ImportError:
            pass

    def _paint_hook(self, card, base=None, start_blank: bool = False) -> bool:
        start = None
        if base is not None:
            try:
                from mse_studio.core.paint import pil_to_qimage
                start = pil_to_qimage(base)
            except Exception:  # noqa: BLE001
                start = None
        return self.paint_card(card, start=start, start_blank=start_blank) is not None

    # ------------------------------------------------------------ where paintings live
    def folder(self) -> Optional[Path]:
        p = self.main.project
        if p is not None:
            return Path(p.folder) / "paintings"
        return self.data_dir / "paintings" if self.data_dir else None

    def card_path(self, card) -> Optional[Path]:
        p = self.main.project
        if p is None:
            return None
        try:
            from mse_studio.core.paint import painting_path
            return painting_path(p, card).with_suffix(files.EXT)
        except Exception:  # noqa: BLE001
            return None

    def _card_paintings(self) -> dict[Path, object]:
        p = self.main.project
        if p is None:
            return {}
        out = {}
        for c in p.set.cards:
            path = self.card_path(c)
            if path is not None and path.exists():
                out[path] = c
        return out

    # ------------------------------------------------------------ the page
    def load(self):
        self.refresh()

    def refresh(self):
        p = self.main.project
        card = self._current_card()
        self.card_btn.setEnabled(card is not None)
        self.card_btn.setText(f"Paint the art of “{card.name or 'untitled'}”" if card is not None
                              else "Paint this card's art")
        self.hint.setText(
            "Open a card on the Cards page to paint its art – or start a painting of your own."
            if p is not None else "Open a deck to paint its cards' art. Paintings you start "
            "now are kept with Paint studio.")
        self.gallery.clear()
        items = []
        for path, c in self._card_paintings().items():
            items.append((path, f"{c.name or 'untitled'}\n(card art)"))
        folder = self.folder()
        if folder is not None and folder.is_dir():
            for path in sorted(folder.glob(f"*{files.EXT}"), key=lambda q: -q.stat().st_mtime):
                items.append((path, path.stem))
        for path, label in items:
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, str(path))
            thumb = files.thumbnail(path, 220)
            if thumb is not None and not thumb.isNull():
                it.setIcon(QIcon(QPixmap.fromImage(thumb)))
            it.setToolTip(str(path))
            self.gallery.addItem(it)
        if not items:
            it = QListWidgetItem("No paintings yet")
            it.setFlags(Qt.NoItemFlags)
            self.gallery.addItem(it)

    def _current_card(self):
        if self.main.project is None:
            return None
        try:
            return self.main.cards_tab.editor.card
        except AttributeError:
            return None

    def _open_item(self, it: QListWidgetItem) -> None:
        path = it.data(Qt.UserRole)
        if path:
            self.open_painting(Path(path))

    def _menu(self, pos) -> None:
        it = self.gallery.itemAt(pos)
        path = it.data(Qt.UserRole) if it is not None else None
        if not path:
            return
        path = Path(path)
        m = QMenu(self)
        m.addAction("Open", lambda: self.open_painting(path))
        if self.main.project is not None:
            m.addAction("Put it on a card…", lambda: self.put_on_card(path))
        m.addAction("Export as PNG…", lambda: self._export(path))
        m.addAction("Show the file", lambda: self._show(path))
        m.addSeparator()
        m.addAction("Delete…", lambda: self._delete(path))
        m.exec(self.gallery.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ opening paintings
    def _studio(self, doc: Document, path: Path, title: str, card=None):
        from .studio import StudioWindow
        key = str(path)
        old = self.windows.get(key)
        if old is not None:
            try:
                old.show()
                old.raise_()
                old.activateWindow()
                return old
            except RuntimeError:
                self.windows.pop(key, None)
        on_use = None
        if self.main.project is not None:
            on_use = (lambda png, c=card: self._use_on_card(png, c)) if card is not None \
                else self._use_on_chosen_card
        w = StudioWindow(self.main, doc, path, self.data_dir, title, on_use=on_use)
        w.saved.connect(self._saved)
        w.destroyed.connect(self._window_gone)
        w.setAttribute(Qt.WA_DeleteOnClose)
        self.windows[key] = w
        w.showMaximized()
        if card is not None:
            self._frame_for(card, key)
        return w

    def _window_gone(self, *_):
        try:
            for k in [k for k, w in self.windows.items() if not _alive(w)]:
                del self.windows[k]
            self.refresh()
        except RuntimeError:
            return

    def _saved(self, _path: str) -> None:
        try:
            if self.isVisible():
                self.refresh()
        except RuntimeError:
            return

    def open_painting(self, path: Path):
        try:
            doc = files.load(path)
        except (OSError, ValueError) as e:
            self._error(f"The painting can't be opened: {e}")
            return None
        card = self._card_paintings().get(path)
        title = (card.name or "untitled") if card is not None else path.stem
        return self._studio(doc, path, title, card)

    def new_painting(self, *_args, name: str = "", width: int = 0, height: int = 0,
                     background: Optional[QColor] = None):
        """A new painting: asks for its size unless ``width`` and ``height`` are given."""
        folder = self.folder()
        if folder is None:
            return None
        if not width or not height:
            card = self._current_card()
            box = self.main.project.art_box_for(card) if card is not None else (745, 986)
            dlg = NewPaintingDialog(self, box, QColor("#3a6ea5"))
            if dlg.exec() != QDialog.Accepted:
                return None
            name, width, height = dlg.name.text(), dlg.w.value(), dlg.h.value()
            background = dlg.background()
        doc = Document(width, height, background if background is not None else QColor("white"))
        doc.add_layer("Sketch")
        doc._undo.clear()
        folder.mkdir(parents=True, exist_ok=True)
        path = self._free_path(folder, _safe(name or "Painting"))
        try:
            files.save(doc, path)
        except OSError as e:
            self._error(f"The painting can't be saved there: {e}")
            return None
        doc.dirty = False
        self.refresh()
        return self._studio(doc, path, path.stem)

    @staticmethod
    def _free_path(folder: Path, stem: str) -> Path:
        path = folder / f"{stem}{files.EXT}"
        n = 2
        while path.exists():
            path = folder / f"{stem} {n}{files.EXT}"
            n += 1
        return path

    def open_file(self, path: str = ""):
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Open a picture or painting", "",
                "Paintings and pictures (*.ora *.psd *.psb *.png *.jpg *.jpeg *.webp *.bmp "
                "*.tif *.tiff)")
        if not path:
            return None
        src = Path(path)
        folder = self.folder()
        if folder is None:
            return None
        try:
            if src.suffix.lower() == files.EXT:
                doc = files.load(src)
            else:
                got = files.import_psd_layers(src) if src.suffix.lower() in (".psd", ".psb") \
                    else None
                if got:
                    w, h, layers = got
                    doc = Document(w, h)
                    doc.layers = list(layers)
                    doc.active = len(layers) - 1
                else:
                    img = files.import_image(src)
                    doc = Document(img.width(), img.height())
                    doc.layers = [Layer("Picture", img)]
                    doc.add_layer("Paint")
                doc._undo.clear()
        except (OSError, ValueError) as e:
            self._error(f"That file can't be opened: {e}")
            return None
        folder.mkdir(parents=True, exist_ok=True)
        dst = self._free_path(folder, _safe(src.stem))
        try:
            files.save(doc, dst)
        except OSError as e:
            self._error(f"The painting can't be saved there: {e}")
            return None
        doc.dirty = False
        self.refresh()
        return self._studio(doc, dst, dst.stem)

    # ------------------------------------------------------------ a card's art
    def paint_current_card(self):
        card = self._current_card()
        if card is None:
            self._error("Open a card on the Cards page first.")
            return None
        return self.paint_card(card)

    def paint_card(self, card, start: Optional[QImage] = None, start_blank: bool = False):
        """Paint ``card``'s art: its painting if it has one, else a new one over
        its art (or over ``start``, or blank)."""
        p = self.main.project
        path = self.card_path(card)
        if p is None or path is None:
            return None
        doc = None
        if path.exists() and start is None and not start_blank:
            try:
                doc = files.load(path)
            except (OSError, ValueError) as e:
                self._error(f"The card's painting can't be opened ({e}); starting a new one.")
        old = path.with_suffix(".msepaint")
        if doc is None and old.exists() and start is None and not start_blank:
            doc = _from_old_painting(old)
        if doc is None:
            bw, bh = p.art_box_for(card)
            doc = Document(CARD_W, max(1, round(CARD_W * bh / max(1, bw))))
            art = start
            if art is None and not start_blank:
                data = p.set.card_image_bytes(card)
                art = QImage.fromData(data) if data else None
            if art is not None and not art.isNull():
                doc.add_layer("Card's art", art.convertToFormat(QImage.Format_ARGB32_Premultiplied))
            doc.add_layer("Paint")
            doc._undo.clear()
            doc.dirty = False
        return self._studio(doc, path, card.name or "untitled", card)

    def _frame_for(self, card, key: str) -> None:
        """The card's frame over the painting: MSE draws the card without art."""
        if not getattr(self.main.settings, "mse_path", ""):
            return
        try:
            ct = self.main.cards_tab
            if ct.editor.card is not card:
                cards = self.main.project.set.cards
                row = next((i for i, c in enumerate(cards) if c is card), -1)
                if row >= 0:
                    ct.select_row(row)
            if ct.editor.card is not card:
                return
            self._overlay_for = key
            ct.editor.art_layers(self._frame_ready)
        except Exception:  # noqa: BLE001 - no frame on top then
            return

    def _frame_ready(self, renders) -> None:
        try:
            w = self.windows.get(self._overlay_for or "")
            if w is None or not _alive(w) or not renders:
                return
            from PIL import Image
            from mse_studio.pipeline import art_preview
            with Image.open(renders[0]) as a, Image.open(renders[1]) as b:
                got = art_preview.layers(a, b)
            if got is None:
                return
            frame, mask, box = got
            from PIL import ImageChops
            alpha = ImageChops.invert(mask.convert("L"))
            frame = frame.copy()
            frame.putalpha(ImageChops.multiply(frame.getchannel("A"), alpha))
            import io
            buf = io.BytesIO()
            frame.save(buf, format="PNG")
            img = QImage.fromData(buf.getvalue(), "PNG")
            x0, y0, x1, y1 = box
            w.set_overlay(img, QRectF(x0, y0, x1 - x0, y1 - y0))
        except (RuntimeError, OSError, ValueError):
            return

    def _use_on_card(self, png: Path, card) -> None:
        p = self.main.project
        if p is None or card is None:
            return
        from mse_studio.core import art as art_ops
        with_size = QImage(str(png))
        art_ops.assign_art(p, card, png, [0, 0, with_size.width(), with_size.height()],
                           prefer_upscaled=False, set_credit=False, original=str(png))
        try:
            self.main.record(f"Paint · {card.name or 'untitled'}")
        except Exception:  # noqa: BLE001
            p.dirty = True
        ct = self.main.cards_tab
        cards = p.set.cards
        row = next((i for i, c in enumerate(cards) if c is card), -1)
        try:
            ct.reload(row if row >= 0 else None)
        except TypeError:
            ct.reload()

    def _use_on_chosen_card(self, png: Path) -> None:
        card = self._choose_card()
        if card is not None:
            self._use_on_card(png, card)

    def _choose_card(self):
        p = self.main.project
        if p is None or not p.set.cards:
            return None
        cards = list(p.set.cards)
        names = [f"{i + 1}. {c.name or 'untitled'}" for i, c in enumerate(cards)]
        cur = self._current_card()
        start = cards.index(cur) if cur in cards else 0
        name, ok = QInputDialog.getItem(self, "Put it on a card", "Which card?", names, start,
                                        False)
        if not ok:
            return None
        return cards[names.index(name)]

    def put_on_card(self, path: Path) -> None:
        card = self._choose_card()
        if card is None:
            return
        try:
            doc = files.load(path)
            png = path.with_suffix(".png")
            files.export_png(doc, png)
        except (OSError, ValueError) as e:
            self._error(str(e))
            return
        self._use_on_card(png, card)

    # ------------------------------------------------------------ the gallery's menu
    def _export(self, path: Path) -> None:
        dst, _ = QFileDialog.getSaveFileName(self, "Export", f"{path.stem}.png", "PNG (*.png)")
        if not dst:
            return
        try:
            files.export_png(files.load(path), Path(dst))
        except (OSError, ValueError) as e:
            self._error(str(e))

    def _show(self, path: Path) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _delete(self, path: Path) -> None:
        try:
            from mse_studio.gui.common import ask_delete
            if not ask_delete(self, f"Delete the painting “{path.stem}”? Its layers are "
                                    f"lost (a card keeps the art it has now)."):
                return
        except ImportError:
            pass
        w = self.windows.pop(str(path), None)
        if w is not None and _alive(w):
            w.doc.dirty = False
            w.close()
        try:
            path.unlink()
        except OSError as e:
            self._error(f"It can't be deleted: {e}")
        self.refresh()

    def _error(self, text: str) -> None:
        try:
            from mse_studio.gui.common import error
            error(self, "Paint studio", text)
        except ImportError:
            pass

    def shutdown(self):
        for w in list(self.windows.values()):
            if _alive(w):
                w.close()
        self.windows.clear()


def _alive(w) -> bool:
    try:
        import shiboken6
        return shiboken6.isValid(w)
    except Exception:  # noqa: BLE001
        return True


def _from_old_painting(path: Path) -> Optional[Document]:
    """A painting from MSE Studio's own paint window (.msepaint) as layers."""
    try:
        from mse_studio.core.paint import PaintDoc
        old = PaintDoc.load(path)
    except Exception:  # noqa: BLE001
        return None
    doc = Document(old.width, old.height)
    blends = {"Normal": "normal", "Multiply": "multiply", "Screen": "screen",
              "Overlay": "overlay", "Darken": "darken", "Lighten": "lighten",
              "Add": "add", "Soft light": "soft-light", "Hard light": "hard-light"}
    doc.layers = [Layer(lay.name, lay.image.convertToFormat(QImage.Format_ARGB32_Premultiplied),
                        float(lay.opacity), blends.get(lay.blend, "normal"), bool(lay.visible))
                  for lay in old.layers] or doc.layers
    doc.active = min(old.active, len(doc.layers) - 1)
    doc._undo.clear()
    doc.dirty = False
    return doc
