from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.video_utils import format_time


class RoiPlotIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle = 0
        self.state = "idle"
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.setFixedSize(14, 14)
        self.setToolTip("ROI plot has not been generated.")

    def advance(self):
        self.angle = (self.angle + 35) % 360
        self.update()

    def set_idle(self):
        self.timer.stop()
        self.angle = 0
        self.state = "idle"
        self.setToolTip("ROI plot has not been generated.")
        self.show()
        self.update()

    def start_rendering(self):
        self.angle = 0
        self.state = "rendering"
        self.setToolTip("Generating ROI plot...")
        self.show()
        self.timer.start(80)
        self.update()

    def set_done(self, has_points):
        self.timer.stop()
        self.state = "done" if has_points else "empty"
        self.setToolTip(
            "ROI plot generated."
            if has_points
            else "ROI plot generated without brightness data."
        )
        self.show()
        self.update()

    def set_failed(self):
        self.timer.stop()
        self.state = "failed"
        self.setToolTip("LED analysis failed.")
        self.show()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)

        if self.state == "done":
            painter.setBrush(QColor("#2f80ed"))
            painter.setPen(QPen(QColor("#2f80ed"), 2))
            painter.drawEllipse(rect)
            return

        if self.state == "failed":
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#c0392b"), 2))
            painter.drawEllipse(rect)
            return

        if self.state == "rendering":
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#d2e4ff"), 2))
            painter.drawEllipse(rect)
            painter.setPen(QPen(QColor("#2f80ed"), 2))
            painter.drawArc(rect, self.angle * 16, 115 * 16)
            return

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#777777"), 2))
        painter.drawEllipse(rect)


