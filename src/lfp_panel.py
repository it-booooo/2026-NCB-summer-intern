from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget


class LfpPanel(QWidget):
    CHANNEL_COUNT = 4

    def __init__(self):
        super().__init__()

        self.file_label = QLabel("No LFP CSV imported")
        self.file_label.setStyleSheet("color: #666;")

        self.channel_grid = QGridLayout()
        self.channel_grid.setVerticalSpacing(6)

        for row in range(self.CHANNEL_COUNT):
            channel_label = QLabel(f"Ch {row + 1}")
            channel_label.setFixedWidth(48)

            waveform_area = QFrame()
            waveform_area.setMinimumHeight(34)
            waveform_area.setStyleSheet(
                """
                QFrame {
                    background-color: #fbfbfb;
                    border: 1px solid #d0d0d0;
                }
                """
            )

            self.channel_grid.addWidget(channel_label, row, 0)
            self.channel_grid.addWidget(waveform_area, row, 1)

        hint = QLabel("LFP waveform display will be connected to the CSV module later.")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color: #777;")

        layout = QVBoxLayout()
        layout.addWidget(self.file_label)
        layout.addLayout(self.channel_grid)
        layout.addWidget(hint)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.setLayout(layout)

    def set_lfp_path(self, path):
        self.file_label.setText(f"LFP CSV: {path}")