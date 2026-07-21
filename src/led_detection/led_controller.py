from PySide6.QtWidgets import QMessageBox

from .led_worker import LedDetectionWorker, coarse_scan_step_for_fps
from .status_text import format_led_detection_status


class LedControllerMixin:
    """LED ROI selection, background detection, and status handling."""

    def show_opencl_status(self):
        """Show opencl status.

        Args:
            None.
        """
        try:
            from .led_opencl import opencl_status

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
        """Select led roi.

        Args:
            None.
        """
        if not self.video_player.has_video():
            QMessageBox.warning(self, "No video", "Please import a video first.")
            return
        self.video_player.start_roi_selection()

    def set_led_roi(self, roi):
        """Set led roi.

        Args:
            roi: LED region of interest as (x, y, width, height).
        """
        self.led_state.roi = roi
        self.sync_panel.set_led_roi(roi)
        self.start_led_detection()

    def start_led_detection(self):
        """Start led detection.

        Args:
            None.
        """
        if not self.video_player.has_video() or self.led_state.roi is None:
            return

        try:
            scan_start_sec, scan_end_sec, scan_start_frame, scan_end_frame = (
                self.sync_panel.led_scan_range_sec(
                    self.video_state.metadata.using_fps,
                    self.video_state.metadata.total_frames,
                )
            )
        except ValueError as error:
            self.sync_panel.mark_scan_range_valid(False)
            QMessageBox.warning(self, "Invalid LED scan range", str(error))
            return

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
            if self.sync_state.time_marker_info is None:
                QMessageBox.warning(
                    self,
                    "TTL marker required",
                    "Please import TTL CSV before detecting multiple LED events.",
                )
                return

            max_events = int(
                self.sync_state.time_marker_info.get("marker_count") or 0
            )
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
        cached_points = self.led_state.brightness_cache.get(cache_key)

        self.sync_panel.set_led_detection_status(
            "LED detection: using cached ROI brightness data."
            if cached_points is not None
            else "LED detection: analyzing ROI frame changes. You can wait here."
        )
        self.sync_panel.begin_led_detection_progress()
        self.led_worker = LedDetectionWorker(
            video_path=self.video_state.metadata.path,
            roi=self.led_state.roi,
            rotate_180=self.video_state.rotate_180_enabled,
            rotation_degrees=self.video_state.rotation_degrees,
            fps=self.video_state.metadata.using_fps,
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
        """Provide led cache key functionality.

        Args:
            scan_start_frame: Input used by this operation.
            scan_end_frame: Input used by this operation.
        """
        return (
            self.video_state.metadata.path,
            tuple(self.led_state.roi) if self.led_state.roi is not None else None,
            int(self.video_state.rotation_degrees),
            float(self.video_state.metadata.using_fps or 0.0),
            int(scan_start_frame),
            int(scan_end_frame),
            coarse_scan_step_for_fps(self.video_state.metadata.using_fps),
        )

    def stop_led_detection(self, wait=False):
        """Stop led detection.

        Args:
            wait: Input used by this operation.
        """
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
        """Finish led detection.

        Args:
            worker: Input used by this operation.
            points: Brightness or analysis points used by the operation.
            threshold: Input used by this operation.
            events: Event records to display, analyze, or export.
            stats: Input used by this operation.
            cache_key: Input used by this operation.
        """
        if self.led_worker is not None and worker is not self.led_worker:
            return

        cache_hit = worker.cached_points is not None
        stats = dict(stats or {})
        stats["scan_outcome"] = "events_found" if events else "no_events"
        if points and cache_key is not None and not cache_hit:
            self.led_state.brightness_cache[cache_key] = points

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
        """Update led detection progress.

        Args:
            worker: Input used by this operation.
            current_frame: Input used by this operation.
            total_frames: Input used by this operation.
        """
        if self.led_worker is not None and worker is not self.led_worker:
            return

        self.sync_panel.update_led_detection_progress(current_frame, total_frames)

    def update_led_detection_stage(self, worker, text):
        """Update led detection stage.

        Args:
            worker: Input used by this operation.
            text: Text displayed to the user.
        """
        if self.led_worker is not None and worker is not self.led_worker:
            return

        self.sync_panel.set_led_detection_stage(text)

    def fail_led_detection(self, worker, message):
        """Report failure for led detection.

        Args:
            worker: Input used by this operation.
            message: Input used by this operation.
        """
        if self.led_worker is not None and worker is not self.led_worker:
            return

        self.sync_panel.fail_led_detection_progress()
        self.sync_panel.set_led_detection_status("LED detection: failed")
        QMessageBox.warning(self, "LED detection failed", message)

    def cleanup_led_worker(self):
        """Provide cleanup led worker functionality.

        Args:
            None.
        """
        worker = self.sender()
        if worker is not None:
            worker.deleteLater()

        if worker is self.led_worker:
            self.led_worker = None
