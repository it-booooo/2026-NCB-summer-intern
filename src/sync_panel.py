from pathlib import Path

from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
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
        info_grid.addWidget(self.offset_label, 4, 0, 1, 2)

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
        status = f"LED detection: {interval_count} intervals | threshold={threshold:.4f}"
        if baseline is not None:
            status += f" | baseline={baseline:.4f}"
        if stats is not None:
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
        ax.axhline(threshold, color="red", linestyle="--", linewidth=0.8)
        if baseline is not None:
            ax.axhline(baseline, color="gray", linestyle=":", linewidth=0.8)
        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_ylabel("Brightness", fontsize=8)
        ax.tick_params(axis="both", labelsize=8, pad=1)
        ax.grid(True, linewidth=0.4, alpha=0.35)

        self.led_curve_area.addWidget(canvas)
        self.led_curve_canvas = canvas
        canvas.draw_idle()

    def set_led_detection_status(self, text):
        self.led_detection_label.setText(text)

    def set_offset(self, offset_sec):
        self.offset_label.setText(f"Time offset: {offset_sec:.6f} sec")
