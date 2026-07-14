from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
)


class NoteEditor(QLineEdit):
    def __init__(self, text=""):
        super().__init__(text)

        self.setFrame(False)
        self.setPlaceholderText("Add note...")
        self.setClearButtonEnabled(True)

    def text(self):
        return super().text()


class EventTable(QTableWidget):
    DISPLAY_HEADERS = ["event type", "video time", "note"]
    events_changed = Signal()
    video_time_selected = Signal(float)

    EVENT_TYPE_COLUMN = 0
    VIDEO_TIME_COLUMN = 1
    NOTE_COLUMN = 2
    FRAME_ROLE = Qt.UserRole + 1
    SOURCE_ROLE = Qt.UserRole + 2

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
                background: transparent;
                color: black;
            }
            """
        )
        self.cellClicked.connect(self.handle_cell_clicked)

    def handle_cell_clicked(self, row, column):
        if column != self.VIDEO_TIME_COLUMN:
            return

        item = self.item(row, self.VIDEO_TIME_COLUMN)
        if item is None:
            return

        try:
            video_time_sec = float(item.text())
        except ValueError:
            return

        self.video_time_selected.emit(video_time_sec)

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
            item.setFlags(Qt.ItemIsEnabled)
            if column == self.EVENT_TYPE_COLUMN:
                item.setData(self.FRAME_ROLE, int(frame_index))
                item.setData(self.SOURCE_ROLE, source)
            self.setItem(row, column, item)

        note_editor = NoteEditor(note)
        self.setCellWidget(row, self.NOTE_COLUMN, note_editor)
        self.events_changed.emit()

    def delete_selected_rows(self):
        current_row = self.currentRow()

        if current_row >= 0:
            self.removeRow(current_row)
            self.events_changed.emit()

    def delete_events_by_source(self, source):
        removed = False
        for row in range(self.rowCount() - 1, -1, -1):
            event_item = self.item(row, self.EVENT_TYPE_COLUMN)
            if event_item is not None and event_item.data(self.SOURCE_ROLE) == source:
                self.removeRow(row)
                removed = True

        if removed:
            self.events_changed.emit()

    def events(self):
        rows = []

        for row in range(self.rowCount()):
            event_item = self.item(row, self.EVENT_TYPE_COLUMN)
            time_item = self.item(row, self.VIDEO_TIME_COLUMN)
            note_widget = self.cellWidget(row, self.NOTE_COLUMN)

            frame_index = (
                event_item.data(self.FRAME_ROLE)
                if event_item is not None
                else 0
            )

            event = {
                "event_type": event_item.text() if event_item else "",
                "video_time_sec": float(time_item.text() if time_item else 0),
                "frame_index": int(frame_index or 0),
                "note": note_widget.text() if note_widget else "",
                "source": (
                    event_item.data(self.SOURCE_ROLE)
                    if event_item is not None
                    else "manual"
                ),
            }

            rows.append(event)

        return rows
