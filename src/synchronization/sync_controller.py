from ..markers import (
    Marker,
    MarkerKind,
    MarkerSource,
    RecordPosition,
    VideoPosition,
    marker_record_time,
    marker_video_time,
)


SYNC_VIDEO_REFERENCE_KINDS = frozenset(
    {MarkerKind.LED_ON, MarkerKind.BEHAVIOR_START}
)


def resolve_sync_reference_markers(markers, sync_state):
    markers = tuple(markers)
    if sync_state.reference_mode == "manual":
        by_id = {marker.marker_id: marker for marker in markers}
        ttl_marker = by_id.get(sync_state.ttl_reference_marker_id)
        video_marker = by_id.get(sync_state.video_reference_marker_id)
        if (
            ttl_marker is None
            or ttl_marker.kind != MarkerKind.TTL
            or not isinstance(ttl_marker.position, RecordPosition)
            or video_marker is None
            or video_marker.kind not in SYNC_VIDEO_REFERENCE_KINDS
            or not isinstance(video_marker.position, VideoPosition)
        ):
            return None, None
        return ttl_marker, video_marker

    ttl_markers = [
        marker
        for marker in markers
        if marker.kind == MarkerKind.TTL
        and isinstance(marker.position, RecordPosition)
    ]
    led_markers = [
        marker
        for marker in markers
        if marker.kind == MarkerKind.LED_ON
        and isinstance(marker.position, VideoPosition)
    ]
    return (
        min(ttl_markers, key=lambda marker: marker.position.time_sec)
        if ttl_markers
        else None,
        min(led_markers, key=lambda marker: marker.position.time_sec)
        if led_markers
        else None,
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
        wave_panel,
        ttl_panel,
        marker_panel,
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
        self.wave_panel = wave_panel
        self.ttl_panel = ttl_panel
        self.marker_panel = marker_panel
        self.find_peak_panel = find_peak_panel
        self.led_analysis_panel = led_analysis_panel

    def connect_signals(self):
        """Connect synchronization-owned interactions."""
        self.video_player.frame_changed.connect(self.update_waveform_current_time)
        self.wave_panel.time_selected.connect(self.seek_video_record_time)
        self.ttl_panel.record_time_selected.connect(
            self.seek_video_record_time
        )
        self.event_table.events_changed.connect(self.update_time_offset)
        self.event_table.video_time_selected.connect(self.seek_video_marker_time)
        self.marker_panel.sync_selection_changed.connect(self.set_sync_selection)
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
        self.sync_state.reference_mode = "auto"
        self.sync_state.ttl_reference_marker_id = None
        self.sync_state.video_reference_marker_id = None

        self.ttl_panel.set_markers(None, emit=False)
        self.marker_store.clear(emit=False)
        self.event_table.refresh()
        self.wave_panel.update_lfp_peak_artist()
        self.event_table.set_sync_time_origin(None)
        self.video_player.set_sync_time_origin(None)
        self.wave_panel.set_sync_time_origin(None)
        self.find_peak_panel.refresh_table()
        self.wave_panel.clear_current_time_marker()
        self.wave_panel.set_event_intervals([])

        self.video_player.update_time_offset_display()
        self.marker_panel.update_sync_selection_status()
        self.led_analysis_panel.led_roi_label.setText("LED ROI: Not selected")
        self.led_analysis_panel.set_roi_plot_idle()
        self.led_analysis_panel.set_led_detection_status(
            "LED detection: Not analyzed"
        )

    def seek_video_marker_time(self, video_time_sec):
        """Seek video marker time."""
        if not self.video_player.has_video():
            return

        self._seek_video_time(video_time_sec)

    def _seek_video_time(self, video_time_sec):
        self.video_player.pause()
        self.video_player.seek_time_sec(video_time_sec)
        self.video_player.update_seek_inputs_from_current_frame()
        if self.sync_state.time_offset_sec is not None:
            self.wave_panel.set_current_time_marker(
                float(video_time_sec) - self.sync_state.time_offset_sec,
                force_follow=True,
            )

    def seek_video_record_time(self, record_time_sec):
        """Seek video record time."""
        if (
            not self.video_player.has_video()
            or self.sync_state.time_offset_sec is None
        ):
            return

        video_time_sec = float(record_time_sec) + self.sync_state.time_offset_sec
        self._seek_video_time(video_time_sec)

    def add_led_events(self, led_events):
        """Add led events."""
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

    def set_sync_selection(self, mode, ttl_marker_id, video_marker_id):
        self.sync_state.reference_mode = mode
        self.sync_state.ttl_reference_marker_id = ttl_marker_id
        self.sync_state.video_reference_marker_id = video_marker_id
        self.update_time_offset()
        self.ttl_panel.refresh_table()

    def sync_reference_markers(self):
        return resolve_sync_reference_markers(
            self.marker_store.all(),
            self.sync_state,
        )

    def clear_time_offset(self):
        """Clear time offset.

        Args:
            None.
        """
        self.sync_state.time_offset_sec = None
        self.video_player.update_time_offset_display()
        self.video_player.set_sync_time_origin(None)
        self.wave_panel.set_sync_time_origin(None)
        self.event_table.set_sync_time_origin(None)
        self.find_peak_panel.refresh_table()
        self.wave_panel.clear_current_time_marker()
        self.update_event_intervals()
        self.marker_panel.update_sync_selection_status()

    def update_time_offset(self):
        """Update time offset.

        Args:
            None.
        """
        ttl_marker, video_marker = self.sync_reference_markers()
        if ttl_marker is None or video_marker is None:
            self.clear_time_offset()
            return

        ttl_marker_sec = ttl_marker.position.time_sec
        video_marker_sec = video_marker.position.time_sec

        previous_video_origin_sec = self.sync_state.video_time_origin_sec
        self.sync_state.time_offset_sec = video_marker_sec - ttl_marker_sec
        self.video_player.set_sync_time_origin(video_marker_sec)
        self.wave_panel.set_sync_time_origin(ttl_marker_sec)
        self.event_table.set_sync_time_origin(video_marker_sec)
        self.find_peak_panel.refresh_table()
        self.video_player.update_time_offset_display()
        if (
            previous_video_origin_sec is None
            or abs(previous_video_origin_sec - video_marker_sec) > 1e-6
        ):
            self.video_player.seek_time_sec(video_marker_sec)

        self.update_waveform_current_time()
        self.update_event_intervals()
        self.marker_panel.update_sync_selection_status()

    def update_event_intervals(self):
        """Update event intervals.

        Args:
            None.
        """
        markers = self.marker_store.all()
        record_intervals = []
        for marker in markers:
            if marker.kind != MarkerKind.TTL:
                continue
            record_time_sec = marker_record_time(marker, self.sync_state.time_offset_sec)
            if record_time_sec is None:
                continue
            record_intervals.append(
                {
                    "event_type": "ttl",
                    "record_time_sec": record_time_sec,
                    "marker_id": marker.marker_id,
                }
            )

        if self.sync_state.time_offset_sec is None:
            self.wave_panel.set_event_intervals([])
            return

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

        self.wave_panel.set_event_intervals(record_intervals)

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
        self.wave_panel.set_current_time_marker(
            record_time_sec,
            follow_playback=self.video_state.is_playing,
        )
