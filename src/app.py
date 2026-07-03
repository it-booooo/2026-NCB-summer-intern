from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout
from src.video_player import VideoPlayer


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Video Behavior Annotation Tool")
        self.resize(1000, 700)

        self.video_player = VideoPlayer()

        layout = QVBoxLayout()
        layout.addWidget(self.video_player)

        container = QWidget()
        container.setLayout(layout)

        self.setCentralWidget(container)