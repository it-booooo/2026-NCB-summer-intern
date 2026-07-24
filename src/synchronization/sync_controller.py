from ..markers import (
    Marker,
    MarkerKind,
    MarkerSource,
    VideoPosition,
    marker_record_time,
    marker_video_time,
)


def pair_event_intervals(markers, start_kind, end_kind, interval_type, offset_sec):
    """Pair matching start/end point markers in table order."""
    intervals = []
    pending_start = None
    for marker in markers:
        if marker.kind == start_kind:
            pending_start = marker
        elif marker.kind == end_kind and pending_start is not None:
            start_sec = marker_video_time(pending_start, offset_sec)
            end_sec = marker_video_time(marker, offset_sec)
            if start_sec is None or end_sec is None:
                continue
            if end_sec > start_sec:
                intervals.append(
                    {
                        "event_type": interval_type,
                        "video_start_sec": start_sec,
                        "video_end_sec": end_sec,
                        "start_marker_id": pending_start.marker_id,
                        "end_marker_id": marker.marker_id,
                    }
                )
                pending_start = None
    return intervals


class SyncController:
    """TTL, event marker, and video-to-record-time synchronization logic."""

    def __init__(
        self,
        *,
        sync_state,
        ttl_state,
        led_state,
        video_state,
        marker_store,
        video_player,
        event_table,
        lfp_panel,
        ttl_panel,
        find_peak_panel,
        led_analysis_panel,
    ):
        self.sync_state = sync_state
        self.ttl_state = ttl_state
        self.led_state = led_state
        self.video_state = video_state
        self.marker_store = marker_store
        self.video_player = video_player
        self.event_table = event_table
        self.lfp_panel = lfp_panel
        self.ttl_panel = ttl_panel
        self.find_peak_panel = find_peak_panel
        self.led_analysis_panel = led_analysis_panel

    def connect_signals(self):
        """Connect synchronization-owned interactions."""
        self.video_player.frame_changed.connect(self.update_waveform_current_time)
        self.lfp_panel.time_selected.connect(self.seek_video_record_time)
        self.ttl_panel.record_time_selected.connect(
            self.seek_video_record_time
        )
        self.event_table.events_changed.connect(self.update_time_offset)
        self.event_table.video_time_selected.connect(self.seek_video_marker_time)
        self.find_peak_panel.video_time_selected.connect(
            self.seek_video_marker_time
        )

    def reset_sync_state_for_new_video(self):
        """Reset sync state for new video.

        Args:
            None.
        """
        self.ttl_state.metadata = None
        self.led_state.roi = None
        self.sync_state.time_offset_sec = None

        self.ttl_panel.set_markers(None, emit=False)
        self.marker_store.clear(emit=False)
        self.event_table.refresh()
        self.lfp_panel.update_lfp_peak_artist()
        self.event_table.set_sync_time_origin(None)
        self.video_player.set_sync_time_origin(None)
        self.lfp_panel.set_sync_time_origin(None)
        self.find_peak_panel.refresh_table()
        self.lfp_panel.clear_current_time_marker()
        self.lfp_panel.set_event_intervals([])

        self.video_player.update_time_offset_display()
        self.led_analysis_panel.led_roi_label.setText("LED ROI: Not selected")
        self.led_analysis_panel.set_roi_plot_idle()
        self.led_analysis_panel.set_led_detection_status(
            "LED detection: Not analyzed"
        )

    def seek_video_marker_time(self, video_time_sec):
        """Seek video marker time.

        Args:
            video_time_sec: Input used by this operation.
        """
        if not self.video_player.has_video():
            return

        self._seek_video_time(video_time_sec)

    def _seek_video_time(self, video_time_sec):
        self.video_player.pause()
        self.video_player.seek_time_sec(video_time_sec)
        self.video_player.update_seek_inputs_from_current_frame()
        if self.sync_state.time_offset_sec is not None:
            self.lfp_panel.set_current_time_marker(
                float(video_time_sec) - self.sync_state.time_offset_sec,
                force_follow=True,
            )

    def seek_video_record_time(self, record_time_sec):
        """Seek video record time.

        Args:
            record_time_sec: Input used by this operation.
        """
        if (
            not self.video_player.has_video()
            or self.sync_state.time_offset_sec is None
        ):
            return

        video_time_sec = float(record_time_sec) + self.sync_state.time_offset_sec
        self._seek_video_time(video_time_sec)

    def add_led_events(self, led_events):
        """Add led events.

        Args:
            led_events: Input used by this operation.
        """
        markers = [
            Marker(
                kind=MarkerKind(event.event_type),
                source=MarkerSource.LED_DETECTION,
                position=VideoPosition(event.video_time_sec, event.frame_index),
                note=f"brightness={event.brightness:.4f}",
                payload={"brightness": float(event.brightness)},
            )
            for event in led_events
        ]
        self.marker_store.replace_by_source(MarkerSource.LED_DETECTION, markers)
        return markers

    def first_video_led_time_sec(self):
        """Provide first video led time sec functionality.

        Args:
            None.
        """
        led_events = self.marker_store.by_kind(MarkerKind.LED_ON)
        if not led_events:
            return None

        video_events = [
            marker for marker in led_events if isinstance(marker.position, VideoPosition)
        ]
        if not video_events:
            return None
        return min(video_events, key=lambda marker: marker.position.time_sec).position.time_sec

    def clear_time_offset(self):
        """Clear time offset.

        Args:
            None.
        """
        self.sync_state.time_offset_sec = None
        self.video_player.update_time_offset_display()
        self.video_player.set_sync_time_origin(None)
        self.lfp_panel.set_sync_time_origin(None)
        self.event_table.set_sync_time_origin(None)
        self.find_peak_panel.refresh_table()
        self.lfp_panel.clear_current_time_marker()
        self.update_event_intervals()

    def update_time_offset(self):
        """Update time offset.

        Args:
            None.
        """
        video_led_sec = self.first_video_led_time_sec()
        ttl_markers = self.marker_store.by_kind(MarkerKind.TTL)
        ttl_marker_sec = (
            min(marker.position.time_sec for marker in ttl_markers)
            if ttl_markers
            else None
        )
        if video_led_sec is None or ttl_marker_sec is None:
            self.clear_time_offset()
            return

        previous_video_origin_sec = self.sync_state.video_time_origin_sec
        self.sync_state.time_offset_sec = video_led_sec - ttl_marker_sec
        self.video_player.set_sync_time_origin(video_led_sec)
        self.lfp_panel.set_sync_time_origin(ttl_marker_sec)
        self.event_table.set_sync_time_origin(video_led_sec)
        self.find_peak_panel.refresh_table()
        self.video_player.update_time_offset_display()
        if (
            previous_video_origin_sec is None
            or abs(previous_video_origin_sec - video_led_sec) > 1e-6
        ):
            self.video_player.seek_time_sec(video_led_sec)

        self.update_waveform_current_time()
        self.update_event_intervals()

    def update_event_intervals(self):
        """Update event intervals.

        Args:
            None.
        """
        if self.sync_state.time_offset_sec is None:
            self.lfp_panel.set_event_intervals([])
            return

        markers = self.marker_store.all()
        video_intervals = [
            *pair_event_intervals(
                markers,
                MarkerKind.BEHAVIOR_START,
                MarkerKind.BEHAVIOR_END,
                "behavior",
                self.sync_state.time_offset_sec,
            ),
            *pair_event_intervals(
                markers,
                MarkerKind.LED_ON,
                MarkerKind.LED_OFF,
                "led",
                self.sync_state.time_offset_sec,
            ),
        ]

        record_intervals = []
        for interval in video_intervals:
            record_intervals.append(
                {
                    **interval,
                    "record_start_sec": (
                        interval["video_start_sec"]
                        - self.sync_state.time_offset_sec
                    ),
                    "record_end_sec": (
                        interval["video_end_sec"]
                        - self.sync_state.time_offset_sec
                    ),
                }
            )

        for marker in markers:
            if marker.kind != MarkerKind.SEIZURE_LIKE:
                continue
            video_time_sec = marker_video_time(marker, self.sync_state.time_offset_sec)
            record_time_sec = marker_record_time(marker, self.sync_state.time_offset_sec)
            if video_time_sec is None or record_time_sec is None:
                continue
            record_intervals.append(
                {
                    "event_type": "seizure_like_event",
                    "video_time_sec": video_time_sec,
                    "record_time_sec": record_time_sec,
                    "marker_id": marker.marker_id,
                }
            )

        self.lfp_panel.set_event_intervals(record_intervals)

    def update_waveform_current_time(self):
        """Update waveform current time.

        Args:
            None.
        """
        video_time_sec = self.video_player.current_time_sec()
        if (
            self.sync_state.loading_video
            or self.sync_state.time_offset_sec is None
        ):
            return

        record_time_sec = video_time_sec - self.sync_state.time_offset_sec
        self.lfp_panel.set_current_time_marker(
            record_time_sec,
            follow_playback=self.video_state.is_playing,
        )
