from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..app_state import LedState, SyncState, VideoState
from ..synchronization.time_conversion import absolute_time, relative_time
from .video_helpers import (
    format_time,
    frame_to_time_sec,
    parse_time_input,
    parse_video_metadata,
    read_frame,
    time_sec_to_frame,
)


class RoiVideoLabel(QLabel):
    roi_selected = Signal(tuple)

    def __init__(self, text, led_state=None):
        super().__init__(text)
        self.led_state = led_state or LedState()
        self.selecting_roi = False
        self.drag_start = None
        self.drag_end = None
        self.hover_pos = None
        self.display_rect = QRect()
        self.frame_size = None

        # 儲存已完成選取的 LED ROI，座標格式是影片原始 frame 座標：
        # (x, y, width, height)

    def set_roi_selection_enabled(self, enabled):
        """Set roi selection enabled.

        Args:
            enabled: Whether the feature should be enabled.
        """
        self.selecting_roi = enabled
        self.setMouseTracking(enabled)
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        self.drag_start = None
        self.drag_end = None
        self.hover_pos = None
        self.update()

    def set_saved_roi(self, roi):
        """Set saved roi.

        Args:
            roi: LED region of interest as (x, y, width, height).
        """
        self.led_state.roi = roi
        self.update()

    def clear_saved_roi(self):
        """Clear saved roi.

        Args:
            None.
        """
        self.led_state.roi = None
        self.update()

    def set_display_geometry(self, display_rect, frame_size):
        """Set display geometry.

        Args:
            display_rect: Input used by this operation.
            frame_size: Input used by this operation.
        """
        self.display_rect = display_rect
        self.frame_size = frame_size

    def mousePressEvent(self, event):
        """Provide mouse press event functionality.

        Args:
            event: Event record to process.
        """
        if self.selecting_roi and self.display_rect.contains(event.position().toPoint()):
            self.drag_start = event.position().toPoint()
            self.drag_end = self.drag_start
            self.update()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Provide mouse move event functionality.

        Args:
            event: Event record to process.
        """
        if self.selecting_roi and self.drag_start is None:
            self.hover_pos = event.position().toPoint()
            self.update()
            return

        if self.selecting_roi and self.drag_start is not None:
            self.drag_end = event.position().toPoint()
            self.update()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Provide mouse release event functionality.

        Args:
            event: Event record to process.
        """
        if self.selecting_roi and self.drag_start is not None:
            self.drag_end = event.position().toPoint()
            roi = self.current_roi()
            self.set_roi_selection_enabled(False)

            if roi is not None:
                self.set_saved_roi(roi)
                self.roi_selected.emit(roi)

            return

        super().mouseReleaseEvent(event)

    def current_roi(self):
        """Provide current roi functionality.

        Args:
            None.
        """
        if not self.frame_size or self.drag_start is None or self.drag_end is None:
            return None

        rect = QRect(self.drag_start, self.drag_end).normalized()
        rect = rect.intersected(self.display_rect)

        if rect.width() < 3 or rect.height() < 3:
            return None

        frame_width, frame_height = self.frame_size
        scale_x = frame_width / self.display_rect.width()
        scale_y = frame_height / self.display_rect.height()

        x = int((rect.x() - self.display_rect.x()) * scale_x)
        y = int((rect.y() - self.display_rect.y()) * scale_y)
        width = int(rect.width() * scale_x)
        height = int(rect.height() * scale_y)

        return (x, y, width, height)

    def roi_to_display_rect(self, roi):
        """Provide roi to display rect functionality.

        Args:
            roi: LED region of interest as (x, y, width, height).
        """
        if roi is None or not self.frame_size or self.display_rect.isNull():
            return None

        frame_width, frame_height = self.frame_size
        if frame_width <= 0 or frame_height <= 0:
            return None

        x, y, width, height = roi

        scale_x = self.display_rect.width() / frame_width
        scale_y = self.display_rect.height() / frame_height

        display_x = self.display_rect.x() + int(x * scale_x)
        display_y = self.display_rect.y() + int(y * scale_y)
        display_w = int(width * scale_x)
        display_h = int(height * scale_y)

        return QRect(display_x, display_y, display_w, display_h)

    def paintEvent(self, event):
        """Provide paint event functionality.

        Args:
            event: Event record to process.
        """
        super().paintEvent(event)

        painter = QPainter(self)

        # 1. 永久顯示已儲存的 LED ROI
        if self.led_state.roi is not None:
            saved_rect = self.roi_to_display_rect(self.led_state.roi)
            if saved_rect is not None:
                painter.setPen(QPen(Qt.green, 2, Qt.SolidLine))
                painter.drawRect(saved_rect)

        # 2. 沒有進入 ROI 選取模式時，只顯示永久 ROI，不畫暫時框
        if not self.selecting_roi:
            return

        # 3. ROI 選取模式：顯示紅色游標小方框或拖曳框
        painter.setPen(QPen(Qt.red, 2, Qt.SolidLine))

        if self.drag_start is None and self.hover_pos is not None:
            painter.drawRect(
                QRect(
                    self.hover_pos.x() - 8,
                    self.hover_pos.y() - 8,
                    16,
                    16,
                )
            )
            return

        if self.drag_start is None or self.drag_end is None:
            return

        drag_rect = QRect(self.drag_start, self.drag_end).normalized()
        drag_rect = drag_rect.intersected(self.display_rect)

        if not drag_rect.isNull():
            painter.drawRect(drag_rect)


