from typing import ClassVar

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
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

from ..app_state import LedState
from ..led_detection.status_text import format_led_detection_status
from ..markers import MarkerKind, MarkerSource, marker_video_time
from ..video_player.video_helpers import (
    format_time,
    parse_time_input,
    time_sec_to_frame,
)
from .marker_view_panel import MarkerViewPanel


class RoiPlotIndicator(QLabel):
    SPINNER_FRAMES = ("◜", "◝", "◞", "◟")
    STATE_TOOLTIPS: ClassVar[dict[str, str]] = {
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


class LedAnalysisPanel(MarkerViewPanel):
    """LED ROI selection, scan controls, progress, and analysis details."""

    def __init__(self, led_state=None, video_player=None, marker_store=None):
        if marker_store is None:
            raise ValueError("LedAnalysisPanel requires the shared MarkerStore.")
        super().__init__(marker_store)
        self.led_state = led_state or LedState()
        self.video_player = video_player

        self.led_roi_label = QLabel("LED ROI: Not selected")
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

        self.select_roi_button = QPushButton("Select LED")
        self.select_roi_button.setFixedHeight(24)
        self.select_roi_button.clicked.connect(self.select_led_roi)

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
        info_grid.addWidget(self.led_roi_label, 0, 0, 1, 2)

        scan_range_layout = QHBoxLayout()
        scan_range_layout.setContentsMargins(0, 0, 0, 0)
        scan_range_layout.setSpacing(4)
        scan_range_layout.addWidget(self.select_roi_button)
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

        self.analysis_status_labels = []
        self.analysis_status_grid = QGridLayout()
        self.analysis_status_grid.setContentsMargins(0, 0, 0, 0)
        self.analysis_status_grid.setHorizontalSpacing(18)
        self.analysis_status_grid.setVerticalSpacing(4)
        for column in range(4):
            self.analysis_status_grid.setColumnStretch(column, 1)

        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.figure import Figure

        self.analysis_figure = Figure(figsize=(8, 2.2), tight_layout=True)
        self.analysis_canvas = FigureCanvas(self.analysis_figure)
        self.analysis_canvas.setMinimumHeight(180)
        self.analysis_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.analysis_details = QWidget()
        analysis_details_layout = QVBoxLayout()
        analysis_details_layout.setContentsMargins(0, 0, 0, 0)
        analysis_details_layout.setSpacing(4)
        analysis_details_layout.addLayout(self.analysis_status_grid)
        analysis_details_layout.addWidget(self.analysis_canvas, stretch=1)
        self.analysis_details.setLayout(analysis_details_layout)
        self.analysis_details.setVisible(False)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.video_marker_controls, 0, Qt.AlignTop)
        layout.addWidget(self.analysis_details, stretch=1)
        layout.addStretch(1)
        self.setLayout(layout)

    def accepts_marker(self, marker):
        return marker.source == MarkerSource.LED_DETECTION

    def refresh_markers(self):
        pass

    def select_led_roi(self):
        if self.video_player is None or not self.video_player.has_video():
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "No video", "Please import a video first.")
            return
        self.video_player.start_roi_selection()

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
        self.led_state.analysis_stats = None
        self.led_state.analysis_status = None
        self.clear_analysis_details()
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
        self.led_state.analysis_stats = dict(stats or {})
        self.led_state.analysis_status = status or format_led_detection_status(
            self.led_state.analysis_points,
            self.led_state.analysis_threshold,
            events,
            self.led_state.analysis_stats,
        )
        self.roi_plot_indicator.set_state(
            "done" if self.led_state.analysis_points else "empty"
        )
        self.update_analysis_details(events)

    def clear_analysis_details(self):
        """Clear the embedded LED analysis details."""
        self.clear_analysis_status_grid()
        self.analysis_figure.clear()
        self.analysis_canvas.draw_idle()
        self.analysis_details.setVisible(False)

    def clear_analysis_status_grid(self):
        """Remove all status labels from the embedded analysis grid."""
        while self.analysis_status_grid.count():
            item = self.analysis_status_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self.analysis_status_labels = []

    def update_analysis_details(self, events=None):
        """Render LED analysis status and plot below the progress bar."""
        if self.led_state.analysis_status is None:
            return

        self.clear_analysis_status_grid()

        status_items = self.compact_analysis_status_items()
        for index, text in enumerate(status_items):
            label = QLabel(text)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.analysis_status_grid.addWidget(label, index // 4, index % 4)
            self.analysis_status_labels.append(label)

        self.analysis_figure.clear()
        ax = self.analysis_figure.add_subplot(111)
        points = self.led_state.analysis_points or []
        if events is None:
            events = self.marker_store.by_source(MarkerSource.LED_DETECTION)
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
        for marker in events:
            video_time = marker_video_time(marker, None)
            if video_time is None:
                continue
            color = "green" if marker.kind == MarkerKind.LED_ON else "red"
            ax.axvline(video_time, color=color, linestyle="--", linewidth=0.8)
        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_ylabel("ROI Brightness Delta", fontsize=8)
        ax.tick_params(axis="both", labelsize=8, pad=1)
        ax.grid(True, linewidth=0.4, alpha=0.35)
        self.analysis_details.setVisible(True)
        self.analysis_canvas.draw_idle()

    def compact_analysis_status_items(self):
        """Return the most useful LED analysis fields for inline display."""
        if not self.led_state.analysis_status:
            return []

        raw_items = self.led_state.analysis_status.split(" | ")
        selected = []
        wanted_fragments = (
            "interval",
            "scan frames=",
            "points=",
            "single",
            "multiple",
            "threshold=",
            "duration=",
            "scan=",
            "brightness=",
        )
        for item in raw_items:
            if not selected:
                selected.append(item)
                continue
            if any(fragment in item for fragment in wanted_fragments):
                selected.append(item)
            if len(selected) >= 8:
                break

        return selected

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



