from typing import ClassVar

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..app_state import SyncState, VideoState
from ..markers import (
    MarkerKind,
    VideoPosition,
)
from ..synchronization import resolve_sync_reference_markers
from ..synchronization.time_conversion import relative_time

VIDEO_MARKER_KINDS = [kind for kind in MarkerKind if kind != MarkerKind.TTL]


class EventEditDialog(QDialog):
    def __init__(
        self,
        marker,
        fps=None,
        total_frames=None,
        parent=None,
        marker_number=1,
        marker_count=1,
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit Marker")
        self.fps = float(fps or 0.0)
        self.updating_video_position = False
        position = marker.position

        self.marker_number_input = QSpinBox()
        self.marker_number_input.setRange(1, max(int(marker_count), 1))
        self.marker_number_input.setValue(int(marker_number))

        self.event_type_input = QComboBox()
        self.event_type_input.setEditable(True)
        self.event_type_input.addItems([kind.value for kind in VIDEO_MARKER_KINDS])
        self.event_type_input.setCurrentText(marker.kind.value)

        self.video_time_input = QDoubleSpinBox()
        self.video_time_input.setDecimals(6)
        self.video_time_input.setRange(-1_000_000_000.0, 1_000_000_000.0)
        self.video_time_input.setSuffix(" s")
        self.video_time_input.setValue(float(position.time_sec))

        self.frame_input = QSpinBox()
        maximum_frame = (
            max(int(total_frames) - 1, 0)
            if total_frames is not None and int(total_frames) > 0
            else 2_147_483_647
        )
        self.frame_input.setRange(0, maximum_frame)
        self.frame_input.setValue(int(position.frame_index))
        if self.fps > 0:
            self.video_time_input.valueChanged.connect(self.sync_frame_from_time)
            self.frame_input.valueChanged.connect(self.sync_time_from_frame)

        self.note_input = QLineEdit(marker.note)
        form = QFormLayout()
        form.addRow("Event number", self.marker_number_input)
        form.addRow("Marker type", self.event_type_input)
        form.addRow("Video time", self.video_time_input)
        form.addRow("Frame index", self.frame_input)
        form.addRow("Note", self.note_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def sync_frame_from_time(self, video_time_sec):
        if self.updating_video_position or self.fps <= 0:
            return
        self.updating_video_position = True
        try:
            frame_index = round(float(video_time_sec) * self.fps)
            frame_index = max(
                self.frame_input.minimum(),
                min(frame_index, self.frame_input.maximum()),
            )
            self.frame_input.setValue(frame_index)
            if video_time_sec >= 0:
                self.video_time_input.setValue(frame_index / self.fps)
        finally:
            self.updating_video_position = False

    def sync_time_from_frame(self, frame_index):
        if self.updating_video_position or self.fps <= 0:
            return
        self.updating_video_position = True
        try:
            self.video_time_input.setValue(float(frame_index) / self.fps)
        finally:
            self.updating_video_position = False

    def accept(self):
        try:
            MarkerKind(self.event_type_input.currentText().strip())
        except ValueError:
            QMessageBox.warning(self, "Invalid marker type", "Select a known marker type.")
            return
        super().accept()

    def values(self):
        return {
            "kind": MarkerKind(self.event_type_input.currentText().strip()),
            "position": VideoPosition(
                float(self.video_time_input.value()),
                int(self.frame_input.value()),
            ),
            "note": self.note_input.text(),
        }

    def marker_number(self):
        return self.marker_number_input.value()


class NoteEditor(QLineEdit):
    selection_requested = Signal()

    def __init__(self, text=""):
        super().__init__(text)
        self.setFrame(False)
        self.setPlaceholderText("Add note...")
        self.setClearButtonEnabled(True)

    def focusInEvent(self, event):
        self.selection_requested.emit()
        super().focusInEvent(event)

    def set_row_selected(self, selected, sync_reference=False):
        if selected:
            style = "background-color: #dcecff; border: 1px solid #2f80ed;"
        elif sync_reference:
            style = "background-color: #d8f3dc; border: 1px solid #40916c;"
        else:
            style = "background-color: #ffffff; border: none;"
        self.setStyleSheet(f"{style} color: #111111;")


class MarkerTable(QTableWidget):
    """Video-marker view backed by the shared ``MarkerStore``."""

    DISPLAY_HEADERS: ClassVar[list[str]] = ["#", "marker type", "video time", "note"]
    events_changed = Signal()
    video_time_selected = Signal(float)
    MARKER_ID_ROLE = Qt.UserRole + 1
    VIDEO_TIME_ROLE = Qt.UserRole + 2

    def __init__(self, marker_store, video_state=None, sync_state=None):
        super().__init__(0, len(self.DISPLAY_HEADERS))
        self.marker_store = marker_store
        self.video_state = video_state or VideoState()
        self.sync_state = sync_state or SyncState()
        self._standalone_video_fps = None
        self._standalone_video_total_frames = None
        self._refreshing = False

        self.setHorizontalHeaderLabels(self.DISPLAY_HEADERS)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setShowGrid(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(32)
        header = self.horizontalHeader()
        header.setFixedHeight(24)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.setColumnWidth(0, 38)
        self.setColumnWidth(1, 110)
        self.setColumnWidth(2, 92)

        self.marker_store.changed.connect(self._store_changed)
        self.itemSelectionChanged.connect(self.update_note_selection_styles)
        self.cellClicked.connect(self.handle_cell_clicked)
        self.refresh()

    def video_markers(self):
        return [
            marker
            for marker in self.marker_store.all()
            if isinstance(marker.position, VideoPosition)
        ]

    def _store_changed(self):
        self.refresh()
        self.events_changed.emit()

    def refresh(self):
        current_id = self.selected_marker_id()
        _ttl_reference, video_reference = resolve_sync_reference_markers(
            self.marker_store.all(),
            self.sync_state,
        )
        sync_marker_id = video_reference.marker_id if video_reference else None
        self._refreshing = True
        try:
            self.setRowCount(0)
            for marker_number, marker in enumerate(self.video_markers(), start=1):
                row = self.rowCount()
                self.insertRow(row)
                number_item = QTableWidgetItem(str(marker_number))
                number_item.setData(self.MARKER_ID_ROLE, marker.marker_id)
                number_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                number_item.setTextAlignment(Qt.AlignCenter)
                type_item = QTableWidgetItem(marker.kind.value)
                type_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                type_item.setTextAlignment(Qt.AlignCenter)
                time_item = QTableWidgetItem(self.format_display_time(marker.position.time_sec))
                time_item.setData(self.VIDEO_TIME_ROLE, marker.position.time_sec)
                time_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                time_item.setTextAlignment(Qt.AlignCenter)
                if marker.marker_id == sync_marker_id:
                    for item in (number_item, type_item, time_item):
                        item.setBackground(QColor("#d8f3dc"))
                self.setItem(row, 0, number_item)
                self.setItem(row, 1, type_item)
                self.setItem(row, 2, time_item)
                note_editor = NoteEditor(marker.note)
                note_editor.selection_requested.connect(
                    lambda editor=note_editor: self.select_note_editor_row(editor)
                )
                note_editor.editingFinished.connect(
                    lambda editor=note_editor, marker_id=marker.marker_id: self.update_note(
                        marker_id, editor.text()
                    )
                )
                self.setCellWidget(row, 3, note_editor)
                if marker.marker_id == current_id:
                    self.selectRow(row)
        finally:
            self._refreshing = False
        self.update_note_selection_styles()

    def selected_marker_id(self):
        row = self.currentRow()
        item = self.item(row, 0) if row >= 0 else None
        return item.data(self.MARKER_ID_ROLE) if item is not None else None

    def set_video_timing(self, fps, total_frames):
        self._standalone_video_fps = float(fps or 0.0)
        self._standalone_video_total_frames = int(total_frames or 0)

    def set_sync_time_origin(self, origin_sec):
        self.sync_state.video_time_origin_sec = (
            None if origin_sec is None else float(origin_sec)
        )
        self.setHorizontalHeaderItem(
            2,
            QTableWidgetItem(
                "sync time"
                if self.sync_state.video_time_origin_sec is not None
                else "video time"
            ),
        )
        self.refresh()

    def format_display_time(self, video_time_sec):
        return f"{relative_time(video_time_sec, self.sync_state.video_time_origin_sec):.3f}"

    def handle_cell_clicked(self, row, column):
        item = self.item(row, 2)
        if item is not None:
            self.video_time_selected.emit(float(item.data(self.VIDEO_TIME_ROLE)))

    def select_note_editor_row(self, editor):
        for row in range(self.rowCount()):
            if self.cellWidget(row, 3) is editor:
                self.selectRow(row)
                item = self.item(row, 2)
                if item is not None:
                    self.video_time_selected.emit(float(item.data(self.VIDEO_TIME_ROLE)))
                return

    def update_note(self, marker_id, note):
        if not self._refreshing:
            self.marker_store.update(marker_id, note=str(note))

    def update_note_selection_styles(self):
        selected = {index.row() for index in self.selectionModel().selectedRows()}
        _ttl_reference, video_reference = resolve_sync_reference_markers(
            self.marker_store.all(),
            self.sync_state,
        )
        sync_marker_id = video_reference.marker_id if video_reference else None
        for row in range(self.rowCount()):
            editor = self.cellWidget(row, 3)
            if editor is not None:
                marker_id = self.item(row, 0).data(self.MARKER_ID_ROLE)
                editor.set_row_selected(
                    row in selected,
                    marker_id == sync_marker_id,
                )

    def edit_selected_event(self):
        marker_id = self.selected_marker_id()
        if marker_id is None:
            QMessageBox.information(self, "Edit Marker", "Please select a marker.")
            return
        marker = self.marker_store.get(marker_id)
        video_markers = self.video_markers()
        marker_number = next(
            index
            for index, item in enumerate(video_markers, start=1)
            if item.marker_id == marker_id
        )
        metadata = self.video_state.metadata
        dialog = EventEditDialog(
            marker,
            marker_number=marker_number,
            marker_count=len(video_markers),
            fps=metadata.using_fps if metadata else self._standalone_video_fps,
            total_frames=(
                metadata.total_frames if metadata else self._standalone_video_total_frames
            ),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = self.update_and_reorder_marker(
            marker_id,
            dialog.marker_number(),
            dialog.values(),
        )
        self.video_time_selected.emit(updated.position.time_sec)

    def update_and_reorder_marker(self, marker_id, marker_number, changes):
        updated = self.marker_store.update(marker_id, emit=False, **changes)
        all_markers = list(self.marker_store.all())
        video_markers = [
            marker for marker in all_markers if isinstance(marker.position, VideoPosition)
        ]
        current_index = next(
            index
            for index, marker in enumerate(video_markers)
            if marker.marker_id == marker_id
        )
        video_markers.insert(marker_number - 1, video_markers.pop(current_index))
        reordered_video_markers = iter(video_markers)
        self.marker_store.replace_all(
            [
                next(reordered_video_markers)
                if isinstance(marker.position, VideoPosition)
                else marker
                for marker in all_markers
            ]
        )
        return updated

    def delete_selected_rows(self):
        marker_id = self.selected_marker_id()
        if marker_id is not None:
            self.marker_store.delete(marker_id)

# Backward-compatible import name for external callers.
EventTable = MarkerTable
