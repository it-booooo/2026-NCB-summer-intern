from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..led_detection.status_text import format_led_detection_status
from ..app_state import LedState
from ..video_player.video_helpers import format_time, parse_time_input, time_sec_to_frame


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
        # The application stylesheet specifies label fonts in pixels, for which
        # QFont.pointSize() is -1.  Give this text-based spinner an explicit
        # point size so Qt never forwards that sentinel to setPointSize().
        indicator_font = self.font()
        indicator_font.setPointSize(9)
        self.setFont(indicator_font)
        self.frame_index = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.setFixedSize(14, 14)
        self.setAlignment(Qt.AlignCenter)
        self.set_state("idle")

    def advance(self):
        """Advance the current synchronization workflow to its next stage.

        Args:
            None.
        """
        self.frame_index = (self.frame_index + 1) % len(self.SPINNER_FRAMES)
        self.setText(self.SPINNER_FRAMES[self.frame_index])

    def _set_visual(self, text, color):
        self.setText(text)
        self.setStyleSheet(
            f"font-size: 9pt; color: {color}; "
            "background: transparent; border: none;"
        )

    def set_state(self, state):
        """Apply one ROI rendering state and its timer/tooltip behavior."""
        if state not in self.STATE_TOOLTIPS:
            raise ValueError(f"Unknown ROI plot state: {state}")

        self.timer.stop()
        self.frame_index = 0
        self.setToolTip(self.STATE_TOOLTIPS[state])
        if state == "rendering":
            self._set_visual(self.SPINNER_FRAMES[0], "#2f80ed")
            self.timer.start(120)
        elif state == "done":
            self._set_visual("●", "#2f80ed")
        elif state == "failed":
            self._set_visual("○", "#c0392b")
        else:
            self._set_visual("○", "#777777")
        self.show()


