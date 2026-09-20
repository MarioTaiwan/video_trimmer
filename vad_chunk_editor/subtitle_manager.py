from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QProgressBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from project import Chunk
from subtitle_style_dialog import SubtitleStyleDialog
from subtitles import (
    OutputSubtitleCue,
    SubtitleCue,
    SubtitleState,
    language_name,
    map_output_cues_to_source,
    map_source_cues_to_output,
    parse_srt,
    render_srt,
)
from time_utils import format_time


class TranscriptionWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    status = Signal(str)

    def __init__(
        self,
        video_path: str,
        language: str,
        model_size: str = "small",
        parent=None,
    ):
        super().__init__(parent)
        self.video_path = video_path
        self.language = language
        self.model_size = model_size

    def run(self) -> None:
        try:
            self.status.emit(
                "Loading Whisper model… First use may download the model."
            )

            from faster_whisper import WhisperModel

            # CPU/int8 is deliberately the compatibility-first default for
            # Windows. GPU support can be added later as an advanced option.
            model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8",
            )

            self.status.emit(
                f"Transcribing raw video in {language_name(self.language)}…"
            )

            segments, _ = model.transcribe(
                self.video_path,
                language=self.language,
                beam_size=5,
                vad_filter=True,
            )

            cues: list[SubtitleCue] = []
            for segment in segments:
                if self.isInterruptionRequested():
                    return

                text = str(segment.text).strip()
                start = float(segment.start)
                end = float(segment.end)

                if text and end > start:
                    cues.append(SubtitleCue(start, end, text))

            self.completed.emit(cues)

        except Exception as exc:
            self.failed.emit(str(exc))


class PasteTextDialog(QDialog):
    def __init__(self, title: str, explanation: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 520)

        label = QLabel(explanation)
        label.setWordWrap(True)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "Paste SRT content here, or paste one translated line per "
            "current subtitle when using the translation track."
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.editor, 1)
        layout.addWidget(buttons)

    @property
    def text(self) -> str:
        return self.editor.toPlainText()


class SubtitleTrackWidget(QWidget):
    text_edited = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Chunk", "Final Start", "Final End", "Text"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.table.verticalHeader().setVisible(False)

        self._mapped: list[OutputSubtitleCue] = []
        self._updating = False
        self.table.cellChanged.connect(self._cell_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)

    def set_mapped_cues(self, mapped: list[OutputSubtitleCue]) -> None:
        self._mapped = mapped
        self._updating = True

        try:
            self.table.setRowCount(len(mapped))

            for row, cue in enumerate(mapped):
                values = [
                    str(cue.chunk_index + 1),
                    format_time(cue.start),
                    format_time(cue.end),
                    cue.text,
                ]

                for col, value in enumerate(values):
                    item = self.table.item(row, col)
                    if item is None:
                        item = QTableWidgetItem()
                        self.table.setItem(row, col, item)

                    item.setText(value)

                    if col == 3:
                        item.setFlags(
                            Qt.ItemFlag.ItemIsSelectable
                            | Qt.ItemFlag.ItemIsEnabled
                            | Qt.ItemFlag.ItemIsEditable
                        )
                    else:
                        item.setFlags(
                            Qt.ItemFlag.ItemIsSelectable
                            | Qt.ItemFlag.ItemIsEnabled
                        )
        finally:
            self._updating = False

    def _cell_changed(self, row: int, col: int) -> None:
        if self._updating or col != 3:
            return
        if not 0 <= row < len(self._mapped):
            return

        item = self.table.item(row, col)
        self.text_edited.emit(
            self._mapped[row].source_index,
            item.text() if item else "",
        )


