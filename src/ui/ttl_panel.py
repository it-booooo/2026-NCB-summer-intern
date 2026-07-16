from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..state import SyncState
from ..time_utils import record_time_parts


class TtlPanel(QWidget):
    HEADERS = ["#", "Local time", "Record time"]
    markers_changed = Signal(dict)

    def __init__(self, video_player=None, sync_state=None):
        super().__init__()
        self.sync_state = sync_state or SyncState()
        self.video_player = video_player

        self.record_time_input = QLineEdit()
        self.record_time_input.setPlaceholderText("HH:MM:SS.ffffff")
        self.record_time_input.setToolTip(
            "Manual TTL record time. Accepts seconds or HH:MM:SS.ffffff."
        )
        self.record_time_input.returnPressed.connect(self.add_ttl_marker)

        self.add_button = QPushButton("Add TTL")
        self.add_button.clicked.connect(self.add_ttl_marker)

        self.remove_button = QPushButton("Remove TTL")
        self.remove_button.clicked.connect(self.remove_selected_marker)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(4)
        controls.addWidget(self.record_time_input)
        controls.addWidget(self.add_button)
        controls.addWidget(self.remove_button)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.setStyleSheet(
            """
            QTableWidget::item:selected {
                background-color: #dcecff;
                color: #111111;
                border: 1px solid #2f80ed;
            }
            """
        )

        header = self.table.horizontalHeader()
        header.setFixedHeight(32)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 38)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(controls)
        layout.addWidget(self.table)
        self.setLayout(layout)

    @property
    def info(self):
        """Describe info.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
        """
        if self.sync_state.time_marker_info is None:
            return self.empty_info()
        return self.sync_state.time_marker_info

    @info.setter
    def info(self, info):
        """Describe info.

        Args:
            info: Input accepted by this function.

        Returns:
            The value produced by this function, if any.
        """
        self.sync_state.time_marker_info = info

    def empty_info(self):
        """Describe empty_info.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
        """
        return {
            "path": None,
            "filename": "Manual TTL",
            "time_column_name": None,
            "marker_count": 0,
            "markers": [],
            "first_marker_sec": None,
        }

    def set_markers(self, info):
        """Describe set_markers.

        Args:
            info: Input accepted by this function.

        Returns:
            The value produced by this function, if any.
        """
        self.info = info
        self.refresh_table()

    def paused_video_time_for_ttl(self):
        """Describe paused_video_time_for_ttl.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
        """
        if self.video_player is None or not self.video_player.has_video():
            raise ValueError("Please import a video or enter a TTL time manually.")
        if self.video_player.is_playing:
            raise ValueError("Pause the video before adding its current time as TTL.")
        return self.video_player.current_time_sec()

    def add_ttl_marker(self):
        """Describe add_ttl_marker.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
        """
        text = self.record_time_input.text().strip()

        if text:
            try:
                record_time = self.parse_record_time_us(text)
            except ValueError as error:
                QMessageBox.warning(self, "Invalid TTL record time", str(error))
                return
        else:
            try:
                video_time_sec = self.paused_video_time_for_ttl()
                record_time = int(
                    (Decimal(str(video_time_sec)) * 1_000_000).to_integral_value(
                        rounding=ROUND_HALF_UP
                    )
                )
            except (TypeError, InvalidOperation, ValueError) as error:
                QMessageBox.warning(self, "Cannot add TTL", str(error))
                return

        marker = self.create_record_time_marker(record_time)
        markers = list(self.info.get("markers", []))
        markers.append(marker)
        markers.sort(key=lambda item: item["record_time"])
        self._update_marker_info(markers, ensure_filename=True)

        self.record_time_input.clear()
        self.refresh_table()
        self.markers_changed.emit(self.info)

    def remove_selected_marker(self):
        """Describe remove_selected_marker.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
        """
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(
                self,
                "Remove TTL",
                "Please select a TTL event to remove.",
            )
            return

        row = selected_rows[0].row()
        markers = list(self.info.get("markers", []))
        if row < 0 or row >= len(markers):
            return

        del markers[row]
        self._update_marker_info(markers)

        self.refresh_table()
        self.markers_changed.emit(self.info)

    def _update_marker_info(self, markers, ensure_filename=False):
        """Keep the marker list and its derived summary fields consistent."""
        updates = {
            "marker_count": len(markers),
            "markers": markers,
            "first_marker_sec": (
                markers[0]["record_time"] / 1_000_000.0 if markers else None
            ),
        }
        if ensure_filename:
            updates["filename"] = self.info.get("filename") or "Manual TTL"

        self.info = {
            **self.info,
            **updates,
        }

    def parse_record_time_us(self, text):
        """Describe parse_record_time_us.

        Args:
            text: Input accepted by this function.

        Returns:
            The value produced by this function, if any.
        """
        if not text:
            raise ValueError("Please enter a TTL record time.")

        try:
            if ":" not in text:
                seconds = Decimal(text)
            else:
                parts = text.split(":")
                if len(parts) != 3:
                    raise ValueError

                hours = Decimal(parts[0])
                minutes = Decimal(parts[1])
                seconds_part = Decimal(parts[2])

                if minutes >= 60 or seconds_part >= 60:
                    raise ValueError

                seconds = hours * 3600 + minutes * 60 + seconds_part
        except (InvalidOperation, ValueError):
            raise ValueError(
                "Use seconds or HH:MM:SS.ffffff, for example 12.345678 or 00:00:12.345678."
            ) from None

        if seconds < 0:
            raise ValueError("TTL record time cannot be negative.")

        return int((seconds * 1_000_000).to_integral_value(rounding=ROUND_HALF_UP))

    def create_record_time_marker(self, record_time):
        """Describe create_record_time_marker.

        Args:
            record_time: Input accepted by this function.

        Returns:
            The value produced by this function, if any.
        """
        return {
            "local_time_us": None,
            "local_time": None,
            "record_time": record_time,
            **record_time_parts(record_time),
            "source": "manual",
        }

    def refresh_table(self):
        """Describe refresh_table.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
        """
        self.table.setRowCount(0)

        markers = self.info.get("markers", [])

        for row, marker in enumerate(markers):
            self.table.insertRow(row)

            local_time = marker.get("local_time")
            if local_time is None:
                local_time_text = ""
            else:
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
                self.table.setItem(row, column, item)
