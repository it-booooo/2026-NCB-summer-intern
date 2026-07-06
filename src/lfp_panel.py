from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class LfpPanel(QWidget):
    def __init__(self):
        super().__init__()

        self.lfp_path = None
        self.axis_path = None
        self.time_marker_path = None

        self.lfp_file_label = QLabel("LFP CSV: Not imported")
        self.axis_file_label = QLabel("3-axis CSV: Not imported")
        self.time_marker_file_label = QLabel("Time marker CSV: Not imported")

        self.lfp_channel_selector = QComboBox()
        self.lfp_channel_selector.addItem("No LFP channel")
        self.lfp_channel_selector.setEnabled(False)

        self.axis_channel_selector = QComboBox()
        self.axis_channel_selector.addItem("No 3-axis channel")
        self.axis_channel_selector.setEnabled(False)

        self.time_marker_label = QLabel("First TTL marker: --")

        waveform_grid = QGridLayout()
        waveform_grid.setVerticalSpacing(6)

        self.lfp_waveform_area = self.create_waveform_area("Selected LFP channel")
        self.axis_waveform_area = self.create_waveform_area("Selected 3-axis channel")
        self.marker_waveform_area = self.create_waveform_area("Time marker / TTL events")

        waveform_grid.addWidget(QLabel("LFP"), 0, 0)
        waveform_grid.addWidget(self.lfp_waveform_area, 0, 1)

        waveform_grid.addWidget(QLabel("3-axis"), 1, 0)
        waveform_grid.addWidget(self.axis_waveform_area, 1, 1)

        waveform_grid.addWidget(QLabel("TTL"), 2, 0)
        waveform_grid.addWidget(self.marker_waveform_area, 2, 1)

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        layout.addWidget(self.lfp_file_label)
        layout.addWidget(self.lfp_channel_selector)

        layout.addWidget(self.axis_file_label)
        layout.addWidget(self.axis_channel_selector)

        layout.addWidget(self.time_marker_file_label)
        layout.addWidget(self.time_marker_label)

        layout.addLayout(waveform_grid)

        self.setLayout(layout)

    def create_waveform_area(self, text):
        frame = QFrame()
        frame.setMinimumHeight(42)
        frame.setStyleSheet(
            """
            QFrame {
                background-color: #fbfbfb;
                border: 1px solid #d0d0d0;
            }
            """
        )

        frame.setToolTip(text)
        return frame

    def set_lfp_info(self, info):
        self.lfp_path = info["path"]
        self.lfp_file_label.setText(f"LFP CSV: {info['filename']}")

        self.lfp_channel_selector.clear()

        channels = info.get("channels", [])

        if channels:
            for channel in channels:
                self.lfp_channel_selector.addItem(f"Channel {channel}", channel)

            self.lfp_channel_selector.setEnabled(True)
        else:
            self.lfp_channel_selector.addItem("No LFP channel")
            self.lfp_channel_selector.setEnabled(False)

    def set_axis_info(self, info):
        self.axis_path = info["path"]
        self.axis_file_label.setText(f"3-axis CSV: {info['filename']}")

        self.axis_channel_selector.clear()

        channels = info.get("channels", [])

        if channels:
            for channel in channels:
                self.axis_channel_selector.addItem(f"Channel {channel}", channel)

            self.axis_channel_selector.setEnabled(True)
        else:
            self.axis_channel_selector.addItem("No 3-axis channel")
            self.axis_channel_selector.setEnabled(False)

    def set_time_marker_info(self, info):
        self.time_marker_path = info["path"]
        self.time_marker_file_label.setText(f"Time marker CSV: {info['filename']}")

        first_marker_sec = info.get("first_marker_sec")

        if first_marker_sec is None:
            self.time_marker_label.setText("First TTL marker: --")
        else:
            self.time_marker_label.setText(
                f"First TTL marker: {first_marker_sec:.6f} sec"
            )