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
)

from ..app_state import TtlState, VideoState
from ..markers import Marker, MarkerKind, MarkerSource, RecordPosition
from ..synchronization.time_conversion import record_time_parts
from .marker_view_panel import MarkerViewPanel


class TtlPanel(MarkerViewPanel):
    HEADERS = ["#", "Local time", "Record time"]
    MARKER_ID_ROLE = Qt.UserRole + 1
    RECORD_TIME_ROLE = Qt.UserRole + 2
    record_time_selected = Signal(float)

    def __init__(
        self,
        marker_store,
        ttl_state=None,
        video_player=None,
        video_state=None,
    ):
        super().__init__(marker_store)
        self.ttl_state = ttl_state or TtlState()
        self.video_state = video_state or VideoState()
        self.video_player = video_player

        self.record_time_input = QLineEdit()
        self.record_time_input.setPlaceholderText("HH:MM:SS.ffffff")
        self.record_time_input.setFixedHeight(24)
        self.record_time_input.returnPressed.connect(self.add_ttl_marker)
        add_button = QPushButton("Add TTL")
        remove_button = QPushButton("Remove TTL")
        add_button.clicked.connect(self.add_ttl_marker)
        remove_button.clicked.connect(self.remove_selected_marker)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(self.record_time_input)
        controls.addWidget(add_button)
        controls.addWidget(remove_button)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.cellClicked.connect(self.handle_cell_clicked)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 38)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(controls)
        layout.addWidget(self.table)
        self.refresh_table()

    def accepts_marker(self, marker):
        return marker.kind == MarkerKind.TTL

    def refresh_markers(self):
        self.refresh_table()

    def ttl_markers(self):
        return sorted(
            self.markers(),
            key=lambda marker: marker.position.time_sec,
        )

    def set_markers(self, markers, metadata=None, emit=True):
        self.ttl_state.metadata = dict(metadata or {}) if metadata else None
        self.marker_store.replace_by_kind(
            MarkerKind.TTL,
            list(markers or []),
            emit=emit,
        )
        if not emit:
            self.refresh_table()

    def paused_video_time_for_ttl(self):
        if self.video_player is None or not self.video_player.has_video():
            raise ValueError("Please import a video or enter a TTL time manually.")
        if self.video_state.is_playing:
            raise ValueError("Pause the video before adding its current time as TTL.")
        return self.video_player.current_time_sec()

    def add_ttl_marker(self):
        text = self.record_time_input.text().strip()
        try:
            record_time_us = (
                self.parse_record_time_us(text)
                if text
                else int(
                    (Decimal(str(self.paused_video_time_for_ttl())) * 1_000_000)
                    .to_integral_value(rounding=ROUND_HALF_UP)
                )
            )
        except (TypeError, InvalidOperation, ValueError) as error:
            QMessageBox.warning(self, "Cannot add TTL", str(error))
            return

        parts = record_time_parts(record_time_us)
        self.marker_store.add(
            Marker(
                kind=MarkerKind.TTL,
                source=MarkerSource.MANUAL,
                position=RecordPosition(record_time_us / 1_000_000.0),
                payload={"record_time_us": record_time_us, **parts},
            )
        )
        self.record_time_input.clear()

    def remove_selected_marker(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.information(self, "Remove TTL", "Please select a TTL marker.")
            return
        item = self.table.item(selected[0].row(), 0)
        self.marker_store.delete(item.data(self.MARKER_ID_ROLE))

    def handle_cell_clicked(self, row, column):
        item = self.table.item(row, 0)
        if item is None:
            return
        record_time_sec = item.data(self.RECORD_TIME_ROLE)
        if record_time_sec is not None:
            self.record_time_selected.emit(float(record_time_sec))

    def parse_record_time_us(self, text):
        if not text:
            raise ValueError("Please enter a TTL record time.")
        try:
            if ":" not in text:
                seconds = Decimal(text)
            else:
                parts = text.split(":")
                if len(parts) != 3:
                    raise ValueError
                hours, minutes, seconds_part = map(Decimal, parts)
                if minutes >= 60 or seconds_part >= 60:
                    raise ValueError
                seconds = hours * 3600 + minutes * 60 + seconds_part
        except (InvalidOperation, ValueError):
            raise ValueError(
                "Use seconds or HH:MM:SS.ffffff, for example 12.345678."
            ) from None
        if seconds < 0:
            raise ValueError("TTL record time cannot be negative.")
        return int((seconds * 1_000_000).to_integral_value(rounding=ROUND_HALF_UP))

    def refresh_table(self):
        self.table.setRowCount(0)
        for row, marker in enumerate(self.ttl_markers()):
            self.table.insertRow(row)
            local_time = marker.payload.get("local_time")
            local_text = str(local_time or "")
            record_time_us = int(
                marker.payload.get(
                    "record_time_us", round(marker.position.time_sec * 1_000_000)
                )
            )
            parts = record_time_parts(record_time_us)
            record_text = (
                f"{parts['record_hours']:02d}:{parts['record_minutes']:02d}:"
                f"{parts['record_seconds']:02d}.{parts['record_microseconds']:06d}"
            )
            for column, text in enumerate((str(row + 1), local_text, record_text)):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                if column == 0:
                    item.setData(self.MARKER_ID_ROLE, marker.marker_id)
                    item.setData(self.RECORD_TIME_ROLE, marker.position.time_sec)
                self.table.setItem(row, column, item)
