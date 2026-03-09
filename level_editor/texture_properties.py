"""
Per-face texture property controls: tiling, rotation, offset,
alignment tools, defaults, Texture Tool toggle, and continuation picker.
"""

import json
import os

from PySide6.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QDoubleSpinBox,
    QPushButton,
    QCheckBox,
)
from PySide6.QtCore import Signal

_DEFAULT_PROPS = {
    "tile_u": 1.0,
    "tile_v": 1.0,
    "rotation": 0.0,
    "offset_u": 0.0,
    "offset_v": 0.0,
}


class TexturePropertiesWidget(QGroupBox):

    properties_changed = Signal()

    # Lock signals
    texture_lock_toggled = Signal(bool)
    uv_lock_toggled = Signal(bool)

    # Continuation picker signals
    continuation_pick_requested = Signal()
    continuation_cleared = Signal()

    # Alignment
    fit_requested = Signal(str)  # "h", "v", or "both"

    def __init__(self, parent=None):
        super().__init__("Texture Properties", parent)
        self._suppress_change = False
        self._defaults = dict(_DEFAULT_PROPS)
        self._defaults_path = self._resolve_defaults_path()
        self._load_defaults()
        self._build_ui()

    @staticmethod
    def _resolve_defaults_path() -> str:
        try:
            from pymxs import runtime as rt
            d = str(rt.getDir(rt.Name("userScripts")))
        except Exception:
            d = os.path.expanduser("~")
        return os.path.join(d, "LevelEditor_TextureDefaults.json")

    def _load_defaults(self):
        try:
            with open(self._defaults_path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in _DEFAULT_PROPS:
                    if k in data:
                        self._defaults[k] = float(data[k])
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            pass

    def _save_defaults(self):
        try:
            with open(self._defaults_path, "w") as f:
                json.dump(self._defaults, f, indent=2)
        except OSError:
            pass

    def _build_ui(self):
        layout = QVBoxLayout(self)

        lock_row = QHBoxLayout()
        self._texture_lock_cb = QCheckBox("Texture Lock")
        self._texture_lock_cb.setToolTip(
            "When ON, texture rotation sticks to faces during any geometry "
            "change. The rotation/offset values update automatically, then "
            "UVs are re-projected with the corrected params (auto-tiling "
            "still works)."
        )
        self._texture_lock_cb.toggled.connect(self.texture_lock_toggled.emit)
        lock_row.addWidget(self._texture_lock_cb)
        self._uv_lock_cb = QCheckBox("UV Lock")
        self._uv_lock_cb.setToolTip(
            "When ON, UVs stay completely frozen during geometry edits "
            "(no re-projection, texture stretches with geometry)."
        )
        self._uv_lock_cb.toggled.connect(self.uv_lock_toggled.emit)
        lock_row.addWidget(self._uv_lock_cb)
        layout.addLayout(lock_row)

        self.face_count_label = QLabel("Selected Faces: 0")
        layout.addWidget(self.face_count_label)

        row_tile = QHBoxLayout()
        row_tile.addWidget(QLabel("Tiling"))
        self.tile_u = self._make_spin(0.01, 100.0, 1.0, 0.1, "U: ")
        row_tile.addWidget(self.tile_u)
        self.tile_v = self._make_spin(0.01, 100.0, 1.0, 0.1, "V: ")
        row_tile.addWidget(self.tile_v)
        layout.addLayout(row_tile)

        row_rot = QHBoxLayout()
        row_rot.addWidget(QLabel("Rotation"))
        self.rotation = self._make_spin(-360.0, 360.0, 0.0, 5.0, suffix=" deg")
        row_rot.addWidget(self.rotation)
        layout.addLayout(row_rot)

        row_off = QHBoxLayout()
        row_off.addWidget(QLabel("Offset"))
        self.offset_u = self._make_spin(-100.0, 100.0, 0.0, 0.05, "U: ")
        row_off.addWidget(self.offset_u)
        self.offset_v = self._make_spin(-100.0, 100.0, 0.0, 0.05, "V: ")
        row_off.addWidget(self.offset_v)
        layout.addLayout(row_off)

        for spin in (self.tile_u, self.tile_v, self.rotation,
                     self.offset_u, self.offset_v):
            spin.valueChanged.connect(self._on_value_changed)

        align_row1 = QHBoxLayout()
        btn_fit_h = QPushButton("Fit H")
        btn_fit_h.setToolTip("Scale U tiling to fit face width")
        btn_fit_h.clicked.connect(lambda: self.fit_requested.emit("h"))
        align_row1.addWidget(btn_fit_h)
        btn_fit_v = QPushButton("Fit V")
        btn_fit_v.setToolTip("Scale V tiling to fit face height")
        btn_fit_v.clicked.connect(lambda: self.fit_requested.emit("v"))
        align_row1.addWidget(btn_fit_v)
        btn_fit = QPushButton("Fit")
        btn_fit.setToolTip("Scale both U and V tiling to fit face")
        btn_fit.clicked.connect(lambda: self.fit_requested.emit("both"))
        align_row1.addWidget(btn_fit)
        btn_reset = QPushButton("Reset")
        btn_reset.setToolTip("Reset UV properties to saved defaults")
        btn_reset.clicked.connect(self._on_reset)
        align_row1.addWidget(btn_reset)
        layout.addLayout(align_row1)

        align_row2 = QHBoxLayout()
        btn_rot90 = QPushButton("+90")
        btn_rot90.setToolTip("Rotate texture 90 degrees")
        btn_rot90.clicked.connect(lambda: self._rotate_by(90.0))
        align_row2.addWidget(btn_rot90)
        btn_rot45 = QPushButton("+45")
        btn_rot45.setToolTip("Rotate texture 45 degrees")
        btn_rot45.clicked.connect(lambda: self._rotate_by(45.0))
        align_row2.addWidget(btn_rot45)
        btn_world = QPushButton("World")
        btn_world.setToolTip("Reset rotation and offset to world-aligned")
        btn_world.clicked.connect(self._on_align_world)
        align_row2.addWidget(btn_world)
        layout.addLayout(align_row2)

        defaults_row = QHBoxLayout()
        btn_set_default = QPushButton("Set as Default")
        btn_set_default.setToolTip("Save current UV values as the default for new faces")
        btn_set_default.clicked.connect(self._on_set_default)
        defaults_row.addWidget(btn_set_default)
        btn_reset_default = QPushButton("Reset to Defaults")
        btn_reset_default.setToolTip("Restore UV values to saved defaults")
        btn_reset_default.clicked.connect(self._on_reset)
        defaults_row.addWidget(btn_reset_default)
        layout.addLayout(defaults_row)

        cont_row = QHBoxLayout()
        self._cont_pick_btn = QPushButton("Pick Source")
        self._cont_pick_btn.setToolTip(
            "Click, then select a face to use as the continuation source"
        )
        self._cont_pick_btn.clicked.connect(self._on_pick_source)
        cont_row.addWidget(self._cont_pick_btn)
        self._cont_clear_btn = QPushButton("Clear")
        self._cont_clear_btn.setToolTip("Clear continuation source")
        self._cont_clear_btn.clicked.connect(self._on_clear_source)
        cont_row.addWidget(self._cont_clear_btn)
        layout.addLayout(cont_row)

        self._cont_status = QLabel("(no source)")
        self._cont_status.setWordWrap(True)
        layout.addWidget(self._cont_status)

    def _rotate_by(self, degrees: float):
        self.rotation.setValue(self.rotation.value() + degrees)

    def _on_align_world(self):
        self._suppress_change = True
        try:
            self.rotation.setValue(0.0)
            self.offset_u.setValue(0.0)
            self.offset_v.setValue(0.0)
        finally:
            self._suppress_change = False
        self.properties_changed.emit()

    def _on_reset(self):
        self.set_properties(self._defaults)
        self.properties_changed.emit()

    def _on_set_default(self):
        self._defaults = self.get_properties()
        self._save_defaults()

    def _on_pick_source(self):
        self._cont_pick_btn.setStyleSheet("background-color: #7a6a2a;")
        self._cont_status.setText("Select a face as source...")
        self.continuation_pick_requested.emit()

    def _on_clear_source(self):
        self._cont_pick_btn.setStyleSheet("")
        self._cont_status.setText("(no source)")
        self.continuation_cleared.emit()

    def _on_value_changed(self):
        if not self._suppress_change:
            self.properties_changed.emit()

    @staticmethod
    def _make_spin(lo: float, hi: float, default: float, step: float,
                   prefix: str = "", suffix: str = "") -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setValue(default)
        spin.setSingleStep(step)
        if prefix:
            spin.setPrefix(prefix)
        if suffix:
            spin.setSuffix(suffix)
        return spin

    @property
    def texture_lock_active(self) -> bool:
        return self._texture_lock_cb.isChecked()

    @property
    def uv_lock_active(self) -> bool:
        return self._uv_lock_cb.isChecked()

    def set_face_count(self, count: int):
        self.face_count_label.setText(f"Selected Faces: {count}")

    def get_properties(self) -> dict:
        return {
            "tile_u": self.tile_u.value(),
            "tile_v": self.tile_v.value(),
            "rotation": self.rotation.value(),
            "offset_u": self.offset_u.value(),
            "offset_v": self.offset_v.value(),
        }

    def set_properties(self, props: dict):
        self._suppress_change = True
        try:
            self.tile_u.setValue(props.get("tile_u", 1.0))
            self.tile_v.setValue(props.get("tile_v", 1.0))
            self.rotation.setValue(props.get("rotation", 0.0))
            self.offset_u.setValue(props.get("offset_u", 0.0))
            self.offset_v.setValue(props.get("offset_v", 0.0))
        finally:
            self._suppress_change = False

    def get_defaults(self) -> dict:
        return dict(self._defaults)

    def set_continuation_status(self, text: str):
        self._cont_status.setText(text)
        if text.startswith("Source:"):
            self._cont_pick_btn.setStyleSheet("background-color: #4a7a4a;")
        elif text == "(no source)":
            self._cont_pick_btn.setStyleSheet("")