class SyncPanel(QWidget):
    def __init__(self, led_state=None):
        super().__init__()
        self.led_state = led_state or LedState()

        self.led_roi_label = QLabel("LED ROI: Not selected")
        self.analysis_info_button = QPushButton("Analysis Info")
        self.analysis_info_button.setFixedSize(108, 24)
        self.analysis_info_button.setStyleSheet(
            "font-size: 9pt; padding: 2px 6px;"
        )
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
        self.led_progress_bar.setTextVisible(False)
        self.led_progress_bar.setFixedHeight(6)
        self.led_progress_bar.setFixedWidth(300)
        self.led_progress_bar.setStyleSheet(
            """
            QProgressBar {
                background-color: #ffffff;
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #2f80ed;
                border-radius: 2px;
            }
            """
        )
        self.led_progress_label = QLabel("LED analysis: Not started")
        self.led_progress_label.setWordWrap(False)

        self.roi_plot_indicator = RoiPlotIndicator(self)

        self.marker_selector = QComboBox()
        self.marker_selector.addItems(["TTL", "Video", "Find Peak"])
        self.marker_selector.setFixedHeight(24)
        self.marker_stack = QStackedWidget()
        self.marker_selector.currentIndexChanged.connect(
            self.marker_stack.setCurrentIndex
        )

        self.led_scan_start_input.returnPressed.connect(
            self.normalize_led_scan_range_inputs
        )
        self.led_scan_end_input.returnPressed.connect(self.normalize_led_scan_range_inputs)

        for label in [
            self.led_roi_label,
            self.led_detection_label,
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
        progress_layout = QHBoxLayout()
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(6)
        progress_layout.addWidget(self.led_progress_bar)
        progress_layout.addWidget(self.led_progress_label, stretch=1)
        info_grid.addLayout(progress_layout, 3, 0, 1, 2)

        self.video_marker_controls = QWidget()
        self.video_marker_controls.setLayout(info_grid)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.marker_selector)
        layout.addWidget(self.marker_stack, stretch=1)
        self.setLayout(layout)

    def set_marker_panels(self, ttl_panel, video_marker_panel, find_peak_panel):
        """Set the panels shown by the Marker selector.

        Args:
            ttl_panel: TTL marker widget.
            video_marker_panel: Video marker widget.
            find_peak_panel: LFP peak marker widget.
        """
        while self.marker_stack.count():
            widget = self.marker_stack.widget(0)
            self.marker_stack.removeWidget(widget)
            widget.setParent(None)

        video_marker_panel.set_status_panel(self.video_marker_controls)
        for panel in (ttl_panel, video_marker_panel, find_peak_panel):
            self.marker_stack.addWidget(panel)

        self.marker_selector.setCurrentIndex(1)

    def set_led_roi(self, roi):
        """Set led roi.

        Args:
            roi: LED region of interest as (x, y, width, height).
        """
        self.led_state.roi = roi
        x, y, width, height = roi
        self.led_roi_label.setText(
            f"LED ROI: x={x}, y={y}, width={width}, height={height}"
        )

    def format_scan_input(self, widget):
        """Format scan input.

        Args:
            widget: Input used by this operation.
        """
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
        """Normalize led scan range inputs.

        Args:
            None.
        """
        start_ok = self.format_scan_input(self.led_scan_start_input)
        end_ok = self.format_scan_input(self.led_scan_end_input)
        if start_ok and end_ok:
            self.mark_scan_range_valid(True)

    def mark_scan_range_valid(self, is_valid):
        """Mark scan range valid.

        Args:
            is_valid: Input used by this operation.
        """
        style = "" if is_valid else "border: 1px solid #c0392b;"
        self.led_scan_start_input.setStyleSheet(style)
        self.led_scan_end_input.setStyleSheet(style)

    def led_scan_range_sec(self, fps, total_frames):
        """Provide led scan range sec functionality.

        Args:
            fps: Video frame rate in frames per second.
            total_frames: Input used by this operation.
        """
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

        scan_start_frame = (
            time_sec_to_frame(start_sec, fps, total_frames)
            if start_sec is not None
            else 0
        )
        scan_end_frame = (
            time_sec_to_frame(end_sec, fps, total_frames)
            if end_sec is not None
            else max(total_frames - 1, 0)
        )

        self.mark_scan_range_valid(True)
        return start_sec, end_sec, scan_start_frame, scan_end_frame

    def detect_multiple_led_events(self):
        """Detect multiple led events.

        Args:
            None.
        """
        return self.detect_multiple_led_checkbox.isChecked()

    def set_roi_plot_idle(self):
        """Set roi plot idle.

        Args:
            None.
        """
        self.led_state.analysis_points = None
        self.led_state.analysis_threshold = 0.0
        self.led_state.analysis_events = None
        self.led_state.analysis_stats = None
        self.led_state.analysis_status = None
        self.analysis_info_button.setEnabled(False)
        self.roi_plot_indicator.set_state("idle")
        self.led_progress_bar.setRange(0, 100)
        self.led_progress_bar.setValue(0)
        self.led_progress_label.setText("LED analysis: Not started")

    def set_led_analysis(self, points, threshold, events, stats=None, status=None):
        """Set led analysis.

        Args:
            points: Brightness or analysis points used by the operation.
            threshold: Input used by this operation.
            events: Event records to display, analyze, or export.
            stats: Input used by this operation.
            status: Input used by this operation.
        """
        self.led_state.analysis_points = list(points or [])
        self.led_state.analysis_threshold = float(threshold or 0.0)
        self.led_state.analysis_events = list(events or [])
        self.led_state.analysis_stats = dict(stats or {})
        self.led_state.analysis_status = status or format_led_detection_status(
            self.led_state.analysis_points,
            self.led_state.analysis_threshold,
            self.led_state.analysis_events,
            self.led_state.analysis_stats,
        )
        self.roi_plot_indicator.set_state(
            "done" if self.led_state.analysis_points else "empty"
        )
        self.analysis_info_button.setEnabled(True)

    def show_analysis_info(self):
        """Show analysis info.

        Args:
            None.
        """
        if self.led_state.analysis_status is None:
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
        status_items = self.led_state.analysis_status.split(" | ")
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
        points = self.led_state.analysis_points or []
        events = self.led_state.analysis_events or []
        stats = self.led_state.analysis_stats or {}
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
        threshold_value = stats.get("threshold", self.led_state.analysis_threshold)
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
        """Begin led detection progress.

        Args:
            None.
        """
        self.set_roi_plot_idle()
        self.roi_plot_indicator.set_state("rendering")
        self.led_progress_bar.setRange(0, 100)
        self.led_progress_bar.setValue(0)
        self.led_progress_label.setText("Analyzing LED ROI: 0%")

    def update_led_detection_progress(self, current_frame, total_frames):
        """Update led detection progress.

        Args:
            current_frame: Input used by this operation.
            total_frames: Input used by this operation.
        """
        if total_frames <= 0:
            self.led_progress_bar.setRange(0, 0)
            self.led_progress_label.setText(
                f"Analyzing LED ROI: frame {current_frame}"
            )
            return

        progress = int(min(max(current_frame / total_frames, 0.0), 1.0) * 100)
        self.led_progress_bar.setRange(0, 100)
        self.led_progress_bar.setValue(progress)
        self.led_progress_label.setText(
            f"Analyzing LED ROI: {progress}% ({current_frame}/{total_frames})"
        )

    def finish_led_detection_progress(self, has_events=True):
        """Finish led detection progress.

        Args:
            has_events: Input used by this operation.
        """
        self.led_progress_bar.setRange(0, 100)
        self.led_progress_bar.setValue(100)
        self.led_progress_label.setText(
            "LED analysis complete"
            if has_events
            else "LED scan complete: no events found"
        )

    def set_led_detection_stage(self, text):
        """Set led detection stage.

        Args:
            text: Text displayed to the user.
        """
        self.led_detection_label.setText(f"LED detection: {text}")
        self.led_progress_bar.setRange(0, 0)
        self.led_progress_label.setText(text)

    def fail_led_detection_progress(self):
        """Report failure for led detection progress.

        Args:
            None.
        """
        self.roi_plot_indicator.set_state("failed")
        self.led_progress_bar.setRange(0, 100)
        self.led_progress_bar.setValue(0)
        self.led_progress_label.setText("LED analysis failed")

    def set_led_detection_status(self, text):
        """Set led detection status.

        Args:
            text: Text displayed to the user.
        """
        self.led_detection_label.setText(text)
        self.led_detection_label.setToolTip(text)

