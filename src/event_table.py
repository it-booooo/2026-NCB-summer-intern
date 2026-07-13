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

    EVENT_TYPE_COLUMN = 0
    VIDEO_TIME_COLUMN = 1
    NOTE_COLUMN = 2
    FRAME_ROLE = Qt.UserRole + 1
    VIDEO_TIME_ROLE = Qt.UserRole + 2

    def __init__(self):
        super().__init__(0, len(self.DISPLAY_HEADERS))
        self.sync_time_origin_sec = None

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

    def set_sync_time_origin(self, origin_sec):
        next_origin = None if origin_sec is None else float(origin_sec)
        if self.sync_time_origin_sec == next_origin:
            return

        self.sync_time_origin_sec = next_origin
        self.setHorizontalHeaderItem(
            self.VIDEO_TIME_COLUMN,
            QTableWidgetItem(
                "sync time" if self.sync_time_origin_sec is not None else "video time"
            ),
        )
        self.refresh_time_display()

    def display_time(self, video_time_sec):
        if self.sync_time_origin_sec is None:
            return float(video_time_sec)

        return float(video_time_sec) - self.sync_time_origin_sec

    def format_display_time(self, video_time_sec):
        return f"{self.display_time(video_time_sec):.3f}"

    def refresh_time_display(self):
        for row in range(self.rowCount()):
            time_item = self.item(row, self.VIDEO_TIME_COLUMN)
            if time_item is None:
                continue

            video_time_sec = self.item_video_time_sec(time_item)
            time_item.setText(self.format_display_time(video_time_sec))

    def item_video_time_sec(self, item):
        if item is None:
            return 0.0

        stored_time = item.data(self.VIDEO_TIME_ROLE)
        if stored_time is not None:
            try:
                return float(stored_time)
            except (TypeError, ValueError):
                pass

        try:
            display_time = float(item.text())
        except (TypeError, ValueError):
            return 0.0

        if self.sync_time_origin_sec is None:
            return display_time

        return display_time + self.sync_time_origin_sec

    def add_event(self, event_type, video_time_sec, frame_index, note=""):
        row = self.rowCount()
        self.insertRow(row)

        fixed_values = [
            event_type,
            self.format_display_time(video_time_sec),
        ]

        for column, value in enumerate(fixed_values):
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemIsEnabled)
            if column == self.EVENT_TYPE_COLUMN:
                item.setData(self.FRAME_ROLE, int(frame_index))
            elif column == self.VIDEO_TIME_COLUMN:
                item.setData(self.VIDEO_TIME_ROLE, float(video_time_sec))
            self.setItem(row, column, item)

        note_editor = NoteEditor(note)
        self.setCellWidget(row, self.NOTE_COLUMN, note_editor)
        self.events_changed.emit()

    def clear_events(self, emit=True):
        self.setRowCount(0)
        if emit:
            self.events_changed.emit()

    def delete_selected_rows(self):
        current_row = self.currentRow()

        if current_row >= 0:
            self.removeRow(current_row)
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
                "video_time_sec": self.item_video_time_sec(time_item),
                "frame_index": int(frame_index or 0),
                "note": note_widget.text() if note_widget else "",
            }

            rows.append(event)

        return rows
