import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from scipy.signal import find_peaks


class FindPeakPanel(QWidget):
    DISPLAY_HEADERS = ["event type", "video time", "note"]
    LFP_PEAK_HEIGHT_SIGMA = 8.0
    LFP_PEAK_PROMINENCE_SIGMA = 6.0
    LFP_PEAK_MIN_DISTANCE_SEC = 1.0

    def __init__(self, app_state, event_table, video_player, lfp_panel):
        super().__init__()
        self.video_state = app_state.video
        self.sync_state = app_state.sync
        self.event_state = app_state.events
        self.event_table = event_table
        self.video_player = video_player
        self.lfp_panel = lfp_panel

        find_peaks_button = QPushButton("Find Peak")
        find_peaks_button.setFixedHeight(26)
        find_peaks_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        find_peaks_button.clicked.connect(self.add_lfp_peaks)

        self.table = QTableWidget(0, len(self.DISPLAY_HEADERS))
        self.table.setHorizontalHeaderLabels(self.DISPLAY_HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)

        header = self.table.horizontalHeader()
        header.setFixedHeight(24)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 92)
        self.table.setColumnWidth(1, 92)
        self.table.setStyleSheet(
            """
            QTableWidget::item:selected {
                background-color: #dcecff;
                color: #111111;
                border: 1px solid #2f80ed;
            }
            """
        )
        self.event_table.events_changed.connect(self.refresh_table)

        layout = QVBoxLayout()
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(6)
        layout.addWidget(find_peaks_button)
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.refresh_table()

    def refresh_table(self):
        self.table.setRowCount(0)
        peak_events = [
            event
            for event in self.event_state.events
            if event.get("source") == "lfp_peak"
        ]
        for row, event in enumerate(peak_events):
            self.table.insertRow(row)
            values = [
                str(event.get("event_type", "")),
                f"{float(event.get('video_time_sec', 0.0)):.3f}",
                str(event.get("note", "")),
            ]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if column < 2:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)

    def add_lfp_peaks(self):
        """Detect peaks in the selected LFP channel and add video markers."""
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

        channel = self.lfp_panel.selected_channel(
            self.lfp_panel.lfp_channel_selector
        )
        if channel is None:
            QMessageBox.warning(self, "No LFP channel", "Please select a channel.")
            return

        metadata = self.video_state.metadata
        fps = float(metadata.using_fps)
        duration = float(metadata.duration_sec)
        offset = float(self.sync_state.time_offset_sec)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            dataset = self.lfp_panel.ensure_lfp_dataset()
            settings = self.lfp_panel.current_lfp_filter_settings()
            values = dataset.signal_values(channel, settings)

            video_times = dataset.record_time_s + offset
            in_video = (video_times >= 0.0) & (video_times <= duration)
            valid_indices = np.flatnonzero(in_video)
            if valid_indices.size:
                first_index = int(valid_indices[0])
                last_index = int(valid_indices[-1]) + 1
                visible_values = values[first_index:last_index]
                baseline = float(np.nanmedian(visible_values))
                mad = float(np.nanmedian(np.abs(visible_values - baseline)))
                noise_sigma = 1.4826 * mad
                if not np.isfinite(noise_sigma) or noise_sigma <= 0.0:
                    noise_sigma = float(np.nanstd(visible_values))
                if not np.isfinite(noise_sigma) or noise_sigma <= 0.0:
                    noise_sigma = np.finfo(float).eps

                minimum_height = (
                    baseline + self.LFP_PEAK_HEIGHT_SIGMA * noise_sigma
                )
                minimum_prominence = (
                    self.LFP_PEAK_PROMINENCE_SIGMA * noise_sigma
                )
                minimum_distance = max(
                    1,
                    int(
                        round(
                            dataset.sample_rate_hz(channel)
                            * self.LFP_PEAK_MIN_DISTANCE_SEC
                        )
                    ),
                )
                local_peaks, _ = find_peaks(
                    visible_values,
                    height=minimum_height,
                    prominence=minimum_prominence,
                    distance=minimum_distance,
                )
                peak_indices = local_peaks + first_index
            else:
                peak_indices = np.array([], dtype=int)

            self.event_table.delete_events_by_source("lfp_peak", emit=False)
            for peak_index in peak_indices:
                video_time_sec = float(video_times[peak_index])
                frame_index = min(
                    max(int(round(video_time_sec * fps)), 0),
                    max(int(metadata.total_frames) - 1, 0),
                )
                self.event_table.add_event(
                    event_type="LFP_peak",
                    video_time_sec=video_time_sec,
                    frame_index=frame_index,
                    note=(
                        f"channel={channel}, value={values[peak_index]:.6g}, "
                        "positive peak"
                    ),
                    source="lfp_peak",
                    emit=False,
                )

            # Redraw once, after the complete replacement is visible in EventState.
            self.event_table.events_changed.emit()
        except Exception as error:
            QMessageBox.warning(self, "Peak detection failed", str(error))
            return
        finally:
            QApplication.restoreOverrideCursor()

        added = len(peak_indices)
        QMessageBox.information(
            self,
            "LFP peaks",
            f"Added {added} peak markers from channel {channel}.",
        )
