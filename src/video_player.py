import cv2

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class VideoPlayer(QWidget):
    frame_changed = Signal(int, float)

    def __init__(self):
        super().__init__()

        self.cap = None
        self.video_path = ""
        self.fps = 0.0
        self.total_frames = 0
        self.current_frame = 0
        self.is_playing = False

        self.video_label = QLabel("No video loaded")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(640, 360)
        self.video_label.setStyleSheet("background: #111; color: #ddd;")

        self.info_label = QLabel("Load an MP4 to begin.")

        self.load_button = QPushButton("Load MP4")
        self.play_button = QPushButton("Play")
        self.prev_frame_button = QPushButton("Prev Frame")
        self.next_frame_button = QPushButton("Next Frame")

        self.play_button.setEnabled(False)
        self.prev_frame_button.setEnabled(False)
        self.next_frame_button.setEnabled(False)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)

        self.load_button.clicked.connect(self.load_video)
        self.play_button.clicked.connect(self.toggle_play)
        self.prev_frame_button.clicked.connect(self.previous_frame)
        self.next_frame_button.clicked.connect(self.advance_one_frame)
        self.slider.sliderMoved.connect(self.seek_frame)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.load_button)
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.prev_frame_button)
        controls_layout.addWidget(self.next_frame_button)

        layout = QVBoxLayout()
        layout.addWidget(self.video_label)
        layout.addWidget(self.info_label)
        layout.addWidget(self.slider)
        layout.addLayout(controls_layout)

        self.setLayout(layout)

        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)

    def has_video(self):
        return self.cap is not None and self.cap.isOpened()

    def current_time_sec(self):
        if not self.fps:
            return 0.0

        return self.current_frame / self.fps

    def load_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open MP4",
            "",
            "Video Files (*.mp4)",
        )

        if not path:
            return

        if self.cap is not None:
            self.cap.release()

        self.cap = cv2.VideoCapture(path)

        if not self.cap.isOpened():
            self.info_label.setText("Failed to open video.")
            return

        self.video_path = path
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.current_frame = 0
        self.is_playing = False

        self.slider.setRange(0, max(self.total_frames - 1, 0))
        self.slider.setEnabled(self.total_frames > 0)

        self.play_button.setEnabled(True)
        self.prev_frame_button.setEnabled(True)
        self.next_frame_button.setEnabled(True)
        self.play_button.setText("Play")

        self.show_frame(0)

    def toggle_play(self):
        if not self.has_video():
            return

        self.is_playing = not self.is_playing

        if self.is_playing:
            self.play_button.setText("Pause")
            interval_ms = int(1000 / self.fps) if self.fps else 33
            self.timer.start(max(interval_ms, 1))
        else:
            self.play_button.setText("Play")
            self.timer.stop()

    def next_frame(self):
        self.seek_frame(self.current_frame + 1)

    def advance_one_frame(self):
        self.pause()
        self.seek_frame(self.current_frame + 1)

    def previous_frame(self):
        self.pause()
        self.seek_frame(self.current_frame - 1)

    def pause(self):
        self.is_playing = False
        self.timer.stop()
        self.play_button.setText("Play")

    def seek_frame(self, frame_index):
        if not self.has_video():
            return

        if self.total_frames <= 0:
            return

        frame_index = max(0, min(int(frame_index), self.total_frames - 1))

        if frame_index >= self.total_frames - 1 and self.is_playing:
            self.pause()

        self.show_frame(frame_index)

    def show_frame(self, frame_index):
        if not self.has_video():
            return

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        success, frame = self.cap.read()

        if not success:
            return

        self.current_frame = frame_index

        self.slider.blockSignals(True)
        self.slider.setValue(frame_index)
        self.slider.blockSignals(False)

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

        current_sec = self.current_time_sec()
        total_sec = self.total_frames / self.fps if self.fps else 0.0

        self.info_label.setText(
            f"Frame: {frame_index} / {max(self.total_frames - 1, 0)} | "
            f"Time: {current_sec:.3f} / {total_sec:.3f} sec | "
            f"FPS: {self.fps:.2f}"
        )

        self.frame_changed.emit(frame_index, current_sec)