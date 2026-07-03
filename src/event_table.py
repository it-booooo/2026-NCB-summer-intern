from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)


class EventTable(QTableWidget):
    HEADERS = ["event_type", "video_time_sec", "frame_index", "note"]

    def __init__(self):
        super().__init__(0, len(self.HEADERS))

        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def add_event(self, event_type, video_time_sec, frame_index, note=""):
        row = self.rowCount()
        self.insertRow(row)

        values = [
            event_type,
            f"{video_time_sec:.6f}",
            str(frame_index),
            note,
        ]

        for column, value in enumerate(values):
            self.setItem(row, column, QTableWidgetItem(value))

    def delete_selected_rows(self):
        selected_rows = sorted(
            {index.row() for index in self.selectedIndexes()},
            reverse=True,
        )

        for row in selected_rows:
            self.removeRow(row)

    def events(self):
        rows = []

        for row in range(self.rowCount()):
            event = {}

            for column, key in enumerate(self.HEADERS):
                item = self.item(row, column)
                event[key] = item.text() if item else ""

            event["video_time_sec"] = float(event["video_time_sec"] or 0)
            event["frame_index"] = int(event["frame_index"] or 0)

            rows.append(event)

        return rows