import cv2

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.video_utils import (
    format_time,
    frame_to_time_sec,
    parse_video_metadata,
    read_frame,
    time_sec_to_frame,
)


class VideoPlayer(QWidget):
    frame_changed = Signal(int, float)

    FIXED_VIDEO_FPS = 30.0

    def __init__(self):
        super().__init__()

        self.cap = None
        self.video_path = ""
        self.metadata = None
        self.fps = self.FIXED_VIDEO_FPS
        self.total_frames = 0
        self.current_frame = 0
        self.is_playing = False
        self.rotate_180_enabled = False
        self.current_pixmap = None

        self.video_label = QLabel("No video loaded")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(360, 203)
        self.video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_label.setStyleSheet("background: #111; color: #ddd;")

        self.info_label = QLabel("Frame: -- | FPS: --")
        self.time_label = QLabel("00:00.000 / 00:00.000")
        self.info_label.setWordWrap(False)
        self.time_label.setWordWrap(False)

        self.play_button = QPushButton("Play")
        self.stop_button = QPushButton("Stop")
        self.prev_frame_button = QPushButton("Prev Frame")
        self.next_frame_button = QPushButton("Next Frame")
        self.rotate_button = QPushButton("Rotate 180°")

        button_sizes = {
            self.play_button: 64,
            self.stop_button: 64,
            self.prev_frame_button: 88,
            self.next_frame_button: 88,
            self.rotate_button: 100,
        }

        for button, width in button_sizes.items():
            button.setEnabled(False)
            button.setFixedSize(width, 26)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.setFixedHeight(20)

        self.play_button.clicked.connect(self.toggle_play)
        self.stop_button.clicked.connect(self.stop)
        self.prev_frame_button.clicked.connect(self.previous_frame)
        self.next_frame_button.clicked.connect(self.advance_one_frame)
        self.rotate_button.clicked.connect(self.toggle_rotate_180)
        self.slider.sliderMoved.connect(self.seek_frame)

        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(4)
        controls_layout.addStretch()
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.stop_button)
        controls_layout.addWidget(self.prev_frame_button)
        controls_layout.addWidget(self.next_frame_button)
        controls_layout.addWidget(self.rotate_button)
        controls_layout.addStretch()

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(2)
        main_layout.addWidget(self.video_label, stretch=1)
        main_layout.addWidget(self.info_label)
        main_layout.addWidget(self.time_label)
        main_layout.addWidget(self.slider)
        main_layout.addLayout(controls_layout)

        self.setLayout(main_layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.play_next_frame)

    def has_video(self):
        return self.cap is not None and self.cap.isOpened()

    def current_time_sec(self):
        return frame_to_time_sec(self.current_frame, self.fps)

    def frame_to_time_sec(self, frame_index):
        return frame_to_time_sec(frame_index, self.fps)

    def time_sec_to_frame(self, time_sec):
        return time_sec_to_frame(time_sec, self.fps, self.total_frames)

    def load_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open MP4",
            "",
            "Video Files (*.mp4)",
        )

        if not path:
            return False

        if self.cap is not None:
            self.cap.release()

        self.metadata = parse_video_metadata(path, using_fps=self.FIXED_VIDEO_FPS)
        self.cap = cv2.VideoCapture(path)

        if not self.cap.isOpened():
            self.info_label.setText("Failed to open video")
            return False

        self.video_path = path
        self.fps = self.metadata.using_fps
        self.total_frames = self.metadata.total_frames
        self.current_frame = 0
        self.is_playing = False
        self.rotate_180_enabled = False

        self.slider.setRange(0, max(self.total_frames - 1, 0))
        self.slider.setEnabled(self.total_frames > 0)

        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.prev_frame_button.setEnabled(True)
        self.next_frame_button.setEnabled(True)
        self.rotate_button.setEnabled(True)

        self.play_button.setText("Play")
        self.rotate_button.setText("Rotate 180°")

        return self.show_frame(0)

    def toggle_play(self):
        if not self.has_video():
            return

        if self.is_playing:
            self.pause()
            return

        self.is_playing = True
        self.play_button.setText("Pause")

        interval_ms = int(1000 / self.fps) if self.fps else 33
        self.timer.start(max(interval_ms, 1))

    def pause(self):
        self.is_playing = False
        self.timer.stop()
        self.play_button.setText("Play")

    def stop(self):
        if not self.has_video():
            return

        self.pause()
        self.seek_frame(0)

    def play_next_frame(self):
        if not self.has_video():
            self.pause()
            return

        if self.current_frame >= self.total_frames - 1:
            self.pause()
            return

        success, frame = self.cap.read()

        if not success:
            self.pause()
            return

        self.display_frame(frame, self.current_frame + 1)

    def advance_one_frame(self):
        self.pause()
        self.seek_frame(self.current_frame + 1)

    def previous_frame(self):
        self.pause()
        self.seek_frame(self.current_frame - 1)

    def seek_frame(self, frame_index):
        if not self.has_video() or self.total_frames <= 0:
            return

        frame_index = max(0, min(int(frame_index), self.total_frames - 1))
        self.show_frame(frame_index)

    def seek_time_sec(self, time_sec):
        frame_index = self.time_sec_to_frame(time_sec)
        self.seek_frame(frame_index)

    def toggle_rotate_180(self):
        if not self.has_video():
            return

        self.rotate_180_enabled = not self.rotate_180_enabled

        if self.rotate_180_enabled:
            self.rotate_button.setText("Rotation: 180°")
        else:
            self.rotate_button.setText("Rotate 180°")

        self.show_frame(self.current_frame)

    def show_frame(self, frame_index):
        if not self.has_video():
            return False

        success, frame = read_frame(self.cap, frame_index)

        if not success:
            return False

        self.display_frame(frame, frame_index)
        return True

    def display_frame(self, frame, frame_index):
        if self.rotate_180_enabled:
            frame = cv2.rotate(frame, cv2.ROTATE_180)

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

        self.current_pixmap = QPixmap.fromImage(image)
        self.update_video_display()

        current_sec = self.current_time_sec()
        total_sec = self.total_frames / self.fps if self.fps else 0.0
        detected_fps = self.metadata.detected_fps if self.metadata else 0.0

        self.info_label.setText(
            f"Frame: {frame_index} / {max(self.total_frames - 1, 0)} | "
            f"Detected FPS: {detected_fps:.2f} | "
            f"Using FPS: {self.fps:.2f}"
        )

        self.time_label.setText(
            f"{format_time(current_sec)} / {format_time(total_sec)}"
        )

        self.frame_changed.emit(frame_index, current_sec)

    def update_video_display(self):
        if self.current_pixmap is None:
            return

        scaled_pixmap = self.current_pixmap.scaled(
            self.video_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )

        self.video_label.setPixmap(scaled_pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_video_display()