class SubtitleManagerDialog(QDialog):
    state_changed = Signal()

    def __init__(
        self,
        video_path: str,
        chunks: list[Chunk],
        state: SubtitleState,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Manage Subtitles")
        self.resize(1080, 760)

        self.video_path = video_path
        self.chunks = chunks
        self.state = state
        self.worker: TranscriptionWorker | None = None

        explanation = QLabel(
            "<b>Subtitle timing follows the source video internally.</b> "
            "When chunks are moved or trimmed, exported SRT timing is "
            "recalculated automatically for the final edited timeline."
        )
        explanation.setWordWrap(True)

        self.primary_language_combo = QComboBox()
        self.primary_language_combo.addItem("English", "en")
        self.primary_language_combo.addItem("Chinese", "zh")
        self._set_combo_code(
            self.primary_language_combo,
            self.state.primary_language,
        )

        self.translation_language_combo = QComboBox()
        self.translation_language_combo.addItem("Chinese", "zh")
        self.translation_language_combo.addItem("English", "en")
        self._set_combo_code(
            self.translation_language_combo,
            self.state.translation_language,
        )

        top_controls = QHBoxLayout()
        top_controls.addWidget(QLabel("Detection language:"))
        top_controls.addWidget(self.primary_language_combo)
        top_controls.addSpacing(18)
        top_controls.addWidget(QLabel("Translation language:"))
        top_controls.addWidget(self.translation_language_combo)
        top_controls.addStretch(1)

        self.generate_button = QPushButton("Generate Draft Subtitles")
        self.generate_button.setToolTip(
            "Transcribe the raw source video with faster-whisper. "
            "Only subtitles that overlap retained chunks are shown/exported."
        )
        self.generate_button.clicked.connect(self.generate_draft)

        self.status_label = QLabel("Ready.")
        self.status_label.setWordWrap(True)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()

        generation_row = QHBoxLayout()
        generation_row.addWidget(self.generate_button)
        generation_row.addWidget(self.status_label, 1)
        generation_row.addWidget(self.progress)

        self.appearance_button = QPushButton("Video Subtitle Appearance…")
        self.appearance_button.clicked.connect(self.open_video_appearance)

        self.tabs = QTabWidget()

        # Primary track
        primary_page = QWidget()
        primary_layout = QVBoxLayout(primary_page)

        primary_actions = QHBoxLayout()
        import_primary = QPushButton("Import / Replace Original SRT…")
        paste_primary = QPushButton("Paste Original SRT / Text…")
        copy_primary = QPushButton("Copy Original Text")
        export_primary = QPushButton("Export Original SRT…")

        import_primary.clicked.connect(
            lambda: self.import_srt_file("primary")
        )
        paste_primary.clicked.connect(
            lambda: self.paste_text("primary")
        )
        copy_primary.clicked.connect(self.copy_primary_text)
        export_primary.clicked.connect(
            lambda: self.export_track("primary")
        )

        for button in (
            import_primary,
            paste_primary,
            copy_primary,
            export_primary,
        ):
            primary_actions.addWidget(button)
        primary_actions.addStretch(1)

        self.primary_table = SubtitleTrackWidget()
        self.primary_table.text_edited.connect(
            self._edit_primary_text
        )

        primary_layout.addLayout(primary_actions)
        primary_layout.addWidget(self.primary_table, 1)

        # Translation track
        translation_page = QWidget()
        translation_layout = QVBoxLayout(translation_page)

        translation_help = QLabel(
            "You can import a translated SRT, or paste plain translated "
            "lines. Plain lines are matched to the currently retained "
            "primary subtitles in order."
        )
        translation_help.setWordWrap(True)

        translation_actions = QHBoxLayout()
        import_translation = QPushButton("Import / Replace Translation SRT…")
        paste_translation = QPushButton("Paste Translation SRT / Text…")
        export_translation = QPushButton("Export Translation SRT…")

        import_translation.clicked.connect(
            lambda: self.import_srt_file("translation")
        )
        paste_translation.clicked.connect(
            lambda: self.paste_text("translation")
        )
        export_translation.clicked.connect(
            lambda: self.export_track("translation")
        )

        for button in (
            import_translation,
            paste_translation,
            export_translation,
        ):
            translation_actions.addWidget(button)
        translation_actions.addStretch(1)

        self.translation_table = SubtitleTrackWidget()
        self.translation_table.text_edited.connect(
            self._edit_translation_text
        )

        translation_layout.addWidget(translation_help)
        translation_layout.addLayout(translation_actions)
        translation_layout.addWidget(self.translation_table, 1)

        self.tabs.addTab(primary_page, "Original")
        self.tabs.addTab(translation_page, "Translation")

        close_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close
        )
        close_buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(explanation)
        layout.addLayout(top_controls)
        layout.addLayout(generation_row)
        layout.addWidget(self.appearance_button)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(close_buttons)

        self.primary_language_combo.currentIndexChanged.connect(
            self._languages_changed
        )
        self.translation_language_combo.currentIndexChanged.connect(
            self._languages_changed
        )

        self.refresh_tables()

    def open_video_appearance(self) -> None:
        dialog = SubtitleStyleDialog(
            self.video_path,
            self.chunks,
            self.state,
            self,
        )
        if dialog.exec():
            self.state.render_settings = dialog.settings
            self.state_changed.emit()
            first = (
                "Original"
                if dialog.settings.first_track == "primary"
                else "Translated"
            )
            second = {
                "none": "None",
                "primary": "Original",
                "translation": "Translated",
            }[dialog.settings.second_track]
            placement = (
                "banner overlay"
                if dialog.settings.layout == "banner"
                else "subtitles below video"
            )
            self.status_label.setText(
                f"Video subtitle style: {first} / {second}, "
                f"{placement}, {dialog.settings.font_size}px."
            )

    def _set_combo_code(self, combo: QComboBox, code: str) -> None:
        index = combo.findData(code)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _languages_changed(self) -> None:
        self.state.primary_language = str(
            self.primary_language_combo.currentData()
        )
        self.state.translation_language = str(
            self.translation_language_combo.currentData()
        )
        self.state_changed.emit()

    def refresh_tables(self) -> None:
        self.primary_table.set_mapped_cues(
            map_source_cues_to_output(
                self.state.primary_cues,
                self.chunks,
            )
        )
        self.translation_table.set_mapped_cues(
            map_source_cues_to_output(
                self.state.translation_cues,
                self.chunks,
            )
        )

        self.tabs.setTabText(
            0,
            f"Original ({len(self.primary_table._mapped)})",
        )
        self.tabs.setTabText(
            1,
            f"Translation ({len(self.translation_table._mapped)})",
        )

    def generate_draft(self) -> None:
        if self.worker and self.worker.isRunning():
            return

        language = str(self.primary_language_combo.currentData())
        self.state.primary_language = language

        answer = QMessageBox.question(
            self,
            "Replace original subtitles?",
            "Generating a new draft will replace the current original "
            "subtitle track. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.generate_button.setEnabled(False)
        self.progress.show()
        self.status_label.setText("Starting transcription…")

        self.worker = TranscriptionWorker(
            self.video_path,
            language,
            parent=self,
        )
        self.worker.status.connect(self.status_label.setText)
        self.worker.completed.connect(self._draft_completed)
        self.worker.failed.connect(self._draft_failed)
        self.worker.finished.connect(self._draft_finished)
        self.worker.start()

    def _draft_completed(self, cues: object) -> None:
        self.state.primary_cues = list(cues)
        self.refresh_tables()
        self.state_changed.emit()

        kept = len(self.primary_table._mapped)
        self.status_label.setText(
            f"Draft complete. {len(self.state.primary_cues)} source cues "
            f"were found; {kept} currently overlap retained chunks."
        )

    def _draft_failed(self, message: str) -> None:
        QMessageBox.critical(
            self,
            "Subtitle transcription failed",
            "Whisper could not create the draft subtitles.\n\n" + message,
        )
        self.status_label.setText("Transcription failed.")

    def _draft_finished(self) -> None:
        self.progress.hide()
        self.generate_button.setEnabled(True)

    def _edit_primary_text(self, source_index: int, text: str) -> None:
        if 0 <= source_index < len(self.state.primary_cues):
            self.state.primary_cues[source_index].text = text
            self.state_changed.emit()

    def _edit_translation_text(self, source_index: int, text: str) -> None:
        if 0 <= source_index < len(self.state.translation_cues):
            self.state.translation_cues[source_index].text = text
            self.state_changed.emit()

    def import_srt_file(self, track: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import SRT",
            "",
            "SubRip subtitles (*.srt);;Text files (*.txt);;All files (*.*)",
        )
        if not path:
            return

        try:
            text = Path(path).read_text(encoding="utf-8-sig")
            self._replace_track_from_srt(track, text)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Could not import subtitles",
                str(exc),
            )

    def paste_text(self, track: str) -> None:
        dialog = PasteTextDialog(
            "Paste subtitles",
            "Paste a complete SRT file, or paste plain text. For the "
            "translation track, one plain-text line can be supplied for "
            "each currently retained primary subtitle.",
            self,
        )

        if not dialog.exec():
            return

        raw = dialog.text.strip()
        if not raw:
            return

        try:
            if "-->" in raw:
                self._replace_track_from_srt(track, raw)
            else:
                self._apply_plain_lines(track, raw)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Could not apply pasted subtitles",
                str(exc),
            )

    def _replace_track_from_srt(self, track: str, text: str) -> None:
        parsed = parse_srt(text)
        if not parsed:
            raise ValueError("No subtitle cues were found in the SRT.")

        source_cues = map_output_cues_to_source(parsed, self.chunks)
        if not source_cues:
            raise ValueError(
                "The SRT does not overlap the current final video timeline."
            )

        if track == "primary":
            self.state.primary_cues = source_cues
        else:
            self.state.translation_cues = source_cues

        self.refresh_tables()
        self.state_changed.emit()

        self.status_label.setText(
            f"Imported {len(source_cues)} {track} subtitle cues."
        )

    def _apply_plain_lines(self, track: str, text: str) -> None:
        lines = [
            line.strip()
            for line in text.replace("\r\n", "\n").split("\n")
            if line.strip()
        ]
        if not lines:
            raise ValueError("No text lines were pasted.")

        if track == "translation":
            primary_mapped = map_source_cues_to_output(
                self.state.primary_cues,
                self.chunks,
            )
            if not primary_mapped:
                raise ValueError(
                    "Create or import the original subtitles first."
                )
            if len(lines) != len(primary_mapped):
                raise ValueError(
                    f"Expected {len(primary_mapped)} translated lines, "
                    f"but received {len(lines)}."
                )

            self.state.translation_cues = [
                SubtitleCue(
                    source_start=cue.source_start,
                    source_end=cue.source_end,
                    text=line,
                )
                for cue, line in zip(primary_mapped, lines)
            ]
        else:
            primary_mapped = map_source_cues_to_output(
                self.state.primary_cues,
                self.chunks,
            )
            if len(lines) != len(primary_mapped):
                raise ValueError(
                    "Plain primary text can only replace existing cues. "
                    f"Expected {len(primary_mapped)} lines, "
                    f"but received {len(lines)}. Import an SRT if timing "
                    "also needs to be replaced."
                )

            for mapped, line in zip(primary_mapped, lines):
                self.state.primary_cues[mapped.source_index].text = line

        self.refresh_tables()
        self.state_changed.emit()
        self.status_label.setText(
            f"Applied {len(lines)} pasted {track} lines."
        )

    def copy_primary_text(self) -> None:
        mapped = map_source_cues_to_output(
            self.state.primary_cues,
            self.chunks,
        )
        if not mapped:
            QMessageBox.information(
                self,
                "No original subtitles",
                "There are no retained original subtitles to copy.",
            )
            return

        QGuiApplication.clipboard().setText(
            "\n".join(cue.text.replace("\n", " ").strip() for cue in mapped)
        )
        self.status_label.setText(
            f"Copied {len(mapped)} primary subtitle lines."
        )

    def export_track(self, track: str) -> None:
        cues = (
            self.state.primary_cues
            if track == "primary"
            else self.state.translation_cues
        )
        mapped = map_source_cues_to_output(cues, self.chunks)

        if not mapped:
            QMessageBox.information(
                self,
                "No subtitles to export",
                f"The {track} subtitle track is empty for the current chunks.",
            )
            return

        language = (
            self.state.primary_language
            if track == "primary"
            else self.state.translation_language
        )

        source = Path(self.video_path)
        # Do not use the same basename as the default burned-in MP4
        # (source_trimmed.mp4). VLC and other players often auto-load
        # source_trimmed.zh.srt / source_trimmed.en.srt, which would display
        # the same subtitle a second time over the already burned-in text.
        default = source.with_name(
            source.stem + f"_subtitles_{language}.srt"
        )

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export SRT",
            str(default),
            "SubRip subtitles (*.srt)",
        )
        if not path:
            return

        output = Path(path)
        if output.suffix.lower() != ".srt":
            output = output.with_suffix(".srt")

        output.write_text(
            render_srt(mapped),
            encoding="utf-8-sig",
        )
        self.status_label.setText(
            f"Exported {len(mapped)} cues to {output.name}."
        )

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            answer = QMessageBox.question(
                self,
                "Transcription is running",
                "Subtitle transcription is still running. Stop it and close?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

            self.worker.requestInterruption()
            self.worker.wait(1500)

        super().closeEvent(event)
