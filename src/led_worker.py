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
        scan_start_frame,
        scan_end_frame,
        parent=None,
    ):
        super().__init__(parent)
        self.video_path = video_path
        self.roi = roi
        self.rotate_180 = rotate_180
        self.fps = fps
        self.baseline_frame = baseline_frame
        self.scan_start_frame = scan_start_frame
        self.scan_end_frame = scan_end_frame

    def run(self):
        try:
            from src.led_detector import (
                compute_led_brightness_curve,
                detect_led_events_from_frame_deltas,
                refine_led_events_from_frame_deltas,
                score_at_frame,
                summarize_brightness,
            )

            coarse_step = 20
            points = compute_led_brightness_curve(
                self.video_path,
                roi=self.roi,
                rotate_180=self.rotate_180,
                using_fps=self.fps,
                detection_mode="brightness",
                frame_step=coarse_step,
                start_frame=self.scan_start_frame,
                end_frame=self.scan_end_frame,
                should_stop=self.isInterruptionRequested,
                progress_callback=self.progress_changed.emit,
            )

            if self.isInterruptionRequested():
                return

            baseline = score_at_frame(points, self.baseline_frame)
            threshold, stats = 0.0, summarize_brightness(
                points,
                detection_mode="frame_delta_mean_brightness",
            )
            events, threshold, delta_stats = detect_led_events_from_frame_deltas(
                points,
                fps=self.fps,
                min_duration_sec=0.1,
            )
            stats.update(delta_stats)
            stats["coarse_step"] = coarse_step
            stats["refined"] = False
            stats["scan_start_frame"] = self.scan_start_frame
            stats["scan_end_frame"] = self.scan_end_frame

            if events and not self.isInterruptionRequested():
                refined_events, refined_threshold, refined_stats = (
                    refine_led_events_from_frame_deltas(
                        self.video_path,
                        roi=self.roi,
                        coarse_events=events,
                        rotate_180=self.rotate_180,
                        using_fps=self.fps,
                        window_sec=1.0,
                        scan_start_frame=self.scan_start_frame,
                        scan_end_frame=self.scan_end_frame,
                        should_stop=self.isInterruptionRequested,
                    )
                )

                if refined_events:
                    events = refined_events
                    threshold = refined_threshold
                    stats.update(refined_stats)
                    stats["refined"] = True

            if self.isInterruptionRequested():
                return

            self.result_ready.emit(points, threshold, events, baseline, stats)
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))
