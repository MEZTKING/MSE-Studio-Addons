"""Art only: just the art of a card – cut out of its window, or with the frame
and text painted over (full-art cards) – for your own cards. The Decklists
page and Proxy decks send cards here: right-click a card → Keep only the art.

Network: none of its own (Scryfall's cut-out art of a real card is downloaded
by MSE Studio when you ask for it; AI fill – only when AI is switched on in
MSE Studio's settings and you press Fill with AI – is sent by MSE Studio to
the AI service set there). Files: the picture you open (read) and the deck's art
folder (the result)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog,
                               QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout,
                               QLabel, QPushButton, QRadioButton, QSlider, QSplitter,
                               QVBoxLayout, QWidget)

from mse_studio.gui import icons
from mse_studio.gui.common import Job, error, forget, start
from mse_studio.gui.nav import page_header

from . import artonly as ao

ADDON_ID = "art-only"
MAX_VIEW = 1100              # the painting is done on a picture this tall at most


def _qimage(img) -> QImage:
    img = img.convert("RGBA")
    return QImage(img.tobytes("raw", "RGBA"), img.width, img.height, img.width * 4,
                  QImage.Format_RGBA8888).copy()


class PaintView(QGraphicsView):
    """The card with the parts to paint over in red: drag to paint more,
    right-drag to paint less."""

    def __init__(self, on_painted):
        super().__init__()
        self.on_painted = on_painted
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#2b2b2b"))
        self.pic_item: Optional[QGraphicsPixmapItem] = None
        self.mask_item: Optional[QGraphicsPixmapItem] = None
        self.overlay: Optional[QImage] = None
        self.brush = 30
        self.enabled = True
        self._last: Optional[QPointF] = None
        self._erase = False

    def show_picture(self, pm: QPixmap, mask=None):
        """The card, and the parts to paint over (a PIL 'L' mask, 255 = over)."""
        from PIL import Image
        sc = self.scene()
        sc.clear()
        self.pic_item = sc.addPixmap(pm)
        size = (pm.width(), pm.height())
        red = Image.new("RGBA", size, (220, 40, 40, 0))
        if mask is not None:
            red.putalpha(mask.resize(size).point(lambda v: 120 if v > 127 else 0))
        self.overlay = _qimage(red).convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self.mask_item = sc.addPixmap(QPixmap.fromImage(self.overlay))
        self.mask_item.setZValue(1)
        sc.setSceneRect(QRectF(pm.rect()))
        self.fitInView(sc.sceneRect(), Qt.KeepAspectRatio)

    def mask(self):
        """The painting as a PIL 'L' mask (255 = paint over), the size on screen."""
        if self.overlay is None:
            return None
        from PIL import Image
        q = self.overlay.convertToFormat(QImage.Format_RGBA8888)
        raw = bytes(q.constBits())[:q.bytesPerLine() * q.height()]
        img = Image.frombytes("RGBA", (q.width(), q.height()), raw, "raw", "RGBA",
                              q.bytesPerLine())
        return img.getchannel("A").point(lambda v: 255 if v > 10 else 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.scene().sceneRect().width() > 0:
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)

    def _paint(self, p: QPointF):
        if self.overlay is None:
            return
        qp = QPainter(self.overlay)
        qp.setRenderHint(QPainter.Antialiasing)
        if self._erase:
            qp.setCompositionMode(QPainter.CompositionMode_Clear)
        else:
            qp.setCompositionMode(QPainter.CompositionMode_Source)
        pen = QPen(QColor(220, 40, 40, 120), self.brush, Qt.SolidLine, Qt.RoundCap,
                   Qt.RoundJoin)
        qp.setPen(pen)
        a = self._last if self._last is not None else p
        qp.drawLine(a, p)
        qp.end()
        self._last = p
        self.mask_item.setPixmap(QPixmap.fromImage(self.overlay))

    def mousePressEvent(self, e):
        if self.overlay is None or not self.enabled:
            return super().mousePressEvent(e)
        self._erase = e.button() == Qt.RightButton
        self._last = None
        self._paint(self.mapToScene(e.position().toPoint()))

    def mouseMoveEvent(self, e):
        if self._last is not None and self.enabled:
            self._paint(self.mapToScene(e.position().toPoint()))
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._last is not None:
            self._last = None
            self.on_painted()
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e):
        e.accept()                  # right-drag paints less, no menu


class ArtOnlyPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._jobs: list = []
        self.path: Optional[Path] = None
        self.info: dict = {}
        self.card_img = None          # the card (PIL), full size
        self.result = None            # the art (PIL)
        lay = QVBoxLayout(self)
        lay.addWidget(page_header(
            "Art only", "Just the art of a card: cut out of its window, or with the frame and "
                        "text painted over for full-art cards – to use on your own cards. On "
                        "the Decklists page and in Proxy decks: right-click a card → Keep only "
                        "the art."))
        split = QSplitter(Qt.Horizontal)
        self.view = PaintView(self._painted)
        split.addWidget(self.view)
        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        b = QPushButton("Open a card picture…")
        icons.set_icon(b, "folder_open")
        b.clicked.connect(self.open_file)
        sv.addWidget(b)
        self.name = QLabel()
        self.name.setWordWrap(True)
        sv.addWidget(self.name)
        self.mode_group = QButtonGroup(self)
        self.window_rb = QRadioButton("Cut out the art window (normal cards)")
        self.full_rb = QRadioButton("Paint over the frame and text (full-art cards)")
        for rb in (self.window_rb, self.full_rb):
            self.mode_group.addButton(rb)
            sv.addWidget(rb)
        self.window_rb.toggled.connect(self._mode_changed)
        self.parts_box = QWidget()
        pv = QVBoxLayout(self.parts_box)
        pv.setContentsMargins(18, 0, 0, 0)
        self.parts: dict = {}
        for name in list(ao.ERASE) + ["border"]:
            cb = QCheckBox({"border": "The black border"}.get(name, name.capitalize()))
            cb.setChecked(True)
            cb.toggled.connect(self._parts_changed)
            pv.addWidget(cb)
            self.parts[name] = cb
        row = QHBoxLayout()
        row.addWidget(QLabel("Brush"))
        self.brush = QSlider(Qt.Horizontal)
        self.brush.setRange(6, 120)
        self.brush.setValue(30)
        self.brush.valueChanged.connect(lambda v: setattr(self.view, "brush", v))
        row.addWidget(self.brush)
        pv.addLayout(row)
        hint = QLabel("Drag on the card to paint more over, right-drag to paint less.")
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        pv.addWidget(hint)
        row = QHBoxLayout()
        row.addWidget(QLabel("Fill with"))
        self.fill = QComboBox()
        for k, label in ao.FILLS.items():
            self.fill.addItem(label, k)
        self.fill.setToolTip("Content-aware: rebuilt from the art around it, textures and lines "
                             "carry on (a few seconds). Quick: smoothed over at once.")
        self.fill.currentIndexChanged.connect(self._fill_changed)
        row.addWidget(self.fill, 1)
        pv.addLayout(row)
        self.ai_fill_btn = QPushButton("Fill with AI")
        icons.set_icon(self.ai_fill_btn, "auto_fix_high")
        self.ai_fill_btn.clicked.connect(self.ai_fill)
        pv.addWidget(self.ai_fill_btn)
        self._gen = 0                  # the newest fill; older ones are stopped
        sv.addWidget(self.parts_box)
        self.scry_btn = QPushButton("Use Scryfall's cut-out art (sharpest)")
        self.scry_btn.setToolTip("A real card: Scryfall's own picture of just the art")
        self.scry_btn.clicked.connect(self.scryfall_art)
        sv.addWidget(self.scry_btn)
        sv.addWidget(QLabel("<b>The art</b>"))
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(220)
        sv.addWidget(self.preview, 1)
        self.save_btn = QPushButton("Save in my art folder")
        self.save_btn.setProperty("kind", "primary")
        icons.set_icon(self.save_btn, "save")
        self.save_btn.setToolTip("In the deck's art folder (Art page), with the card's credit")
        self.save_btn.clicked.connect(lambda: self.save("folder"))
        sv.addWidget(self.save_btn)
        self.on_card_btn = QPushButton("Use it on the card I'm editing")
        self.on_card_btn.clicked.connect(lambda: self.save("card"))
        sv.addWidget(self.on_card_btn)
        self.new_card_btn = QPushButton("Use it on a new card of mine")
        self.new_card_btn.clicked.connect(lambda: self.save("new"))
        sv.addWidget(self.new_card_btn)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("Hint")
        sv.addWidget(self.status)
        split.addWidget(side)
        split.setSizes([800, 320])
        lay.addWidget(split, 1)
        try:                                    # Decklists / Proxy decks offer it
            from mse_studio.core import picture_tools
            picture_tools.register(ADDON_ID, "Keep only the art…", self.open_tool,
                                   tooltip="The card's art without its frame and text, for "
                                           "your own cards (Art only add-on)", owner=self)
        except ImportError:
            pass
        self._buttons()

    # ------------------------------------------------------------ MSE Studio calls these
    def load(self):
        self._buttons()

    def refresh(self):
        self._buttons()

    def shutdown(self):
        forget(self._jobs)

    # ------------------------------------------------------------ a picture in
    def open_tool(self, parent, picture: Path, info: dict):
        """From the Decklists page or Proxy decks."""
        try:
            self.main.tabs.setCurrentWidget(self)
        except Exception:  # noqa: BLE001
            pass
        self.open_picture(Path(picture), info)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "A card picture", "",
                                              "Pictures (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.open_picture(Path(path), {"name": Path(path).stem})

    def open_picture(self, path: Path, info: Optional[dict] = None):
        try:
            img = ao.open_card(path)
        except Exception as e:  # noqa: BLE001
            error(self, "Art only", f"Couldn't open that picture: {e}")
            return
        self.path, self.info, self.card_img = path, dict(info or {}), img
        self.name.setText(f"<b>{self.info.get('name') or path.stem}</b>")
        mode = ao.guess_mode(img)
        self.window_rb.blockSignals(True)
        (self.window_rb if mode == "window" else self.full_rb).setChecked(True)
        self.window_rb.blockSignals(False)
        self._show_card()
        self.make()

    def _view_image(self):
        img = self.card_img
        if img.height > MAX_VIEW:
            img = img.resize((round(img.width * MAX_VIEW / img.height), MAX_VIEW))
        return img

    def _show_card(self):
        if self.card_img is None:
            return
        img = self._view_image()
        mask = None
        if self.full_rb.isChecked():
            parts = [k for k in ao.ERASE if self.parts[k].isChecked()]
            mask = ao.default_mask(img.size, parts, self.parts["border"].isChecked())
        self.view.show_picture(QPixmap.fromImage(_qimage(img)), mask)
        self.view.enabled = self.full_rb.isChecked()
        self._buttons()

    def _fill_changed(self, *_):
        self._buttons()
        self.make()

    def _mode_changed(self, *_):
        self._show_card()
        self.make()

    def _parts_changed(self, *_):
        self._show_card()
        self.make()

    def _painted(self):
        self.make()

    # ------------------------------------------------------------ the art
    def _mask(self):
        return self.view.mask()

    def make(self):
        """Work out the art (in the background) and show it."""
        if self.card_img is None:
            return
        img = self.card_img
        if self.window_rb.isChecked():
            self._made(ao.art_window(img))
            return
        mask = self._mask()
        if mask is None or mask.getbbox() is None:
            mask = ao.default_mask(img.size)
        fill = self.fill.currentData()
        if fill == "ai":
            self.status.setText("Press Fill with AI when the painted parts are right.")
            return
        self._run(fill, lambda progress=None, cancel=None:
                  ao.erase(img, mask.resize(img.size), fill, progress=progress, cancel=cancel))

    def _run(self, fill: str, fn):
        """One fill in the background; a newer one stops it."""
        for j in self._jobs:
            j.cancel.cancel()
        self._gen += 1
        gen = self._gen

        def work(progress=None, cancel=None):
            progress(0, 0, "Painting over the frame and text…")
            try:
                return gen, fn(progress=progress, cancel=cancel)
            except ao.Stopped:
                return gen, None

        self.status.setText("Asking the AI to paint over the frame and text…" if fill == "ai"
                            else "Painting over the frame and text…")
        job = Job(work, label="Art only: painting over the frame and text")
        job.signals.finished.connect(self._done)
        job.signals.failed.connect(self._failed)
        job.signals.cancelled.connect(self._stopped)
        self._jobs = [j for j in self._jobs if not j.cancel.cancelled] + [start(job)]

    def _done(self, result):
        try:
            gen, art = result
            if gen == self._gen and art is not None:
                self._made(art)
        except RuntimeError:
            return

    def _failed(self, msg: str):
        try:
            self.status.setText(msg.splitlines()[0] if msg else "")
        except RuntimeError:
            return

    def _stopped(self):
        return

    # ------------------------------------------------------------ AI (only when switched on)
    def _ai(self):
        """MSE Studio's AI for add-ons, when it can repaint pictures and AI is
        switched on (MSE Studio's Settings) – else None."""
        try:
            from mse_studio.ai import for_addons as ai
        except ImportError:
            return None
        if not hasattr(ai, "edit_picture") or not ai.enabled(self.main.settings):
            return None
        return ai

    def ai_fill(self):
        ai = self._ai()
        if ai is None or self.card_img is None or not self.full_rb.isChecked():
            return
        why = ai.picture_edit_not_ready(self.main.settings)
        if why:
            error(self, "AI fill", why)
            return
        import io
        img = self.card_img
        mask = self._mask()
        if mask is None or mask.getbbox() is None:
            mask = ao.default_mask(img.size)
        mask = mask.resize(img.size)
        settings = self.main.settings

        def png(im) -> bytes:
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()

        def fill(progress=None, cancel=None):
            from PIL import Image
            data = ai.edit_picture(settings, png(img), png(mask), ao.AI_PROMPT)
            with Image.open(io.BytesIO(data)) as im:
                return im.convert("RGB")
        self._run("ai", fill)

    def _made(self, art):
        try:
            self.result = art
            pm = QPixmap.fromImage(_qimage(art))
            self.preview.setPixmap(pm.scaled(300, 300, Qt.KeepAspectRatio,
                                             Qt.SmoothTransformation))
            soft = self.fill.currentData() in ("smart", "blur")
            self.status.setText(f"{art.width} × {art.height} pixels" +
                                (" – painted-over parts are soft (Content-aware fill keeps "
                                 "them sharp)" if self.full_rb.isChecked() and soft else ""))
            self._buttons()
        except RuntimeError:
            return

    def scryfall_art(self):
        card = self.info.get("card") or {}
        p = self.main.project
        if not card or p is None:
            return
        from mse_studio.core import decklists as dl
        entry = dl.Entry(name=self.info.get("name") or card.get("name", ""), card=card)
        folder = p.folder / "real card art"

        def work(progress=None, cancel=None):
            from mse_studio.pipeline import real_cards as rc
            progress(0, 0, "Getting Scryfall's cut-out art…")
            return rc.art_picture(entry, folder)

        job = Job(work, label="Getting the art")
        job.signals.finished.connect(self._scryfall_ready)
        job.signals.failed.connect(lambda m: error(self, "Art only", m.splitlines()[0]))
        self._jobs.append(start(job))

    def _scryfall_ready(self, path):
        try:
            if path is None:
                self.status.setText("Scryfall has no cut-out art for that card.")
                return
            from PIL import Image
            with Image.open(path) as im:
                self._made(im.convert("RGB"))
            self.status.setText("Scryfall's cut-out art – " + self.status.text())
        except RuntimeError:
            return

    def _buttons(self):
        has = self.card_img is not None
        p = self.main.project
        self.parts_box.setVisible(self.full_rb.isChecked())
        for w in (self.window_rb, self.full_rb, self.fill):
            w.setEnabled(has)
        ai = self._ai()
        if ai is not None and self.fill.findData("ai") < 0:
            self.fill.addItem(ao.AI_FILL[1], ao.AI_FILL[0])
        elif ai is None and self.fill.findData("ai") >= 0:
            self.fill.removeItem(self.fill.findData("ai"))
        self.ai_fill_btn.setVisible(ai is not None and self.fill.currentData() == "ai")
        self.ai_fill_btn.setEnabled(has and self.full_rb.isChecked())
        if ai is not None:
            self.ai_fill_btn.setToolTip(f"{ai.service(self.main.settings)} repaints the "
                                        "painted parts (one paid request)")
        ok = self.result is not None and p is not None
        self.save_btn.setEnabled(ok)
        self.new_card_btn.setEnabled(ok)
        self.on_card_btn.setEnabled(ok and getattr(getattr(self.main, "cards_tab", None),
                                                   "editor", None) is not None
                                    and getattr(self.main.cards_tab.editor, "card", None)
                                    is not None)
        self.scry_btn.setVisible(bool((self.info.get("card") or {}).get("id")))
        self.scry_btn.setEnabled(p is not None)
        if not has:
            self.status.setText("Open a card picture – or right-click a card on the Decklists "
                                "page or in Proxy decks → Keep only the art.")

    # ------------------------------------------------------------ using it
    def save(self, where: str):
        import io
        from mse_studio.core import art_import
        p, art = self.main.project, self.result
        if p is None or art is None:
            return
        buf = io.BytesIO()
        art.convert("RGB").save(buf, "PNG")
        folder = art_import.default_folder(p)
        path = art_import.save_image_bytes(buf.getvalue(), folder,
                                           ao.file_name(self.info.get("name") or "card"))
        card = self.info.get("card") or {}
        credit = self.info.get("credit") or ""
        artist = card.get("artist", "") or self.info.get("maker", "")
        art_import.set_credit(p, path, artist, credit, card.get("scryfall_uri", "")
                              or self.info.get("page", ""))
        p.save_config()
        try:
            self.main.art_tab.rescan()
        except Exception:  # noqa: BLE001
            pass
        if where == "folder":
            self.status.setText(f"Saved in your art folder: {path.name}")
            return
        tab = self.main.cards_tab
        tab.editor.commit()
        if where == "new":
            card_obj = p.new_card()
            card_obj.set_text("name", self.info.get("name") or "New card")
            row = len(p.set.cards) - 1
            self.main.record(f"Art only · new card with the art of {self.info.get('name', '')}",
                             row=row)
            tab.reload(row)
            tab.select_row(row)
        self.main.tabs.setCurrentWidget(tab)
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        tab.editor.open_editor(Path(path), crop=[0, 0, w, h], original=str(path),
                               fit={"mode": "stretch"})