class SyncPanel(QWidget):
    def __init__(self):
        super().__init__()

        self.video_file_label = QLabel("Video file: Not imported")
        self.lfp_file_label = QLabel("LFP file: Not imported")
        self.video_led_label = QLabel("Video LED marker: Not selected")
        self.ttl_label = QLabel("TTL marker: Not loaded")
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
        self.led_progress_bar.setTextVisible(True)
        self.led_progress_bar.hide()

        self.roi_plot_indicator = RoiPlotIndicator(self)
        self.roi_plot_indicator.set_idle()

        self.offset_label = QLabel("Time offset: Not calculated")
        self.led_curve_canvas = None

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

        info_grid = QGridLayout()
        info_grid.setVerticalSpacing(4)
        info_grid.addWidget(self.led_roi_label, 0, 0, 1, 2)

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

        self.action_layout = QHBoxLayout()
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.addStretch()

        layout = QVBoxLayout()
        layout.setSpacing(4)
        layout.addLayout(self.action_layout)
        layout.addLayout(info_grid)
        self.led_curve_area = QVBoxLayout()
        layout.addLayout(self.led_curve_area, stretch=1)

        self.setLayout(layout)

    def add_top_left_widget(self, widget):
        self.action_layout.insertWidget(0, widget)

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

    def parse_time_input(self, text):
        text = text.strip()
        if not text:
            return None

        try:
            if ":" not in text:
                return float(text)

            parts = [float(part) for part in text.split(":")]
            if len(parts) == 2:
                minutes, seconds = parts
                return minutes * 60 + seconds

            if len(parts) == 3:
                hours, minutes, seconds = parts
                return hours * 3600 + minutes * 60 + seconds
        except ValueError:
            return None

        return None

    def format_scan_input(self, widget):
        text = widget.text().strip()
        if not text:
            widget.setStyleSheet("")
            return True

        seconds = self.parse_time_input(text)
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

        start_sec = self.parse_time_input(start_text)
        end_sec = self.parse_time_input(end_text)

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
        self.roi_plot_indicator.set_idle()

    def begin_roi_plot_render(self):
        self.roi_plot_indicator.start_rendering()

    def finish_roi_plot_render(self, has_points):
        self.roi_plot_indicator.set_done(has_points)

    def set_led_analysis(self, points, threshold, events, stats=None):
        points = points or []
        events = events or []
        stats = stats or {}
        self.begin_roi_plot_render()
        self.led_detection_label.setText(
            f"Generating ROI plot... points={len(points)}"
        )
        QTimer.singleShot(
            50,
            lambda: self.render_led_analysis(
                points,
                threshold,
                events,
                stats=stats,
            ),
        )

    def render_led_analysis(self, points, threshold, events, stats=None):
        stats = stats or {}

        if self.led_curve_canvas is not None:
            self.led_curve_canvas.setParent(None)
            self.led_curve_canvas.deleteLater()
            self.led_curve_canvas = None
        while self.led_curve_area.count():
            item = self.led_curve_area.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        if not points:
            self.led_detection_label.setText("LED detection: No brightness data")
        else:
            interval_count = stats.get("event_count", len(events) // 2)
            mode_label = stats.get("mode_label", "Frame delta (ROI mean brightness)")
            event_status = (
                f"event pairs={interval_count}"
                if interval_count
                else "no LED event selected"
            )
            status = (
                f"LED detection: {mode_label} | {interval_count} intervals | "
                f"scan frames={stats.get('scan_start_frame', 0)}-{stats.get('scan_end_frame', 0)} | "
                f"coarse step={stats.get('coarse_step', 20)} frames | "
                f"refine window={stats.get('refine_window_sec', 1.0):.1f}s | "
                f"points={stats.get('points_count', len(points))} | "
                f"{'multiple' if stats.get('detect_multiple') else 'single'} | "
                f"threshold={stats.get('threshold', threshold):.6f} | "
                f"duration={stats.get('min_duration_sec', 0.6):.1f}-{stats.get('max_duration_sec', 1.5):.1f}s "
                f"target={stats.get('expected_duration_sec', 1.0):.1f}s | "
                f"{event_status}"
            )
            status += self.format_timing_status(stats)
            status += self.format_acceleration_status(stats)
            self.led_detection_label.setText(status)
            self.led_detection_label.setToolTip(status)

        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.figure import Figure

        figure = Figure(figsize=(5, 1.8), tight_layout=True)
        canvas = FigureCanvas(figure)
        canvas.setMinimumHeight(120)
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        ax = figure.add_subplot(111)
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
        threshold_value = stats.get("threshold", threshold)
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

        self.led_curve_area.addWidget(canvas)
        self.led_curve_canvas = canvas
        canvas.draw_idle()
        QTimer.singleShot(
            250,
            lambda has_points=bool(points): self.finish_roi_plot_render(has_points),
        )

    def begin_led_detection_progress(self):
        self.set_roi_plot_idle()
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

    def finish_led_detection_progress(self):
        self.led_progress_bar.setRange(0, 100)
        self.led_progress_bar.setValue(100)
        self.led_progress_bar.setFormat("LED analysis complete")
        self.led_progress_bar.show()

    def set_led_detection_stage(self, text):
        self.led_detection_label.setText(f"LED detection: {text}")
        self.led_progress_bar.setRange(0, 0)
        self.led_progress_bar.setFormat(text)
        self.led_progress_bar.show()

    def fail_led_detection_progress(self):
        self.roi_plot_indicator.set_failed()
        self.led_progress_bar.setRange(0, 100)
        self.led_progress_bar.setValue(0)
        self.led_progress_bar.setFormat("LED analysis failed")
        self.led_progress_bar.show()

    def set_led_detection_status(self, text):
        self.led_detection_label.setText(text)
        self.led_detection_label.setToolTip(text)

    def format_timing_status(self, stats):
        return (
            f" | scan={stats.get('scan_elapsed_sec', 0.0):.1f}s"
            f" detect={stats.get('detect_elapsed_sec', 0.0):.1f}s"
        )

    def format_acceleration_status(self, stats):
        backend = stats.get("brightness_backend")
        status = ""
        if backend == "opencl":
            status += (
                f" | brightness=OpenCL"
                f" device={stats.get('opencl_device', 'GPU')}"
                f" selected={stats.get('opencl_selected_reason', 'auto')}"
                f" batch={stats.get('opencl_batch_mode', 'fixed')}"
                f" capacity={stats.get('opencl_batch_capacity', 0)}"
                f" batches={stats.get('opencl_batches', 0)}"
                f" max_batch={stats.get('opencl_max_batch_frames', 0)}"
            )
        elif backend == "cpu":
            status += " | brightness=CPU"
            if stats.get("opencl_fallback_reason"):
                status += (
                    f" (OpenCL fallback: {stats.get('opencl_fallback_reason')})"
                )
        elif backend == "cache":
            status += " | brightness=cached"

        if stats.get("video_decode_backend"):
            status += f" | decode={stats.get('video_decode_backend')}"
            if (
                stats.get("video_decode_backend") == "opencv_cpu"
                and stats.get("video_decode_fallback_reason")
            ):
                status += " (hw fallback)"

        return status

    def set_offset(self, offset_sec):
        self.offset_label.setText(f"Time offset (video - TTL): {offset_sec:.6f} sec")
