from PySide6.QtCore import Qt
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
    DISPLAY_HEADERS = ["event type", "video time", "frame", "note"]
    DATA_KEYS = ["event_type", "video_time_sec", "frame_index", "note"]

    NOTE_COLUMN = 3

    def __init__(self):
        super().__init__(0, len(self.DISPLAY_HEADERS))

        self.setHorizontalHeaderLabels(self.DISPLAY_HEADERS)

        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)

        self.setShowGrid(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(32)

        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        self.setColumnWidth(0, 78)
        self.setColumnWidth(1, 78)
        self.setColumnWidth(2, 58)

        self.setStyleSheet(
            """
            QTableWidget::item:selected {
                background: transparent;
                color: black;
            }
            """
        )

    def add_event(self, event_type, video_time_sec, frame_index, note=""):
        row = self.rowCount()
        self.insertRow(row)

        fixed_values = [
            event_type,
            f"{video_time_sec:.3f}",
            str(frame_index),
        ]

        for column, value in enumerate(fixed_values):
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemIsEnabled)
            self.setItem(row, column, item)

        note_editor = NoteEditor(note)
        self.setCellWidget(row, self.NOTE_COLUMN, note_editor)

    def delete_selected_rows(self):
        current_row = self.currentRow()

        if current_row >= 0:
            self.removeRow(current_row)

    def events(self):
        rows = []

        for row in range(self.rowCount()):
            event = {}

            for column, key in enumerate(self.DATA_KEYS):
                if column == self.NOTE_COLUMN:
                    note_widget = self.cellWidget(row, column)
                    event[key] = note_widget.text() if note_widget else ""
                else:
                    item = self.item(row, column)
                    event[key] = item.text() if item else ""

            event["video_time_sec"] = float(event["video_time_sec"] or 0)
            event["frame_index"] = int(event["frame_index"] or 0)

            rows.append(event)

        return rows