"""
Texture browser: filterable thumbnail grid for selecting textures.
"""

import os

from PySide6.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QWidget,
    QLabel,
    QPushButton,
    QGridLayout,
)
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtCore import Qt, Signal, QSize

from .texture_ops import TextureOps


THUMB_SIZE = 64
COLUMNS = 4


class TextureBrowserWidget(QGroupBox):

    texture_selected = Signal(str)  # full path of selected texture

    ACTIVE_STYLE = "border: 2px solid #4a7a4a;"
    NORMAL_STYLE = ""

    def __init__(self, textures_dir: str, parent=None):
        super().__init__("Textures", parent)
        self._textures_dir = textures_dir
        self._all_textures: list[dict] = []
        self._thumb_cache: dict[str, QPixmap] = {}
        self._active_path: str | None = None
        self._thumb_buttons: dict[str, QPushButton] = {}  # path -> button
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter textures...")
        self._search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._search)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setMaximumHeight(250)
        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setSpacing(4)
        self._scroll.setWidget(self._grid_container)
        layout.addWidget(self._scroll)

        bottom = QHBoxLayout()
        self._selected_label = QLabel("(none)")
        self._selected_label.setWordWrap(True)
        bottom.addWidget(self._selected_label, 1)
        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self.refresh)
        bottom.addWidget(btn_refresh)
        layout.addLayout(bottom)

    def set_directory(self, textures_dir: str):
        self._textures_dir = textures_dir
        self._active_path = None
        self._thumb_cache.clear()
        self._selected_label.setText("(none)")
        self.refresh()

    def refresh(self):
        self._all_textures = TextureOps.scan_texture_directory(
            self._textures_dir
        )
        self._rebuild_grid(self._all_textures)

    def _apply_filter(self, text: str):
        text = text.strip().lower()
        if not text:
            filtered = self._all_textures
        else:
            filtered = [
                t for t in self._all_textures if text in t["name"].lower()
            ]
        self._rebuild_grid(filtered)

    def _rebuild_grid(self, textures: list[dict]):
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self._thumb_buttons.clear()

        for idx, tex in enumerate(textures):
            btn = QPushButton()
            pixmap = self._get_thumbnail(tex["path"])
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(THUMB_SIZE, THUMB_SIZE))
            btn.setToolTip(tex["name"])
            btn.setFixedSize(THUMB_SIZE + 8, THUMB_SIZE + 8)

            if tex["path"] == self._active_path:
                btn.setStyleSheet(self.ACTIVE_STYLE)

            path = tex["path"]
            btn.clicked.connect(
                lambda checked=False, p=path: self._on_thumb_clicked(p)
            )
            self._thumb_buttons[path] = btn
            row = idx // COLUMNS
            col = idx % COLUMNS
            self._grid_layout.addWidget(btn, row, col)

    def _get_thumbnail(self, path: str) -> QPixmap:
        if path in self._thumb_cache:
            return self._thumb_cache[path]

        pixmap = QPixmap(path)
        if pixmap.isNull():
            pixmap = QPixmap(THUMB_SIZE, THUMB_SIZE)
            pixmap.fill(Qt.darkGray)
        else:
            pixmap = pixmap.scaled(
                THUMB_SIZE, THUMB_SIZE,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )

        self._thumb_cache[path] = pixmap
        return pixmap

    def _on_thumb_clicked(self, path: str):
        self._set_active(path)
        self.texture_selected.emit(path)

    def _set_active(self, path: str):
        if self._active_path and self._active_path in self._thumb_buttons:
            self._thumb_buttons[self._active_path].setStyleSheet(self.NORMAL_STYLE)

        self._active_path = path
        rel = os.path.relpath(path, self._textures_dir).replace("\\", "/")
        self._selected_label.setText(rel)

        if path in self._thumb_buttons:
            self._thumb_buttons[path].setStyleSheet(self.ACTIVE_STYLE)

    def get_active_path(self) -> str | None:
        return self._active_path

    def set_active_by_path(self, texture_path: str):
        norm = os.path.normcase(os.path.abspath(texture_path))
        for tex in self._all_textures:
            if os.path.normcase(os.path.abspath(tex["path"])) == norm:
                self._set_active(tex["path"])
                return
        self._active_path = texture_path
        rel = os.path.basename(texture_path)
        self._selected_label.setText(rel)
