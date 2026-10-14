"""The Frame designer window: every setting of a designed frame, a live
preview of each colour, and AI that turns a description (or an example
card) into settings and paints textures – through MSE Studio's own AI
settings (MSE Studio 0.20.0), only when you press its buttons."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from PIL import Image
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSlider,
                               QSpinBox, QSplitter, QVBoxLayout, QWidget)

from mse_studio.gui import icons
from mse_studio.gui.common import Job, error, forget, start

from . import designer as ds
from . import framegen as fg

PREVIEW_W = 420


def _qimage(img: Image.Image) -> QImage:
    img = img.convert("RGBA")
    return QImage(img.tobytes("raw", "RGBA"), img.width, img.height, img.width * 4,
                  QImage.Format_RGBA8888).copy()


def _sample_art(w: int, h: int) -> Image.Image:
    """Something art-like under the preview's window."""
    top = Image.new("RGB", (w, h), (70, 60, 120))
    bottom = Image.new("RGB", (w, h), (190, 110, 80))
    mask = Image.linear_gradient("L").resize((w, h))
    return Image.composite(bottom, top, mask).convert("RGBA")


def ai_module():
    """MSE Studio's AI for add-ons (0.20.0), or None in older versions."""
    try:
        from mse_studio.ai import for_addons
        return for_addons
    except ImportError:
        return None


