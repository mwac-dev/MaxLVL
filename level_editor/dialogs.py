"""
Reusable Qt dialogs for the Level Editor.
"""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QVBoxLayout,
)


class TriggerPickerDialog(QDialog):
    def __init__(self, trigger_names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pick Trigger")
        self.setMinimumWidth(250)
        self.picked = None

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        self.list_widget.addItems(trigger_names)
        self.list_widget.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        item = self.list_widget.currentItem()
        if item:
            self.picked = item.text()
        super().accept()
