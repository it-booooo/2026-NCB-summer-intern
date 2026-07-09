from PySide6.QtCore import QThread, Signal
from time import perf_counter


class LedDetectionWorker(QThread):
    result_ready = Signal(object, float, object, float, object)
    progress_changed = Signal(int, int)
    stage_changed = Signal(str)
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
        detect_multiple=False,
        cached_points=None,
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
        self.detect_multiple = detect_multiple
        self.cached_points = cached_points

    def run(self):
        try:
            from src.led_multi_detector import (
                detect_led_event_pairs_from_frame_deltas,
                refine_led_event_pairs_from_frame_deltas,
            )
            from src.led_detector import (
                compute_led_brightness_curve,
                detect_led_events_from_frame_deltas,
                refine_led_events_from_frame_deltas,
                score_at_frame,
                summarize_brightness,
            )

            started_at = perf_counter()
            coarse_step = 20
            if self.cached_points is None:
                points = compute_led_brightness_curve(
                    self.video_path,
                    roi=self.roi,
                    rotate_180=self.rotate_180,
                    using_fps=self.fps,
                    frame_step=coarse_step,
                    start_frame=self.scan_start_frame,
                    end_frame=self.scan_end_frame,
                    should_stop=self.isInterruptionRequested,
                    progress_callback=self.progress_changed.emit,
                )
            else:
                points = self.cached_points
                scan_total_frames = max(
                    self.scan_end_frame - self.scan_start_frame + 1,
                    1,
                )
                self.progress_changed.emit(scan_total_frames, scan_total_frames)
            scan_elapsed_sec = perf_counter() - started_at

            if self.isInterruptionRequested():
                return

            self.stage_changed.emit("Detecting LED events...")
            detect_started_at = perf_counter()
            baseline = score_at_frame(points, self.baseline_frame)
            threshold, stats = 0.0, summarize_brightness(
                points,
                detection_mode="frame_delta_mean_brightness",
            )
            events = []
            try:
                if self.detect_multiple:
                    events, threshold, delta_stats = detect_led_event_pairs_from_frame_deltas(
                        points,
                        fps=self.fps,
                        min_duration_sec=0.1,
                        min_gap_sec=0.5,
                    )
                else:
                    events, threshold, delta_stats = detect_led_events_from_frame_deltas(
                        points,
                        fps=self.fps,
                        min_duration_sec=0.1,
                    )
                stats.update(delta_stats)
            except Exception as error:
                stats["detection_error"] = str(error)
            detect_elapsed_sec = perf_counter() - detect_started_at
            stats["coarse_step"] = coarse_step
            stats["refined"] = False
            stats["scan_start_frame"] = self.scan_start_frame
            stats["scan_end_frame"] = self.scan_end_frame
            stats["detect_multiple"] = self.detect_multiple
            stats["scan_elapsed_sec"] = scan_elapsed_sec
            stats["scan_cache_hit"] = self.cached_points is not None
            stats["detect_elapsed_sec"] = detect_elapsed_sec
            stats["refine_elapsed_sec"] = 0.0

            if events and not self.isInterruptionRequested():
                self.stage_changed.emit("Refining LED events...")
                refine_started_at = perf_counter()
                try:
                    refine_func = (
                        refine_led_event_pairs_from_frame_deltas
                        if self.detect_multiple
                        else refine_led_events_from_frame_deltas
                    )
                    refined_events, refined_threshold, refined_stats = (
                        refine_func(
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

                    events = refined_events
                    threshold = refined_threshold
                    stats.update(refined_stats)
                    stats["refined"] = True
                except Exception as error:
                    stats["refine_error"] = str(error)
                    stats["refined"] = False
                stats["refine_elapsed_sec"] = perf_counter() - refine_started_at

            if self.isInterruptionRequested():
                return

            self.result_ready.emit(points, threshold, events, baseline, stats)
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))
