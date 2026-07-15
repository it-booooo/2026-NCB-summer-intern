from PySide6.QtCore import QThread, Signal
from time import perf_counter


def coarse_scan_step_for_fps(fps):
    return max(int(round(float(fps or 30.0) * 2.0 / 3.0)), 1)


class LedDetectionWorker(QThread):
    result_ready = Signal(object, float, object, object)
    progress_changed = Signal(int, int)
    stage_changed = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        video_path,
        roi,
        rotate_180,
        fps,
        scan_start_frame,
        scan_end_frame,
        detect_multiple=False,
        max_events=None,
        cached_points=None,
        parent=None,
    ):
        super().__init__(parent)
        self.video_path = video_path
        self.roi = roi
        self.rotate_180 = rotate_180
        self.fps = fps
        self.scan_start_frame = scan_start_frame
        self.scan_end_frame = scan_end_frame
        self.detect_multiple = detect_multiple
        self.max_events = max_events
        self.cached_points = cached_points

    def run(self):
        try:
            from .led_detector import (
                compute_led_brightness_curve,
                detect_led_event_pairs_from_frame_deltas,
                refine_led_event_pairs_from_frame_deltas,
            )

            started_at = perf_counter()
            coarse_step = coarse_scan_step_for_fps(self.fps)
            refine_window_sec = 1.0
            max_events = (
                max(int(self.max_events or 0), 0)
                if self.detect_multiple
                else 1
            )
            scan_acceleration_info = {}
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
                    acceleration_info=scan_acceleration_info,
                )
            else:
                points = self.cached_points
                scan_acceleration_info["brightness_backend"] = "cache"
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
            coarse_events, threshold, stats = detect_led_event_pairs_from_frame_deltas(
                points,
                fps=self.fps,
                max_events=max_events,
            )

            events = coarse_events
            refine_acceleration_info = {}
            if coarse_events and not self.isInterruptionRequested():
                self.stage_changed.emit("Refining LED events...")
                refined_events, refined_threshold, _ = (
                    refine_led_event_pairs_from_frame_deltas(
                        self.video_path,
                        roi=self.roi,
                        coarse_events=coarse_events,
                        rotate_180=self.rotate_180,
                        using_fps=self.fps,
                        window_sec=refine_window_sec,
                        scan_start_frame=self.scan_start_frame,
                        scan_end_frame=self.scan_end_frame,
                        should_stop=self.isInterruptionRequested,
                        max_events=max_events,
                        acceleration_info=refine_acceleration_info,
                    )
                )
                events = refined_events
                threshold = refined_threshold if refined_events else threshold

            detect_elapsed_sec = perf_counter() - detect_started_at
            stats["threshold"] = threshold
            stats["event_count"] = len(events) // 2
            stats["requested_event_count"] = max_events
            stats["scan_start_frame"] = self.scan_start_frame
            stats["scan_end_frame"] = self.scan_end_frame
            stats["detect_multiple"] = self.detect_multiple
            stats["points_count"] = len(points)
            stats["coarse_step"] = coarse_step
            stats["refine_window_sec"] = refine_window_sec
            stats["scan_elapsed_sec"] = scan_elapsed_sec
            stats["detect_elapsed_sec"] = detect_elapsed_sec
            stats.update(scan_acceleration_info)
            if coarse_events:
                stats["refine_brightness_backend"] = refine_acceleration_info.get(
                    "brightness_backend",
                    "cpu",
                )

            if self.isInterruptionRequested():
                return

            self.result_ready.emit(points, threshold, events, stats)
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))
