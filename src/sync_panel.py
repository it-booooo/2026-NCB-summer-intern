from pathlib import Path

from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class SyncPanel(QWidget):
    def __init__(self):
        super().__init__()

        self.video_file_label = QLabel("Video file: Not imported")
        self.lfp_file_label = QLabel("LFP file: Not imported")
        self.video_led_label = QLabel("Video LED marker: Not selected")
        self.ttl_label = QLabel("TTL marker: Not loaded")
        self.led_roi_label = QLabel("LED ROI: Not selected")
        self.led_detection_label = QLabel("LED detection: Not analyzed")
        self.led_progress_bar = QProgressBar()
        self.led_progress_bar.setRange(0, 100)
        self.led_progress_bar.setValue(0)
        self.led_progress_bar.setTextVisible(True)
        self.led_progress_bar.hide()
        self.offset_label = QLabel("Time offset: Not calculated")
        self.led_curve_canvas = None

        self.note_label = QLabel(
            "This area will summarize video-LFP synchronization after LED and TTL markers are available."
        )
        self.note_label.setStyleSheet("color: #666;")

        for label in [
            self.video_file_label,
            self.lfp_file_label,
            self.video_led_label,
            self.ttl_label,
            self.led_roi_label,
            self.led_detection_label,
            self.offset_label,
            self.note_label,
        ]:
            label.setWordWrap(True)

        info_grid = QGridLayout()
        info_grid.addWidget(self.video_file_label, 0, 0)
        info_grid.addWidget(self.lfp_file_label, 0, 1)
        info_grid.addWidget(self.video_led_label, 1, 0)
        info_grid.addWidget(self.ttl_label, 1, 1)
        info_grid.addWidget(self.led_roi_label, 2, 0, 1, 2)
        info_grid.addWidget(self.led_detection_label, 3, 0, 1, 2)
        info_grid.addWidget(self.led_progress_bar, 4, 0, 1, 2)
        info_grid.addWidget(self.offset_label, 5, 0, 1, 2)

        self.action_layout = QHBoxLayout()
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(self.action_layout)
        layout.addLayout(info_grid)
        layout.addWidget(self.note_label)
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

    def set_led_analysis(self, points, threshold, events, baseline=None, stats=None):
        if not points:
            self.led_detection_label.setText("LED detection: No brightness data")
            return

        interval_count = len(events) // 2
        mode_label = stats["mode_label"] if stats is not None else "LED score"
        is_frame_delta = stats is not None and stats.get("mode", "").startswith("frame_delta")
        if is_frame_delta:
            event_status = (
                f"on delta={stats.get('selected_on_delta', 0.0):.4f}"
                f" at {stats.get('selected_on_time_sec', 0.0):.3f}s | "
                f"off delta={stats.get('selected_off_delta', 0.0):.4f}"
                f" at {stats.get('selected_off_time_sec', 0.0):.3f}s"
                if interval_count
                else "no LED event selected"
            )
            status = (
                f"LED detection: {mode_label} | {interval_count} intervals | "
                f"step={stats.get('coarse_step', 1)} | "
                f"{'refined' if stats.get('refined') else 'coarse only'} | "
                f"{event_status}"
            )
        else:
            status = (
                f"LED detection: {mode_label} | "
                f"{interval_count} intervals | threshold={threshold:.4f}"
            )
            if baseline is not None:
                status += f" | baseline={baseline:.4f}"

        if stats is not None and not is_frame_delta:
            status += (
                f" | max={stats['max']:.4f}"
                f" at {stats['peak_time_sec']:.3f}s"
            )
        self.led_detection_label.setText(status)

        if self.led_curve_canvas is not None:
            self.led_curve_canvas.setParent(None)
            self.led_curve_canvas.deleteLater()

        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.figure import Figure

        figure = Figure(figsize=(5, 1.8), tight_layout=True)
        canvas = FigureCanvas(figure)
        canvas.setMinimumHeight(120)
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        ax = figure.add_subplot(111)
        times = [point.video_time_sec for point in points]
        values = [point.brightness for point in points]
        ax.plot(times, values, linewidth=0.8)
        for event in events:
            color = "green" if event.event_type == "LED_on" else "red"
            ax.axvline(event.video_time_sec, color=color, linestyle="--", linewidth=0.8)
        if baseline is not None and not is_frame_delta:
            ax.axhline(baseline, color="gray", linestyle=":", linewidth=0.8)
        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_ylabel("Grayscale mean brightness", fontsize=8)
        ax.tick_params(axis="both", labelsize=8, pad=1)
        ax.grid(True, linewidth=0.4, alpha=0.35)

        self.led_curve_area.addWidget(canvas)
        self.led_curve_canvas = canvas
        canvas.draw_idle()

    def begin_led_detection_progress(self):
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

    def fail_led_detection_progress(self):
        self.led_progress_bar.setRange(0, 100)
        self.led_progress_bar.setValue(0)
        self.led_progress_bar.setFormat("LED analysis failed")
        self.led_progress_bar.show()

    def set_led_detection_status(self, text):
        self.led_detection_label.setText(text)

    def set_offset(self, offset_sec):
        self.offset_label.setText(f"Time offset: {offset_sec:.6f} sec")
