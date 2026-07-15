from PySide6.QtWidgets import QMessageBox

from .detection.led_worker import LedDetectionWorker, coarse_scan_step_for_fps
from .led_status import format_led_detection_status


class LedControllerMixin:
    """LED ROI selection, background detection, and status handling."""

    def show_opencl_status(self):
        try:
            from .detection.led_opencl import opencl_status

            status = opencl_status()
        except Exception as error:
            QMessageBox.warning(
                self,
                "OpenCL GPU",
                f"OpenCL check failed:\n{error}",
            )
            return

        if not status.get("available"):
            QMessageBox.warning(
                self,
                "OpenCL GPU",
                "OpenCL GPU is not available.\n\n"
                f"Reason: {status.get('reason', 'unknown')}\n\n"
                "LED detection will use CPU fallback.",
            )
            return

        QMessageBox.information(
            self,
            "OpenCL GPU",
            "OpenCL GPU is available.\n\n"
            f"Device: {status.get('device')}\n"
            f"Vendor: {status.get('device_vendor')}\n"
            f"Platform: {status.get('platform')}\n"
            f"Selected by: {status.get('selected_reason')}\n"
            f"Supported GPU vendors: {', '.join(status.get('supported_vendors', []))}\n"
            f"Target refine batch: {status.get('target_batch_frames')} sampled frames\n"
            f"Target coarse batch: {status.get('target_coarse_batch_mode')} "
            f"({status.get('target_coarse_batch_frames')} sampled frames base)\n"
            f"Target transfer limit: {status.get('target_batch_mb'):.0f} MB\n"
            f"Device max allocation: {status.get('max_alloc_mb'):.0f} MB\n"
            f"Device global memory: {status.get('global_mem_mb'):.0f} MB\n\n"
            "Detected OpenCL GPUs:\n"
            + "\n".join(
                (
                    f"- {device.get('name')} | {device.get('vendor')} | "
                    f"{device.get('global_mem_mb'):.0f} MB"
                )
                for device in status.get("devices", [])
            ),
        )

    def select_led_roi(self):
        if not self.video_player.has_video():
            QMessageBox.warning(self, "No video", "Please import a video first.")
            return
        self.video_player.start_roi_selection()

    def set_led_roi(self, roi):
        self.led_roi = roi
        self.sync_panel.set_led_roi(roi)
        self.start_led_detection()

    def start_led_detection(self):
        if not self.video_player.has_video() or self.led_roi is None:
            return

        try:
            scan_start_sec, scan_end_sec = self.sync_panel.led_scan_range_sec()
        except ValueError as error:
            self.sync_panel.mark_scan_range_valid(False)
            QMessageBox.warning(self, "Invalid LED scan range", str(error))
            return

        scan_start_frame = (
            self.video_player.time_sec_to_frame(scan_start_sec)
            if scan_start_sec is not None
            else 0
        )
        scan_end_frame = (
            self.video_player.time_sec_to_frame(scan_end_sec)
            if scan_end_sec is not None
            else max(self.video_player.total_frames - 1, 0)
        )
        if scan_start_frame >= scan_end_frame:
            self.sync_panel.mark_scan_range_valid(False)
            QMessageBox.warning(
                self,
                "Invalid LED scan range",
                "LED scan range is too short after converting to frames.",
            )
            return

        detect_multiple = self.sync_panel.detect_multiple_led_events()
        max_events = 1
        if detect_multiple:
            if self.timeMarker_info is None:
                QMessageBox.warning(
                    self,
                    "TTL marker required",
                    "Please import TTL CSV before detecting multiple LED events.",
                )
                return

            max_events = int(self.timeMarker_info.get("marker_count") or 0)
            if max_events <= 0:
                QMessageBox.warning(
                    self,
                    "TTL marker required",
                    "The imported TTL CSV does not contain any TTL events.",
                )
                return

        if self.led_worker is not None and self.led_worker.isRunning():
            if not self.stop_led_detection(wait=True):
                QMessageBox.information(
                    self,
                    "LED detection",
                    "LED detection is still stopping. Please try again in a moment.",
                )
                return

        cache_key = self.led_cache_key(scan_start_frame, scan_end_frame)
        cached_points = self.led_brightness_cache.get(cache_key)

        self.sync_panel.set_led_detection_status(
            "LED detection: using cached ROI brightness data."
            if cached_points is not None
            else "LED detection: analyzing ROI frame changes. You can wait here."
        )
        self.sync_panel.begin_led_detection_progress()
        self.led_worker = LedDetectionWorker(
            video_path=self.video_player.video_path,
            roi=self.led_roi,
            rotate_180=self.video_player.rotate_180_enabled,
            fps=self.video_player.fps,
            scan_start_frame=scan_start_frame,
            scan_end_frame=scan_end_frame,
            detect_multiple=detect_multiple,
            max_events=max_events,
            cached_points=cached_points,
        )
        worker = self.led_worker
        worker.result_ready.connect(
            lambda points, threshold, events, stats, worker=worker: (
                self.finish_led_detection(
                    worker,
                    points,
                    threshold,
                    events,
                    stats,
                    cache_key,
                )
            )
        )
        worker.progress_changed.connect(
            lambda current_frame, total_frames, worker=worker: (
                self.update_led_detection_progress(worker, current_frame, total_frames)
            )
        )
        worker.stage_changed.connect(
            lambda text, worker=worker: self.update_led_detection_stage(worker, text)
        )
        worker.failed.connect(
            lambda message, worker=worker: self.fail_led_detection(worker, message)
        )
        self.led_worker.finished.connect(self.cleanup_led_worker)
        self.led_worker.start()

    def led_cache_key(self, scan_start_frame, scan_end_frame):
        return (
            self.video_player.video_path,
            tuple(self.led_roi) if self.led_roi is not None else None,
            bool(self.video_player.rotate_180_enabled),
            float(self.video_player.fps or 0.0),
            int(scan_start_frame),
            int(scan_end_frame),
            coarse_scan_step_for_fps(self.video_player.fps),
        )

    def stop_led_detection(self, wait=False):
        if self.led_worker is None:
            return True

        if self.led_worker.isRunning():
            self.led_worker.requestInterruption()
            if wait:
                self.led_worker.wait(3000)

        return not self.led_worker.isRunning()

    def finish_led_detection(
        self,
        worker,
        points,
        threshold,
        events,
        stats,
        cache_key,
    ):
        if self.led_worker is not None and worker is not self.led_worker:
            return

        cache_hit = worker.cached_points is not None
        stats = dict(stats or {})
        stats["scan_outcome"] = "events_found" if events else "no_events"
        if points and cache_key is not None and not cache_hit:
            self.led_brightness_cache[cache_key] = points

        status = format_led_detection_status(points, threshold, events, stats)
        if cache_hit:
            status += " | cached scan"
        self.sync_panel.finish_led_detection_progress(has_events=bool(events))
        self.sync_panel.set_led_analysis(
            points,
            threshold,
            events,
            stats=stats,
            status=status,
        )
        self.event_table.delete_events_by_source("led_detection")
        self.add_led_events(events)
        self.sync_panel.set_led_detection_status(
            "LED detection: complete. Click Analysis Info to view results."
            if events
            else "LED scan complete: no events found. Click Analysis Info to view results."
        )

        if not events:
            QMessageBox.warning(
                self,
                "No LED event found",
                "The scan completed successfully, but no LED event was found.\n\n"
                "Please select the ROI again, adjust the scan range, or add markers manually.",
            )

    def update_led_detection_progress(self, worker, current_frame, total_frames):
        if self.led_worker is not None and worker is not self.led_worker:
            return

        self.sync_panel.update_led_detection_progress(current_frame, total_frames)

    def update_led_detection_stage(self, worker, text):
        if self.led_worker is not None and worker is not self.led_worker:
            return

        self.sync_panel.set_led_detection_stage(text)

    def fail_led_detection(self, worker, message):
        if self.led_worker is not None and worker is not self.led_worker:
            return

        self.sync_panel.fail_led_detection_progress()
        self.sync_panel.set_led_detection_status("LED detection: failed")
        QMessageBox.warning(self, "LED detection failed", message)

    def cleanup_led_worker(self):
        worker = self.sender()
        if worker is not None:
            worker.deleteLater()

        if worker is self.led_worker:
            self.led_worker = None
