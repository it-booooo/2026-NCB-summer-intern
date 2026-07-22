import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from scipy.signal import find_peaks

from ..markers import (
    Marker,
    MarkerKind,
    MarkerSource,
    RecordPosition,
    marker_video_time,
)
from ..synchronization import relative_time
from .marker_view_panel import MarkerViewPanel


class FindPeakPanel(MarkerViewPanel):
    DISPLAY_HEADERS = ["marker type", "video time", "note"]
    video_time_selected = Signal(float)
    VIDEO_TIME_ROLE = Qt.UserRole + 1
    LFP_PEAK_HEIGHT_SIGMA = 8.0
    LFP_PEAK_PROMINENCE_SIGMA = 6.0
    LFP_PEAK_MIN_DISTANCE_SEC = 1.0

    def __init__(
        self,
        marker_store,
        lfp_service,
        sync_state,
        video_state,
        video_player,
    ):
        super().__init__(marker_store)
        self.lfp_service = lfp_service
        self.sync_state = sync_state
        self.video_state = video_state
        self.video_player = video_player

        self.find_peaks_button = QPushButton("Find Peak")
        self.delete_selected_button = QPushButton("Delete Selected")
        for button in (self.find_peaks_button, self.delete_selected_button):
            button.setFixedHeight(26)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.find_peaks_button.clicked.connect(self.add_lfp_peaks)
        self.delete_selected_button.clicked.connect(self.delete_selected_peak)
        self.delete_selected_button.setEnabled(False)
        self.table = QTableWidget(0, len(self.DISPLAY_HEADERS))
        self.table.setHorizontalHeaderLabels(self.DISPLAY_HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 92)
        self.table.cellClicked.connect(self.handle_cell_clicked)
        self.table.itemSelectionChanged.connect(
            lambda: self.delete_selected_button.setEnabled(
                bool(self.table.selectionModel().selectedRows())
            )
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.find_peaks_button, stretch=1)
        button_layout.addWidget(self.delete_selected_button, stretch=1)
        layout.addLayout(button_layout)
        layout.addWidget(self.table)
        self.refresh_table()

    def accepts_marker(self, marker):
        return marker.kind == MarkerKind.LFP_PEAK

    def refresh_markers(self):
        self.refresh_table()

    def peak_markers(self):
        return self.markers()

    def refresh_table(self):
        self.table.setRowCount(0)
        offset = self.sync_state.time_offset_sec
        is_synchronized = self.sync_state.video_time_origin_sec is not None
        self.table.setHorizontalHeaderItem(
            1,
            QTableWidgetItem("sync time" if is_synchronized else "video time"),
        )
        for row, marker in enumerate(self.peak_markers()):
            self.table.insertRow(row)
            video_time = marker_video_time(marker, offset)
            display_time = (
                relative_time(video_time, self.sync_state.video_time_origin_sec)
                if video_time is not None
                else None
            )
            values = (
                marker.kind.value,
                f"{display_time:.3f}" if display_time is not None else "--",
                marker.note,
            )
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if column == 1 and video_time is not None:
                    item.setData(self.VIDEO_TIME_ROLE, video_time)
                if column < 2:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)

    def handle_cell_clicked(self, row, column):
        """Seek to a peak when its displayed time is clicked."""
        if column != 1:
            return
        item = self.table.item(row, column)
        video_time = item.data(self.VIDEO_TIME_ROLE) if item is not None else None
        if video_time is not None:
            self.video_time_selected.emit(float(video_time))

    def delete_selected_peak(self):
        """Delete the selected peak through the canonical marker store."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return
        markers = self.peak_markers()
        row = selected_rows[0].row()
        if 0 <= row < len(markers):
            self.marker_store.delete(markers[row].marker_id)
            if self.table.rowCount() > 0:
                self.table.selectRow(min(row, self.table.rowCount() - 1))

    def add_lfp_peaks(self):
        if not self.video_player.has_video():
            QMessageBox.warning(self, "No video", "Please import a video first.")
            return
        if self.sync_state.time_offset_sec is None:
            QMessageBox.warning(
                self,
                "LFP is not synchronized",
                "Please synchronize the video and LFP before finding peaks.",
            )
            return
        channel = self.lfp_service.selected_channel()
        if channel is None:
            QMessageBox.warning(self, "No LFP channel", "Please select a channel.")
            return

        metadata = self.video_state.metadata
        duration = float(metadata.duration_sec)
        offset = float(self.sync_state.time_offset_sec)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            dataset = self.lfp_service.dataset()
            values = dataset.signal_values(channel, self.lfp_service.filter_settings())
            video_times = dataset.record_time_s + offset
            valid_indices = np.flatnonzero(
                (video_times >= 0.0) & (video_times <= duration)
            )
            peak_indices = np.array([], dtype=int)
            if valid_indices.size:
                first = int(valid_indices[0])
                last = int(valid_indices[-1]) + 1
                visible = values[first:last]
                baseline = float(np.nanmedian(visible))
                mad = float(np.nanmedian(np.abs(visible - baseline)))
                sigma = 1.4826 * mad
                if not np.isfinite(sigma) or sigma <= 0.0:
                    sigma = float(np.nanstd(visible))
                if not np.isfinite(sigma) or sigma <= 0.0:
                    sigma = np.finfo(float).eps
                local_peaks, _ = find_peaks(
                    visible,
                    height=baseline + self.LFP_PEAK_HEIGHT_SIGMA * sigma,
                    prominence=self.LFP_PEAK_PROMINENCE_SIGMA * sigma,
                    distance=max(
                        1,
                        round(
                            dataset.sample_rate_hz(channel)
                            * self.LFP_PEAK_MIN_DISTANCE_SEC
                        ),
                    ),
                )
                peak_indices = local_peaks + first

            markers = [
                Marker(
                    kind=MarkerKind.LFP_PEAK,
                    source=MarkerSource.LFP_DETECTION,
                    position=RecordPosition(float(dataset.record_time_s[index])),
                    note=f"channel={channel}, value={values[index]:.6g}, positive peak",
                    payload={"channel": channel, "value": float(values[index])},
                )
                for index in peak_indices
            ]
            self.marker_store.replace_by_source(MarkerSource.LFP_DETECTION, markers)
        except Exception as error:
            QMessageBox.warning(self, "Peak detection failed", str(error))
            return
        finally:
            QApplication.restoreOverrideCursor()

        QMessageBox.information(
            self, "LFP peaks", f"Added {len(peak_indices)} peak markers from channel {channel}."
        )
