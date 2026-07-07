from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
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
        self.offset_label = QLabel("Time offset: Not calculated")

        self.note_label = QLabel(
            "This area will summarize video-LFP synchronization after LED and TTL markers are available."
        )
        self.note_label.setStyleSheet("color: #666;")

        info_grid = QGridLayout()
        info_grid.addWidget(self.video_file_label, 0, 0)
        info_grid.addWidget(self.lfp_file_label, 0, 1)
        info_grid.addWidget(self.video_led_label, 1, 0)
        info_grid.addWidget(self.ttl_label, 1, 1)
        info_grid.addWidget(self.offset_label, 2, 0, 1, 2)

        layout = QVBoxLayout()
        layout.addLayout(info_grid)
        layout.addWidget(self.note_label)

        self.setLayout(layout)

    def set_video_path(self, path):
        self.video_file_label.setText(f"Video file: {path}")

    def set_lfp_status(self, text):
        self.lfp_file_label.setText(text)

    def set_video_led_marker(self, video_time_sec):
        self.video_led_label.setText(f"Video LED marker: {video_time_sec:.3f} sec")

    def set_ttl_marker(self, ttl_time_sec):
        self.ttl_label.setText(f"TTL marker: {ttl_time_sec:.6f} sec")

    def set_offset(self, offset_sec):
        self.offset_label.setText(f"Time offset: {offset_sec:.6f} sec")