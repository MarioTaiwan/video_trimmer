from __future__ import annotations

import copy
import random
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from audio import find_ffmpeg
from project import Chunk
from subtitle_render import selected_track_cues, selected_tracks, subtitle_layout_metrics
from subtitles import SubtitleRenderSettings, SubtitleState
from time_utils import format_time


class SubtitlePreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(680, 390)
        self.frame = QPixmap()
        self.source_time = 0.0
        self.settings = SubtitleRenderSettings()
        self.first_text = "Original subtitle preview"
        self.second_text = "翻譯字幕預覽"
        self._scroll_phase = 0.0

        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._advance_scroll)
        self.timer.start()

    def set_content(
        self,
        frame: QPixmap,
        source_time: float,
        settings: SubtitleRenderSettings,
        first_text: str,
        second_text: str,
    ) -> None:
        self.frame = frame
        self.source_time = source_time
        self.settings = copy.deepcopy(settings)
        self.first_text = first_text
        self.second_text = second_text
        self._scroll_phase = 0.0
        self.update()

    def update_settings(
        self,
        settings: SubtitleRenderSettings,
        first_text: str,
        second_text: str,
    ) -> None:
        self.settings = copy.deepcopy(settings)
        self.first_text = first_text
        self.second_text = second_text
        self._scroll_phase = 0.0
        self.update()

    def _advance_scroll(self) -> None:
        if self.settings.overflow != "scroll":
            return
        self._scroll_phase = (self._scroll_phase + 0.007) % 1.0
        self.update()

    def _aspect_fit(self, source_w: int, source_h: int, target: QRectF) -> QRectF:
        if source_w <= 0 or source_h <= 0:
            return target
        scale = min(target.width() / source_w, target.height() / source_h)
        width = source_w * scale
        height = source_h * scale
        return QRectF(
            target.center().x() - width / 2,
            target.center().y() - height / 2,
            width,
            height,
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("black"))

        if self.frame.isNull():
            painter.setPen(QColor("white"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Preview frame unavailable",
            )
            return

        canvas = self._aspect_fit(
            self.frame.width(),
            self.frame.height(),
            QRectF(self.rect()).adjusted(8, 8, -8, -8),
        )

        tracks = selected_tracks(self.settings)
        preview_texts = [self.first_text]
        if len(tracks) >= 2:
            preview_texts.append(self.second_text)

        source_area_h, _, _, _ = subtitle_layout_metrics(
            self.frame.width(),
            self.frame.height(),
            self.settings.font_size,
            preview_texts,
            self.settings.overflow,
        )
        scale = canvas.height() / self.frame.height()
        area_h = source_area_h * scale

        if self.settings.layout == "below":
            video_rect = QRectF(
                canvas.left(),
                canvas.top(),
                canvas.width(),
                max(1.0, canvas.height() - area_h),
            )
            fitted = self._aspect_fit(
                self.frame.width(), self.frame.height(), video_rect
            )
            painter.drawPixmap(fitted, self.frame, QRectF(self.frame.rect()))
            subtitle_rect = QRectF(
                canvas.left(),
                canvas.bottom() - area_h,
                canvas.width(),
                area_h,
            )
            painter.fillRect(subtitle_rect, QColor("black"))
        else:
            painter.drawPixmap(canvas, self.frame, QRectF(self.frame.rect()))
            subtitle_rect = QRectF(
                canvas.left(),
                canvas.bottom() - area_h,
                canvas.width(),
                area_h,
            )
            painter.fillRect(subtitle_rect, QColor(0, 0, 0, 145))

        font = QFont("Microsoft JhengHei")
        font.setPixelSize(max(10, round(self.settings.font_size * scale)))
        painter.setFont(font)
        painter.setPen(QColor("white"))

        texts = [self.first_text]
        if self.settings.second_track != "none":
            texts.append(self.second_text)

        if len(texts) == 1:
            bands = [subtitle_rect.adjusted(18, 8, -18, -8)]
        else:
            half = subtitle_rect.height() / 2
            bands = [
                QRectF(
                    subtitle_rect.left() + 18,
                    subtitle_rect.top() + 3,
                    subtitle_rect.width() - 36,
                    half - 5,
                ),
                QRectF(
                    subtitle_rect.left() + 18,
                    subtitle_rect.top() + half + 2,
                    subtitle_rect.width() - 36,
                    half - 7,
                ),
            ]

        for text, band in zip(texts, bands):
            self._draw_subtitle(painter, band, text)

    def _draw_subtitle(self, painter: QPainter, rect: QRectF, text: str) -> None:
        text = text.strip() or "(No subtitle text in this track)"

        if self.settings.overflow == "wrap":
            painter.drawText(
                rect,
                int(
                    Qt.AlignmentFlag.AlignCenter
                    | Qt.TextFlag.TextWordWrap
                ),
                text,
            )
            return

        metrics = QFontMetrics(painter.font())
        one_line = text.replace("\n", " ")
        text_width = metrics.horizontalAdvance(one_line)

        if text_width <= rect.width():
            painter.drawText(
                rect,
                int(Qt.AlignmentFlag.AlignCenter),
                one_line,
            )
            return

        painter.save()
        painter.setClipRect(rect)
        travel = text_width + rect.width()
        x = rect.right() - self._scroll_phase * travel
        y = rect.center().y() + (metrics.ascent() - metrics.descent()) / 2
        painter.drawText(round(x), round(y), one_line)
        painter.restore()


class SubtitleStyleDialog(QDialog):
    def __init__(
        self,
        video_path: str,
        chunks: list[Chunk],
        state: SubtitleState,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Video Subtitle Appearance")
        self.resize(1080, 720)

        self.video_path = video_path
        self.chunks = chunks
        self.state = state
        self.settings = copy.deepcopy(state.render_settings)
        self.preview_source_time = 0.0
        self.preview_frame = QPixmap()

        self.first_combo = QComboBox()
        self.first_combo.addItem("Original", "primary")
        self.first_combo.addItem("Translated", "translation")

        self.second_combo = QComboBox()
        self.second_combo.addItem("None", "none")
        self.second_combo.addItem("Original", "primary")
        self.second_combo.addItem("Translated", "translation")

        self.layout_combo = QComboBox()
        self.layout_combo.addItem(
            "Overlay at bottom with semi-transparent banner", "banner"
        )
        self.layout_combo.addItem(
            "Resize video and place subtitles below", "below"
        )

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(16, 72)
        self.font_size_spin.setSuffix(" px")

        self.overflow_combo = QComboBox()
        self.overflow_combo.addItem("Line break (wrap text)", "wrap")
        self.overflow_combo.addItem(
            "Running text (scroll long lines horizontally)", "scroll"
        )

        self._set_combo_data(self.first_combo, self.settings.first_track)
        self._set_combo_data(self.second_combo, self.settings.second_track)
        self._set_combo_data(self.layout_combo, self.settings.layout)
        self._set_combo_data(self.overflow_combo, self.settings.overflow)
        self.font_size_spin.setValue(self.settings.font_size)

        form = QFormLayout()
        form.addRow("First subtitle:", self.first_combo)
        form.addRow("Second subtitle:", self.second_combo)
        form.addRow("Placement:", self.layout_combo)
        form.addRow("Font size:", self.font_size_spin)
        form.addRow("Long text:", self.overflow_combo)

        description = QLabel(
            "The preview uses a random retained source frame. In running-text "
            "mode only lines that are too wide are scrolled; short lines remain "
            "centered. The final MP4 keeps the source output resolution."
        )
        description.setWordWrap(True)

        self.preview = SubtitlePreviewWidget()
        self.frame_label = QLabel("")

        random_button = QPushButton("Another random frame")
        random_button.clicked.connect(self.choose_random_frame)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self._accept_settings)
        buttons.rejected.connect(self.reject)

        left = QVBoxLayout()
        left.addWidget(description)
        left.addLayout(form)
        left.addSpacing(8)
        left.addWidget(random_button)
        left.addWidget(self.frame_label)
        left.addStretch(1)

        body = QHBoxLayout()
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMaximumWidth(350)
        body.addWidget(left_widget)
        body.addWidget(self.preview, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)

        for widget in (
            self.first_combo,
            self.second_combo,
            self.layout_combo,
            self.overflow_combo,
        ):
            widget.currentIndexChanged.connect(self._controls_changed)
        self.font_size_spin.valueChanged.connect(self._controls_changed)

        self.choose_random_frame()

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _read_settings(self) -> SubtitleRenderSettings:
        first = str(self.first_combo.currentData())
        second = str(self.second_combo.currentData())
        if second == first:
            second = "none"
            self._set_combo_data(self.second_combo, "none")

        return SubtitleRenderSettings(
            first_track=first,
            second_track=second,
            layout=str(self.layout_combo.currentData()),
            font_size=int(self.font_size_spin.value()),
            overflow=str(self.overflow_combo.currentData()),
        )

    def _controls_changed(self, *args) -> None:
        self.settings = self._read_settings()
        first, second = self._preview_texts(self.preview_source_time)
        self.preview.update_settings(self.settings, first, second)

    def _accept_settings(self) -> None:
        self.settings = self._read_settings()
        self.accept()

    def _candidate_times(self) -> list[float]:
        cues = selected_track_cues(self.state, self.settings.first_track)
        candidates: list[float] = []

        for chunk in self.chunks:
            for cue in cues:
                start = max(chunk.start, cue.source_start)
                end = min(chunk.end, cue.source_end)
                if end > start:
                    candidates.append((start + end) / 2)

        if candidates:
            return candidates

        return [
            (chunk.start + chunk.end) / 2
            for chunk in self.chunks
            if chunk.end > chunk.start
        ]

    def choose_random_frame(self) -> None:
        candidates = self._candidate_times()
        if not candidates:
            return

        self.preview_source_time = random.choice(candidates)
        pixmap = self._extract_frame(self.preview_source_time)
        if not pixmap.isNull():
            self.preview_frame = pixmap

        first, second = self._preview_texts(self.preview_source_time)
        self.preview.set_content(
            self.preview_frame,
            self.preview_source_time,
            self.settings,
            first,
            second,
        )
        self.frame_label.setText(
            f"Preview source frame: {format_time(self.preview_source_time)}"
        )

    def _track_text(self, track: str, source_time: float) -> str:
        if track == "none":
            return ""
        cues = selected_track_cues(self.state, track)
        for cue in cues:
            if cue.source_start <= source_time <= cue.source_end:
                return cue.text
        for cue in cues:
            if cue.text.strip():
                return cue.text
        return (
            "Original subtitle preview" if track == "primary"
            else "翻譯字幕預覽"
        )

    def _preview_texts(self, source_time: float) -> tuple[str, str]:
        return (
            self._track_text(self.settings.first_track, source_time),
            self._track_text(self.settings.second_track, source_time),
        )

    def _extract_frame(self, source_time: float) -> QPixmap:
        ffmpeg = find_ffmpeg()
        temp = tempfile.NamedTemporaryFile(
            suffix=".png", prefix="subtitle_preview_", delete=False
        )
        temp.close()
        try:
            result = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{source_time:.3f}",
                    "-i",
                    self.video_path,
                    "-frames:v",
                    "1",
                    temp.name,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                return QPixmap()
            return QPixmap(temp.name)
        finally:
            Path(temp.name).unlink(missing_ok=True)
