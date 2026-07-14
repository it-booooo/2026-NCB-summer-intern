from PySide6.QtWidgets import QMessageBox


def pair_event_intervals(events, start_type, end_type, interval_type):
    """Pair matching start/end point markers in table order."""
    intervals = []
    pending_start = None
    for event in events:
        event_type = event.get("event_type")
        if event_type == start_type:
            pending_start = event
        elif event_type == end_type and pending_start is not None:
            start_sec = float(pending_start.get("video_time_sec", 0.0))
            end_sec = float(event.get("video_time_sec", 0.0))
            if end_sec > start_sec:
                intervals.append(
                    {
                        "event_type": interval_type,
                        "video_start_sec": start_sec,
                        "video_end_sec": end_sec,
                        "start_frame": int(pending_start.get("frame_index", 0)),
                        "end_frame": int(event.get("frame_index", 0)),
                    }
                )
                pending_start = None
    return intervals


class SyncControllerMixin:
    """TTL, event marker, and video-to-record-time synchronization logic."""

    def reset_sync_state_for_new_video(self):
        self.timeMarker_info = None
        self.led_roi = None
        self.time_offset_sec = None

        self.ttl_panel.set_markers(None)
        self.event_table.clear_events(emit=False)
        self.event_table.set_sync_time_origin(None)
        self.video_player.set_sync_time_origin(None)
        self.lfp_panel.set_sync_time_origin(None)
        self.lfp_panel.clear_current_time_marker()
        self.lfp_panel.set_event_intervals([])

        self.sync_panel.video_led_label.setText("Video LED marker: Not selected")
        self.sync_panel.ttl_label.setText("TTL marker: Not loaded")
        self.sync_panel.offset_label.setText(
            "Time offset (video - TTL): Not calculated"
        )
        self.sync_panel.led_roi_label.setText("LED ROI: Not selected")
        self.sync_panel.set_roi_plot_idle()
        self.sync_panel.set_led_detection_status("LED detection: Not analyzed")

    def set_ttl_markers(self, info):
        self.timeMarker_info = info
        first_marker_sec = (
            self.timeMarker_info.get("first_marker_sec")
            if self.timeMarker_info is not None
            else None
        )
        if first_marker_sec is not None:
            self.sync_panel.set_ttl_marker(first_marker_sec)
        else:
            self.sync_panel.ttl_label.setText("TTL marker: Not loaded")
        self.update_time_offset()

    def add_event(self, event_type):
        if not self.video_player.has_video():
            QMessageBox.warning(self, "No video", "Please import a video first.")
            return

        self.event_table.add_event(
            event_type=event_type,
            video_time_sec=self.video_player.current_time_sec(),
            frame_index=self.video_player.current_frame,
            note="",
        )

    def seek_video_marker_time(self, video_time_sec):
        if not self.video_player.has_video():
            return

        self.video_player.pause()
        self.video_player.seek_time_sec(video_time_sec)
        self.video_player.update_seek_inputs_from_current_frame()

    def seek_video_record_time(self, record_time_sec):
        if not self.video_player.has_video() or self.time_offset_sec is None:
            return

        video_time_sec = float(record_time_sec) + self.time_offset_sec
        self.video_player.pause()
        self.video_player.seek_time_sec(video_time_sec)
        self.video_player.update_seek_inputs_from_current_frame()

    def add_led_events(self, led_events):
        for event in led_events:
            self.event_table.add_event(
                event_type=event.event_type,
                video_time_sec=event.video_time_sec,
                frame_index=event.frame_index,
                note=f"brightness={event.brightness:.4f}",
                source="led_detection",
            )

        if led_events:
            self.show_marker_panel()

    def first_video_led_time_sec(self):
        led_events = [
            event
            for event in self.event_table.events()
            if event["event_type"] == "LED_on"
        ]
        if not led_events:
            return None

        first_led_event = min(led_events, key=lambda event: event["frame_index"])
        if self.video_player.has_video() and self.video_player.fps:
            return self.video_player.frame_to_time_sec(first_led_event["frame_index"])

        return first_led_event["video_time_sec"]

    def clear_time_offset(self):
        self.sync_panel.offset_label.setText(
            "Time offset (video - TTL): Not calculated"
        )
        self.time_offset_sec = None
        self.video_player.set_sync_time_origin(None)
        self.lfp_panel.set_sync_time_origin(None)
        self.event_table.set_sync_time_origin(None)
        self.lfp_panel.clear_current_time_marker()
        self.update_event_intervals()

    def update_time_offset(self):
        video_led_sec = self.first_video_led_time_sec()
        if video_led_sec is None:
            self.sync_panel.video_led_label.setText("Video LED marker: Not selected")
            self.clear_time_offset()
            return

        self.sync_panel.set_video_led_marker(video_led_sec)

        if self.timeMarker_info is None:
            self.clear_time_offset()
            return

        ttl_marker_sec = self.timeMarker_info.get("first_marker_sec")
        if ttl_marker_sec is None:
            self.clear_time_offset()
            return

        previous_video_origin_sec = self.video_player.sync_time_origin_sec
        self.time_offset_sec = video_led_sec - ttl_marker_sec
        self.video_player.set_sync_time_origin(video_led_sec)
        self.lfp_panel.set_sync_time_origin(ttl_marker_sec)
        self.event_table.set_sync_time_origin(video_led_sec)
        self.sync_panel.set_offset(self.time_offset_sec)
        if (
            previous_video_origin_sec is None
            or abs(previous_video_origin_sec - video_led_sec) > 1e-6
        ):
            self.video_player.seek_time_sec(video_led_sec)

        self.update_waveform_current_time(
            self.video_player.current_frame,
            self.video_player.current_time_sec(),
        )
        self.update_event_intervals()

    def update_event_intervals(self):
        if self.time_offset_sec is None:
            self.lfp_panel.set_event_intervals([])
            return

        events = self.event_table.events()
        video_intervals = [
            *pair_event_intervals(events, "behavior_start", "behavior_end", "behavior"),
            *pair_event_intervals(events, "LED_on", "LED_off", "led"),
        ]

        record_intervals = []
        for interval in video_intervals:
            record_intervals.append(
                {
                    **interval,
                    "record_start_sec": (
                        interval["video_start_sec"] - self.time_offset_sec
                    ),
                    "record_end_sec": (
                        interval["video_end_sec"] - self.time_offset_sec
                    ),
                }
            )

        self.lfp_panel.set_event_intervals(record_intervals)

    def update_waveform_current_time(self, frame_index, video_time_sec):
        if self.loading_video or self.time_offset_sec is None:
            return

        record_time_sec = video_time_sec - self.time_offset_sec
        self.lfp_panel.set_current_time_marker(
            record_time_sec,
            follow_playback=self.video_player.is_playing,
        )
