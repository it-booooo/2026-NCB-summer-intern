import cv2

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
)


class VideoPlayer(QWidget):
    def __init__(self):
        super().__init__()

        self.cap = None
        self.fps = 0
        self.total_frames = 0
        self.current_frame = 0
        self.is_playing = False

        self.video_label = QLabel("No video loaded")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(640, 360)

        self.info_label = QLabel("")

        self.load_button = QPushButton("Load MP4")
        self.play_button = QPushButton("Play")
        self.play_button.setEnabled(False)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)

        self.load_button.clicked.connect(self.load_video)
        self.play_button.clicked.connect(self.toggle_play)
        self.slider.sliderMoved.connect(self.seek_frame)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.load_button)
        controls_layout.addWidget(self.play_button)

        layout = QVBoxLayout()
        layout.addWidget(self.video_label)
        layout.addWidget(self.info_label)
        layout.addWidget(self.slider)
        layout.addLayout(controls_layout)

        self.setLayout(layout)

        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)

    def load_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open MP4",
            "",
            "Video Files (*.mp4)",
        )

        if not path:
            return

        self.cap = cv2.VideoCapture(path)

        if not self.cap.isOpened():
            self.info_label.setText("Failed to open video.")
            return

        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.current_frame = 0

        self.slider.setRange(0, self.total_frames - 1)
        self.slider.setEnabled(True)
        self.play_button.setEnabled(True)

        self.show_frame(0)

    def toggle_play(self):
        if self.cap is None:
            return

        self.is_playing = not self.is_playing

        if self.is_playing:
            self.play_button.setText("Pause")
            interval_ms = int(1000 / self.fps) if self.fps else 33
            self.timer.start(interval_ms)
        else:
            self.play_button.setText("Play")
            self.timer.stop()

    def next_frame(self):
        if self.cap is None:
            return

        next_frame_index = self.current_frame + 1

        if next_frame_index >= self.total_frames:
            self.timer.stop()
            self.is_playing = False
            self.play_button.setText("Play")
            return

        self.show_frame(next_frame_index)

    def seek_frame(self, frame_index):
        self.show_frame(frame_index)

    def show_frame(self, frame_index):
        if self.cap is None:
            return

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        success, frame = self.cap.read()

        if not success:
            return

        self.current_frame = frame_index
        self.slider.setValue(frame_index)

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = frame_rgb.shape
        bytes_per_line = channels * width

        image = QImage(
            frame_rgb.data,
            width,
            height,
            bytes_per_line,
            QImage.Format_RGB888,
        )

        pixmap = QPixmap.fromImage(image)
        self.video_label.setPixmap(
            pixmap.scaled(
                self.video_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

        current_sec = frame_index / self.fps if self.fps else 0
        total_sec = self.total_frames / self.fps if self.fps else 0

        self.info_label.setText(
            f"Frame: {frame_index} / {self.total_frames} | "
            f"Time: {current_sec:.2f} / {total_sec:.2f} sec | "
            f"FPS: {self.fps:.2f}"
        )