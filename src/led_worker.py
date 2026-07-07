from PySide6.QtCore import QThread, Signal


class LedDetectionWorker(QThread):
    result_ready = Signal(object, float, object, float, object)
    progress_changed = Signal(int, int)
    failed = Signal(str)

    def __init__(
        self,
        video_path,
        roi,
        rotate_180,
        fps,
        baseline_frame,
        parent=None,
    ):
        super().__init__(parent)
        self.video_path = video_path
        self.roi = roi
        self.rotate_180 = rotate_180
        self.fps = fps
        self.baseline_frame = baseline_frame

    def run(self):
        try:
            from src.led_detector import (
                compute_led_brightness_curve,
                detect_led_events_from_frame_deltas,
                score_at_frame,
                summarize_brightness,
            )

            points = compute_led_brightness_curve(
                self.video_path,
                roi=self.roi,
                rotate_180=self.rotate_180,
                using_fps=self.fps,
                detection_mode="max_brightness",
                should_stop=self.isInterruptionRequested,
                progress_callback=self.progress_changed.emit,
            )

            if self.isInterruptionRequested():
                return

            baseline = score_at_frame(points, self.baseline_frame)
            threshold, stats = 0.0, summarize_brightness(points, detection_mode="frame_delta")
            events, threshold, delta_stats = detect_led_events_from_frame_deltas(
                points,
                fps=self.fps,
                min_duration_sec=0.1,
            )
            stats.update(delta_stats)

            if self.isInterruptionRequested():
                return

            self.result_ready.emit(points, threshold, events, baseline, stats)
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))
