from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..led_status import format_led_detection_status
from ..video.video_utils import format_time, parse_time_input


class RoiPlotIndicator(QLabel):
    SPINNER_FRAMES = ("◜", "◝", "◞", "◟")
    STATE_TOOLTIPS = {
        "idle": "ROI plot has not been generated.",
        "rendering": "Analyzing LED ROI...",
        "done": "ROI plot generated.",
        "empty": "ROI plot generated without brightness data.",
        "failed": "LED analysis failed.",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame_index = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.setFixedSize(14, 14)
        self.setAlignment(Qt.AlignCenter)
        self.set_state("idle")

    def advance(self):
        self.frame_index = (self.frame_index + 1) % len(self.SPINNER_FRAMES)
        self.setText(self.SPINNER_FRAMES[self.frame_index])

    def set_state(self, state):
        """Apply one ROI rendering state and its timer/tooltip behavior."""
        if state not in self.STATE_TOOLTIPS:
            raise ValueError(f"Unknown ROI plot state: {state}")

        self.timer.stop()
        self.frame_index = 0
        self.state = state
        self.setToolTip(self.STATE_TOOLTIPS[state])
        if state == "rendering":
            self.setText(self.SPINNER_FRAMES[0])
            self.setStyleSheet(
                "color: #2f80ed; background: transparent; border: none;"
            )
            self.timer.start(120)
        elif state == "done":
            self.setText("●")
            self.setStyleSheet(
                "color: #2f80ed; background: transparent; border: none;"
            )
        elif state == "failed":
            self.setText("○")
            self.setStyleSheet(
                "color: #c0392b; background: transparent; border: none;"
            )
        else:
            self.setText("○")
            self.setStyleSheet(
                "color: #777777; background: transparent; border: none;"
            )
        self.show()


class SyncPanel(QWidget):
    def __init__(self):
        super().__init__()

        self.video_file_label = QLabel("Video file: Not imported")
        self.lfp_file_label = QLabel("LFP file: Not imported")
        self.video_led_label = QLabel("Video LED marker: Not selected")
        self.ttl_label = QLabel("TTL marker: Not loaded")
        self.led_roi_label = QLabel("LED ROI: Not selected")
        self.analysis_info_button = QPushButton("Analysis Info")
        self.analysis_info_button.setFixedSize(120, 26)
        self.analysis_info_button.setEnabled(False)
        self.analysis_info_button.clicked.connect(self.show_analysis_info)
        self.led_scan_start_input = QLineEdit()
        self.led_scan_start_input.setPlaceholderText("00:00.000")
        self.led_scan_start_input.setToolTip("LED scan start time. Blank = beginning.")
        self.led_scan_start_input.setFixedWidth(88)
        self.led_scan_end_input = QLineEdit()
        self.led_scan_end_input.setPlaceholderText("00:30.000")
        self.led_scan_end_input.setToolTip("LED scan end time. Blank = full video end.")
        self.led_scan_end_input.setFixedWidth(88)
        self.detect_multiple_led_checkbox = QCheckBox("Detect multiple LED events")
        self.led_detection_label = QLabel("LED detection: Not analyzed")
        self.led_progress_bar = QProgressBar()
        self.led_progress_bar.setRange(0, 100)
        self.led_progress_bar.setValue(0)
        self.led_progress_bar.setTextVisible(True)
        self.led_progress_bar.setFixedHeight(20)
        progress_size_policy = self.led_progress_bar.sizePolicy()
        progress_size_policy.setRetainSizeWhenHidden(True)
        self.led_progress_bar.setSizePolicy(progress_size_policy)
        self.led_progress_bar.hide()

        self.roi_plot_indicator = RoiPlotIndicator(self)

        self.offset_label = QLabel("Time offset: Not calculated")
        self.analysis_points = None
        self.analysis_threshold = 0.0
        self.analysis_events = None
        self.analysis_stats = None
        self.analysis_status = None

        self.led_scan_start_input.returnPressed.connect(
            self.normalize_led_scan_range_inputs
        )
        self.led_scan_end_input.returnPressed.connect(self.normalize_led_scan_range_inputs)

        for label in [
            self.video_file_label,
            self.lfp_file_label,
            self.video_led_label,
            self.ttl_label,
            self.led_roi_label,
            self.led_detection_label,
            self.offset_label,
        ]:
            label.setWordWrap(True)
            label.setContentsMargins(0, 0, 0, 0)
            label.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Maximum,
            )

        info_grid = QGridLayout()
        info_grid.setContentsMargins(0, 0, 0, 0)
        info_grid.setVerticalSpacing(1)
        info_grid.setColumnStretch(0, 1)
        info_grid.addWidget(self.led_roi_label, 0, 0)
        info_grid.addWidget(
            self.analysis_info_button,
            0,
            1,
            alignment=Qt.AlignRight | Qt.AlignVCenter,
        )

        scan_range_layout = QHBoxLayout()
        scan_range_layout.setContentsMargins(0, 0, 0, 0)
        scan_range_layout.setSpacing(4)
        scan_range_layout.addWidget(QLabel("LED scan range"))
        scan_range_layout.addWidget(self.led_scan_start_input)
        scan_range_layout.addWidget(QLabel("to"))
        scan_range_layout.addWidget(self.led_scan_end_input)
        scan_range_layout.addWidget(self.detect_multiple_led_checkbox)
        scan_range_layout.addStretch()
        info_grid.addLayout(scan_range_layout, 1, 0, 1, 2)

        led_status_layout = QHBoxLayout()
        led_status_layout.setContentsMargins(0, 0, 0, 0)
        led_status_layout.setSpacing(5)
        led_status_layout.addWidget(self.roi_plot_indicator)
        led_status_layout.addWidget(self.led_detection_label, stretch=1)
        info_grid.addLayout(led_status_layout, 2, 0, 1, 2)
        info_grid.addWidget(self.led_progress_bar, 3, 0, 1, 2)
        info_grid.addWidget(self.offset_label, 4, 0, 1, 2)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addLayout(info_grid)
        self.embedded_panels_layout = QHBoxLayout()
        self.embedded_panels_layout.setContentsMargins(0, 4, 0, 0)
        self.embedded_panels_layout.setSpacing(6)
        layout.addLayout(self.embedded_panels_layout, stretch=1)
        self.setLayout(layout)

    def set_embedded_panels(self, ttl_group, marker_group):
        self.embedded_panels_layout.addWidget(ttl_group, stretch=1)
        self.embedded_panels_layout.addWidget(marker_group, stretch=1)

    def set_video_path(self, path):
        self.video_file_label.setText(f"Video file: {Path(path).name}")

    def set_lfp_status(self, text):
        self.lfp_file_label.setText(text)

    def set_video_led_marker(self, video_time_sec):
        self.video_led_label.setText(f"Video LED marker: {video_time_sec:.3f} sec")

    def set_ttl_marker(self, ttl_time_sec):
        self.ttl_label.setText(f"TTL marker: {ttl_time_sec:.6f} sec")

    def set_led_roi(self, roi):
        x, y, width, height = roi
        self.led_roi_label.setText(
            f"LED ROI: x={x}, y={y}, width={width}, height={height}"
        )

    def format_scan_input(self, widget):
        text = widget.text().strip()
        if not text:
            widget.setStyleSheet("")
            return True

        seconds = parse_time_input(text)
        if seconds is None or seconds < 0:
            widget.setStyleSheet("border: 1px solid #c0392b;")
            return False

        widget.setStyleSheet("")
        widget.setText(format_time(seconds))
        return True

    def normalize_led_scan_range_inputs(self):
        start_ok = self.format_scan_input(self.led_scan_start_input)
        end_ok = self.format_scan_input(self.led_scan_end_input)
        if start_ok and end_ok:
            self.mark_scan_range_valid(True)

    def mark_scan_range_valid(self, is_valid):
        style = "" if is_valid else "border: 1px solid #c0392b;"
        self.led_scan_start_input.setStyleSheet(style)
        self.led_scan_end_input.setStyleSheet(style)

    def led_scan_range_sec(self):
        start_text = self.led_scan_start_input.text().strip()
        end_text = self.led_scan_end_input.text().strip()

        start_sec = parse_time_input(start_text)
        end_sec = parse_time_input(end_text)

        if start_text and start_sec is None:
            raise ValueError("Invalid LED scan start time.")

        if end_text and end_sec is None:
            raise ValueError("Invalid LED scan end time.")

        if start_sec is not None and start_sec < 0:
            raise ValueError("LED scan start time cannot be negative.")

        if end_sec is not None and end_sec < 0:
            raise ValueError("LED scan end time cannot be negative.")

        if start_sec is not None and end_sec is not None and start_sec >= end_sec:
            raise ValueError("LED scan start time must be earlier than end time.")

        self.mark_scan_range_valid(True)
        return start_sec, end_sec

    def detect_multiple_led_events(self):
        return self.detect_multiple_led_checkbox.isChecked()

    def set_roi_plot_idle(self):
        self.analysis_points = None
        self.analysis_threshold = 0.0
        self.analysis_events = None
        self.analysis_stats = None
        self.analysis_status = None
        self.analysis_info_button.setEnabled(False)
        self.roi_plot_indicator.set_state("idle")

    def set_led_analysis(self, points, threshold, events, stats=None, status=None):
        self.analysis_points = list(points or [])
        self.analysis_threshold = float(threshold or 0.0)
        self.analysis_events = list(events or [])
        self.analysis_stats = dict(stats or {})
        self.analysis_status = status or format_led_detection_status(
            self.analysis_points,
            self.analysis_threshold,
            self.analysis_events,
            self.analysis_stats,
        )
        self.roi_plot_indicator.set_state(
            "done" if self.analysis_points else "empty"
        )
        self.analysis_info_button.setEnabled(True)

    def show_analysis_info(self):
        if self.analysis_status is None:
            return

        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.figure import Figure

        dialog = QDialog(self)
        dialog.setWindowTitle("LED Analysis Info")
        dialog.resize(900, 620)

        status_grid = QGridLayout()
        status_grid.setHorizontalSpacing(24)
        status_grid.setVerticalSpacing(5)
        status_grid.setColumnStretch(0, 1)
        status_grid.setColumnStretch(1, 1)
        status_grid.setColumnStretch(2, 1)
        status_items = self.analysis_status.split(" | ")
        for index, text in enumerate(status_items):
            label = QLabel(text)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            status_grid.addWidget(label, index // 3, index % 3)

        figure = Figure(figsize=(8, 3.5), tight_layout=True)
        canvas = FigureCanvas(figure)
        canvas.setMinimumHeight(300)
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        ax = figure.add_subplot(111)
        points = self.analysis_points or []
        events = self.analysis_events or []
        stats = self.analysis_stats or {}
        times = [point.video_time_sec for point in points]
        delta_times = [points[index].video_time_sec for index in range(1, len(points))]
        delta_values = [
            points[index].brightness - points[index - 1].brightness
            for index in range(1, len(points))
        ]
        if points:
            if delta_values:
                ax.plot(delta_times, delta_values, linewidth=0.8)
            else:
                ax.plot(times, [0.0 for _ in times], linewidth=0.8)
            if len(times) == 1:
                ax.set_xlim(times[0] - 1.0, times[0] + 1.0)
            else:
                ax.set_xlim(min(times), max(times))
        else:
            ax.set_xlim(0.0, 1.0)
            ax.set_ylim(-1.0, 1.0)
        ax.axhline(0.0, color="gray", linestyle=":", linewidth=0.7)
        threshold_value = stats.get("threshold", self.analysis_threshold)
        if threshold_value > 0:
            ax.axhline(threshold_value, color="gray", linestyle="--", linewidth=0.6)
            ax.axhline(-threshold_value, color="gray", linestyle="--", linewidth=0.6)
        for event in events:
            color = "green" if event.event_type == "LED_on" else "red"
            ax.axvline(event.video_time_sec, color=color, linestyle="--", linewidth=0.8)
        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_ylabel("ROI Brightness Delta", fontsize=8)
        ax.tick_params(axis="both", labelsize=8, pad=1)
        ax.grid(True, linewidth=0.4, alpha=0.35)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)

        layout = QVBoxLayout(dialog)
        layout.addLayout(status_grid)
        layout.addWidget(canvas, stretch=1)
        layout.addWidget(buttons)
        canvas.draw_idle()
        dialog.exec()

    def begin_led_detection_progress(self):
        self.set_roi_plot_idle()
        self.roi_plot_indicator.set_state("rendering")
        self.led_progress_bar.setRange(0, 100)
        self.led_progress_bar.setValue(0)
        self.led_progress_bar.setFormat("Analyzing LED ROI: 0%")
        self.led_progress_bar.show()

    def update_led_detection_progress(self, current_frame, total_frames):
        if total_frames <= 0:
            self.led_progress_bar.setRange(0, 0)
            self.led_progress_bar.setFormat(f"Analyzing LED ROI: frame {current_frame}")
            self.led_progress_bar.show()
            return

        progress = int(min(max(current_frame / total_frames, 0.0), 1.0) * 100)
        self.led_progress_bar.setRange(0, 100)
        self.led_progress_bar.setValue(progress)
        self.led_progress_bar.setFormat(
            f"Analyzing LED ROI: {progress}% ({current_frame}/{total_frames})"
        )
        self.led_progress_bar.show()

    def finish_led_detection_progress(self, has_events=True):
        self.led_progress_bar.setRange(0, 100)
        self.led_progress_bar.setValue(100)
        self.led_progress_bar.setFormat(
            "LED analysis complete"
            if has_events
            else "LED scan complete: no events found"
        )
        self.led_progress_bar.show()

    def set_led_detection_stage(self, text):
        self.led_detection_label.setText(f"LED detection: {text}")
        self.led_progress_bar.setRange(0, 0)
        self.led_progress_bar.setFormat(text)
        self.led_progress_bar.show()

    def fail_led_detection_progress(self):
        self.roi_plot_indicator.set_state("failed")
        self.led_progress_bar.setRange(0, 100)
        self.led_progress_bar.setValue(0)
        self.led_progress_bar.setFormat("LED analysis failed")
        self.led_progress_bar.show()

    def set_led_detection_status(self, text):
        self.led_detection_label.setText(text)
        self.led_detection_label.setToolTip(text)

    def set_offset(self, offset_sec):
        self.offset_label.setText(f"Time offset (video - TTL): {offset_sec:.6f} sec")
