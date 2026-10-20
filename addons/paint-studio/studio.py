"""The studio: a window to paint in. The canvas in the middle; tools along
the top with their options underneath; brush size, opacity, undo and redo
on the left; brushes, colours and layers on the right."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QSlider, QSpinBox,
                               QStackedWidget, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from . import adjust
from . import brushes as bl
from . import files
from . import tools as tl
from .brushes import Brush
from .colours import ColourPanel
from .doc import Document, Layer
from .engine import Symmetry
from .panels import BrushPanel, BrushStudio, LayersPanel
from .view import SELECT_SHAPES, SHAPES, TOOLS, CanvasView, Options

AUTOSAVE_MS = 90_000
TOOL_ICONS = {"brush": "brush", "smudge": "water_drop", "erase": "ink_eraser",
              "fill": "format_color_fill", "gradient": "style", "picker": "colorize",
              "select": "select", "move": "open_with", "liquify": "gesture",
              "shape": "rectangle"}
TOOL_KEYS = {"brush": "B", "smudge": "S", "erase": "E", "fill": "G", "gradient": "D",
             "picker": "I", "select": "M", "move": "V", "liquify": "L", "shape": "U"}
TOOL_TIPS = {
    "brush": "Paint with the chosen brush",
    "smudge": "Push and blend the paint that's there (any brush's shape)",
    "erase": "Rub out (any brush's shape)",
    "fill": "Fill an area of one colour",
    "gradient": "Drag from one colour to the second colour",
    "picker": "Take a colour from the painting (or hold Alt while painting)",
    "select": "Choose a part: painting and changes then stay inside it",
    "move": "Move, resize, turn or flip the layer (or the selected part)",
    "liquify": "Push, twirl, pinch or swell the paint like soft clay",
    "shape": "Rectangles, ellipses and lines – filled or drawn with the brush",
}
DEFAULT_BRUSH = {"brush": "Round brush", "smudge": "Soft smudge", "erase": "Soft eraser"}
SYMMETRY = [("", "No mirror"), ("vertical", "Mirror left – right"),
            ("horizontal", "Mirror top – bottom"), ("quadrant", "Mirror four ways"),
            ("radial:6", "Kaleidoscope (6)"), ("radial:8", "Kaleidoscope (8)"),
            ("radial:12", "Kaleidoscope (12)")]


def _icon(button, name: str) -> None:
    try:
        from mse_studio.gui import icons
        icons.set_icon(button, name)
    except Exception:  # noqa: BLE001
        pass


def _error(parent, title: str, text: str) -> None:
    try:
        from mse_studio.gui.common import error
        error(parent, title, text)
    except ImportError:
        QMessageBox.warning(parent, title, text)


class SizeDialog(QDialog):
    """A new size for the painting."""

    def __init__(self, parent, w: int, h: int):
        super().__init__(parent)
        self.setWindowTitle("Canvas size")
        f = QFormLayout(self)
        self.w, self.h = QSpinBox(), QSpinBox()
        for s, v in ((self.w, w), (self.h, h)):
            s.setRange(16, 12000)
            s.setValue(v)
            s.setSuffix(" px")
        f.addRow("Width", self.w)
        f.addRow("Height", self.h)
        self.scale = QCheckBox("Stretch the painting to the new size")
        self.scale.setToolTip("Untick to keep the painting as it is and add or cut away "
                              "canvas round its middle")
        self.scale.setChecked(True)
        f.addRow(self.scale)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)


class ReferenceWindow(QWidget):
    """A picture to look at while painting, in a small window of its own."""

    def __init__(self, parent, image: QImage, title: str):
        super().__init__(parent, Qt.Tool)
        self.setWindowTitle(f"Reference · {title}")
        self.image = image
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.label)
        w = min(420, image.width())
        self.resize(w, max(120, int(w * image.height() / max(1, image.width()))))

    def resizeEvent(self, e):
        self.label.setPixmap(QPixmap.fromImage(self.image.scaled(
            self.label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        super().resizeEvent(e)


class StudioWindow(QMainWindow):
    """Paint one painting. ``on_use(png)`` (optional) is the "Use as the
    card's art" button; ``overlay`` is (frame picture, art box) to show on top."""
    saved = Signal(str)                 # the painting's file, after each save

    def __init__(self, parent, doc: Document, path: Path, data_dir: Optional[Path],
                 title: str = "Painting", on_use: Optional[Callable[[Path], None]] = None,
                 use_label: str = "Use as the card's art"):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle(f"Paint studio · {title}")
        self.doc, self.path, self.data_dir = doc, Path(path), data_dir
        self.title = title
        self.on_use = on_use
        self.opts = Options()
        self.selection = tl.Selection(doc.width, doc.height)
        self.tool_brush: dict[str, Brush] = {}
        self.tool_size: dict[str, float] = {}
        self.tool_opacity: dict[str, float] = {}
        self._jobs: list = []
        self._clipboard: Optional[QImage] = None
        self._reference: Optional[ReferenceWindow] = None
        self._closing = False
        self._last_save = time.monotonic()

        self.view = CanvasView(self)
        self.brushes = BrushPanel(data_dir)
        self.colours = ColourPanel(data_dir, image_source=self.view.picture)
        self.layers = LayersPanel()
        for tool, name in DEFAULT_BRUSH.items():
            b = self.brushes.find(name) or bl.LIBRARY[0]
            self.tool_brush[tool] = b
            self.tool_size[tool] = b.size
            self.tool_opacity[tool] = b.opacity

        self._build()
        self.view.set_document(doc, self.selection)
        self.layers.set_document(doc)
        self._autosave = QTimer(self)
        self._autosave.setInterval(AUTOSAVE_MS)
        self._autosave.timeout.connect(self._autosave_now)
        self._autosave.start()
        self.set_tool("brush")
        self._update_title()
        self.resize(1400, 900)

    # ------------------------------------------------------------ building it
    def _build(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(4)
        # the top bar: menus on the left, tools on the right
        top = QHBoxLayout()
        self.gallery_btn = QPushButton("Done")
        self.gallery_btn.setToolTip("Save and close the painting")
        top.addWidget(self.gallery_btn)
        self.actions_btn = QPushButton("Actions")
        self.actions_btn.setToolTip("Add pictures, the canvas, sharing and saving")
        self.adjust_btn = QPushButton("Adjustments")
        self.adjust_btn.setToolTip("Colour, blur, sharpen, glow… on the layer (or the "
                                   "selected part)")
        self.select_btn = QPushButton("Selection")
        self.select_btn.setToolTip("Select all or nothing, turn it inside out, soften it…")
        for b in (self.actions_btn, self.adjust_btn, self.select_btn):
            top.addWidget(b)
        self.use_btn = QPushButton("Use as the card's art")
        self.use_btn.setProperty("kind", "primary")
        self.use_btn.setToolTip("Save the painting and put it on the card")
        self.use_btn.setVisible(self.on_use is not None)
        top.addWidget(self.use_btn)
        top.addStretch(1)
        self.tool_name = QLabel()
        self.tool_name.setObjectName("PageTitle")
        top.addWidget(self.tool_name)
        self.swatch = QToolButton()
        self.swatch.setToolTip("The colour (X swaps it with the second colour)")
        self.swatch.setFixedSize(36, 36)
        top.addWidget(self.swatch)
        outer.addLayout(top)
        # each tool's options
        self.options = QStackedWidget()
        self.options.setMaximumHeight(44)
        self._option_pages: dict[str, int] = {}
        for key in TOOLS:
            self._option_pages[key] = self.options.addWidget(self._options_for(key))
        outer.addWidget(self.options)
        # the middle: the tools, size and opacity, the canvas, the panels
        mid = QHBoxLayout()
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        grid.setSpacing(2)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_buttons: dict[str, QToolButton] = {}
        for i, (key, label) in enumerate(TOOLS.items()):
            b = QToolButton()
            b.setCheckable(True)
            b.setToolTip(f"{label} ({TOOL_KEYS[key]}) – {TOOL_TIPS[key]}")
            b.setAccessibleName(label)
            _icon(b, TOOL_ICONS[key])
            b.setIconSize(QSize(24, 24))
            b.setFixedSize(40, 40)
            b.setAutoRaise(True)
            b.setStyleSheet("QToolButton:checked { background: palette(highlight); "
                            "border-radius: 8px; }")
            self.tool_group.addButton(b)
            self.tool_buttons[key] = b
            grid.addWidget(b, i // 2, i % 2)
            b.clicked.connect(self._tool_clicked)
        left.addLayout(grid)
        left.addSpacing(8)
        sliders = QGridLayout()
        sliders.setSpacing(2)
        sliders.addWidget(QLabel("Size"), 0, 0, Qt.AlignHCenter)
        sliders.addWidget(QLabel("Opac."), 0, 1, Qt.AlignHCenter)
        self.size_slider = QSlider(Qt.Vertical)
        self.size_slider.setRange(1, 1000)
        self.size_slider.setToolTip("Brush size ([ and ] change it, or Ctrl + wheel)")
        self.opacity_slider = QSlider(Qt.Vertical)
        self.opacity_slider.setRange(1, 100)
        self.opacity_slider.setToolTip("Opacity: how much one stroke covers (keys 1–9)")
        sliders.addWidget(self.size_slider, 1, 0, Qt.AlignHCenter)
        sliders.addWidget(self.opacity_slider, 1, 1, Qt.AlignHCenter)
        sliders.setRowStretch(1, 1)
        self.size_label = QLabel()
        self.size_label.setAlignment(Qt.AlignCenter)
        self.opacity_label = QLabel()
        self.opacity_label.setAlignment(Qt.AlignCenter)
        sliders.addWidget(self.size_label, 2, 0)
        sliders.addWidget(self.opacity_label, 2, 1)
        left.addLayout(sliders, 1)
        left.addSpacing(8)
        self.undo_btn = QToolButton()
        self.undo_btn.setToolTip("Undo (Ctrl+Z, or tap with two fingers)")
        _icon(self.undo_btn, "undo")
        self.redo_btn = QToolButton()
        self.redo_btn.setToolTip("Redo (Ctrl+Shift+Z, or tap with three fingers)")
        _icon(self.redo_btn, "redo")
        row = QHBoxLayout()
        for btn in (self.undo_btn, self.redo_btn):
            btn.setIconSize(QSize(24, 24))
            btn.setFixedSize(40, 40)
            row.addWidget(btn)
        left.addLayout(row)
        holder = QWidget()
        holder.setLayout(left)
        holder.setFixedWidth(88)
        mid.addWidget(holder)
        mid.addWidget(self.view, 1)
        self.panels = QTabWidget()
        self.panels.addTab(self.brushes, "Brushes")
        self.panels.addTab(self.colours, "Colour")
        self.panels.addTab(self.layers, "Layers")
        self.panels.setMinimumWidth(330)
        self.panels.setMaximumWidth(460)
        mid.addWidget(self.panels)
        outer.addLayout(mid, 1)
        self.setCentralWidget(central)
        self.status = QLabel()
        self.status.setObjectName("Hint")
        self.zoom_label = QLabel()
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().addPermanentWidget(self.zoom_label)

        # menus
        self.actions_menu = QMenu(self)
        self.adjust_menu = QMenu(self)
        self.select_menu = QMenu(self)
        self._fill_menus()
        self.actions_btn.setMenu(self.actions_menu)
        self.adjust_btn.setMenu(self.adjust_menu)
        self.select_btn.setMenu(self.select_menu)
        self._shortcuts()

        # wiring
        self.gallery_btn.clicked.connect(self.close)
        self.use_btn.clicked.connect(self.use_on_card)
        self.size_slider.valueChanged.connect(self._size_changed)
        self.opacity_slider.valueChanged.connect(self._opacity_changed)
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)
        self.swatch.clicked.connect(lambda: self.panels.setCurrentWidget(self.colours))
        self.view.changed.connect(self._painted)
        self.view.picked.connect(self._picked)
        self.view.message.connect(self.say)
        self.view.view_changed.connect(self._view_changed)
        self.view.undo_requested.connect(self.undo)
        self.view.redo_requested.connect(self.redo)
        self.brushes.chosen.connect(self._brush_chosen)
        self.brushes.edit_requested.connect(self.edit_brush)
        self.colours.changed.connect(self._colour_changed)
        self.layers.changed.connect(self._layers_changed)
        self.layers.message.connect(self.say)
        self.brushes.set_ink(self.palette().color(self.foregroundRole()))
        self._colour_changed()

    def _options_for(self, tool: str) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(4, 0, 4, 0)
        o = self.opts
        if tool in ("brush", "smudge", "erase"):
            name = QPushButton()
            name.setToolTip("The brush this tool uses – choose another in Brushes")
            name.clicked.connect(lambda: self.panels.setCurrentWidget(self.brushes))
            setattr(self, f"_{tool}_name", name)
            row.addWidget(name)
            edit = QPushButton("Edit brush…")
            edit.clicked.connect(lambda: self.edit_brush(self.tool_brush[self.opts.tool]))
            row.addWidget(edit)
            sym = QComboBox()
            for k, label in SYMMETRY:
                sym.addItem(label, k)
            sym.setToolTip("Paint in mirror: everything you paint is copied across")
            sym.currentIndexChanged.connect(self._symmetry_changed)
            row.addWidget(sym)
            setattr(self, f"_{tool}_sym", sym)
            if tool == "brush":
                qs = QCheckBox("Hold to straighten")
                qs.setChecked(o.quickshape)
                qs.setToolTip("Finish a line and keep the pen still for a moment: it becomes "
                              "a straight line, or a neat ellipse when it closes")
                qs.toggled.connect(lambda v: setattr(self.opts, "quickshape", v))
                row.addWidget(qs)
            sp = QCheckBox("Mouse: thinner when fast")
            sp.setToolTip("Without a pen, faster strokes are drawn thinner – like pressure")
            sp.setChecked(o.speed_pressure)
            sp.toggled.connect(lambda v: setattr(self.opts, "speed_pressure", v))
            setattr(self, f"_{tool}_speed", sp)
            row.addWidget(sp)
        elif tool in ("fill", "select"):
            if tool == "select":
                shapes = QComboBox()
                for k, label in SELECT_SHAPES.items():
                    shapes.addItem(label, k)
                shapes.currentIndexChanged.connect(
                    lambda _i, c=shapes: setattr(self.opts, "select_shape", c.currentData()))
                row.addWidget(shapes)
                self._select_shapes = shapes
                mode = QComboBox()
                for k, label in (("replace", "New selection"), ("add", "Add (Shift)"),
                                 ("subtract", "Take away (Alt)"),
                                 ("intersect", "Only where both")):
                    mode.addItem(label, k)
                mode.currentIndexChanged.connect(
                    lambda _i, c=mode: setattr(self.opts, "select_mode", c.currentData()))
                row.addWidget(mode)
                for label, fn in (("All", self.select_all), ("None", self.select_none),
                                  ("Inside out", self.select_invert)):
                    b = QPushButton(label)
                    b.clicked.connect(fn)
                    row.addWidget(b)
            row.addWidget(QLabel("Colour tolerance"))
            tol = QSlider(Qt.Horizontal)
            tol.setRange(0, 160)
            tol.setValue(o.fill_tolerance)
            tol.setMaximumWidth(160)
            tol.setToolTip("How different a colour may be and still count as the same")
            tol.valueChanged.connect(lambda v: setattr(self.opts, "fill_tolerance", v))
            row.addWidget(tol)
            cont = QCheckBox("Only touching areas")
            cont.setChecked(o.fill_contiguous)
            cont.setToolTip("Untick to take that colour everywhere in the painting")
            cont.toggled.connect(lambda v: setattr(self.opts, "fill_contiguous", v))
            row.addWidget(cont)
            if tool == "fill":
                allx = QCheckBox("Look at every layer")
                allx.setChecked(o.fill_all_layers)
                allx.setToolTip("Fill up to lines on other layers (colour under your "
                                "line art on a layer of its own)")
                allx.toggled.connect(lambda v: setattr(self.opts, "fill_all_layers", v))
                row.addWidget(allx)
        elif tool == "gradient":
            kind = QComboBox()
            kind.addItem("Straight", False)
            kind.addItem("Round (from the middle)", True)
            kind.currentIndexChanged.connect(
                lambda _i, c=kind: setattr(self.opts, "gradient_radial", c.currentData()))
            row.addWidget(kind)
            row.addWidget(QLabel("From the colour to the second colour – drag across the "
                                 "painting."))
        elif tool == "picker":
            row.addWidget(QLabel("Click or drag on the painting. While painting, hold Alt "
                                 "and click to pick a colour."))
        elif tool == "move":
            for label, fn in (("Flip ↔", lambda: self.view.transform_flip(True)),
                              ("Flip ↕", lambda: self.view.transform_flip(False)),
                              ("Turn left", lambda: self.view.transform_rotate(-90)),
                              ("Turn right", lambda: self.view.transform_rotate(90)),
                              ("Fill the painting", self.view_fit_content)):
                b = QPushButton(label)
                b.clicked.connect(fn)
                row.addWidget(b)
            ok = QPushButton("Put it down")
            ok.setToolTip("Keep it here (Enter)")
            ok.clicked.connect(self._transform_done)
            back = QPushButton("Put it back")
            back.setToolTip("Undo the move (Esc)")
            back.clicked.connect(self._transform_cancel)
            row.addWidget(ok)
            row.addWidget(back)
        elif tool == "liquify":
            mode = QComboBox()
            from .tools import LIQUIFY
            for k, label in LIQUIFY.items():
                mode.addItem(label, k)
            mode.currentIndexChanged.connect(
                lambda _i, c=mode: setattr(self.opts, "liquify_mode", c.currentData()))
            row.addWidget(mode)
            row.addWidget(QLabel("Size"))
            size = QSlider(Qt.Horizontal)
            size.setRange(10, 800)
            size.setValue(int(o.liquify_size))
            size.setMaximumWidth(180)
            size.valueChanged.connect(self._liquify_size)
            row.addWidget(size)
            row.addWidget(QLabel("Strength"))
            st = QSlider(Qt.Horizontal)
            st.setRange(5, 100)
            st.setValue(int(o.liquify_strength * 100))
            st.setMaximumWidth(140)
            st.valueChanged.connect(lambda v: setattr(self.opts, "liquify_strength", v / 100))
            row.addWidget(st)
        elif tool == "shape":
            kind = QComboBox()
            for k, label in SHAPES.items():
                kind.addItem(label, k)
            kind.currentIndexChanged.connect(
                lambda _i, c=kind: setattr(self.opts, "shape", c.currentData()))
            row.addWidget(kind)
            fill = QComboBox()
            fill.addItem("Filled with the colour", True)
            fill.addItem("Drawn with the brush", False)
            fill.currentIndexChanged.connect(
                lambda _i, c=fill: setattr(self.opts, "shape_fill", c.currentData()))
            row.addWidget(fill)
            row.addWidget(QLabel("Shift: a square, a circle, or a line at 45°."))
        row.addStretch(1)
        return w

    def _fill_menus(self) -> None:
        m = self.actions_menu
        add = m.addMenu("Add")
        add.addAction("A picture as a new layer…", self.import_picture)
        add.addAction("Layers from a Photoshop file (.psd)…", self.import_psd)
        add.addAction("Paste (Ctrl+V)", self.paste)
        add.addAction("Copy (Ctrl+C)", self.copy)
        add.addAction("Copy everything you see", lambda: self.copy(merged=True))
        canvas = m.addMenu("Canvas")
        canvas.addAction("Canvas size…", self.canvas_size)
        canvas.addAction("Crop to the selection", self.crop_to_selection)
        canvas.addAction("Flip the canvas ↔", lambda: self._flip_canvas(True))
        canvas.addAction("Flip the canvas ↕", lambda: self._flip_canvas(False))
        canvas.addSeparator()
        self.frame_act = canvas.addAction("Show the card's frame on top")
        self.frame_act.setCheckable(True)
        self.frame_act.setChecked(self.opts.show_frame)
        self.frame_act.toggled.connect(self._frame_toggled)
        self.frame_see = canvas.addAction("See through the frame")
        self.frame_see.setCheckable(True)
        self.frame_see.toggled.connect(self._frame_see)
        self.grid_act = canvas.addAction("Thirds grid (for the layout)")
        self.grid_act.setCheckable(True)
        self.grid_act.toggled.connect(self._grid_toggled)
        canvas.addAction("A reference picture beside it…", self.reference)
        view = m.addMenu("View")
        view.addAction("Fit to the window (Ctrl+0)", self.view.fit)
        view.addAction("Actual size (Ctrl+1)", self.view.actual_size)
        view.addAction("Turn back upright (R)", self.view.reset_rotation)
        view.addAction("Mirror the view (H) – check the drawing", self.view.flip_view)
        view.addAction("Hide the panels (Tab)", self.toggle_panels)
        share = m.addMenu("Save and share")
        share.addAction("Save (Ctrl+S)", self.save)
        share.addAction("Export as PNG…", lambda: self.export("png"))
        share.addAction("Export as JPG…", lambda: self.export("jpg"))
        share.addAction("Export every layer as a PNG…", lambda: self.export("layers"))
        share.addAction("Save a copy (.ora, opens in Krita and GIMP)…", lambda: self.export("ora"))
        m.addSeparator()
        m.addAction("Keyboard and touch help", self.help)

        a = self.adjust_menu
        for key, adj in adjust.ADJUSTMENTS.items():
            act = a.addAction(adj.label + "…", lambda k=key: self.adjustment(k))
            act.setToolTip(adj.tip)
        a.setToolTipsVisible(True)

        s = self.select_menu
        s.addAction("Select all (Ctrl+A)", self.select_all)
        s.addAction("Select nothing (Ctrl+D)", self.select_none)
        s.addAction("Inside out (Ctrl+Shift+I)", self.select_invert)
        s.addAction("The layer's paint", self.select_layer)
        s.addSeparator()
        s.addAction("Soften the edge…", self.select_feather)
        s.addAction("Bigger or smaller…", self.select_grow)
        s.addSeparator()
        s.addAction("Fill it with the colour", self.fill_selection)
        s.addAction("Clear it (Delete)", self.clear_selection)
        s.addAction("Copy to a new layer (Ctrl+J)", self.selection_to_layer)

        self.layers.extra_actions = []
        for label, fn in (("Select its paint", self.select_layer),
                          ("A picture as a new layer…", self.import_picture),
                          ("Fill the layer with the colour", self.fill_layer)):
            act = QAction(label, self)
            act.triggered.connect(fn)
            self.layers.extra_actions.append(act)

    def _shortcuts(self) -> None:
        def key(seq, fn):
            act = QAction(self)
            act.setShortcut(QKeySequence(seq))
            act.setShortcutContext(Qt.WindowShortcut)
            act.triggered.connect(fn)
            self.addAction(act)
            return act
        for tool, k in TOOL_KEYS.items():
            key(k, lambda t=tool: self.set_tool(t))
        key("Ctrl+Z", self.undo)
        key("Ctrl+Shift+Z", self.redo)
        key("Ctrl+Y", self.redo)
        key("Ctrl+S", self.save)
        key("Ctrl+0", self.view.fit)
        key("Ctrl+1", self.view.actual_size)
        key("Ctrl+=", lambda: self.view.zoom_by(1.25))
        key("Ctrl++", lambda: self.view.zoom_by(1.25))
        key("Ctrl+-", lambda: self.view.zoom_by(0.8))
        key("R", self.view.reset_rotation)
        key("H", self.view.flip_view)
        key("[", lambda: self.change_size(1 / 1.15))
        key("]", lambda: self.change_size(1.15))
        key("X", self.colours.swap)
        key("Ctrl+A", self.select_all)
        key("Ctrl+D", self.select_none)
        key("Ctrl+Shift+I", self.select_invert)
        key("Ctrl+J", self.selection_to_layer)
        key("Ctrl+Shift+N", self.layers.add)
        key("Ctrl+E", self.layers.merge_down)
        key("Ctrl+C", self.copy)
        key("Ctrl+V", self.paste)
        key("Delete", self.clear_selection)
        key("Tab", self.toggle_panels)
        for n in range(1, 10):
            key(str(n), lambda v=n: self.set_opacity(v / 10))

    # ------------------------------------------------------------ tools
    def _tool_clicked(self) -> None:
        for k, b in self.tool_buttons.items():
            if b.isChecked():
                self.set_tool(k)
                return

    def set_tool(self, tool: str) -> None:
        if self.view.transform_active() and tool != "move":
            self.view.apply_transform()
        self.opts.tool = tool
        b = self.tool_buttons[tool]
        if not b.isChecked():
            b.setChecked(True)
        self.options.setCurrentIndex(self._option_pages[tool])
        self.tool_name.setText(TOOLS[tool])
        if tool in ("brush", "smudge", "erase"):
            self.brushes.select(self.tool_brush[tool])
            getattr(self, f"_{tool}_name").setText(f"Brush: {self.tool_brush[tool].name}")
        self._sliders_from_tool()
        self.view.tool_changed()
        if tool == "move":
            self.view.begin_transform()
        hints = {"brush": "Hold Alt and click to pick a colour. Space and drag moves the "
                          "canvas; the wheel zooms, Shift + wheel turns it.",
                 "liquify": "Hold the button down to twirl, pinch or swell.",
                 "select": "Shift adds to the selection, Alt takes away. Ctrl+D selects "
                           "nothing."}
        self.say(hints.get(tool, TOOL_TIPS[tool] + "."))

    def brush_now(self, tool: str) -> tuple[Brush, float, float]:
        """The brush a tool paints with now, its size and opacity."""
        t = tool if tool in self.tool_brush else "brush"
        b = self.tool_brush[t]
        if t == "smudge" and b.mode in ("paint", "erase"):
            b = b.copy(mode="smudge", wet=max(0.6, b.wet), blend="normal")
        elif t == "erase" and b.mode in ("paint", "smudge", "blur"):
            b = b.copy(mode="erase", blend="normal", wet=0.0)
        return b, self.tool_size[t], self.tool_opacity[t]

    def _brush_chosen(self, brush: Brush) -> None:
        t = self.opts.tool if self.opts.tool in self.tool_brush else "brush"
        if t != self.opts.tool:
            self.set_tool(t)
        self.tool_brush[t] = brush
        self.tool_size[t] = brush.size
        self.tool_opacity[t] = brush.opacity
        getattr(self, f"_{t}_name").setText(f"Brush: {brush.name}")
        self._sliders_from_tool()

    def _sliders_from_tool(self) -> None:
        t = self.opts.tool
        if t == "liquify":
            size, opacity, on = self.opts.liquify_size, self.opts.liquify_strength, True
        elif t in self.tool_size:
            size, opacity, on = self.tool_size[t], self.tool_opacity[t], True
        else:
            size, opacity, on = self.tool_size["brush"], self.tool_opacity["brush"], False
        for s in (self.size_slider, self.opacity_slider):
            s.blockSignals(True)
        self.size_slider.setValue(self._size_to_slider(size))
        self.opacity_slider.setValue(round(opacity * 100))
        for s in (self.size_slider, self.opacity_slider):
            s.blockSignals(False)
            s.setEnabled(on)
        self.size_label.setText(f"{size:.0f}" if size >= 10 else f"{size:.1f}")
        self.opacity_label.setText(f"{round(opacity * 100)}%")

    # the size slider goes up in bigger steps for big brushes
    @staticmethod
    def _size_to_slider(size: float) -> int:
        import math
        return int(round(math.log(max(1.0, size)) / math.log(1000) * 1000))

    @staticmethod
    def _slider_to_size(v: int) -> float:
        return max(1.0, 1000 ** (v / 1000))

    def _size_changed(self, v: int) -> None:
        t = self.opts.tool
        size = self._slider_to_size(v)
        if t == "liquify":
            self.opts.liquify_size = size
        elif t in self.tool_size:
            self.tool_size[t] = size
        self.size_label.setText(f"{size:.0f}" if size >= 10 else f"{size:.1f}")
        self.view.update()

    def _opacity_changed(self, v: int) -> None:
        t = self.opts.tool
        if t == "liquify":
            self.opts.liquify_strength = v / 100
        elif t in self.tool_opacity:
            self.tool_opacity[t] = v / 100
        self.opacity_label.setText(f"{v}%")

    def change_size(self, factor: float) -> None:
        t = self.opts.tool if self.opts.tool in self.tool_size else "brush"
        self.tool_size[t] = max(1.0, min(1000.0, self.tool_size[t] * factor))
        self._sliders_from_tool()
        self.view.update()

    def set_opacity(self, v: float) -> None:
        t = self.opts.tool if self.opts.tool in self.tool_opacity else "brush"
        self.tool_opacity[t] = v
        self._sliders_from_tool()

    def _liquify_size(self, v: int) -> None:
        self.opts.liquify_size = float(v)
        self._sliders_from_tool()

    def _symmetry_changed(self, _i: int) -> None:
        combo = self.sender()
        k = combo.currentData() if combo is not None else ""
        kind, _, n = (k or "").partition(":")
        self.opts.symmetry = Symmetry(kind, int(n or 6))
        for t in ("brush", "smudge", "erase"):
            c = getattr(self, f"_{t}_sym", None)
            if c is not None and c is not combo:
                c.blockSignals(True)
                c.setCurrentIndex(max(0, c.findData(k)))
                c.blockSignals(False)
        self.view.update()

    def edit_brush(self, brush: Brush) -> None:
        dlg = BrushStudio(self, brush, self.colour())
        if dlg.exec() != QDialog.Accepted:
            return
        new = dlg.result_brush()
        kept = self.brushes.save_brush(new, None if dlg.as_new else brush)
        self._brush_chosen(kept)
        self.say(f"Saved “{kept.name}” in My brushes.")

    # ------------------------------------------------------------ colours
    def colour(self) -> QColor:
        return self.colours.colour()

    def secondary(self) -> QColor:
        return self.colours.secondary()

    def _colour_changed(self, *_):
        c = self.colours.colour()
        self.swatch.setStyleSheet(f"background: {c.name()}; border-radius: 18px; "
                                  f"border: 2px solid palette(mid);")

    def _picked(self, c: QColor) -> None:
        self.colours.set_colour(c, emit=False)
        self.colours.add_recent(c)
        self._colour_changed()

    # ------------------------------------------------------------ changes
    def _painted(self) -> None:
        if self.opts.tool in ("brush", "fill", "gradient", "shape"):
            self.colours.add_recent(self.colour())
        self.layers.refresh_thumbs(self.doc.active)
        self._update_title()

    def _layers_changed(self) -> None:
        self.view.refresh_all()
        self._update_title()

    def _update_title(self) -> None:
        star = " •" if self.doc.dirty else ""
        self.setWindowTitle(f"Paint studio · {self.title}{star}")
        self.undo_btn.setEnabled(self.doc.can_undo())
        self.redo_btn.setEnabled(self.doc.can_redo())

    def _view_changed(self) -> None:
        v = self.view
        turn = f" · turned {v.rotation:.0f}°" if abs(v.rotation) > 0.5 else ""
        mirror = " · mirrored" if v.mirrored else ""
        self.zoom_label.setText(f"{v.zoom * 100:.0f}%{turn}{mirror} · "
                                f"{self.doc.width} × {self.doc.height}")

    def say(self, text: str) -> None:
        self.status.setText(text)

    def undo(self) -> None:
        if self.view.transform_active():
            self.view.cancel_transform()
            return
        label = self.doc.undo()
        self._after_history(f"Undone: {label}" if label else "Nothing to undo.")

    def redo(self) -> None:
        label = self.doc.redo()
        self._after_history(f"Done again: {label}" if label else "Nothing to redo.")

    def _after_history(self, text: str) -> None:
        if self.selection.width != self.doc.width or self.selection.height != self.doc.height:
            self.selection = tl.Selection(self.doc.width, self.doc.height)
            self.view.selection = self.selection
        self.view.refresh_all()
        self.layers.rebuild()
        self._update_title()
        self.say(text)

    def _flip_canvas(self, horizontal: bool) -> None:
        self.doc.flip_canvas(horizontal)
        self._after_history("Flipped the canvas.")

    def _frame_toggled(self, on: bool) -> None:
        self.opts.show_frame = on
        self.view.update()

    def _frame_see(self, on: bool) -> None:
        self.opts.frame_opacity = 0.45 if on else 1.0
        self.view.update()

    def _grid_toggled(self, on: bool) -> None:
        self.opts.grid = on
        self.view.update()

    def set_overlay(self, image: Optional[QImage], box: QRectF) -> None:
        self.view.set_overlay(image, box)
        self.frame_act.setEnabled(image is not None)
        self.frame_see.setEnabled(image is not None)

    def toggle_panels(self) -> None:
        on = not self.panels.isVisible()
        self.panels.setVisible(on)
        self.options.setVisible(on)

    def view_fit_content(self) -> None:
        self.view.transform_fit()

    def _transform_done(self) -> None:
        self.view.apply_transform()
        self.layers.refresh_thumbs()
        self._update_title()

    def _transform_cancel(self) -> None:
        self.view.cancel_transform()

    # ------------------------------------------------------------ selections
    def select_all(self) -> None:
        self.selection.select_all()
        self.view.update()

    def select_none(self) -> None:
        self.selection.clear()
        self.view.update()

    def select_invert(self) -> None:
        self.selection.invert()
        self.view.update()

    def select_layer(self) -> None:
        self.selection.from_alpha(self.doc.layer.image)
        self.view.update()
        if not self.selection.active():
            self.say("This layer has no paint to select.")

    def select_feather(self) -> None:
        if not self.selection.active():
            self.say("Select something first.")
            return
        v, ok = QInputDialog.getInt(self, "Soften the edge", "How soft (pixels)", 12, 1, 400)
        if ok:
            self.selection.feather(v)
            self.view.update()

    def select_grow(self) -> None:
        if not self.selection.active():
            self.say("Select something first.")
            return
        v, ok = QInputDialog.getInt(self, "Bigger or smaller",
                                    "Pixels (below 0 makes it smaller)", 8, -400, 400)
        if ok and v:
            self.selection.grow(v)
            self.view.update()

    def fill_selection(self) -> None:
        if not self._can_change():
            return
        import numpy as np
        mask = np.full((self.doc.height, self.doc.width), 255, np.uint8)
        r = tl.fill_mask(self.doc, mask, self.colour(), self.selection, "Fill")
        if not r.isEmpty():
            self._after_change()

    def fill_layer(self) -> None:
        if not self._can_change():
            return
        import numpy as np
        mask = np.full((self.doc.height, self.doc.width), 255, np.uint8)
        tl.fill_mask(self.doc, mask, self.colour(), None, "Fill layer")
        self._after_change()

    def clear_selection(self) -> None:
        if self.view.transform_active():
            return
        if not self._can_change():
            return
        if not self.selection.active():
            self.say("Nothing selected: clear the whole layer from Layers → More.")
            return
        tl.clear_selection_area(self.doc, self.selection)
        self._after_change()

    def selection_to_layer(self) -> None:
        if not self.selection.active():
            self.layers.duplicate()
            self._layers_changed()
            return
        img = tl.selection_copy(self.doc, self.selection)
        lay = self.doc.add_layer(f"{self.doc.layer.name} (part)", img, fit=False)
        self.selection.clear()
        self.layers.rebuild()
        self._layers_changed()
        self.say(f"Copied to the new layer “{lay.name}”.")

    def _can_change(self) -> bool:
        if self.doc.layer.locked:
            self.say("This layer is locked – unlock it in Layers to change it.")
            return False
        return True

    def _after_change(self) -> None:
        self.view.refresh_all()
        self.layers.refresh_thumbs(self.doc.active)
        self._update_title()

    # ------------------------------------------------------------ adjustments
    def adjustment(self, key: str) -> None:
        if not self._can_change():
            return
        if self.view.transform_active():
            self.view.apply_transform()
        lay = self.doc.layer
        before = lay.image
        mask = self.selection.mask if self.selection.active() else None
        idx = self.doc.active

        def preview(img: QImage) -> None:
            try:
                self.view._refresh(self.doc.rect(), {idx: img})
            except RuntimeError:
                return
        dlg = adjust.AdjustDialog(self, key, before, mask, preview)
        ok = dlg.exec() == QDialog.Accepted and dlg.result_image is not None
        if ok:
            self.doc.push_region(idx, self.doc.rect(), before.copy(),
                                 adjust.ADJUSTMENTS[key].label)
            lay.image = dlg.result_image.convertToFormat(before.format())
            self.doc.dirty = True
        self._after_change()

    # ------------------------------------------------------------ pictures in and out
    def import_picture(self, path: str = "") -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Add a picture", "", "Pictures (*.png *.jpg *.jpeg *.webp *.bmp *.gif "
                "*.tif *.tiff *.ora *.psd)")
        if not path:
            return
        try:
            img = files.import_image(Path(path))
        except (OSError, ValueError) as e:
            _error(self, "Add a picture", f"That picture can't be opened ({e}).")
            return
        self.doc.add_layer(Path(path).stem, img, fit=True)
        self.layers.rebuild()
        self._layers_changed()
        self.set_tool("move")
        self.say("The picture is on a new layer: move and resize it, then press Enter.")

    def import_psd(self, path: str = "") -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Layers from a Photoshop file", "",
                                                  "Photoshop (*.psd *.psb)")
        if not path:
            return
        try:
            got = files.import_psd_layers(Path(path))
        except (OSError, ValueError) as e:
            _error(self, "Photoshop file", f"That file can't be read ({e}).")
            return
        if not got:
            _error(self, "Photoshop file", "No layers could be read from that file – "
                   "it's added as one picture instead.")
            self.import_picture(path)
            return
        _w, _h, layers = got
        self.doc.snapshot_stack("Photoshop layers")
        for lay in layers:
            img = lay.image
            if img.size() != QSize(self.doc.width, self.doc.height):
                img = img.scaled(self.doc.width, self.doc.height, Qt.KeepAspectRatioByExpanding,
                                 Qt.SmoothTransformation)
                from .doc import blank
                canvas = blank(self.doc.width, self.doc.height)
                from PySide6.QtGui import QPainter
                p = QPainter(canvas)
                p.drawImage((self.doc.width - img.width()) // 2,
                            (self.doc.height - img.height()) // 2, img)
                p.end()
                img = canvas
            self.doc.layers.insert(self.doc.active + 1, Layer(lay.name, img, lay.opacity,
                                                              lay.blend, lay.visible))
            self.doc.active += 1
        self.doc.dirty = True
        self.layers.rebuild()
        self._layers_changed()
        self.say(f"Added {len(layers)} layers.")

    def copy(self, merged: bool = False) -> None:
        img = tl.selection_copy(self.doc, self.selection, merged)
        r = self.selection.bounds() if self.selection.active() else tl.paint_bounds(img)
        if r.isEmpty():
            self.say("Nothing to copy.")
            return
        self._clipboard = img.copy(r)
        QGuiApplication.clipboard().setImage(self._clipboard)
        self.say("Copied.")

    def paste(self) -> None:
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            img = self._clipboard
        if img is None or img.isNull():
            self.say("There's no picture to paste.")
            return
        from .doc import FORMAT
        img = img.convertToFormat(FORMAT)
        lay = self.doc.add_layer("Pasted")
        from PySide6.QtGui import QPainter
        p = QPainter(lay.image)
        p.drawImage((self.doc.width - img.width()) // 2, (self.doc.height - img.height()) // 2,
                    img)
        p.end()
        self.layers.rebuild()
        self._layers_changed()
        self.set_tool("move")

    def canvas_size(self) -> None:
        dlg = SizeDialog(self, self.doc.width, self.doc.height)
        if dlg.exec() != QDialog.Accepted:
            return
        w, h = dlg.w.value(), dlg.h.value()
        if (w, h) == (self.doc.width, self.doc.height):
            return
        self.doc.resize_canvas(w, h, dlg.scale.isChecked())
        self.selection = tl.Selection(w, h)
        self.view.set_document(self.doc, self.selection)
        self.layers.rebuild()
        self._update_title()

    def crop_to_selection(self) -> None:
        r = self.selection.bounds() if self.selection.active() else QRectF().toRect()
        if r.isEmpty():
            self.say("Select the part to keep first.")
            return
        self.doc.snapshot_stack("Crop")
        for lay in self.doc.layers:
            lay.image = lay.image.copy(r)
        self.doc.width, self.doc.height = r.width(), r.height()
        self.doc.dirty = True
        self.selection = tl.Selection(r.width(), r.height())
        self.view.set_document(self.doc, self.selection)
        self.layers.rebuild()
        self._update_title()

    def reference(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "A reference picture", "",
                                              "Pictures (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        try:
            img = files.import_image(Path(path))
        except (OSError, ValueError) as e:
            _error(self, "Reference", f"That picture can't be opened ({e}).")
            return
        if self._reference is not None:
            self._reference.close()
            self._reference.deleteLater()
        self._reference = ReferenceWindow(self, img, Path(path).stem)
        self._reference.show()

    def export(self, kind: str) -> None:
        stem = self.path.stem
        try:
            if kind == "layers":
                folder = QFileDialog.getExistingDirectory(self, "A folder for the layers")
                if folder:
                    made = files.export_layers(self.doc, Path(folder))
                    self.say(f"Saved {len(made)} layers.")
                return
            ext = {"png": "PNG (*.png)", "jpg": "JPG (*.jpg)",
                   "ora": "OpenRaster (*.ora)"}[kind]
            path, _ = QFileDialog.getSaveFileName(self, "Export", f"{stem}.{kind}", ext)
            if not path:
                return
            if kind == "png":
                files.export_png(self.doc, Path(path))
            elif kind == "jpg":
                files.export_jpg(self.doc, Path(path))
            else:
                files.save(self.doc, Path(path))
            self.say(f"Saved {Path(path).name}.")
        except OSError as e:
            _error(self, "Export", str(e))

    def help(self) -> None:
        text = (
            "<b>Tools</b>: B paint · S smudge · E erase · G fill · D gradient · I pick a colour "
            "· M select · V move · L liquify · U shapes<br>"
            "<b>Brush</b>: [ and ] size · 1–9 opacity · X swap colours · Alt + click picks "
            "a colour · keep the pen still at the end of a line to straighten it<br>"
            "<b>Canvas</b>: wheel zooms · Shift + wheel turns · Space + drag or the middle "
            "button moves it · Ctrl+0 fits it · R turns it back · H mirrors the view<br>"
            "<b>Touch</b>: two fingers move, zoom and turn · tap with two fingers to undo, "
            "three to redo<br>"
            "<b>Pen</b>: pressure changes size and flow; the pen's eraser end erases<br>"
            "<b>Layers</b>: Ctrl+Shift+N new · Ctrl+J copy · Ctrl+E merge down<br>"
            "<b>Selection</b>: Ctrl+A all · Ctrl+D none · Ctrl+Shift+I inside out · Delete "
            "clears it<br>"
            "<b>Tab</b> hides the panels · Ctrl+Z undo · Ctrl+Shift+Z redo · Ctrl+S save")
        box = QMessageBox(self)
        box.setWindowTitle("Paint studio help")
        box.setTextFormat(Qt.RichText)
        box.setText(text)
        box.exec()

    # ------------------------------------------------------------ saving
    def save(self) -> bool:
        if self.view.transform_active():
            self.view.apply_transform()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            files.save(self.doc, self.path)
        except OSError as e:
            _error(self, "Paint studio", f"The painting couldn't be saved: {e}")
            return False
        self.doc.dirty = False
        self._last_save = time.monotonic()
        self._update_title()
        self.say(f"Saved {self.path.name}.")
        self.saved.emit(str(self.path))
        return True

    def _autosave_now(self) -> None:
        """Every minute and a half: save in the background (a copy of the layers)."""
        if not self.doc.dirty or self.view._stroke is not None or self.view.transform_active():
            return
        try:
            from mse_studio.gui.common import Job, start
        except ImportError:
            return
        snap = Document(self.doc.width, self.doc.height)
        snap.layers = [lay.copy() for lay in self.doc.layers]
        snap.active = self.doc.active
        path = self.path

        def work(progress=None, cancel=None):
            path.parent.mkdir(parents=True, exist_ok=True)
            files.save(snap, path)
        job = Job(work)
        job.signals.finished.connect(self._autosaved)
        self._jobs.append(start(job))

    def _autosaved(self, _result) -> None:
        try:
            self.say("Saved automatically.")
            self.saved.emit(str(self.path))
        except RuntimeError:
            return

    def use_on_card(self) -> None:
        if self.on_use is None or not self.save():
            return
        png = self.path.with_suffix(".png")
        try:
            files.export_png(self.doc, png)
        except OSError as e:
            _error(self, "Paint studio", f"The picture couldn't be made: {e}")
            return
        self.on_use(png)
        self.say("It's on the card now.")

    def closeEvent(self, e):
        if self.doc.dirty and not self.save():
            box = QMessageBox.question(self, "Paint studio",
                                       "The painting couldn't be saved. Close it anyway?")
            if box != QMessageBox.Yes:
                e.ignore()
                return
        self.shutdown()
        super().closeEvent(e)

    def shutdown(self) -> None:
        self._autosave.stop()
        self.view.cancel()
        self.brushes.shutdown()
        try:
            from mse_studio.gui.common import forget
            forget(self._jobs)
        except ImportError:
            pass
        if self._reference is not None:
            self._reference.close()
