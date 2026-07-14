from PySide6.QtCore import Qt, Signal
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


DEFAULT_EVENT_TYPES = [
    "LED_on",
    "LED_off",
    "behavior_start",
    "behavior_end",
    "seizure_like_event",
]


class EventEditDialog(QDialog):
    """Edit all user-facing fields of one event marker."""

    def __init__(self, event, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Event")

        self.event_type_input = QComboBox()
        self.event_type_input.setEditable(True)
        self.event_type_input.addItems(DEFAULT_EVENT_TYPES)
        self.event_type_input.setCurrentText(str(event.get("event_type", "")))

        self.video_time_input = QDoubleSpinBox()
        self.video_time_input.setDecimals(6)
        self.video_time_input.setRange(0.0, 1_000_000_000.0)
        self.video_time_input.setSuffix(" s")
        self.video_time_input.setValue(float(event.get("video_time_sec", 0.0)))

        self.frame_input = QSpinBox()
        self.frame_input.setRange(0, 2_147_483_647)
        self.frame_input.setValue(int(event.get("frame_index", 0)))

        self.note_input = QLineEdit(str(event.get("note", "")))
        self.note_input.setPlaceholderText("Add note...")

        form = QFormLayout()
        form.addRow("Event type", self.event_type_input)
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

    def accept(self):
        if not self.event_type_input.currentText().strip():
            QMessageBox.warning(self, "Invalid event type", "Event type cannot be empty.")
            return
        super().accept()

    def values(self):
        return {
            "event_type": self.event_type_input.currentText().strip(),
            "video_time_sec": float(self.video_time_input.value()),
            "frame_index": int(self.frame_input.value()),
            "note": self.note_input.text(),
        }


class NoteEditor(QLineEdit):
    selection_requested = Signal()

    def __init__(self, text=""):
        super().__init__(text)

        self.setFrame(False)
        self.setPlaceholderText("Add note...")
        self.setClearButtonEnabled(True)

    def text(self):
        return super().text()

    def focusInEvent(self, event):
        self.selection_requested.emit()
        super().focusInEvent(event)

    def set_row_selected(self, selected):
        if selected:
            self.setStyleSheet(
                "background-color: #dcecff;"
                "border: 1px solid #2f80ed;"
                "color: #111111;"
            )
        else:
            self.setStyleSheet(
                "background-color: #ffffff;"
                "border: none;"
                "color: #111111;"
            )


class EventTable(QTableWidget):
    DISPLAY_HEADERS = ["event type", "video time", "note"]
    events_changed = Signal()
    video_time_selected = Signal(float)

    EVENT_TYPE_COLUMN = 0
    VIDEO_TIME_COLUMN = 1
    NOTE_COLUMN = 2
    FRAME_ROLE = Qt.UserRole + 1
    SOURCE_ROLE = Qt.UserRole + 2
    VIDEO_TIME_ROLE = Qt.UserRole + 3

    def __init__(self):
        super().__init__(0, len(self.DISPLAY_HEADERS))

        self.setHorizontalHeaderLabels(self.DISPLAY_HEADERS)

        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

        self.setShowGrid(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(32)

        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)

        self.setColumnWidth(0, 78)
        self.setColumnWidth(1, 78)

        self.setStyleSheet(
            """
            QTableWidget::item:selected {
                background-color: #dcecff;
                color: #111111;
                border: 1px solid #2f80ed;
            }
            """
        )
        self.cellClicked.connect(self.handle_cell_clicked)
        self.itemSelectionChanged.connect(self.update_note_selection_styles)

    def handle_cell_clicked(self, row, column):
        if column != self.VIDEO_TIME_COLUMN:
            return

        item = self.item(row, self.VIDEO_TIME_COLUMN)
        if item is None:
            return

        video_time_sec = item.data(self.VIDEO_TIME_ROLE)
        if video_time_sec is None:
            try:
                video_time_sec = float(item.text())
            except ValueError:
                return

        self.video_time_selected.emit(float(video_time_sec))

    def add_event(
        self,
        event_type,
        video_time_sec,
        frame_index,
        note="",
        source="manual",
    ):
        row = self.rowCount()
        self.insertRow(row)

        fixed_values = [
            event_type,
            f"{video_time_sec:.3f}",
        ]

        for column, value in enumerate(fixed_values):
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if column == self.EVENT_TYPE_COLUMN:
                item.setData(self.FRAME_ROLE, int(frame_index))
                item.setData(self.SOURCE_ROLE, source)
            elif column == self.VIDEO_TIME_COLUMN:
                item.setData(self.VIDEO_TIME_ROLE, float(video_time_sec))
            self.setItem(row, column, item)

        note_editor = NoteEditor(note)
        note_editor.selection_requested.connect(
            lambda editor=note_editor: self.select_note_editor_row(editor)
        )
        self.setCellWidget(row, self.NOTE_COLUMN, note_editor)
        self.update_note_selection_styles()
        self.events_changed.emit()

    def select_note_editor_row(self, editor):
        for row in range(self.rowCount()):
            if self.cellWidget(row, self.NOTE_COLUMN) is editor:
                self.setCurrentCell(row, self.NOTE_COLUMN)
                self.selectRow(row)
                return

    def update_note_selection_styles(self):
        selected_rows = {
            index.row() for index in self.selectionModel().selectedRows()
        }
        for row in range(self.rowCount()):
            note_widget = self.cellWidget(row, self.NOTE_COLUMN)
            if note_widget is not None:
                note_widget.set_row_selected(row in selected_rows)

    def edit_selected_event(self):
        row = self.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Edit Event",
                "Please select an event to edit.",
            )
            return

        dialog = EventEditDialog(self.event_at(row), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self.update_event(row, **dialog.values())

    def update_event(
        self,
        row,
        event_type,
        video_time_sec,
        frame_index,
        note,
    ):
        if row < 0 or row >= self.rowCount():
            raise IndexError("Event row is out of range.")

        event_item = self.item(row, self.EVENT_TYPE_COLUMN)
        time_item = self.item(row, self.VIDEO_TIME_COLUMN)
        note_widget = self.cellWidget(row, self.NOTE_COLUMN)

        event_item.setText(str(event_type))
        event_item.setData(self.FRAME_ROLE, int(frame_index))
        time_item.setText(f"{float(video_time_sec):.3f}")
        time_item.setData(self.VIDEO_TIME_ROLE, float(video_time_sec))
        if note_widget is not None:
            note_widget.setText(str(note))

        self.events_changed.emit()

    def delete_selected_rows(self):
        current_row = self.currentRow()

        if current_row >= 0:
            self.removeRow(current_row)
            if self.rowCount() > 0:
                next_row = min(current_row, self.rowCount() - 1)
                self.setCurrentCell(next_row, self.EVENT_TYPE_COLUMN)
                self.selectRow(next_row)
            else:
                self.clearSelection()
                self.setCurrentItem(None)
            self.update_note_selection_styles()
            self.events_changed.emit()

    def delete_events_by_source(self, source):
        removed = False
        for row in range(self.rowCount() - 1, -1, -1):
            event_item = self.item(row, self.EVENT_TYPE_COLUMN)
            if event_item is not None and event_item.data(self.SOURCE_ROLE) == source:
                self.removeRow(row)
                removed = True

        if removed:
            self.update_note_selection_styles()
            self.events_changed.emit()

    def event_at(self, row):
        if row < 0 or row >= self.rowCount():
            raise IndexError("Event row is out of range.")

        event_item = self.item(row, self.EVENT_TYPE_COLUMN)
        time_item = self.item(row, self.VIDEO_TIME_COLUMN)
        note_widget = self.cellWidget(row, self.NOTE_COLUMN)
        video_time_sec = time_item.data(self.VIDEO_TIME_ROLE)
        if video_time_sec is None:
            video_time_sec = float(time_item.text() if time_item else 0)
        frame_index = event_item.data(self.FRAME_ROLE) if event_item is not None else 0
        source = event_item.data(self.SOURCE_ROLE) if event_item is not None else None

        return {
            "event_type": event_item.text() if event_item else "",
            "video_time_sec": float(video_time_sec),
            "frame_index": int(frame_index or 0),
            "note": note_widget.text() if note_widget else "",
            "source": source or "manual",
        }

    def events(self):
        return [self.event_at(row) for row in range(self.rowCount())]
