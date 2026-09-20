from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, QUrl, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QMenu,
    QProgressBar,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from boundary_editor import BoundaryEditor
from chunk_table import ChunkTableWidget
from exporter import ExportWorker
from project import (
    Chunk,
    SpeechRegion,
    build_chunks,
    delete_chunk,
    insert_chunk,
    merge_chunk_with_next,
    merge_chunk_with_previous,
    move_chunk,
)
from project_io import load_project_file, save_project_file
from settings_dialog import ChunkSettingsDialog
from subtitle_manager import SubtitleManagerDialog
from subtitles import SubtitleState
from time_utils import format_time
from vad import VADWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VAD Chunk Editor")
        self.resize(1280, 800)

        self.settings = QSettings("VADChunkEditor", "VADChunkEditor")
        self.minimum_quiet_duration = float(
            self.settings.value("minimum_quiet_duration", 0.70)
        )

        self.video_path: str | None = None
        self.project_path: str | None = None
        self.video_duration: float | None = None
        self.speech_regions: list[SpeechRegion] = []
        self.chunks: list[Chunk] = []
        self.vad_worker: VADWorker | None = None
        self.export_worker: ExportWorker | None = None
        self.subtitle_state = SubtitleState()

        self._playback_mode: str | None = None
        self._preview_first_end_ms = 0
        self._preview_second_start_ms = 0
        self._preview_stop_ms = 0
        self._preview_jump_done = False
        self._frame_seek_generation = 0

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.video_widget = QVideoWidget(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        self.audio_output.setVolume(1.0)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._media_duration_changed)

        self.boundary_list = QListWidget()
        self.boundary_list.currentRowChanged.connect(self._boundary_selected)
        self.boundary_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.boundary_list.customContextMenuRequested.connect(
            self._show_boundary_context_menu
        )

        self.chunk_table = ChunkTableWidget()
        self.chunk_table.move_requested.connect(self._move_chunk)
        self.chunk_table.extent_changed.connect(self._change_chunk_extent)
        self.chunk_table.insert_requested.connect(self._insert_chunk)
        self.chunk_table.delete_requested.connect(self._delete_chunk)
        self.chunk_table.merge_previous_requested.connect(self._merge_with_previous)
        self.chunk_table.merge_next_requested.connect(self._merge_with_next)
        self.chunk_table.validation_message.connect(self._show_table_message)
        self.chunk_table.set_chunks(self.chunks)

        self.boundary_editor = BoundaryEditor()
        self.boundary_editor.chunk_changed.connect(self._on_boundary_trim_changed)
        self.boundary_editor.frame_preview_requested.connect(
            self._show_frame_at
        )
        self.boundary_editor.play_original_requested.connect(
            self._play_original_range
        )
        self.boundary_editor.preview_cut_requested.connect(self._preview_cut)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(QLabel("<b>Chunk transitions</b>"))
        transition_help = QLabel(
            "Keyboard: − previous transition, + next transition"
        )
        transition_help.setWordWrap(True)
        right_layout.addWidget(transition_help)
        right_layout.addWidget(self.boundary_list, 2)

        chunk_title = QLabel("<b>Chunk extents &amp; order</b>")
        chunk_help = QLabel(
            "Edit the Chunk number to move it, or edit Start/End "
            "to change its source extent. Right-click a chunk to "
            "merge or delete it. Use the empty final row to insert "
            "a new chunk."
        )
        chunk_help.setWordWrap(True)
        right_layout.addWidget(chunk_title)
        right_layout.addWidget(chunk_help)
        right_layout.addWidget(self.chunk_table, 3)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(self.video_widget, 3)
        left_layout.addWidget(self.boundary_editor, 2)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(160)
        self.progress.hide()
        self.status.addPermanentWidget(self.progress)

        self._build_toolbar()
        self._update_status()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_action = QAction("Open Video", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_video)
        toolbar.addAction(open_action)

        open_project_action = QAction("Open Project…", self)
        open_project_action.triggered.connect(self.open_project)
        toolbar.addAction(open_project_action)

        self.save_project_action = QAction("Save Project", self)
        self.save_project_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_project_action.triggered.connect(self.save_project)
        self.save_project_action.setEnabled(False)
        toolbar.addAction(self.save_project_action)

        toolbar.addSeparator()

        self.detect_action = QAction("Split Chunks", self)
        self.detect_action.setToolTip(
            "Detect speech and split the video into chunks using quiet gaps."
        )
        self.detect_action.triggered.connect(self.run_vad)
        self.detect_action.setEnabled(False)
        toolbar.addAction(self.detect_action)

        settings_action = QAction("Chunk Settings", self)
        settings_action.triggered.connect(self.open_chunk_settings)
        toolbar.addAction(settings_action)

        self.subtitle_action = QAction("Manage Subtitles…", self)
        self.subtitle_action.triggered.connect(self.manage_subtitles)
        self.subtitle_action.setEnabled(False)
        toolbar.addAction(self.subtitle_action)

        self.export_action = QAction("Export Trimmed Video…", self)
        self.export_action.triggered.connect(self.export_trimmed_video)
        self.export_action.setEnabled(False)
        toolbar.addAction(self.export_action)

        # Keep transition navigation off the toolbar.
        self.previous_boundary_action = QAction(
            "Previous Boundary", self
        )
        self.previous_boundary_action.setShortcut(
            QKeySequence(Qt.Key.Key_Minus)
        )
        self.previous_boundary_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.previous_boundary_action.triggered.connect(
            self.previous_boundary
        )
        self.addAction(self.previous_boundary_action)

        self.next_boundary_action = QAction(
            "Next Boundary", self
        )
        self.next_boundary_action.setShortcut(
            QKeySequence(Qt.Key.Key_Plus)
        )
        self.next_boundary_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.next_boundary_action.triggered.connect(
            self.next_boundary
        )
        self.addAction(self.next_boundary_action)

    def open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Video",
            "",
            "Video files (*.mp4 *.mov *.mkv *.avi *.m4v *.webm);;All files (*.*)",
        )
        if not path:
            return

        self.video_path = path
        self.project_path = None
        self.video_duration = None
        self.speech_regions = []
        self.chunks = []
        self.subtitle_state = SubtitleState()
        self.boundary_list.clear()
        self.chunk_table.clear_draft()
        self.chunk_table.set_max_duration(None)
        self.chunk_table.set_chunks(self.chunks)
        self.boundary_editor.set_media_duration(None)
        self.boundary_editor.set_chunks([])
        self.player.setSource(QUrl.fromLocalFile(path))
        self.detect_action.setEnabled(True)
        self.save_project_action.setEnabled(True)
        self.subtitle_action.setEnabled(False)
        self.export_action.setEnabled(False)
        self.setWindowTitle(f"VAD Chunk Editor — {Path(path).name}")
        self._update_status(
            "Video loaded. Click Split Chunks or enter chunks manually."
        )

    def _media_duration_changed(self, duration_ms: int) -> None:
        self.video_duration = duration_ms / 1000.0 if duration_ms > 0 else None
        self.chunk_table.set_max_duration(self.video_duration)
        self.boundary_editor.set_media_duration(self.video_duration)

    def run_vad(self) -> None:
        if not self.video_path:
            return
        if self.vad_worker and self.vad_worker.isRunning():
            return

        self.detect_action.setEnabled(False)
        self.progress.show()

        self.vad_worker = VADWorker(self.video_path, self)
        self.vad_worker.progress_text.connect(self._update_status)
        self.vad_worker.finished_regions.connect(self._vad_finished)
        self.vad_worker.failed.connect(self._vad_failed)
        self.vad_worker.finished.connect(self._vad_thread_finished)
        self.vad_worker.start()

    def _vad_finished(self, regions: object) -> None:
        self.speech_regions = list(regions)
        self._rebuild_chunks()

        if not self.speech_regions:
            QMessageBox.information(
                self,
                "No speech detected",
                "Silero VAD did not detect any speech in this video.",
            )

    def _vad_failed(self, message: str) -> None:
        QMessageBox.critical(
            self,
            "VAD failed",
            "The speech-detection step could not be completed.\n\n" + message,
        )
        self._update_status("VAD failed.")

    def _vad_thread_finished(self) -> None:
        self.progress.hide()
        self.detect_action.setEnabled(bool(self.video_path))

    def _rebuild_chunks(self) -> None:
        self.chunks = build_chunks(
            self.speech_regions,
            self.minimum_quiet_duration,
        )
        self.chunk_table.clear_draft()
        self._refresh_all(select_chunk=0 if self.chunks else None)
        self._update_status()

    def _refresh_all(
        self,
        select_chunk: int | None = None,
        preserve_transition: bool = False,
    ) -> None:
        previous_transition = self.boundary_list.currentRow()

        self.boundary_editor.set_chunks(self.chunks)
        self._refresh_boundary_list()
        self.chunk_table.set_chunks(self.chunks)

        if select_chunk is not None and self.chunks:
            select_chunk = max(0, min(select_chunk, len(self.chunks) - 1))
            self.chunk_table.selectRow(select_chunk)
            if len(self.chunks) >= 2:
                transition = max(0, min(select_chunk - 1, len(self.chunks) - 2))
                self.boundary_list.setCurrentRow(transition)
        elif preserve_transition and self.boundary_list.count():
            transition = max(
                0,
                min(previous_transition, self.boundary_list.count() - 1),
            )
            self.boundary_list.setCurrentRow(transition)
        elif self.boundary_list.count():
            self.boundary_list.setCurrentRow(0)
        else:
            self.boundary_editor.clear_selection()

        has_edit = bool(self.video_path and self.chunks)
        self.export_action.setEnabled(has_edit)
        self.subtitle_action.setEnabled(has_edit)
        self.save_project_action.setEnabled(bool(self.video_path))

    def _refresh_boundary_list(self) -> None:
        current = self.boundary_list.currentRow()
        self.boundary_list.blockSignals(True)
        self.boundary_list.clear()

        for index in range(max(0, len(self.chunks) - 1)):
            left = self.chunks[index]
            right = self.chunks[index + 1]
            delta = right.start - left.end
            if delta >= 0:
                detail = f"gap {delta:.2f} s"
            else:
                detail = f"jump back {abs(delta):.2f} s"

            self.boundary_list.addItem(
                QListWidgetItem(
                    f"{index + 1:03d}   "
                    f"{format_time(left.end)} → {format_time(right.start)}   "
                    f"({detail})"
                )
            )

        self.boundary_list.blockSignals(False)

        if self.boundary_list.count() and current >= 0:
            self.boundary_list.setCurrentRow(
                min(current, self.boundary_list.count() - 1)
            )

    def _on_boundary_trim_changed(self) -> None:
        # Keep the active trim controls untouched while a slider is dragged.
        # Only refresh the structural views that mirror the changed times.
        current_transition = self.boundary_list.currentRow()
        self._refresh_boundary_list()
        self.chunk_table.set_chunks(self.chunks)
        if 0 <= current_transition < self.boundary_list.count():
            self.boundary_list.setCurrentRow(current_transition)
        has_edit = bool(self.video_path and self.chunks)
        self.export_action.setEnabled(has_edit)
        self.subtitle_action.setEnabled(has_edit)
        self.save_project_action.setEnabled(bool(self.video_path))

    def _boundary_selected(self, row: int) -> None:
        if row < 0 or row >= len(self.chunks) - 1:
            self.boundary_editor.clear_selection()
            return

        self.boundary_editor.select_boundary(row)

        left = self.chunks[row]
        seek = max(left.start, left.end - 2.0)
        self.player.setPosition(round(seek * 1000))
        self.player.pause()

    def _show_boundary_context_menu(self, position) -> None:
        item = self.boundary_list.itemAt(position)
        if item is None:
            return

        row = self.boundary_list.row(item)
        if row < 0 or row >= len(self.chunks) - 1:
            return

        left = self.chunks[row]
        right = self.chunks[row + 1]
        can_reset = left.vad_end is not None and right.vad_start is not None

        menu = QMenu(self)

        if can_reset:
            action = QAction(
                "Reset this transition to original VAD boundary "
                f"({format_time(left.vad_end)} → {format_time(right.vad_start)})",
                self,
            )
            action.triggered.connect(
                lambda checked=False, r=row: self._reset_transition_to_vad(r)
            )
        else:
            action = QAction(
                "Reset this transition to original VAD boundary "
                "(not available for manually created/merged chunks)",
                self,
            )
            action.setEnabled(False)

        menu.addAction(action)
        menu.exec(self.boundary_list.viewport().mapToGlobal(position))

    def _reset_transition_to_vad(self, row: int) -> None:
        if row < 0 or row >= len(self.chunks) - 1:
            return

        left = self.chunks[row]
        right = self.chunks[row + 1]

        if left.vad_end is None or right.vad_start is None:
            self._update_status(
                "This transition has no complete original VAD boundary to restore."
            )
            return

        left.end = left.vad_end
        right.start = right.vad_start

        self._refresh_all(preserve_transition=True)
        self.boundary_list.setCurrentRow(row)
        self.boundary_editor.select_boundary(row)
        self._show_frame_at(left.end)

        self._update_status(
            f"Reset transition {row + 1} to the original VAD boundary: "
            f"{format_time(left.end)} → {format_time(right.start)}."
        )

    def _show_table_message(self, message: str) -> None:
        self._update_status(message)

    def _move_chunk(self, source_index: int, target_index: int) -> None:
        try:
            new_index = move_chunk(self.chunks, source_index, target_index)
        except (IndexError, ValueError) as exc:
            self._show_table_message(str(exc))
            self.chunk_table.set_chunks(self.chunks)
            return

        self._refresh_all(select_chunk=new_index)
        self._update_status(
            f"Moved Chunk {source_index + 1} to output position {new_index + 1}."
        )

    def _change_chunk_extent(self, row: int, start: float, end: float) -> None:
        if not 0 <= row < len(self.chunks):
            return
        self.chunks[row].start = start
        self.chunks[row].end = end
        self._refresh_all(select_chunk=row)
        self._update_status(
            f"Updated Chunk {row + 1}: {format_time(start)} → {format_time(end)}."
        )

    def _insert_chunk(self, target_index: int, start: float, end: float) -> None:
        try:
            new_index = insert_chunk(
                self.chunks,
                target_index,
                start,
                end,
            )
        except (IndexError, ValueError) as exc:
            self._show_table_message(str(exc))
            return

        self._refresh_all(select_chunk=new_index)
        self._update_status(
            f"Inserted new Chunk {new_index + 1}: "
            f"{format_time(start)} → {format_time(end)}."
        )

    def _delete_chunk(self, row: int) -> None:
        if not 0 <= row < len(self.chunks):
            return

        answer = QMessageBox.question(
            self,
            "Delete chunk",
            f"Delete Chunk {row + 1} from the output sequence?\n\n"
            "The source video is not modified.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        delete_chunk(self.chunks, row)
        next_row = min(row, len(self.chunks) - 1) if self.chunks else None
        self._refresh_all(select_chunk=next_row)
        self._update_status(f"Deleted Chunk {row + 1} from the output sequence.")

    def _merge_with_previous(self, chunk_index: int) -> None:
        if chunk_index <= 0 or chunk_index >= len(self.chunks):
            return

        try:
            merged_index = merge_chunk_with_previous(self.chunks, chunk_index)
        except IndexError as exc:
            self._show_table_message(str(exc))
            return

        self._refresh_all(select_chunk=merged_index)
        self._update_status(
            f"Merged Chunk {chunk_index + 1} with the previous chunk."
        )

    def _merge_with_next(self, chunk_index: int) -> None:
        if chunk_index < 0 or chunk_index >= len(self.chunks) - 1:
            return

        try:
            merged_index = merge_chunk_with_next(self.chunks, chunk_index)
        except IndexError as exc:
            self._show_table_message(str(exc))
            return

        self._refresh_all(select_chunk=merged_index)
        self._update_status(
            f"Merged Chunk {chunk_index + 1} with the next chunk."
        )

    def save_project(self) -> None:
        if not self.video_path:
            QMessageBox.information(
                self,
                "Nothing to save",
                "Open a raw video before saving a project.",
            )
            return

        path = self.project_path
        if not path:
            source = Path(self.video_path)
            default = source.with_name(source.stem + ".vceproj")
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Editing Project",
                str(default),
                "VAD Chunk Editor Project (*.vceproj)",
            )
            if not path:
                return
            if not path.lower().endswith(".vceproj"):
                path += ".vceproj"

        try:
            save_project_file(
                path,
                self.video_path,
                self.minimum_quiet_duration,
                self.speech_regions,
                self.chunks,
                self.subtitle_state,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Could not save project",
                str(exc),
            )
            return

        self.project_path = path
        self._update_status(f"Project saved: {path}")

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Editing Project",
            "",
            "VAD Chunk Editor Project (*.vceproj);;All files (*.*)",
        )
        if not path:
            return

        try:
            data = load_project_file(path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Could not open project",
                str(exc),
            )
            return

        video_path = data["video_path"]
        if not video_path:
            saved = data.get("saved_video_path") or "(unknown path)"
            answer = QMessageBox.information(
                self,
                "Raw video not found",
                "The raw video saved in this project could not be found:\n\n"
                f"{saved}\n\nPlease locate the same raw video.",
            )
            locate, _ = QFileDialog.getOpenFileName(
                self,
                "Locate Raw Video",
                "",
                "Video files (*.mp4 *.mov *.mkv *.avi *.m4v *.webm);;"
                "All files (*.*)",
            )
            if not locate:
                return
            video_path = locate

        self.project_path = path
        self.video_path = video_path
        self.video_duration = None
        self.minimum_quiet_duration = data["minimum_quiet_duration"]
        self.speech_regions = data["speech_regions"]
        self.chunks = data["chunks"]
        self.subtitle_state = data["subtitles"]

        self.settings.setValue(
            "minimum_quiet_duration",
            self.minimum_quiet_duration,
        )

        self.chunk_table.clear_draft()
        self.chunk_table.set_max_duration(None)
        self.boundary_editor.set_media_duration(None)
        self.player.setSource(QUrl.fromLocalFile(self.video_path))

        self.detect_action.setEnabled(True)
        self.save_project_action.setEnabled(True)
        self._refresh_all(select_chunk=0 if self.chunks else None)

        self.setWindowTitle(
            f"VAD Chunk Editor — {Path(path).name}"
        )
        self._update_status(
            f"Loaded project with {len(self.chunks)} chunks and "
            f"{len(self.subtitle_state.primary_cues)} primary subtitle cues."
        )

    def manage_subtitles(self) -> None:
        if not self.video_path or not self.chunks:
            QMessageBox.information(
                self,
                "No edited timeline",
                "Open a video and create at least one chunk before "
                "managing subtitles.",
            )
            return

        dialog = SubtitleManagerDialog(
            self.video_path,
            self.chunks,
            self.subtitle_state,
            self,
        )
        dialog.state_changed.connect(
            lambda: self.save_project_action.setEnabled(True)
        )
        dialog.exec()

    def open_chunk_settings(self) -> None:
        def count_boundaries(threshold: float) -> int:
            if not self.speech_regions:
                return 0
            return max(0, len(build_chunks(self.speech_regions, threshold)) - 1)

        dialog = ChunkSettingsDialog(
            self.minimum_quiet_duration,
            boundary_counter=count_boundaries,
            parent=self,
        )

        if dialog.exec():
            self.minimum_quiet_duration = dialog.threshold
            self.settings.setValue(
                "minimum_quiet_duration",
                self.minimum_quiet_duration,
            )
            if self.speech_regions:
                self._rebuild_chunks()
            else:
                self._update_status()

    def export_trimmed_video(self) -> None:
        if not self.video_path or not self.chunks:
            QMessageBox.information(
                self,
                "Nothing to export",
                "Open a video and create at least one chunk before exporting.",
            )
            return

        source = Path(self.video_path)
        default_output = source.with_name(source.stem + "_trimmed.mp4")
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Trimmed Video",
            str(default_output),
            "MP4 Video (*.mp4)",
        )
        if not output_path:
            return

        output = Path(output_path)
        if output.suffix.lower() != ".mp4":
            output = output.with_suffix(".mp4")

        try:
            if output.resolve() == source.resolve():
                QMessageBox.warning(
                    self,
                    "Choose another filename",
                    "The exported file cannot overwrite the source video.",
                )
                return
        except OSError:
            pass

        if self.export_worker and self.export_worker.isRunning():
            return

        self.player.pause()
        self.export_action.setEnabled(False)
        self.detect_action.setEnabled(False)
        self.progress.show()

        self.export_worker = ExportWorker(
            self.video_path,
            str(output),
            self.chunks,
            self.subtitle_state,
            self,
        )
        self.export_worker.progress_text.connect(self._update_status)
        self.export_worker.completed.connect(self._export_completed)
        self.export_worker.failed.connect(self._export_failed)
        self.export_worker.finished.connect(self._export_thread_finished)
        self.export_worker.start()

    def _export_completed(self, output_path: str) -> None:
        total = sum(chunk.duration for chunk in self.chunks)
        self._update_status(f"Export complete: {output_path}")

        output = Path(output_path)
        matching_srts = []

        direct = output.with_suffix(".srt")
        if direct.exists():
            matching_srts.append(direct)

        for candidate in output.parent.glob(output.stem + ".*.srt"):
            if candidate not in matching_srts:
                matching_srts.append(candidate)

        message = (
            f"Saved the trimmed video to:\n\n{output_path}\n\n"
            f"Output timeline length: approximately {total:.1f} s"
        )

        if matching_srts:
            names = "\n".join(f"• {path.name}" for path in matching_srts)
            message += (
                "\n\nNote: matching external SRT file(s) were found:\n"
                f"{names}\n\n"
                "Players such as VLC may automatically load these in addition "
                "to the subtitles already burned into the video, making a "
                "subtitle appear twice. Disable the external subtitle track "
                "in the player, or rename/move those SRT files."
            )

        QMessageBox.information(
            self,
            "Export complete",
            message,
        )

    def _export_failed(self, message: str) -> None:
        QMessageBox.critical(
            self,
            "Export failed",
            "FFmpeg could not render the trimmed video.\n\n" + message,
        )
        self._update_status("Export failed.")

    def _export_thread_finished(self) -> None:
        self.progress.hide()
        self.detect_action.setEnabled(bool(self.video_path))
        has_edit = bool(self.video_path and self.chunks)
        self.export_action.setEnabled(has_edit)
        self.subtitle_action.setEnabled(has_edit)
        self.save_project_action.setEnabled(bool(self.video_path))

    def previous_boundary(self) -> None:
        if not self.boundary_list.count():
            return
        self.boundary_list.setCurrentRow(
            max(0, self.boundary_list.currentRow() - 1)
        )

    def next_boundary(self) -> None:
        if not self.boundary_list.count():
            return
        self.boundary_list.setCurrentRow(
            min(
                self.boundary_list.count() - 1,
                self.boundary_list.currentRow() + 1,
            )
        )

    def _show_frame_at(self, seconds: float) -> None:
        """Pause playback and display the frame at an edited trim position."""
        if not self.video_path:
            return

        target_ms = max(0, round(seconds * 1000))
        if self.video_duration is not None:
            target_ms = min(target_ms, round(self.video_duration * 1000))

        self._playback_mode = None
        self._frame_seek_generation += 1
        generation = self._frame_seek_generation

        self.player.pause()
        self.player.setPosition(target_ms)

        # Some Windows multimedia backends update the position immediately but
        # deliver the paused video frame a little later. Repeating the seek
        # after the event loop turns makes both trim sliders refresh reliably.
        QTimer.singleShot(
            25,
            lambda g=generation, t=target_ms: self._settle_frame_seek(g, t),
        )

    def _settle_frame_seek(self, generation: int, target_ms: int) -> None:
        if generation != self._frame_seek_generation:
            return
        if self._playback_mode is not None:
            return

        self.player.pause()
        self.player.setPosition(target_ms)

    def _play_original_range(self, start: float, end: float) -> None:
        self._playback_mode = "range"
        self._preview_stop_ms = round(end * 1000)
        self.player.setPosition(round(start * 1000))
        self.player.play()

    def _preview_cut(
        self,
        first_start: float,
        first_end: float,
        second_start: float,
        second_end: float,
    ) -> None:
        self._playback_mode = "cut"
        self._preview_first_end_ms = round(first_end * 1000)
        self._preview_second_start_ms = round(second_start * 1000)
        self._preview_stop_ms = round(second_end * 1000)
        self._preview_jump_done = False
        self.player.setPosition(round(first_start * 1000))
        self.player.play()

    def _position_changed(self, position_ms: int) -> None:
        if self._playback_mode == "range":
            if position_ms >= self._preview_stop_ms:
                self.player.pause()
                self._playback_mode = None

        elif self._playback_mode == "cut":
            if (
                not self._preview_jump_done
                and position_ms >= self._preview_first_end_ms
            ):
                self._preview_jump_done = True
                self.player.setPosition(self._preview_second_start_ms)
            elif self._preview_jump_done and position_ms >= self._preview_stop_ms:
                self.player.pause()
                self._playback_mode = None

    def _update_status(self, message: str | None = None) -> None:
        if message:
            self.status.showMessage(message)
            return

        filename = Path(self.video_path).name if self.video_path else "No video"
        transitions = max(0, len(self.chunks) - 1)
        self.status.showMessage(
            f"{filename}   |   {len(self.chunks)} chunks   |   "
            f"{transitions} transitions   |   "
            f"quiet threshold {self.minimum_quiet_duration:.2f} s"
        )

    def closeEvent(self, event) -> None:
        if self.vad_worker and self.vad_worker.isRunning():
            self.vad_worker.requestInterruption()
            self.vad_worker.wait(1000)
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.requestInterruption()
            self.export_worker.wait(1000)
        super().closeEvent(event)
