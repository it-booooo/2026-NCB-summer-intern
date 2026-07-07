from PySide6.QtCore import QThread, Signal


class LedDetectionWorker(QThread):
    result_ready = Signal(object, float, object, float, object)
    failed = Signal(str)

    def __init__(self, video_path, roi, rotate_180, fps, baseline_frame, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.roi = roi
        self.rotate_180 = rotate_180
        self.fps = fps
        self.baseline_frame = baseline_frame

    def run(self):
        try:
            from src.led_detector import (
                auto_threshold,
                compute_led_brightness_curve,
                detect_led_events_from_curve,
                score_at_frame,
                summarize_brightness,
            )

            points = compute_led_brightness_curve(
                self.video_path,
                roi=self.roi,
                rotate_180=self.rotate_180,
                using_fps=self.fps,
                should_stop=self.isInterruptionRequested,
            )

            if self.isInterruptionRequested():
                return

            baseline = score_at_frame(points, self.baseline_frame)
            threshold = auto_threshold(points, baseline_score=baseline)
            stats = summarize_brightness(points)
            events = detect_led_events_from_curve(
                points,
                threshold=threshold,
                min_duration_sec=0.1,
                min_gap_sec=0.2,
                fps=self.fps,
            )

            if self.isInterruptionRequested():
                return

            self.result_ready.emit(points, threshold, events, baseline, stats)
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))
