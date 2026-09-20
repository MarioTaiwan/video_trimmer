from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from project import Chunk
from time_utils import format_time


class BoundaryEditor(QWidget):
    chunk_changed = Signal()
    frame_preview_requested = Signal(float)
    play_original_requested = Signal(float, float)
    preview_cut_requested = Signal(float, float, float, float)

    # Each edge is edited within a 20-second local window:
    # 10 seconds before to 10 seconds after the VAD edge.
    WINDOW_SECONDS = 10.0
    SLIDER_SCALE = 1000  # one slider unit = 1 ms

    def __init__(self, parent=None):
        super().__init__(parent)

        self.chunks: list[Chunk] = []
        self.boundary_index: int | None = None
        self.media_duration: float | None = None
        self._syncing = False

        self.heading = QLabel("<b>No boundary selected</b>")
        self.gap_label = QLabel("")

        self.left_spin = self._make_time_spin()
        self.right_spin = self._make_time_spin()

        self.left_slider = self._make_slider()
        self.right_slider = self._make_slider()

        left_group = QGroupBox("Previous chunk — end")
        left_layout = QVBoxLayout(left_group)
        left_form = QFormLayout()
        left_form.addRow("Time:", self.left_spin)
        left_layout.addLayout(left_form)
        left_layout.addWidget(self.left_slider)

        right_group = QGroupBox("Next chunk — start")
        right_layout = QVBoxLayout(right_group)
        right_form = QFormLayout()
        right_form.addRow("Time:", self.right_spin)
        right_layout.addLayout(right_form)
        right_layout.addWidget(self.right_slider)

        self.play_original_button = QPushButton("Play original around boundary")
        preview_cut_button = QPushButton("Preview resulting cut")
        self.play_original_button.clicked.connect(self._play_original)
        preview_cut_button.clicked.connect(self._preview_cut)

        playback_layout = QHBoxLayout()
        playback_layout.addWidget(self.play_original_button)
        playback_layout.addWidget(preview_cut_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addWidget(self.gap_label)
        layout.addWidget(left_group)
        layout.addWidget(right_group)
        layout.addLayout(playback_layout)

        self.left_spin.valueChanged.connect(self._left_spin_changed)
        self.right_spin.valueChanged.connect(self._right_spin_changed)

        # valueChanged handles both dragging and clicking the slider groove.
        self.left_slider.valueChanged.connect(self._left_slider_changed)
        self.right_slider.valueChanged.connect(self._right_slider_changed)

        # Clicking a handle without moving it should still update the preview.
        self.left_slider.sliderPressed.connect(self._preview_left_slider_frame)
        self.right_slider.sliderPressed.connect(self._preview_right_slider_frame)

        self.setEnabled(False)

    def _make_time_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(3)
        spin.setSingleStep(0.01)
        spin.setSuffix(" s")
        spin.setKeyboardTracking(False)
        return spin

    def _make_slider(self) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setSingleStep(10)   # 10 ms
        slider.setPageStep(100)    # 100 ms
        slider.setTracking(True)
        return slider

    def set_media_duration(self, seconds: float | None) -> None:
        self.media_duration = seconds if seconds and seconds > 0 else None
        if self.boundary_index is not None:
            self._sync_controls()

    def set_chunks(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        if len(chunks) < 2:
            self.clear_selection()
        elif self.boundary_index is not None:
            self.select_boundary(min(self.boundary_index, len(chunks) - 2))

    def clear_selection(self) -> None:
        self.boundary_index = None
        self.heading.setText("<b>No boundary selected</b>")
        self.gap_label.setText("")
        self.setEnabled(False)

    def select_boundary(self, index: int) -> None:
        if index < 0 or index >= len(self.chunks) - 1:
            self.clear_selection()
            return

        self.boundary_index = index
        self.setEnabled(True)
        self._sync_controls()

    def _local_window(
        self,
        current: float,
        original_vad_edge: float | None,
        hard_min: float,
        hard_max: float,
    ) -> tuple[float, float]:
        """Return a stable ±10 s editing window.

        VAD-created chunks are centered on the original VAD edge. If a value
        has already been manually moved more than 10 s away (e.g. via the
        chunk table), center on the current value so the slider still displays
        the actual edit correctly.
        """
        anchor = current
        if (
            original_vad_edge is not None
            and abs(current - original_vad_edge) <= self.WINDOW_SECONDS
        ):
            anchor = original_vad_edge

        minimum = max(hard_min, anchor - self.WINDOW_SECONDS)
        maximum = min(hard_max, anchor + self.WINDOW_SECONDS)

        # Always include the current value.
        minimum = min(minimum, current)
        maximum = max(maximum, current)

        if maximum < minimum:
            maximum = minimum

        return minimum, maximum

    def _sync_controls(self) -> None:
        if self.boundary_index is None:
            return

        left = self.chunks[self.boundary_index]
        right = self.chunks[self.boundary_index + 1]

        media_end = self.media_duration
        if media_end is None:
            media_end = max(left.end, right.end, 24 * 60 * 60)

        left_min, left_max = self._local_window(
            current=left.end,
            original_vad_edge=left.vad_end,
            hard_min=min(media_end, left.start + 0.001),
            hard_max=media_end,
        )
        right_min, right_max = self._local_window(
            current=right.start,
            original_vad_edge=right.vad_start,
            hard_min=0.0,
            hard_max=max(0.0, min(media_end, right.end - 0.001)),
        )

        self._syncing = True
        try:
            self.heading.setText(
                f"<b>Boundary / transition {self.boundary_index + 1}</b>"
            )
            self._update_gap_label()

            self.left_spin.setRange(left_min, left_max)
            self.right_spin.setRange(right_min, right_max)
            self.left_spin.setValue(left.end)
            self.right_spin.setValue(right.start)

            self.left_slider.setRange(
                round(left_min * self.SLIDER_SCALE),
                round(left_max * self.SLIDER_SCALE),
            )
            self.right_slider.setRange(
                round(right_min * self.SLIDER_SCALE),
                round(right_max * self.SLIDER_SCALE),
            )
            self.left_slider.setValue(round(left.end * self.SLIDER_SCALE))
            self.right_slider.setValue(round(right.start * self.SLIDER_SCALE))

            self.left_slider.setToolTip(
                f"Local range: {format_time(left_min)} to {format_time(left_max)}"
            )
            self.right_slider.setToolTip(
                f"Local range: {format_time(right_min)} to {format_time(right_max)}"
            )

            chronological = right.start >= left.end
            self.play_original_button.setEnabled(chronological)
            if chronological:
                self.play_original_button.setToolTip("")
            else:
                self.play_original_button.setToolTip(
                    "The next chunk occurs earlier in the source, so there is "
                    "no single continuous original interval around this transition."
                )
        finally:
            self._syncing = False

    def _update_gap_label(self) -> None:
        if self.boundary_index is None:
            return

        left = self.chunks[self.boundary_index]
        right = self.chunks[self.boundary_index + 1]
        delta = right.start - left.end

        if delta >= 0:
            description = f"Forward source gap: {delta:.3f} s"
        else:
            description = (
                f"Next chunk jumps {abs(delta):.3f} s backward in source"
            )

        self.gap_label.setText(
            f"{format_time(left.end)}  →  {format_time(right.start)}"
            f"    |    {description}"
        )

    def _left_spin_changed(self, value: float) -> None:
        if self._syncing or self.boundary_index is None:
            return

        seconds = float(value)
        left = self.chunks[self.boundary_index]
        left.end = seconds

        # Keep the slider handle in sync without recursively triggering edits.
        with QSignalBlocker(self.left_slider):
            self.left_slider.setValue(round(seconds * self.SLIDER_SCALE))

        self._update_gap_label()
        self.chunk_changed.emit()
        self.frame_preview_requested.emit(seconds)

    def _right_spin_changed(self, value: float) -> None:
        if self._syncing or self.boundary_index is None:
            return

        seconds = float(value)
        right = self.chunks[self.boundary_index + 1]
        right.start = seconds

        with QSignalBlocker(self.right_slider):
            self.right_slider.setValue(round(seconds * self.SLIDER_SCALE))

        self._update_gap_label()
        self.chunk_changed.emit()
        self.frame_preview_requested.emit(seconds)

    def _left_slider_changed(self, value: int) -> None:
        if self._syncing or self.boundary_index is None:
            return

        seconds = value / self.SLIDER_SCALE
        left = self.chunks[self.boundary_index]
        left.end = seconds

        # Update the timer, but do not route through its valueChanged handler.
        with QSignalBlocker(self.left_spin):
            self.left_spin.setValue(seconds)

        self._update_gap_label()
        self.chunk_changed.emit()
        self.frame_preview_requested.emit(seconds)

    def _right_slider_changed(self, value: int) -> None:
        if self._syncing or self.boundary_index is None:
            return

        seconds = value / self.SLIDER_SCALE
        right = self.chunks[self.boundary_index + 1]
        right.start = seconds

        with QSignalBlocker(self.right_spin):
            self.right_spin.setValue(seconds)

        self._update_gap_label()
        self.chunk_changed.emit()
        self.frame_preview_requested.emit(seconds)

    def _preview_left_slider_frame(self) -> None:
        if self._syncing:
            return
        self.frame_preview_requested.emit(
            self.left_slider.value() / self.SLIDER_SCALE
        )

    def _preview_right_slider_frame(self) -> None:
        if self._syncing:
            return
        self.frame_preview_requested.emit(
            self.right_slider.value() / self.SLIDER_SCALE
        )

    def _play_original(self) -> None:
        if self.boundary_index is None:
            return

        left = self.chunks[self.boundary_index]
        right = self.chunks[self.boundary_index + 1]

        if right.start < left.end:
            return

        self.play_original_requested.emit(
            max(left.start, left.end - 2.0),
            min(right.end, right.start + 2.0),
        )

    def _preview_cut(self) -> None:
        if self.boundary_index is None:
            return

        left = self.chunks[self.boundary_index]
        right = self.chunks[self.boundary_index + 1]

        self.preview_cut_requested.emit(
            max(left.start, left.end - 2.0),
            left.end,
            right.start,
            min(right.end, right.start + 2.0),
        )
