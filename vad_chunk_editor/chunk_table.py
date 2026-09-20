from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
)

from project import Chunk
from time_utils import format_time, parse_time


class ChunkTableWidget(QTableWidget):
    move_requested = Signal(int, int)
    extent_changed = Signal(int, float, float)
    insert_requested = Signal(int, float, float)
    delete_requested = Signal(int)
    merge_previous_requested = Signal(int)
    merge_next_requested = Signal(int)
    validation_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(0, 4, parent)

        self.setHorizontalHeaderLabels(["Chunk", "Start", "End", "Duration"])
        self.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.verticalHeader().setVisible(False)

        self.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )

        self._chunks: list[Chunk] = []
        self._updating = False
        self._max_duration: float | None = None
        self._draft = ["", "", ""]

        self.cellChanged.connect(self._cell_changed)
        self.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.customContextMenuRequested.connect(
            self._show_context_menu
        )

    def set_max_duration(self, seconds: float | None) -> None:
        self._max_duration = (
            seconds if seconds and seconds > 0 else None
        )

    def clear_draft(self) -> None:
        self._draft = ["", "", ""]

    def set_chunks(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks
        selected = self.currentRow()

        self._updating = True
        try:
            # Existing chunks plus one always-empty insertion row.
            self.setRowCount(len(chunks) + 1)

            for row, chunk in enumerate(chunks):
                self._set_editable_item(
                    row, 0, str(row + 1)
                )
                self._set_editable_item(
                    row, 1, format_time(chunk.start)
                )
                self._set_editable_item(
                    row, 2, format_time(chunk.end)
                )
                self._set_readonly_item(
                    row, 3, f"{chunk.duration:.3f} s"
                )

                self.item(row, 0).setToolTip(
                    "Change this number to move the chunk "
                    "to another output position."
                )
                self.item(row, 1).setToolTip(
                    "Edit source start time: seconds, "
                    "MM:SS.mmm, or HH:MM:SS.mmm."
                )
                self.item(row, 2).setToolTip(
                    "Edit source end time: seconds, "
                    "MM:SS.mmm, or HH:MM:SS.mmm."
                )

            draft_row = len(chunks)
            self._set_editable_item(
                draft_row, 0, self._draft[0]
            )
            self._set_editable_item(
                draft_row, 1, self._draft[1]
            )
            self._set_editable_item(
                draft_row, 2, self._draft[2]
            )
            self._set_readonly_item(draft_row, 3, "")

            insertion_tip = (
                "New chunk row. Enter Start and End to create "
                "a chunk. Leave Chunk blank to append, or enter "
                "the desired output position."
            )
            for col in range(3):
                self.item(draft_row, col).setToolTip(
                    insertion_tip
                )
        finally:
            self._updating = False

        if 0 <= selected < len(chunks):
            self.selectRow(selected)

    def _set_editable_item(
        self, row: int, col: int, text: str
    ) -> None:
        item = self.item(row, col)

        if item is None:
            item = QTableWidgetItem()
            self.setItem(row, col, item)

        item.setText(text)
        item.setFlags(
            Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsEditable
        )

    def _set_readonly_item(
        self, row: int, col: int, text: str
    ) -> None:
        item = self.item(row, col)

        if item is None:
            item = QTableWidgetItem()
            self.setItem(row, col, item)

        item.setText(text)
        item.setFlags(
            Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEnabled
        )

    def _cell_changed(self, row: int, col: int) -> None:
        if self._updating:
            return

        if row < len(self._chunks):
            self._edit_existing_chunk(row, col)
        elif row == len(self._chunks):
            self._edit_insertion_row(row)

    def _edit_existing_chunk(
        self, row: int, col: int
    ) -> None:
        if col == 0:
            text = self.item(row, 0).text().strip()
            try:
                target = int(text) - 1
                if not 0 <= target < len(self._chunks):
                    raise ValueError
            except ValueError:
                self.validation_message.emit(
                    "Chunk number must be an integer from "
                    f"1 to {len(self._chunks)}."
                )
                self.set_chunks(self._chunks)
                return

            self.move_requested.emit(row, target)
            return

        if col not in (1, 2):
            return

        try:
            start = parse_time(
                self.item(row, 1).text()
            )
            end = parse_time(
                self.item(row, 2).text()
            )
            self._validate_extent(start, end)
        except ValueError as exc:
            self.validation_message.emit(str(exc))
            self.set_chunks(self._chunks)
            return

        self.extent_changed.emit(row, start, end)

    def _edit_insertion_row(self, row: int) -> None:
        for index in range(3):
            item = self.item(row, index)
            self._draft[index] = (
                item.text().strip() if item else ""
            )

        # Wait until both Start and End are present.
        if not self._draft[1] or not self._draft[2]:
            return

        try:
            start = parse_time(self._draft[1])
            end = parse_time(self._draft[2])
            self._validate_extent(start, end)

            if self._draft[0]:
                target = int(self._draft[0]) - 1
                if not 0 <= target <= len(self._chunks):
                    raise ValueError(
                        "New chunk number must be from "
                        f"1 to {len(self._chunks) + 1}."
                    )
            else:
                target = len(self._chunks)
        except ValueError as exc:
            self.validation_message.emit(str(exc))
            return

        self._draft = ["", "", ""]
        self.insert_requested.emit(
            target, start, end
        )

    def _validate_extent(
        self, start: float, end: float
    ) -> None:
        if end <= start:
            raise ValueError(
                "Chunk end must be later than chunk start."
            )

        if self._max_duration is not None:
            if end > self._max_duration + 0.001:
                raise ValueError(
                    "Chunk end is beyond the video duration "
                    f"({format_time(self._max_duration)})."
                )

    def _show_context_menu(self, position) -> None:
        row = self.rowAt(position.y())
        if row < 0 or row >= len(self._chunks):
            return

        menu = QMenu(self)

        merge_previous = QAction(
            f"Merge Chunk {row + 1} with previous chunk",
            self,
        )
        merge_previous.setEnabled(row > 0)
        merge_previous.triggered.connect(
            lambda checked=False, r=row:
                self.merge_previous_requested.emit(r)
        )
        menu.addAction(merge_previous)

        merge_next = QAction(
            f"Merge Chunk {row + 1} with next chunk",
            self,
        )
        merge_next.setEnabled(
            row < len(self._chunks) - 1
        )
        merge_next.triggered.connect(
            lambda checked=False, r=row:
                self.merge_next_requested.emit(r)
        )
        menu.addAction(merge_next)

        menu.addSeparator()

        delete_action = QAction(
            f"Delete Chunk {row + 1}",
            self,
        )
        delete_action.triggered.connect(
            lambda checked=False, r=row:
                self.delete_requested.emit(r)
        )
        menu.addAction(delete_action)

        menu.exec(
            self.viewport().mapToGlobal(position)
        )