class VideoPlayer(QWidget):
    frame_changed = Signal(int, float)
    roi_selected = Signal(tuple)

    BUTTON_WIDTHS = {
        "Play": 64,
        "Stop": 64,
        "Prev Frame": 88,
        "Next Frame": 88,
        "Rotate 180°": 100,
    }

    def __init__(self, video_state=None, sync_state=None, led_state=None):
        super().__init__()
        self.video_state = video_state or VideoState()
        self.sync_state = sync_state or SyncState()
        self.led_state = led_state or LedState()

        self.cap = None
        self.current_pixmap = None
        self._display_update_pending = False

        self.video_label = RoiVideoLabel("No video loaded", self.led_state)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(360, 203)
        self.video_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.video_label.setStyleSheet("background: #111; color: #ddd;")
        self.video_label.roi_selected.connect(self.set_led_roi_from_label)

        self.info_label = QLabel("Frame: -- | FPS: --")
        self.time_label = QLabel("00:00.000 / 00:00.000")
        self.info_label.setWordWrap(False)
        self.time_label.setWordWrap(False)

        self.time_seek_input = QLineEdit()
        self.time_seek_input.setPlaceholderText("time")
        self.time_seek_input.setToolTip(
            "Jump to time. Examples: 26.5, 00:26.500, 01:02:03.4"
        )
        self.time_seek_input.setFixedWidth(88)

        self.frame_seek_input = QLineEdit()
        self.frame_seek_input.setPlaceholderText("frame")
        self.frame_seek_input.setToolTip("Jump to frame index")
        self.frame_seek_input.setFixedWidth(72)
        self.seek_inputs = [self.time_seek_input, self.frame_seek_input]

        self.play_button = QPushButton("Play")
        self.stop_button = QPushButton("Stop")
        self.prev_frame_button = QPushButton("Prev Frame")
        self.next_frame_button = QPushButton("Next Frame")
        self.rotate_button = QPushButton("Rotate 180°")
        self.control_buttons = [
            self.play_button,
            self.stop_button,
            self.prev_frame_button,
            self.next_frame_button,
            self.rotate_button,
        ]

        for button in self.control_buttons:
            button.setFixedSize(self.BUTTON_WIDTHS[button.text()], 26)

        self.set_controls_enabled(False)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.setFixedHeight(20)

        self.play_button.clicked.connect(self.toggle_play)
        self.stop_button.clicked.connect(self.stop)
        self.prev_frame_button.clicked.connect(
            lambda _checked=False: self.step_frame(-1)
        )
        self.next_frame_button.clicked.connect(
            lambda _checked=False: self.step_frame(1)
        )
        self.rotate_button.clicked.connect(self.toggle_rotate_180)
        self.slider.sliderMoved.connect(self.seek_frame)
        self.time_seek_input.returnPressed.connect(
            lambda: self.seek_to_input("time")
        )
        self.frame_seek_input.returnPressed.connect(
            lambda: self.seek_to_input("frame")
        )

        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(4)
        controls_layout.addStretch()

        for button in self.control_buttons:
            controls_layout.addWidget(button)

        controls_layout.addStretch()

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(2)

        time_seek_layout = QHBoxLayout()
        time_seek_layout.setContentsMargins(0, 0, 0, 0)
        time_seek_layout.setSpacing(4)
        time_seek_layout.addWidget(self.time_label)
        time_seek_layout.addStretch()
        time_seek_layout.addWidget(QLabel("Go time"))
        time_seek_layout.addWidget(self.time_seek_input)
        time_seek_layout.addWidget(QLabel("Go frame"))
        time_seek_layout.addWidget(self.frame_seek_input)

        main_layout.addWidget(self.video_label)
        main_layout.addWidget(self.info_label)
        main_layout.addLayout(time_seek_layout)
        main_layout.addWidget(self.slider)

        main_layout.setStretch(0, 1)
        main_layout.addLayout(controls_layout)
        self.setLayout(main_layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.play_next_frame)

    def start_roi_selection(self):
        """Start roi selection.

        Args:
            None.
        """
        if self.has_video() and self.current_pixmap is not None:
            self.pause()
            self.video_label.set_roi_selection_enabled(True)

    def set_led_roi_from_label(self, roi):
        """Set led roi from label.

        Args:
            roi: LED region of interest as (x, y, width, height).
        """
        self.set_led_roi(roi)
        self.roi_selected.emit(roi)

    def set_led_roi(self, roi):
        """Set led roi.

        Args:
            roi: LED region of interest as (x, y, width, height).
        """
        self.led_state.roi = roi
        self.video_label.set_saved_roi(roi)
        self.update_video_display()

    def clear_led_roi(self):
        """Clear led roi.

        Args:
            None.
        """
        self.led_state.roi = None
        self.video_label.clear_saved_roi()
        self.update_video_display()

    def set_controls_enabled(self, enabled):
        """Set controls enabled.

        Args:
            enabled: Whether the feature should be enabled.
        """
        for button in self.control_buttons:
            button.setEnabled(enabled)

        for seek_input in self.seek_inputs:
            seek_input.setEnabled(enabled)

    def has_video(self):
        """Provide has video functionality.

        Args:
            None.
        """
        return self.cap is not None and self.cap.isOpened()

    def current_time_sec(self):
        """Provide current time sec functionality.

        Args:
            None.
        """
        fps = self.video_state.metadata.using_fps if self.video_state.metadata else None
        return frame_to_time_sec(self.video_state.current_frame, fps)

    def total_time_sec(self):
        """Provide total time sec functionality.

        Args:
            None.
        """
        metadata = self.video_state.metadata
        return metadata.total_frames / metadata.using_fps if metadata and metadata.using_fps else 0.0

    def current_display_time_sec(self):
        """Provide current display time sec functionality.

        Args:
            None.
        """
        return relative_time(
            self.current_time_sec(), self.sync_state.video_time_origin_sec
        )

    def display_total_time_sec(self):
        """Provide display total time sec functionality.

        Args:
            None.
        """
        total_sec = self.total_time_sec()
        return max(
            relative_time(total_sec, self.sync_state.video_time_origin_sec), 0.0
        )

    def format_display_time(self, seconds):
        """Format display time.

        Args:
            seconds: Input used by this operation.
        """
        sign = "-" if seconds < 0 else ""
        return f"{sign}{format_time(abs(seconds))}"

    def set_sync_time_origin(self, origin_sec):
        """Set sync time origin.

        Args:
            origin_sec: Input used by this operation.
        """
        next_origin = None if origin_sec is None else max(float(origin_sec), 0.0)
        self.sync_state.video_time_origin_sec = next_origin
        self.update_time_display()

    def frame_to_time_sec(self, frame_index):
        """Provide frame to time sec functionality.

        Args:
            frame_index: Zero-based video frame index.
        """
        fps = self.video_state.metadata.using_fps if self.video_state.metadata else None
        return frame_to_time_sec(frame_index, fps)

    def time_sec_to_frame(self, time_sec):
        """Convert time to sec to frame.

        Args:
            time_sec: Time value in seconds.
        """
        metadata = self.video_state.metadata
        fps = metadata.using_fps if metadata else None
        total_frames = metadata.total_frames if metadata else 0
        return time_sec_to_frame(time_sec, fps, total_frames)

    def load_video(self, path):
        """Load video.

        Args:
            path: File path to read from or write to.
        """
        import cv2

        new_cap = None
        try:
            new_cap = cv2.VideoCapture(path)
            metadata = parse_video_metadata(new_cap, path)
            if not new_cap.isOpened():
                raise ValueError("The video stream could not be opened.")

            success, first_frame = read_frame(new_cap, 0)
            if not success or first_frame is None:
                raise ValueError("The first video frame could not be decoded.")
        except Exception as error:
            if new_cap is not None:
                new_cap.release()
            if not self.has_video():
                self.info_label.setText("Failed to open video")
            QMessageBox.warning(
                self,
                "Video load failed",
                "Could not open or decode the selected video.\n\n"
                f"Reason: {error}",
            )
            return False

        if self.cap is not None:
            self.cap.release()

        self.video_state.metadata = metadata
        self.cap = new_cap

        self.video_state.current_frame = 0
        self.video_state.is_playing = False
        self.video_state.rotate_180_enabled = False
        self.sync_state.video_time_origin_sec = None

        # 換影片時清掉舊影片的 LED ROI，避免座標套到新影片。
        self.clear_led_roi()

        self.slider.setRange(0, max(metadata.total_frames - 1, 0))
        self.slider.setEnabled(metadata.total_frames > 0)
        self.set_controls_enabled(True)
        self.time_seek_input.clear()
        self.frame_seek_input.clear()
        self.mark_seek_input_valid(self.time_seek_input, True)
        self.mark_seek_input_valid(self.frame_seek_input, True)

        self.play_button.setText("Play")
        self.rotate_button.setText("Rotate 180°")

        self.display_frame(first_frame, 0)
        return True

    def toggle_play(self):
        """Toggle play.

        Args:
            None.
        """
        if not self.has_video():
            return

        if self.video_state.is_playing:
            self.pause()
            return

        self.video_state.is_playing = True
        self.play_button.setText("Pause")

        metadata = self.video_state.metadata
        fps = metadata.using_fps if metadata else None
        interval_ms = int(1000 / fps) if fps else 33
        self.timer.start(max(interval_ms, 1))

    def pause(self):
        """Provide pause functionality.

        Args:
            None.
        """
        self.video_state.is_playing = False
        self.timer.stop()
        self.play_button.setText("Play")

    def stop(self):
        """Provide stop functionality.

        Args:
            None.
        """
        if self.has_video():
            self.pause()
            if self.sync_state.video_time_origin_sec is None:
                self.seek_frame(0)
            else:
                self.seek_time_sec(self.sync_state.video_time_origin_sec)

    def play_next_frame(self):
        """Play next frame.

        Args:
            None.
        """
        metadata = self.video_state.metadata
        total_frames = metadata.total_frames if metadata else 0
        if not self.has_video() or self.video_state.current_frame >= total_frames - 1:
            self.pause()
            return

        success, frame = self.cap.read()

        if success:
            self.display_frame(frame, self.video_state.current_frame + 1)
        else:
            self.pause()

    def step_frame(self, offset):
        """Pause playback and move by a relative number of frames."""
        self.pause()
        self.seek_frame(self.video_state.current_frame + int(offset))

    def seek_frame(self, frame_index):
        """Seek frame.

        Args:
            frame_index: Zero-based video frame index.
        """
        metadata = self.video_state.metadata
        total_frames = metadata.total_frames if metadata else 0
        if not self.has_video() or total_frames <= 0:
            return

        frame_index = max(0, min(int(frame_index), total_frames - 1))
        self.show_frame(frame_index)

    def seek_time_sec(self, time_sec):
        """Seek time sec.

        Args:
            time_sec: Time value in seconds.
        """
        self.seek_frame(self.time_sec_to_frame(time_sec))

    def update_seek_inputs_from_current_frame(self):
        """Update seek inputs from current frame.

        Args:
            None.
        """
        self.time_seek_input.setText(format_time(self.current_time_sec()))
        self.frame_seek_input.setText(str(self.video_state.current_frame))
        self.mark_seek_input_valid(self.time_seek_input, True)
        self.mark_seek_input_valid(self.frame_seek_input, True)

    def mark_seek_input_valid(self, widget, is_valid):
        """Mark seek input valid.

        Args:
            widget: Input used by this operation.
            is_valid: Input used by this operation.
        """
        widget.setStyleSheet("" if is_valid else "border: 1px solid #c0392b;")

    def seek_to_input(self, input_type):
        """Validate and apply either the time or frame seek field."""
        if input_type == "time":
            widget = self.time_seek_input
            value = parse_time_input(widget.text())
        elif input_type == "frame":
            widget = self.frame_seek_input
            try:
                value = int(widget.text().strip())
            except ValueError:
                value = None
        else:
            raise ValueError(f"Unknown seek input type: {input_type}")

        if value is None:
            self.mark_seek_input_valid(widget, False)
            return

        for seek_input in self.seek_inputs:
            self.mark_seek_input_valid(seek_input, True)

        self.pause()
        if input_type == "time":
            self.seek_time_sec(
                absolute_time(value, self.sync_state.video_time_origin_sec)
            )
            widget.setText(
                self.format_display_time(self.current_display_time_sec())
            )
            self.frame_seek_input.clear()
        else:
            self.seek_frame(value)
            widget.setText(str(self.video_state.current_frame))
            self.time_seek_input.clear()

    def toggle_rotate_180(self):
        """Toggle rotate 180.

        Args:
            None.
        """
        if not self.has_video():
            return

        self.video_state.rotate_180_enabled = not self.video_state.rotate_180_enabled
        self.rotate_button.setText(
            "Rotation: 180°"
            if self.video_state.rotate_180_enabled
            else "Rotate 180°"
        )
        self.show_frame(self.video_state.current_frame)

    def show_frame(self, frame_index):
        """Show frame.

        Args:
            frame_index: Zero-based video frame index.
        """
        if not self.has_video():
            return False

        success, frame = read_frame(self.cap, frame_index)

        if success:
            self.display_frame(frame, frame_index)

        return success

    def display_frame(self, frame, frame_index):
        """Provide display frame functionality.

        Args:
            frame: Input used by this operation.
            frame_index: Zero-based video frame index.
        """
        import cv2

        if self.video_state.rotate_180_enabled:
            frame = cv2.rotate(frame, cv2.ROTATE_180)

        self.video_state.current_frame = int(frame_index)

        self.slider.blockSignals(True)
        self.slider.setValue(frame_index)
        self.slider.blockSignals(False)

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = frame_rgb.shape

        image = QImage(
            frame_rgb.data,
            width,
            height,
            channels * width,
            QImage.Format_RGB888,
        )

        self.current_pixmap = QPixmap.fromImage(image)
        self.update_video_display()

        metadata = self.video_state.metadata
        detected_fps = metadata.detected_fps if metadata else 0.0
        using_fps = metadata.using_fps if metadata else 0.0
        total_frames = metadata.total_frames if metadata else 0

        self.info_label.setText(
            f"Frame: {frame_index} / {max(total_frames - 1, 0)} | "
            f"Detected FPS: {detected_fps:.2f} | Using FPS: {using_fps:.2f}"
        )

        self.update_time_display()
        self.frame_seek_input.setPlaceholderText(str(frame_index))

        current_sec = self.current_time_sec()
        self.frame_changed.emit(frame_index, current_sec)

    def update_time_display(self):
        """Update time display.

        Args:
            None.
        """
        current_display_sec = self.current_display_time_sec()
        total_display_sec = self.display_total_time_sec()

        if self.sync_state.video_time_origin_sec is None:
            self.time_label.setText(
                f"{format_time(current_display_sec)} / {format_time(total_display_sec)}"
            )
        else:
            self.time_label.setText(
                "Sync t: "
                f"{self.format_display_time(current_display_sec)} / "
                f"{self.format_display_time(total_display_sec)}"
            )

        self.time_seek_input.setPlaceholderText(
            self.format_display_time(current_display_sec)
        )

    def update_video_display(self):
        """Update video display.

        Args:
            None.
        """
        if self.current_pixmap is None:
            return

        scaled_pixmap = self.current_pixmap.scaled(
            self.video_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )

        x = (self.video_label.width() - scaled_pixmap.width()) // 2
        y = (self.video_label.height() - scaled_pixmap.height()) // 2

        self.video_label.set_display_geometry(
            QRect(QPoint(x, y), scaled_pixmap.size()),
            (self.current_pixmap.width(), self.current_pixmap.height()),
        )

        self.video_label.setPixmap(scaled_pixmap)

        # setPixmap 後主畫面會重繪，所以這裡補 update，
        # 讓 QLabel 的 paintEvent 重新把 LED ROI 畫上去。
        self.video_label.update()

    def schedule_video_display_update(self):
        """Refresh after Qt has completed the active resize/paint event."""
        if self._display_update_pending:
            return

        self._display_update_pending = True

        def refresh_display():
            self._display_update_pending = False
            self.update_video_display()

        QTimer.singleShot(0, refresh_display)

    def resizeEvent(self, event):
        """Resize event.

        Args:
            event: Event record to process.
        """
        super().resizeEvent(event)
        self.schedule_video_display_update()