class DesignerDialog(QDialog):
    """Design a frame; ``design`` and ``name`` are what's made (after exec)."""

    def __init__(self, parent, main, design: Optional[ds.Design] = None, name: str = ""):
        super().__init__(parent)
        self.main = main
        self.setWindowTitle("Frame designer")
        self.resize(1250, 860)
        self.d = design or ds.Design()
        self._jobs: list = []
        self._gen = 0
        self._loading = False
        self.example: Optional[Path] = None
        self.controls: dict = {}
        lay = QVBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._settings_panel())
        split.addWidget(self._preview_panel())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([560, 690])
        lay.addWidget(split, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Name of the frame"))
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("e.g. Gothic red")
        row.addWidget(self.name, 1)
        self.make_btn = QPushButton("Make the frame")
        self.make_btn.setProperty("kind", "primary")
        icons.set_icon(self.make_btn, "check_circle")
        self.make_btn.setToolTip("Draws every colour's frame, the P/T boxes and the mana symbols "
                                 "(it takes about half a minute)")
        self.make_btn.clicked.connect(self._make)
        row.addWidget(self.make_btn)
        b = QPushButton("Cancel")
        b.clicked.connect(self.reject)
        row.addWidget(b)
        lay.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._render)
        self._show_design()
        self._render()

    def done(self, r):
        self.timer.stop()
        forget(self._jobs)
        super().done(r)

    # ------------------------------------------------------------ the settings
    def _settings_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(500)
        inner = QWidget()
        v = QVBoxLayout(inner)
        top = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItem("– pick a starting point –", "")
        for name in ds.PRESETS:
            self.preset.addItem(name, name)
        self.preset.setToolTip("A ready-made look to start from – change anything after")
        self.preset.currentIndexChanged.connect(self._preset)
        top.addRow("Start from", self.preset)
        v.addLayout(top)
        v.addWidget(self._ai_box())

        def group(title: str) -> QFormLayout:
            g = QGroupBox(title)
            f = QFormLayout(g)
            v.addWidget(g)
            return f
        f = group("Look")
        self._combo(f, "layout", "Layout", ds.LAYOUTS)
        self._combo(f, "material", "Material", ds.MATERIALS)
        self._slider(f, "texture", "Texture", 0, 1, "How strongly the material shows")
        self._slider(f, "texture_size", "Texture size", 0.3, 3, "Bigger: a coarser texture")
        row = QHBoxLayout()
        self.picture_lbl = QLabel("no picture")
        self.picture_lbl.setObjectName("Hint")
        row.addWidget(self.picture_lbl, 1)
        b = QPushButton("Choose…")
        b.setToolTip("A texture picture of your own for the material (stone, cloth, metal…)")
        b.clicked.connect(self._choose_picture)
        row.addWidget(b)
        self.ai_texture_btn = QPushButton("Make one with AI")
        icons.set_icon(self.ai_texture_btn, "auto_fix_high")
        self.ai_texture_btn.setToolTip("An AI picture service paints a texture from the "
                                       "description above (Settings → AI)")
        self.ai_texture_btn.clicked.connect(self._ai_texture)
        row.addWidget(self.ai_texture_btn)
        f.addRow("Texture picture", row)
        seed = QHBoxLayout()
        self.seed = QSpinBox()
        self.seed.setRange(0, 99999)
        self.seed.valueChanged.connect(lambda v: self._set("seed", int(v)))
        seed.addWidget(self.seed)
        b = QPushButton("Shuffle")
        icons.set_icon(b, "casino")
        b.setToolTip("Another pattern of the same texture")
        b.clicked.connect(lambda: self.seed.setValue((self.seed.value() * 7919 + 13) % 100000))
        seed.addWidget(b)
        seed.addStretch(1)
        f.addRow("Pattern", seed)

        f = group("Colours")
        self._combo(f, "palette", "Palette", ds.PALETTES)
        grid = QGridLayout()
        self.colour_btns: dict = {}
        for k, (slot, label) in enumerate(fg.SLOTS):
            b = QPushButton(label.split(" (")[0])
            b.setToolTip(f"The {label.lower()} frame's colour – click to choose your own")
            b.clicked.connect(lambda _c=False, s=slot: self._pick_colour(s))
            grid.addWidget(b, k // 3, k % 3)
            self.colour_btns[slot] = b
        f.addRow(grid)
        b = QPushButton("Back to the palette's colours")
        b.clicked.connect(self._reset_colours)
        f.addRow(b)

        f = group("Border")
        self._combo(f, "border", "Border", ds.BORDERS)
        self._slider(f, "border_width", "Width", 0, 0.08)

        f = group("Bars, boxes and the art window")
        self._combo(f, "bars", "Name and type bars", ds.BAR_SHAPES)
        self._slider(f, "bar_opacity", "Bars see-through", 0.2, 1, "Lower: the art shows "
                     "through the bars")
        self._combo(f, "textbox", "Text box", ds.TEXTBOXES)
        self._combo(f, "textbox_shape", "Text box shape", ds.BOX_SHAPES)
        self._slider(f, "textbox_opacity", "Text box see-through", 0.2, 1)
        self._combo(f, "window", "Art window", ds.WINDOWS)
        self._check(f, "pt_box", "A P/T box for creatures")

        f = group("Edges and effects")
        self._slider(f, "pinlines", "Pinlines", 0, 0.02, "Thin lines around the bars, boxes "
                     "and window (0: none)")
        self._combo(f, "pinline_colour", "Pinline colour", ds.PINLINE_COLOURS)
        self._slider(f, "bevel", "Bevel", 0, 1, "Raised, lit edges")
        self._slider(f, "shadow", "Shadows", 0, 1, "Under the bars and boxes")
        self._slider(f, "glow", "Glow", 0, 1, "Glowing pinlines (and symbols with Vivid)")
        self._slider(f, "wear", "Wear", 0, 1, "Worn, scratched edges")
        self._slider(f, "grain", "Grain", 0, 1)
        self._slider(f, "vignette", "Darker corners", 0, 1)

        f = group("Mana symbols")
        self._combo(f, "mana", "Style", ds.MANA_STYLES)
        self._check(f, "mana_column", "The mana cost down the right side")

        f = group("Fonts")
        families = [""] + sorted(set(QFontDatabase.families()), key=str.lower)
        for key, label in (("title_font", "Name and type line"), ("text_font", "Rules text")):
            cb = QComboBox()
            cb.setEditable(True)
            cb.addItems(families)
            cb.setItemText(0, "")
            cb.lineEdit().setPlaceholderText("MSE's usual font")
            cb.currentTextChanged.connect(lambda t, k=key: self._set(k, t.strip()))
            f.addRow(label, cb)
            self.controls[key] = cb
        v.addStretch(1)
        scroll.setWidget(inner)
        return scroll

    def _ai_box(self) -> QWidget:
        g = QGroupBox("Design it with AI")
        v = QVBoxLayout(g)
        self.describe = QPlainTextEdit()
        self.describe.setPlaceholderText("Describe the look: e.g. \"dark gothic like Death Note – "
                                         "black torn paper, blood-red trim, a parchment text box, "
                                         "mana down the side\"")
        self.describe.setMaximumHeight(80)
        v.addWidget(self.describe)
        row = QHBoxLayout()
        self.example_btn = QPushButton("An example card…")
        icons.set_icon(self.example_btn, "image")
        self.example_btn.setToolTip("A picture of a card in the look you want – the AI looks "
                                    "at it too")
        self.example_btn.clicked.connect(self._choose_example)
        row.addWidget(self.example_btn)
        self.ai_btn = QPushButton("Design it with AI")
        self.ai_btn.setProperty("kind", "primary")
        icons.set_icon(self.ai_btn, "auto_fix_high")
        self.ai_btn.clicked.connect(self._ai_design)
        row.addWidget(self.ai_btn)
        row.addStretch(1)
        v.addLayout(row)
        self.ai_status = QLabel()
        self.ai_status.setObjectName("Hint")
        self.ai_status.setWordWrap(True)
        v.addWidget(self.ai_status)
        ai = ai_module()
        if ai is None:
            self.ai_status.setText("Needs MSE Studio 0.20.0 or newer (Help → Check for "
                                   "updates…).")
            for b in (self.ai_btn, self.example_btn):
                b.setEnabled(False)
        else:
            why = ai.not_ready(self.main.settings)
            self.ai_status.setText(why or f"Uses {ai.service(self.main.settings)} (Settings → "
                                          "AI) – each design is one request on your account.")
            self.ai_btn.setEnabled(not why)
        return g

    def _combo(self, f: QFormLayout, key: str, label: str, choices: dict):
        cb = QComboBox()
        for k, text in choices.items():
            cb.addItem(text, k)
        cb.currentIndexChanged.connect(lambda _i, k=key, c=cb: self._set(k, c.currentData()))
        f.addRow(label, cb)
        self.controls[key] = cb

    def _slider(self, f: QFormLayout, key: str, label: str, lo: float, hi: float,
                tip: str = ""):
        row = QHBoxLayout()
        sl = QSlider(Qt.Horizontal)
        sl.setRange(0, 100)
        sl.setProperty("range", (lo, hi))
        val = QLabel()
        val.setMinimumWidth(36)
        sl.valueChanged.connect(lambda v, k=key, a=lo, b=hi, lb=val: (
            lb.setText(f"{v}%"), self._set(k, round(a + (b - a) * v / 100, 4))))
        if tip:
            sl.setToolTip(tip)
        row.addWidget(sl, 1)
        row.addWidget(val)
        f.addRow(label, row)
        self.controls[key] = sl

    def _check(self, f: QFormLayout, key: str, label: str):
        cb = QCheckBox(label)
        cb.toggled.connect(lambda on, k=key: self._set(k, bool(on)))
        f.addRow(cb)
        self.controls[key] = cb

    def _show_design(self):
        """Every control from ``self.d``."""
        self._loading = True
        d = self.d
        for key, w in self.controls.items():
            v = getattr(d, key)
            if isinstance(w, QSlider):
                lo, hi = w.property("range")
                w.setValue(round((float(v) - lo) / (hi - lo) * 100))
            elif isinstance(w, QCheckBox):
                w.setChecked(bool(v))
            elif w.isEditable():
                w.setEditText(v or "")
            else:
                w.setCurrentIndex(max(0, w.findData(v)))
        self.seed.setValue(d.seed)
        self.picture_lbl.setText(Path(d.picture).name if d.picture else "no picture")
        for slot, b in self.colour_btns.items():
            col = ds._hex(ds.palette(d, slot)[0])
            b.setStyleSheet(f"QPushButton {{ background: {col}; color: "
                            f"{'#000' if QColor(col).lightness() > 128 else '#fff'}; }}")
        self._loading = False

    def _set(self, key: str, value):
        if self._loading:
            return
        setattr(self.d, key, value)
        if key == "palette":
            self._show_design()
        self.timer.start()

    def _preset(self, *_):
        name = self.preset.currentData()
        if not name:
            return
        keep = {"title_font": self.d.title_font, "text_font": self.d.text_font,
                "seed": self.d.seed}
        self.d = ds.Design.from_dict({**ds.PRESETS[name], **keep})
        if not self.name.text().strip():
            self.name.setText(name.split(" (")[0])
        self._show_design()
        self.timer.start()

    def _pick_colour(self, slot: str):
        cur = ds._hex(ds.palette(self.d, slot)[0])
        col = QColorDialog.getColor(QColor(cur), self, "The frame's colour")
        if col.isValid():
            self.d.colours[slot] = col.name()
            self._show_design()
            self.timer.start()

    def _reset_colours(self):
        self.d.colours = {}
        self._show_design()
        self.timer.start()

    def _choose_picture(self):
        path, _ = QFileDialog.getOpenFileName(self, "A texture picture", "",
                                              "Pictures (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.d.picture = path
            self.d.material = "picture"
            self._show_design()
            self.timer.start()

    def _choose_example(self):
        path, _ = QFileDialog.getOpenFileName(self, "An example card", "",
                                              "Pictures (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.example = Path(path)
            self.example_btn.setText(f"Example: {self.example.name}")

    # ------------------------------------------------------------ the preview
    def _preview_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("Show the"))
        self.show_slot = QComboBox()
        for k, label in fg.SLOTS:
            self.show_slot.addItem(label, k)
        self.show_slot.currentIndexChanged.connect(lambda *_: self.timer.start())
        row.addWidget(self.show_slot)
        row.addWidget(QLabel("frame"))
        self.sample_cb = QCheckBox("with sample text")
        self.sample_cb.setChecked(True)
        self.sample_cb.toggled.connect(lambda *_: self.timer.start())
        row.addWidget(self.sample_cb)
        row.addStretch(1)
        v.addLayout(row)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(PREVIEW_W, round(PREVIEW_W * 523 / 375))
        v.addWidget(self.preview, 1)
        self.strip = QHBoxLayout()
        self.strip_labels = []
        for k, label in fg.SLOTS:
            lb = QLabel()
            lb.setToolTip(label)
            lb.setFixedSize(62, 86)
            lb.setAlignment(Qt.AlignCenter)
            self.strip.addWidget(lb)
            self.strip_labels.append(lb)
        v.addLayout(self.strip)
        self.mana_row = QHBoxLayout()
        self.mana_labels = []
        for _ in range(7):
            lb = QLabel()
            lb.setFixedSize(40, 40)
            self.mana_row.addWidget(lb)
            self.mana_labels.append(lb)
        self.mana_row.addStretch(1)
        v.addLayout(self.mana_row)
        self.preview_status = QLabel()
        self.preview_status.setObjectName("Hint")
        v.addWidget(self.preview_status)
        return w

    def _render(self):
        self._gen += 1
        gen, d = self._gen, ds.Design.from_dict(self.d.to_dict())
        slot = self.show_slot.currentData() or "w"

        def work(progress=None, cancel=None):
            r = ds.Renderer(d, PREVIEW_W)
            big = r.frame(slot)
            small = ds.Renderer(d, 62)
            strip = [small.frame(k) for k in ds.SLOTS]
            mana = [ds.mana_symbol(d, c, 40) for c in "wubrgcn"] if d.mana != "none" else []
            sample = [ds.mana_symbol(d, c, 64) for c in "nbr"] if d.mana != "none" else []
            return gen, big, strip, mana, r.text_colours(slot), sample

        self.preview_status.setText("Drawing…")
        job = Job(work)
        job.signals.finished.connect(self._rendered)
        job.signals.failed.connect(lambda msg: self.preview_status.setText(
            "Couldn't draw it: " + msg.splitlines()[0] if msg else ""))
        self._jobs = [j for j in self._jobs if not j.cancel.cancelled][-3:]
        self._jobs.append(start(job))

    def _rendered(self, result):
        try:
            gen, big, strip, mana, colours, sample = result
            if gen != self._gen:
                return                                   # an older one
            card = _sample_art(big.width, big.height)
            card.alpha_composite(big)
            pm = QPixmap.fromImage(_qimage(card))
            if self.sample_cb.isChecked():
                self._sample_text(pm, colours, sample)
            self.preview.setPixmap(pm)
            for lb, im in zip(self.strip_labels, strip):
                c = _sample_art(im.width, im.height)
                c.alpha_composite(im)
                lb.setPixmap(QPixmap.fromImage(_qimage(c)))
            for lb, im in zip(self.mana_labels, mana + [None] * 7):
                lb.setPixmap(QPixmap.fromImage(_qimage(im)) if im is not None else QPixmap())
            self.preview_status.setText("")
        except RuntimeError:
            return

    def _sample_text(self, pm: QPixmap, colours: dict, mana: list):
        """A name, mana cost, type line, rules text and P/T where MSE will write them."""
        b = ds.boxes(self.d)
        w, h = pm.width(), pm.height()
        qp = QPainter(pm)
        qp.setRenderHint(QPainter.TextAntialiasing)
        qp.setRenderHint(QPainter.SmoothPixmapTransform)
        x, y, bw, bh = (v * s for v, s in zip(b["cost"], (w, h, w, h)))
        vertical = bh > 1.8 * bw
        side = min(bw, bh) * 0.92
        for k, im in enumerate(mana):                # "{2}{B}{R}": the number on its tile
            px = QPixmap.fromImage(_qimage(im)).scaled(int(side), int(side), Qt.KeepAspectRatio,
                                                      Qt.SmoothTransformation)
            if vertical:
                pos = (int(x + (bw - side) / 2), int(y + k * side * 1.06))
            else:
                pos = (int(x + bw - (len(mana) - k) * side * 1.06), int(y + (bh - side) / 2))
            qp.drawPixmap(pos[0], pos[1], px)
            if k == 0:
                f = QFont(self.d.title_font or "Arial")
                f.setPixelSize(max(6, int(side * 0.6)))
                qp.setFont(f)
                qp.setPen(QColor(ds.number_colour(self.d)))
                qp.drawText(QRectF(pos[0], pos[1], side, side), Qt.AlignCenter, "2")

        def put(key, text, size, flags, family=""):
            x, y, bw, bh = b[key]
            f = QFont(family or ("Beleren Bold" if key in ("name", "type", "pt") else "MPlantin"))
            f.setPixelSize(max(6, int(size / ds.U_H * h)))
            qp.setFont(f)
            qp.setPen(QColor(colours.get(key, "#000000")))
            qp.drawText(QRectF(x * w + 3, y * h, bw * w - 6, bh * h), flags | Qt.TextWordWrap,
                        text)
        put("name", "Card Name", 20, Qt.AlignLeft | Qt.AlignVCenter, self.d.title_font)
        put("type", "Creature — Human Wizard", 16, Qt.AlignLeft | Qt.AlignVCenter,
            self.d.title_font)
        put("text", "Flying\nWhen this creature enters, draw a card.", 17,
            Qt.AlignLeft | Qt.AlignVCenter, self.d.text_font)
        if self.d.pt_box:
            put("pt", "2/3", 20, Qt.AlignCenter, self.d.title_font)
        qp.end()

    # ------------------------------------------------------------ AI
    def _busy(self, on: bool, text: str = ""):
        for b in (self.ai_btn, self.ai_texture_btn, self.make_btn, self.example_btn):
            b.setEnabled(not on)
        if text:
            self.ai_status.setText(text)

    def _ai_design(self):
        ai = ai_module()
        if ai is None:
            return
        why = ai.not_ready(self.main.settings)
        if why:
            error(self, "Frame designer", why)
            return
        want = self.describe.toPlainText().strip()
        if not want and self.example is None:
            error(self, "Frame designer", "Describe the look you want (or choose an example "
                                          "card) first.")
            return
        settings, current = self.main.settings, self.d.to_dict()
        current.pop("picture", None)
        example = self.example.read_bytes() if self.example and self.example.is_file() else None
        system = ("You design trading card frames with MSE Studio's Frame designer: you choose "
                  "its settings so the frame looks like what the user asks for. Every colour of "
                  "Magic gets its own frame in the chosen palette; keep the text readable. "
                  "The settings:\n" + ds.describe_options() +
                  '\n\nAnswer {"settings": {only the settings to change}, "name": "a short '
                  'name for the frame", "note": "one sentence about the look"}.')
        prompt = (f"What I want: {want or 'a frame like the example card'}\n"
                  + ("The picture is an example card in the look I want: match its colours, "
                     "materials, edges, text box and mana symbols.\n" if example else "")
                  + "The settings now: " + json.dumps(current))

        def work(progress=None, cancel=None):
            progress(0, 0, "Asking the AI…")
            return ai.ask_json(settings, system, prompt, images=[example] if example else None)

        self._busy(True, "Asking the AI…")
        job = Job(work, label="Designing the frame with AI")
        job.signals.finished.connect(self._ai_designed)
        job.signals.failed.connect(self._ai_failed)
        self._jobs.append(start(job))

    def _ai_designed(self, data):
        try:
            self._busy(False)
            if not isinstance(data, dict):
                raise ValueError
            settings = data.get("settings") if isinstance(data.get("settings"), dict) else data
            merged = {**self.d.to_dict(), **settings}
            self.d = ds.Design.from_dict(merged)
            if data.get("name") and not self.name.text().strip():
                self.name.setText(str(data["name"])[:60])
            self.ai_status.setText(str(data.get("note") or "Done – change anything you like."))
            self.preset.setCurrentIndex(0)
            self._show_design()
            self.timer.start()
        except (RuntimeError, ValueError):
            self.ai_status.setText("The AI's answer couldn't be used – try again.")

    def _ai_failed(self, msg: str):
        try:
            self._busy(False, "")
            self.ai_status.setText(msg.splitlines()[0] if msg else "The AI didn't answer.")
        except RuntimeError:
            return

    def _ai_texture(self):
        ai = ai_module()
        if ai is None:
            error(self, "Frame designer", "Needs MSE Studio 0.20.0 or newer.")
            return
        why = ai.picture_not_ready(self.main.settings)
        if why:
            error(self, "Frame designer", why)
            return
        want = self.describe.toPlainText().strip() or ds.MATERIALS.get(self.d.material, "")
        prompt = ("A seamless, tileable texture for the frame of a fantasy trading card: "
                  f"{want}. Flat and evenly lit, seen straight on, filling the whole picture. "
                  "No text, no letters, no symbols, no borders, no objects, no card.")
        settings = self.main.settings
        out_dir = _textures_dir()

        def work(progress=None, cancel=None):
            progress(0, 0, "The AI is painting a texture…")
            png = ai.make_picture(settings, prompt, size="1024x1024")
            out = out_dir / (hashlib.sha1(png).hexdigest()[:12] + ".png")
            out.write_bytes(png)
            return str(out)

        self._busy(True, "The AI is painting a texture (this can take a minute)…")
        job = Job(work, label="Making a texture with AI")
        job.signals.finished.connect(self._ai_textured)
        job.signals.failed.connect(self._ai_failed)
        self._jobs.append(start(job))

    def _ai_textured(self, path: str):
        try:
            self._busy(False, "Texture made – it's the material now.")
            self.d.picture = path
            self.d.material = "picture"
            self._show_design()
            self.timer.start()
        except RuntimeError:
            return

    # ------------------------------------------------------------ done
    def _make(self):
        if not self.name.text().strip():
            error(self, "Frame designer", "Give the frame a name.")
            return
        self.accept()

    @property
    def design(self) -> ds.Design:
        return ds.Design.from_dict(self.d.to_dict())


def _textures_dir() -> Path:
    from mse_studio.core import addons
    d = Path(addons.data_dir(fg.ADDON_ID)) / "textures"
    d.mkdir(parents=True, exist_ok=True)
    return d
