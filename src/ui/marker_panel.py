import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from scipy.signal import find_peaks


class MarkerPanel(QWidget):
    MAX_LFP_PEAK_MARKERS = 50
    LFP_PEAK_HEIGHT_SIGMA = 8.0
    LFP_PEAK_PROMINENCE_SIGMA = 6.0
    LFP_PEAK_HEIGHT_PERCENTILE = 99.9
    LFP_PEAK_MIN_DISTANCE_SEC = 1.0

    def __init__(
        self,
        event_table,
        video_player,
        lfp_panel=None,
        sync_state=None,
    ):
        super().__init__()

        self.event_table = event_table
        self.video_player = video_player
        self.lfp_panel = lfp_panel
        self.sync_state = sync_state

        led_on_button = QPushButton("LED On")
        led_off_button = QPushButton("LED Off")
        select_roi_button = QPushButton("Select LED")
        behavior_start_button = QPushButton("Action Start")
        behavior_end_button = QPushButton("Action End")
        seizure_button = QPushButton("Seizure-like")
        edit_button = QPushButton("Edit Selected")
        delete_button = QPushButton("Delete Selected")
        find_peaks_button = QPushButton("Find LFP Peaks")

        for button in (
            led_on_button,
            led_off_button,
            select_roi_button,
            behavior_start_button,
            behavior_end_button,
            seizure_button,
            edit_button,
            delete_button,
            find_peaks_button,
        ):
            button.setFixedHeight(22)

        select_roi_button.setToolTip("Select LED area and run brightness detection")

        led_on_button.clicked.connect(lambda: self.add_event("LED_on"))
        led_off_button.clicked.connect(lambda: self.add_event("LED_off"))
        select_roi_button.clicked.connect(self.select_led_roi)
        behavior_start_button.clicked.connect(lambda: self.add_event("behavior_start"))
        behavior_end_button.clicked.connect(lambda: self.add_event("behavior_end"))
        seizure_button.clicked.connect(lambda: self.add_event("seizure_like_event"))
        edit_button.clicked.connect(self.event_table.edit_selected_event)
        delete_button.clicked.connect(self.event_table.delete_selected_rows)
        find_peaks_button.clicked.connect(self.add_lfp_peaks)

        button_layout = QGridLayout()
        button_layout.setContentsMargins(2, 2, 2, 2)
        button_layout.setHorizontalSpacing(2)
        button_layout.setVerticalSpacing(2)
        for column in range(6):
            button_layout.setColumnStretch(column, 1)
        button_layout.addWidget(select_roi_button, 0, 0, 1, 2)
        button_layout.addWidget(led_on_button, 0, 2, 1, 2)
        button_layout.addWidget(led_off_button, 0, 4, 1, 2)
        button_layout.addWidget(behavior_start_button, 1, 0, 1, 2)
        button_layout.addWidget(behavior_end_button, 1, 2, 1, 2)
        button_layout.addWidget(seizure_button, 1, 4, 1, 2)
        button_layout.addWidget(delete_button, 2, 0, 1, 3)
        button_layout.addWidget(edit_button, 2, 3, 1, 3)
        button_layout.addWidget(find_peaks_button, 3, 0, 1, 6)

        layout = QVBoxLayout()
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        layout.addLayout(button_layout)
        layout.addWidget(self.event_table)

        self.setLayout(layout)

    def add_event(self, event_type):
        """Add a manual event at the current video position."""
        if not self.video_player.has_video():
            QMessageBox.warning(self, "No video", "Please import a video first.")
            return

        self.event_table.add_event(
            event_type=event_type,
            video_time_sec=self.video_player.current_time_sec(),
            frame_index=self.video_player.video_state.current_frame,
            note="",
        )

    def select_led_roi(self):
        """Start LED ROI selection for the loaded video."""
        if not self.video_player.has_video():
            QMessageBox.warning(self, "No video", "Please import a video first.")
            return

        self.video_player.start_roi_selection()

    def add_lfp_peaks(self):
        """Detect peaks in the selected LFP channel and add video markers."""
        if self.lfp_panel is None or self.sync_state is None:
            return
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

        metadata = self.video_player.video_state.metadata
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

                extreme_height = float(
                    np.nanpercentile(
                        visible_values,
                        self.LFP_PEAK_HEIGHT_PERCENTILE,
                    )
                )
                minimum_height = max(
                    baseline + self.LFP_PEAK_HEIGHT_SIGMA * noise_sigma,
                    extreme_height,
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
                local_peaks, properties = find_peaks(
                    visible_values,
                    height=minimum_height,
                    prominence=minimum_prominence,
                    distance=minimum_distance,
                )
                peak_indices = local_peaks + first_index
                peak_prominences = properties["prominences"]
            else:
                peak_indices = np.array([], dtype=int)
                peak_prominences = np.array([], dtype=float)

            detected_count = len(peak_indices)
            if detected_count > self.MAX_LFP_PEAK_MARKERS:
                strongest = np.argpartition(
                    peak_prominences,
                    -self.MAX_LFP_PEAK_MARKERS,
                )[-self.MAX_LFP_PEAK_MARKERS:]
                peak_indices = np.sort(peak_indices[strongest])

            self.event_table.delete_events_by_source("lfp_peak")
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

            if len(peak_indices):
                self.event_table.events_changed.emit()
        except Exception as error:
            QMessageBox.warning(self, "Peak detection failed", str(error))
            return
        finally:
            QApplication.restoreOverrideCursor()

        added = len(peak_indices)
        limit_note = (
            f"\nDetected {detected_count}; kept the {added} most prominent peaks."
            if detected_count > added
            else ""
        )
        QMessageBox.information(
            self,
            "LFP peaks",
            f"Added {added} peak markers from channel {channel}.{limit_note}",
        )
