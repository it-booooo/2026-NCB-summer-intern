from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)


class TtlPanel(QTableWidget):
    HEADERS = ["#", "Local time", "Record time"]

    def __init__(self):
        super().__init__(0, len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(48)

        header = self.horizontalHeader()
        header.setFixedHeight(32)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.setColumnWidth(0, 38)

    def set_markers(self, info):
        self.setRowCount(0)

        markers = info.get("markers", [])

        for row, marker in enumerate(markers):
            self.insertRow(row)

            local_time = marker["local_time"]
            local_time_text = (
                f"{local_time:%Y-%m-%d}\n"
                f"{local_time.strftime('%H:%M:%S.%f')[:-3]} +08:00"
            )

            record_time_text = (
                f"{marker['record_hours']:02d}:"
                f"{marker['record_minutes']:02d}:"
                f"{marker['record_seconds']:02d}."
                f"{marker['record_microseconds']:06d}"
            )

            values = [
                str(row + 1),
                local_time_text,
                record_time_text,
            ]

            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.setItem(row, column, item)
