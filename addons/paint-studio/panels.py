"""The studio's side panels: Layers, the brush library and the brush editor
(Brush studio)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QScrollArea, QSlider,
                               QSpinBox, QToolButton, QVBoxLayout, QWidget)

from . import brushes as bl
from .brushes import Brush
from .doc import BLENDS, Document
from .engine import Stroke, preview_stroke

PREVIEW_W, PREVIEW_H = 200, 52
PREVIEW_VERSION = 2


def _icon(button, name: str) -> None:
    try:
        from mse_studio.gui import icons
        icons.set_icon(button, name)
    except Exception:  # noqa: BLE001 - outside MSE Studio
        pass


def _tool(name: str, tip: str, icon: str = "") -> QToolButton:
    b = QToolButton()
    b.setToolTip(tip)
    b.setAccessibleName(tip)
    if icon:
        _icon(b, icon)
        b.setIconSize(QSize(20, 20))
    else:
        b.setText(name)
    b.setAutoRaise(True)
    return b


# ------------------------------------------------------------------ layers
class LayersPanel(QWidget):
    """The painting's layers, top first: show/hide, pick, drag to reorder,
    and the active layer's opacity, blend mode and locks."""
    changed = Signal()                  # the picture may look different: redraw it
    message = Signal(str)

    THUMB = 52

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc: Optional[Document] = None
        self._filling = False
        self._opacity_step = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.add_btn = _tool("+", "New layer (Ctrl+Shift+N)", "add")
        self.dup_btn = _tool("Copy", "Duplicate the layer (Ctrl+J)", "content_copy")
        self.del_btn = _tool("Delete", "Delete the layer", "delete")
        self.up_btn = _tool("Up", "Move the layer up", "arrow_upward")
        self.down_btn = _tool("Down", "Move the layer down", "arrow_downward")
        self.merge_btn = QPushButton("Merge down")
        self.merge_btn.setToolTip("Put this layer onto the one below it (Ctrl+E)")
        self.more_btn = QPushButton("More")
        self.more_btn.setToolTip("Clear, flatten, select its paint…")
        for b in (self.add_btn, self.dup_btn, self.del_btn, self.up_btn, self.down_btn):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.merge_btn)
        row.addWidget(self.more_btn)
        lay.addLayout(row)
        self.list = QListWidget()
        self.list.setIconSize(QSize(self.THUMB, self.THUMB))
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setSpacing(2)
        self.list.setToolTip("Tick to show a layer, untick to hide it. Drag layers to put "
                             "them in a different order.")
        lay.addWidget(self.list, 1)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Layer name")
        form.addRow("Name", self.name)
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setToolTip("How see-through the layer is")
        form.addRow("Opacity", self.opacity)
        self.blend = QComboBox()
        for k, (label, _m, _o) in BLENDS.items():
            self.blend.addItem(label, k)
        self.blend.setToolTip("How the layer mixes with the ones below: Multiply darkens "
                              "(shadows), Screen and Add lighten (light, glow), Overlay adds "
                              "contrast and colour.")
        form.addRow("Blend", self.blend)
        lay.addLayout(form)
        self.lock = QCheckBox("Locked")
        self.lock.setToolTip("Nothing can change this layer")
        self.alpha = QCheckBox("Paint only on its paint")
        self.alpha.setToolTip("Keeps the see-through parts see-through: recolour or shade "
                              "what's there without going over the edges")
        self.clip = QCheckBox("Clip to the layer below")
        self.clip.setToolTip("This layer shows only where the layer below it has paint – "
                             "shade a shape without touching it")
        grid = QGridLayout()
        grid.addWidget(self.lock, 0, 0)
        grid.addWidget(self.alpha, 0, 1)
        grid.addWidget(self.clip, 1, 0, 1, 2)
        lay.addLayout(grid)

        self.list.currentRowChanged.connect(self._row_changed)
        self.list.itemChanged.connect(self._item_changed)
        self.list.model().rowsMoved.connect(self._rows_moved)
        self.add_btn.clicked.connect(self.add)
        self.dup_btn.clicked.connect(self.duplicate)
        self.del_btn.clicked.connect(self.delete)
        self.up_btn.clicked.connect(lambda: self.move(1))
        self.down_btn.clicked.connect(lambda: self.move(-1))
        self.merge_btn.clicked.connect(self.merge_down)
        self.more_btn.clicked.connect(self._more)
        self.name.editingFinished.connect(self._renamed)
        self.opacity.sliderPressed.connect(self._opacity_pressed)
        self.opacity.valueChanged.connect(self._opacity_changed)
        self.opacity.sliderReleased.connect(self._opacity_released)
        self.blend.currentIndexChanged.connect(self._blend_changed)
        self.lock.toggled.connect(lambda v: self._prop("Lock layer", locked=v))
        self.alpha.toggled.connect(lambda v: self._prop("Lock see-through parts", alpha_lock=v))
        self.clip.toggled.connect(lambda v: self._prop("Clipping mask", clip=v))
        self.more_menu = QMenu(self)

    # ---- showing the layers
    def set_document(self, doc: Document) -> None:
        self.doc = doc
        self.rebuild()

    def _row_of(self, index: int) -> int:
        return len(self.doc.layers) - 1 - index

    def _thumb(self, img: QImage) -> QIcon:
        s = self.THUMB
        pm = QPixmap(s, s)
        pm.fill(QColor("#e8e9ee"))
        p = QPainter(pm)
        for y in range(0, s, 8):
            for x in range(0, s, 8):
                if (x // 8 + y // 8) % 2:
                    p.fillRect(x, y, 8, 8, QColor("#cfd2da"))
        small = img.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawImage((s - small.width()) // 2, (s - small.height()) // 2, small)
        p.end()
        return QIcon(pm)

    def _label(self, i: int) -> str:
        lay = self.doc.layers[i]
        bits = []
        if lay.clip:
            bits.append("clipped")
        if lay.locked:
            bits.append("locked")
        if lay.alpha_lock:
            bits.append("paint only on its paint")
        if lay.blend != "normal":
            bits.append(BLENDS[lay.blend][0])
        if lay.opacity < 0.995:
            bits.append(f"{round(lay.opacity * 100)}%")
        return lay.name + (f"\n{' · '.join(bits)}" if bits else "")

    def rebuild(self) -> None:
        if self.doc is None:
            return
        self._filling = True
        try:
            self.list.clear()
            for i in reversed(range(len(self.doc.layers))):
                lay = self.doc.layers[i]
                it = QListWidgetItem(self._thumb(lay.image), self._label(i))
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
                it.setCheckState(Qt.Checked if lay.visible else Qt.Unchecked)
                if lay.clip:
                    it.setText("    ↳ " + it.text())
                self.list.addItem(it)
            self.list.setCurrentRow(self._row_of(self.doc.active))
            self._show_props()
        finally:
            self._filling = False

    def refresh_thumbs(self, index: Optional[int] = None) -> None:
        """The thumbnails again (after painting)."""
        if self.doc is None or self.list.count() != len(self.doc.layers):
            self.rebuild()
            return
        idx = range(len(self.doc.layers)) if index is None else [index]
        for i in idx:
            it = self.list.item(self._row_of(i))
            if it is not None:
                it.setIcon(self._thumb(self.doc.layers[i].image))

    def _show_props(self) -> None:
        lay = self.doc.layer
        widgets = (self.name, self.opacity, self.blend, self.lock, self.alpha, self.clip)
        for w in widgets:
            w.blockSignals(True)
        self.name.setText(lay.name)
        self.opacity.setValue(round(lay.opacity * 100))
        self.blend.setCurrentIndex(max(0, self.blend.findData(lay.blend)))
        self.lock.setChecked(lay.locked)
        self.alpha.setChecked(lay.alpha_lock)
        self.clip.setChecked(lay.clip)
        self.clip.setEnabled(self.doc.active > 0)
        for w in widgets:
            w.blockSignals(False)
        self.merge_btn.setEnabled(self.doc.active > 0)
        self.down_btn.setEnabled(self.doc.active > 0)
        self.up_btn.setEnabled(self.doc.active < len(self.doc.layers) - 1)

    # ---- changes
    def _row_changed(self, row: int) -> None:
        if self._filling or self.doc is None or row < 0:
            return
        self.doc.active = self._row_of(row)
        self._show_props()

    def _item_changed(self, it: QListWidgetItem) -> None:
        if self._filling or self.doc is None:
            return
        i = self._row_of(self.list.row(it))
        if not 0 <= i < len(self.doc.layers):
            return
        visible = it.checkState() == Qt.Checked
        lay = self.doc.layers[i]
        if lay.visible != visible:
            self.doc.snapshot_stack("Show layer" if visible else "Hide layer", pixels=False)
            lay.visible = visible
            self.doc.dirty = True
            self.changed.emit()

    def _rows_moved(self, _parent, start, _end, _dest, row) -> None:
        if self._filling or self.doc is None:
            return
        dst_row = row if row < start else row - 1
        n = len(self.doc.layers)
        src, dst = n - 1 - start, n - 1 - dst_row
        self.doc.move_layer_to(src, dst)
        self.rebuild()
        self.changed.emit()

    def _prop(self, label: str, **props) -> None:
        if self._filling or self.doc is None:
            return
        self.doc.set_props(label, **props)
        it = self.list.item(self._row_of(self.doc.active))
        if it is not None:
            self._filling = True
            it.setText(("    ↳ " if self.doc.layer.clip else "") +
                       self._label(self.doc.active))
            self._filling = False
        self.changed.emit()

    def _renamed(self) -> None:
        name = self.name.text().strip()
        if self.doc is not None and name and name != self.doc.layer.name:
            self._prop("Rename layer", name=name)

    def _opacity_pressed(self) -> None:
        if self.doc is not None:
            self.doc.snapshot_stack("Layer opacity", pixels=False)
            self._opacity_step = True

    def _opacity_changed(self, v: int) -> None:
        if self.doc is None:
            return
        if self._opacity_step:                  # dragging: one undo step for the drag
            self.doc.layer.opacity = v / 100
            self.doc.dirty = True
            self.changed.emit()
        else:
            self._prop("Layer opacity", opacity=v / 100)

    def _opacity_released(self) -> None:
        self._opacity_step = False
        self._prop_label()

    def _prop_label(self) -> None:
        it = self.list.item(self._row_of(self.doc.active)) if self.doc else None
        if it is not None:
            self._filling = True
            it.setText(("    ↳ " if self.doc.layer.clip else "") +
                       self._label(self.doc.active))
            self._filling = False

    def _blend_changed(self, _i: int) -> None:
        self._prop("Blend mode", blend=self.blend.currentData())

    def add(self) -> None:
        if self.doc is None:
            return
        self.doc.add_layer()
        self.rebuild()
        self.changed.emit()

    def duplicate(self) -> None:
        if self.doc is None:
            return
        self.doc.duplicate_layer()
        self.rebuild()
        self.changed.emit()

    def delete(self) -> None:
        if self.doc is None:
            return
        self.doc.delete_layer()
        self.rebuild()
        self.changed.emit()

    def move(self, step: int) -> None:
        if self.doc is None:
            return
        self.doc.move_layer(step)
        self.rebuild()
        self.changed.emit()

    def merge_down(self) -> None:
        if self.doc is None or self.doc.active == 0:
            return
        self.doc.merge_down()
        self.rebuild()
        self.changed.emit()

    def _more(self) -> None:
        m = self.more_menu
        m.clear()
        m.addAction("Clear the layer", self._clear)
        m.addAction("Flatten (all layers into one)", self._flatten)
        m.addSeparator()
        for a in getattr(self, "extra_actions", []):
            m.addAction(a)
        m.exec(self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()))

    def _clear(self) -> None:
        if self.doc is None or self.doc.layer.locked:
            self.message.emit("This layer is locked.")
            return
        self.doc.clear_layer()
        self.refresh_thumbs(self.doc.active)
        self.changed.emit()

    def _flatten(self) -> None:
        if self.doc is None:
            return
        self.doc.flatten()
        self.rebuild()
        self.changed.emit()


# ------------------------------------------------------------------ brushes
def _preview_key(b: Brush, colour: str) -> str:
    data = json.dumps({"b": b.to_dict(), "c": colour, "v": PREVIEW_VERSION}, sort_keys=True)
    return hashlib.sha1(data.encode()).hexdigest()[:20]


def make_previews(items: list[tuple[str, dict, str]], folder: str, progress=None,
                  cancel=None) -> int:
    """Stroke pictures of brushes (on a worker thread): ``items`` are
    (key, brush dict, colour); each is saved as ``folder/key.png``."""
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    for n, (key, d, colour) in enumerate(items):
        if cancel is not None and cancel.cancelled:
            break
        img = preview_stroke(Brush.from_dict(d), QColor(colour), PREVIEW_W, PREVIEW_H)
        tmp = out / f"{key}.partial.png"
        img.save(str(tmp), "PNG")
        tmp.replace(out / f"{key}.png")
        if progress is not None:
            progress(n + 1, len(items), key)
    return len(items)


class BrushPanel(QWidget):
    """The brush library: sets of brushes, each with a stroke to show what
    it does. ``chosen(Brush)`` when one is picked."""
    chosen = Signal(object)
    edit_requested = Signal(object)

    def __init__(self, data_dir: Optional[Path], parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir) if data_dir else None
        self.mine: list[Brush] = bl.load_user_brushes(self.data_dir)
        self._shown: list[Brush] = []
        self._jobs: list = []
        self._keys: dict[str, int] = {}
        self._colour = "#20232c"
        self.current: Optional[Brush] = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a brush…")
        self.search.setClearButtonEnabled(True)
        lay.addWidget(self.search)
        body = QHBoxLayout()
        self.sets = QListWidget()
        self.sets.setMaximumWidth(150)
        self.sets.setToolTip("Sets of brushes")
        body.addWidget(self.sets)
        self.list = QListWidget()
        self.list.setIconSize(QSize(PREVIEW_W // 2 + 40, PREVIEW_H // 2 + 10))
        self.list.setSpacing(2)
        body.addWidget(self.list, 1)
        lay.addLayout(body, 1)
        row = QHBoxLayout()
        self.edit_btn = QPushButton("Edit brush…")
        self.edit_btn.setToolTip("Change how this brush paints (Brush studio)")
        self.copy_btn = QPushButton("Duplicate")
        self.copy_btn.setToolTip("A copy of this brush in My brushes, to change")
        self.del_btn = QPushButton("Delete")
        self.del_btn.setToolTip("Delete this brush (only your own brushes)")
        self.io_btn = QPushButton("Share…")
        self.io_btn.setToolTip("Save your brushes to a file, or add brushes from a file")
        for b in (self.edit_btn, self.copy_btn, self.del_btn, self.io_btn):
            row.addWidget(b)
        lay.addLayout(row)
        self.sets.currentRowChanged.connect(self._fill)
        self.search.textChanged.connect(self._fill)
        self.list.currentRowChanged.connect(self._picked)
        self.list.itemDoubleClicked.connect(self._edit_current)
        self.edit_btn.clicked.connect(self._edit_current)
        self.copy_btn.clicked.connect(self.duplicate)
        self.del_btn.clicked.connect(self.delete)
        self.io_btn.clicked.connect(self._share_menu)
        self._fill_sets()

    # ---- what's listed
    def _all(self) -> list[Brush]:
        return list(self.mine) + list(bl.LIBRARY)

    def _fill_sets(self) -> None:
        self.sets.blockSignals(True)
        self.sets.clear()
        names = (["My brushes"] if self.mine else []) + list(bl.CATEGORIES) + ["All brushes"]
        self.sets.addItems(names)
        self.sets.setCurrentRow(0)
        self.sets.blockSignals(False)
        self._fill()

    def _fill(self, *_):
        it = self.sets.currentItem()
        name = it.text() if it is not None else "All brushes"
        words = self.search.text().strip().lower()
        if words:
            shown = [b for b in self._all() if words in b.name.lower() or
                     words in b.category.lower()]
        elif name == "My brushes":
            shown = list(self.mine)
        elif name == "All brushes":
            shown = self._all()
        else:
            shown = [b for b in bl.LIBRARY if b.category == name] + \
                [b for b in self.mine if b.category == name]
        self._shown = shown
        self.list.blockSignals(True)
        self.list.clear()
        self._keys.clear()
        missing = []
        folder = self._preview_dir()
        for i, b in enumerate(shown):
            key = _preview_key(b, self._colour)
            self._keys[key] = i
            it = QListWidgetItem(b.name)
            it.setToolTip(f"{b.name} – {b.category}" + ("" if b.builtin else " (yours)"))
            png = folder / f"{key}.png" if folder else None
            if png is not None and png.exists():
                it.setIcon(QIcon(QPixmap(str(png))))
            else:
                missing.append((key, b.to_dict(), self._colour))
            self.list.addItem(it)
            if self.current is not None and b.name == self.current.name and \
                    b.builtin == self.current.builtin:
                self.list.setCurrentRow(i)
        self.list.blockSignals(False)
        self._buttons()
        if missing and folder is not None:
            self._make_previews(missing)

    def _preview_dir(self) -> Optional[Path]:
        return self.data_dir / "brush-previews" if self.data_dir else None

    def _make_previews(self, items) -> None:
        try:
            from mse_studio.gui.common import Job, start
        except ImportError:
            return
        job = Job(make_previews, items, str(self._preview_dir()))
        job.signals.progress.connect(self._preview_ready)
        self._jobs.append(start(job))

    def _preview_ready(self, _done, _total, key) -> None:
        try:
            i = self._keys.get(key)
            if i is None or i >= self.list.count():
                return
            png = self._preview_dir() / f"{key}.png"
            if png.exists():
                self.list.item(i).setIcon(QIcon(QPixmap(str(png))))
        except RuntimeError:                    # the panel is gone
            return

    def set_ink(self, colour: QColor) -> None:
        """The colour the previews are drawn in (dark on light themes)."""
        c = colour.name()
        if c != self._colour:
            self._colour = c
            self._fill()

    def shutdown(self) -> None:
        try:
            from mse_studio.gui.common import forget
            forget(self._jobs)
        except ImportError:
            pass

    # ---- choosing
    def select(self, brush: Brush) -> None:
        """Show ``brush`` as the chosen one (without sending ``chosen``)."""
        self.current = brush
        for i, b in enumerate(self._shown):
            if b.name == brush.name and b.builtin == brush.builtin:
                self.list.blockSignals(True)
                self.list.setCurrentRow(i)
                self.list.blockSignals(False)
                break
        self._buttons()

    def find(self, name: str) -> Optional[Brush]:
        return next((b for b in self._all() if b.name == name), None)

    def _picked(self, row: int) -> None:
        if 0 <= row < len(self._shown):
            self.current = self._shown[row]
            self._buttons()
            self.chosen.emit(self.current)

    def _buttons(self) -> None:
        b = self.current
        self.del_btn.setEnabled(b is not None and not b.builtin)
        self.edit_btn.setEnabled(b is not None)
        self.copy_btn.setEnabled(b is not None)

    def _edit_current(self, *_):
        if self.current is not None:
            self.edit_requested.emit(self.current)

    # ---- my brushes
    def _free_name(self, name: str) -> str:
        names = {b.name for b in self._all()}
        if name not in names:
            return name
        n = 2
        while f"{name} {n}" in names:
            n += 1
        return f"{name} {n}"

    def save_brush(self, brush: Brush, replace: Optional[Brush] = None) -> Brush:
        """Keep ``brush`` in My brushes (instead of ``replace``, one of mine)."""
        brush = brush.copy(builtin=False)
        if replace is not None and not replace.builtin and replace in self.mine:
            i = self.mine.index(replace)
            if brush.name != replace.name:
                brush.name = self._free_name(brush.name)
            self.mine[i] = brush
        else:
            brush.name = self._free_name(brush.name)
            self.mine.insert(0, brush)
        bl.save_user_brushes(self.data_dir, self.mine)
        self.current = brush
        self._fill_sets()
        self.select(brush)
        return brush

    def duplicate(self) -> None:
        if self.current is None:
            return
        b = self.current.copy(name=self.current.name + " copy", category=self.current.category)
        b = self.save_brush(b)
        self.chosen.emit(b)

    def delete(self) -> None:
        b = self.current
        if b is None or b.builtin or b not in self.mine:
            return
        try:
            from mse_studio.gui.common import ask_delete
            if not ask_delete(self, f"Delete the brush “{b.name}”?"):
                return
        except ImportError:
            pass
        self.mine.remove(b)
        bl.save_user_brushes(self.data_dir, self.mine)
        self.current = None
        self._fill_sets()

    def _share_menu(self) -> None:
        m = QMenu(self)
        a = m.addAction("Save my brushes to a file…", self.export_brushes)
        a.setEnabled(bool(self.mine))
        m.addAction("Add brushes from a file…", self.import_brushes)
        m.exec(self.io_btn.mapToGlobal(self.io_btn.rect().bottomLeft()))

    def export_brushes(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save my brushes", "my brushes.json",
                                              "Brushes (*.json)")
        if path:
            Path(path).write_text(json.dumps({"paint-studio-brushes": 1, "brushes": [
                b.to_dict() for b in self.mine]}, indent=1), encoding="utf-8")

    def import_brushes(self, path: str = "") -> int:
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Add brushes", "",
                                                  "Brushes (*.json)")
        if not path:
            return 0
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            try:
                from mse_studio.gui.common import error
                error(self, "Brushes", f"That file can't be read ({e}).")
            except ImportError:
                pass
            return 0
        items = data.get("brushes", []) if isinstance(data, dict) else data
        added = 0
        for d in items if isinstance(items, list) else []:
            if isinstance(d, dict) and d.get("name"):
                try:
                    b = Brush.from_dict(d)
                except (TypeError, ValueError):
                    continue
                b.name = self._free_name(b.name)
                self.mine.append(b)
                added += 1
        if added:
            bl.save_user_brushes(self.data_dir, self.mine)
            self._fill_sets()
        return added


# ------------------------------------------------------------------ Brush studio
class _Pad(QWidget):
    """A scrap of paper to try a brush on."""

    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self.dialog = dialog
        self.setMinimumHeight(170)
        self.doc = Document(900, 220, QColor("#fbfbf8"))
        self.stroke: Optional[Stroke] = None
        self.setToolTip("Try the brush here")
        self.setCursor(Qt.CrossCursor)

    def resizeEvent(self, e):
        w, h = max(50, self.width()), max(50, self.height())
        if (w, h) != (self.doc.width, self.doc.height):
            self.doc = Document(w, h, QColor("#fbfbf8"))
        super().resizeEvent(e)

    def clear(self) -> None:
        self.doc = Document(self.doc.width, self.doc.height, QColor("#fbfbf8"))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        img = self.stroke.preview() if self.stroke is not None else self.doc.layer.image
        p.drawImage(0, 0, img)
        p.setPen(QColor(0, 0, 0, 40))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()

    def _start(self, pos: QPointF, pressure: float) -> None:
        d = self.dialog
        self.stroke = Stroke(self.doc, d.brush(), d.colour, size=d.brush().size)
        self.stroke.add(pos.x(), pos.y(), pressure)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._start(e.position(), 1.0)

    def mouseMoveEvent(self, e):
        if self.stroke is not None:
            self.stroke.add(e.position().x(), e.position().y(), 1.0)
            self.update()

    def mouseReleaseEvent(self, e):
        if self.stroke is not None:
            self.stroke.end()
            self.stroke.commit()
            self.stroke = None
            self.update()

    def tabletEvent(self, e):
        e.accept()
        pos, pr = e.position(), max(0.02, e.pressure())
        if e.type() == e.Type.TabletPress:
            self._start(pos, pr)
        elif e.type() == e.Type.TabletMove and self.stroke is not None:
            self.stroke.add(pos.x(), pos.y(), pr)
            self.update()
        elif e.type() == e.Type.TabletRelease and self.stroke is not None:
            self.mouseReleaseEvent(e)


# (key, label, low, high, scale, tip) – the slider shows value × scale
_SLIDERS = {
    "Size and pressure": [
        ("size", "Size", 1, 600, 1, "How wide the brush is, in pixels of the painting"),
        ("min_size", "Size with a light touch", 0, 100, 100,
         "How wide it is when you press lightly (a part of its size)"),
        ("opacity", "Opacity", 1, 100, 100, "The most one stroke covers"),
        ("flow", "Flow", 1, 100, 100, "How much paint each touch of the tip adds"),
        ("min_flow", "Flow with a light touch", 0, 100, 100,
         "How much paint it adds when you press lightly"),
    ],
    "Stroke": [
        ("spacing", "Spacing", 2, 300, 100,
         "The gap between the tips along a stroke (a part of the size)"),
        ("smoothing", "Steadier lines", 0, 100, 100,
         "Smooths shaky lines: the line follows the pen a little behind"),
        ("taper", "Taper", 0, 100, 100, "The start of a line grows in"),
        ("scatter", "Scatter", 0, 1000, 100, "Tips land up to this far from the line"),
        ("count", "Tips each step", 1, 40, 1, "More tips for sprays"),
    ],
    "Shape": [
        ("hardness", "Hardness", 0, 100, 100, "Soft edge … hard edge"),
        ("roundness", "Roundness", 5, 100, 100, "Round … flat"),
        ("angle", "Angle", 0, 180, 1, "Which way a flat tip points"),
    ],
    "Grain": [
        ("grain_scale", "Grain size", 20, 400, 100, "How big the paper's grain is"),
        ("grain_depth", "Grain depth", 0, 100, 100, "How much of the grain shows"),
    ],
    "Changes along the stroke": [
        ("jitter_size", "Size", 0, 100, 100, "Each tip a different size"),
        ("jitter_angle", "Angle", 0, 100, 100, "Each tip turned differently"),
        ("jitter_opacity", "Opacity", 0, 100, 100, "Each tip a little more see-through"),
        ("jitter_hue", "Colour", 0, 100, 100, "Each tip a slightly different colour"),
    ],
    "Wet paint": [
        ("wet", "Wetness", 0, 100, 100,
         "Paint: picks up the colour under it. Smudge and blur: how strong"),
        ("wet_edges", "Wet edges", 0, 100, 100, "Watercolour's darker rims"),
    ],
}


class BrushStudio(QDialog):
    """Every setting of a brush, a stroke that shows it, and a scrap of
    paper to try it on."""

    def __init__(self, parent, brush: Brush, colour: QColor):
        super().__init__(parent)
        self.setWindowTitle(f"Brush studio · {brush.name}")
        self.original = brush
        self.colour = QColor(colour)
        self._b = brush.copy()
        self._sliders: dict[str, tuple[QSlider, QSpinBox, int]] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._update_preview)
        outer = QHBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        form_lay = QVBoxLayout(holder)
        top = QFormLayout()
        self.name = QLineEdit(brush.name)
        top.addRow("Name", self.name)
        self.category = QComboBox()
        self.category.addItems(bl.CATEGORIES)
        self.category.setCurrentText(brush.category)
        top.addRow("Set", self.category)
        self.mode = QComboBox()
        for k, label in bl.MODES.items():
            self.mode.addItem(label, k)
        self.mode.setCurrentIndex(max(0, self.mode.findData(brush.mode)))
        self.mode.setToolTip("Paint, smudge (pushes paint along), blur or erase")
        top.addRow("Does", self.mode)
        self.shape = QComboBox()
        for k, label in bl.SHAPES.items():
            self.shape.addItem(label, k)
        self.shape.setCurrentIndex(max(0, self.shape.findData(brush.shape)))
        top.addRow("Tip", self.shape)
        self.grain = QComboBox()
        for k, label in bl.GRAINS.items():
            self.grain.addItem(label, k)
        self.grain.setCurrentIndex(max(0, self.grain.findData(brush.grain)))
        self.grain.setToolTip("The texture of the paper or canvas the brush shows")
        top.addRow("Grain", self.grain)
        self.blend = QComboBox()
        for k, label in bl.STROKE_BLENDS.items():
            self.blend.addItem(label, k)
        self.blend.setCurrentIndex(max(0, self.blend.findData(brush.blend)))
        top.addRow("Mixes", self.blend)
        form_lay.addLayout(top)
        checks = QGridLayout()
        self.follow = QCheckBox("Tip turns with the stroke")
        self.follow.setChecked(brush.follow)
        self.build_up = QCheckBox("Builds up (airbrush)")
        self.build_up.setToolTip("Keeps adding paint past its opacity while you go over it")
        self.build_up.setChecked(brush.build_up)
        self.p_size = QCheckBox("Pressure changes the size")
        self.p_size.setChecked(brush.pressure_size)
        self.p_opacity = QCheckBox("Pressure changes the flow")
        self.p_opacity.setChecked(brush.pressure_opacity)
        for i, c in enumerate((self.follow, self.build_up, self.p_size, self.p_opacity)):
            checks.addWidget(c, i // 2, i % 2)
            c.toggled.connect(self._changed)
        form_lay.addLayout(checks)
        for w in (self.mode, self.shape, self.grain, self.blend, self.category):
            w.currentIndexChanged.connect(self._changed)
        for title, rows in _SLIDERS.items():
            box = QGroupBox(title)
            f = QFormLayout(box)
            for key, label, lo, hi, scale, tip in rows:
                s = QSlider(Qt.Horizontal)
                s.setRange(lo, hi)
                sp = QSpinBox()
                sp.setRange(lo, hi)
                v = int(round(float(getattr(brush, key)) * scale))
                s.setValue(v)
                sp.setValue(v)
                s.setToolTip(tip)
                sp.setToolTip(tip)
                s.valueChanged.connect(sp.setValue)
                sp.valueChanged.connect(s.setValue)
                s.valueChanged.connect(self._changed)
                row = QHBoxLayout()
                row.addWidget(s, 1)
                row.addWidget(sp)
                f.addRow(label, row)
                self._sliders[key] = (s, sp, scale)
            form_lay.addWidget(box)
        form_lay.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)
        right = QVBoxLayout()
        right.addWidget(QLabel("What it looks like"))
        self.preview = QLabel()
        self.preview.setMinimumHeight(PREVIEW_H * 2 + 8)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background: #fbfbf8; border-radius: 6px;")
        right.addWidget(self.preview)
        row = QHBoxLayout()
        row.addWidget(QLabel("Try it:"))
        row.addStretch(1)
        clear = QPushButton("Clean the paper")
        row.addWidget(clear)
        right.addLayout(row)
        self.pad = _Pad(self)
        right.addWidget(self.pad, 1)
        self.buttons = QDialogButtonBox()
        self.save_btn = self.buttons.addButton(
            "Save" if not brush.builtin else "Save as my brush", QDialogButtonBox.AcceptRole)
        self.save_btn.setToolTip("Keep these settings" if not brush.builtin else
                                 "Built-in brushes stay as they are: this keeps yours in "
                                 "My brushes")
        self.new_btn = self.buttons.addButton("Save as a new brush",
                                              QDialogButtonBox.ActionRole)
        self.buttons.addButton(QDialogButtonBox.Cancel)
        self.as_new = brush.builtin
        right.addWidget(self.buttons)
        outer.addLayout(right, 1)
        clear.clicked.connect(self.pad.clear)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.new_btn.clicked.connect(self._save_new)
        self.resize(1100, 720)
        self._update_preview()

    def _save_new(self) -> None:
        self.as_new = True
        self.accept()

    def brush(self) -> Brush:
        b = self._b
        b.name = self.name.text().strip() or self.original.name
        b.category = self.category.currentText()
        b.mode = self.mode.currentData()
        b.shape = self.shape.currentData()
        b.grain = self.grain.currentData()
        b.blend = self.blend.currentData()
        b.follow = self.follow.isChecked()
        b.build_up = self.build_up.isChecked()
        b.pressure_size = self.p_size.isChecked()
        b.pressure_opacity = self.p_opacity.isChecked()
        for key, (s, _sp, scale) in self._sliders.items():
            v = s.value() / scale
            setattr(b, key, int(v) if key == "count" else float(v))
        return b

    def result_brush(self) -> Brush:
        return Brush.from_dict(self.brush().to_dict())

    def _changed(self, *_):
        self._timer.start()

    def _update_preview(self) -> None:
        img = preview_stroke(self.brush(), self.colour, PREVIEW_W * 2, PREVIEW_H * 2,
                             QColor("#fbfbf8"))
        self.preview.setPixmap(QPixmap.fromImage(img))

    def done(self, r):
        self._timer.stop()
        super().done(r)
