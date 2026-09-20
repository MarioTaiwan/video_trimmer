from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class ChunkSettingsDialog(QDialog):
    def __init__(
        self,
        threshold: float,
        boundary_counter=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Chunk Detection Settings")
        self.setModal(True)
        self.resize(430, 220)

        self._boundary_counter = boundary_counter

        title = QLabel("<b>Minimum quiet duration for a chunk boundary</b>")
        help_label = QLabel(
            "A non-speech gap shorter than this stays inside the same chunk. "
            "A gap equal to or longer than this creates a new chunk boundary."
        )
        help_label.setWordWrap(True)

        self.spin = QDoubleSpinBox()
        self.spin.setRange(0.05, 30.0)
        self.spin.setDecimals(2)
        self.spin.setSingleStep(0.05)
        self.spin.setSuffix(" s")
        self.spin.setValue(threshold)
        self.spin.setKeyboardTracking(False)

        form = QFormLayout()
        form.addRow("Quiet duration:", self.spin)

        self.count_label = QLabel("")
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._update_count()

        reset_button = QPushButton("Reset to 0.70 s")
        reset_button.clicked.connect(lambda: self.spin.setValue(0.70))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.spin.valueChanged.connect(self._update_count)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(help_label)
        layout.addSpacing(6)
        layout.addLayout(form)
        layout.addWidget(self.count_label)
        layout.addStretch(1)
        layout.addWidget(reset_button)
        layout.addWidget(buttons)

    def _update_count(self) -> None:
        if self._boundary_counter is None:
            self.count_label.setText("")
            return

        count = self._boundary_counter(float(self.spin.value()))
        self.count_label.setText(f"Potential chunk boundaries: {count}")

    @property
    def threshold(self) -> float:
        return float(self.spin.value())
