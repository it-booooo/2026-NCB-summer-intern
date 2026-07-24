from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QLabel

from ..app_state import LedState


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
        self.display_pixmap = None
        self._painting = False
        self._update_queued = False
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)

        # Saved LED ROI in original video-frame coordinates:
        # (x, y, width, height)

    def request_paint_update(self):
        """Queue a paint update without forcing an immediate repaint."""
        if self._painting or self._update_queued:
            return

        self._update_queued = True

        def update_later():
            self._update_queued = False
            self.update()

        QTimer.singleShot(0, update_later)

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
        self.request_paint_update()

    def set_saved_roi(self, roi):
        """Set saved roi.

        Args:
            roi: LED region of interest as (x, y, width, height).
        """
        self.led_state.roi = roi
        self.request_paint_update()

    def clear_saved_roi(self):
        """Clear saved roi.

        Args:
            None.
        """
        self.led_state.roi = None
        self.request_paint_update()

    def set_display_geometry(self, display_rect, frame_size):
        """Set display geometry.

        Args:
            display_rect: Input used by this operation.
            frame_size: Input used by this operation.
        """
        self.display_rect = display_rect
        self.frame_size = frame_size

    def set_display_pixmap(self, pixmap):
        """Set the scaled video pixmap rendered by this label."""
        self.display_pixmap = pixmap
        self.request_paint_update()

    def mousePressEvent(self, event):
        """Provide mouse press event functionality.

        Args:
            event: Event record to process.
        """
        if self.selecting_roi and self.display_rect.contains(event.position().toPoint()):
            self.drag_start = event.position().toPoint()
            self.drag_end = self.drag_start
            self.request_paint_update()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Provide mouse move event functionality.

        Args:
            event: Event record to process.
        """
        if self.selecting_roi and self.drag_start is None:
            self.hover_pos = event.position().toPoint()
            self.request_paint_update()
            return

        if self.selecting_roi and self.drag_start is not None:
            self.drag_end = event.position().toPoint()
            self.request_paint_update()
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
        """Paint the video frame and ROI overlay."""
        if self._painting or self.width() <= 0 or self.height() <= 0:
            return

        self._painting = True
        try:
            painter = QPainter(self)
            if not painter.isActive():
                return

            painter.fillRect(self.rect(), Qt.black)
            if self.display_pixmap is None:
                painter.setPen(Qt.white)
                painter.drawText(self.rect(), Qt.AlignCenter, self.text())
                return

            if not self.display_rect.isNull():
                painter.drawPixmap(self.display_rect.topLeft(), self.display_pixmap)

            if self.led_state.roi is not None:
                saved_rect = self.roi_to_display_rect(self.led_state.roi)
                if saved_rect is not None:
                    painter.setPen(QPen(Qt.green, 2, Qt.SolidLine))
                    painter.drawRect(saved_rect)

            if not self.selecting_roi:
                return

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
        finally:
            self._painting = False
