import unittest

from src.markers import (
    Marker,
    MarkerKind,
    MarkerSource,
    MarkerStore,
    RecordPosition,
    VideoPosition,
    marker_from_dict,
    marker_from_legacy_ttl,
    marker_record_time,
    marker_to_dict,
    marker_video_time,
)
from src.synchronization.sync_controller import pair_event_intervals


class MarkerModelTests(unittest.TestCase):
    def test_timeline_conversion_uses_original_position(self):
        video = Marker(
            kind=MarkerKind.LED_ON,
            source=MarkerSource.MANUAL,
            position=VideoPosition(12.5, 750),
        )
        record = Marker(
            kind=MarkerKind.TTL,
            source=MarkerSource.TTL_IMPORT,
            position=RecordPosition(10.0),
        )

        self.assertEqual(marker_record_time(video, 2.5), 10.0)
        self.assertEqual(marker_video_time(record, 2.5), 12.5)
        self.assertIsNone(marker_record_time(video, None))

    def test_serialization_round_trip_preserves_marker_identity(self):
        marker = Marker(
            kind=MarkerKind.LFP_PEAK,
            source=MarkerSource.LFP_DETECTION,
            position=RecordPosition(42.25),
            note="peak",
            payload={"channel": 3, "value": 1.25},
        )

        restored = marker_from_dict(marker_to_dict(marker))

        self.assertEqual(restored, marker)

    def test_marker_values_use_canonical_snake_case(self):
        self.assertEqual(
            {kind.value for kind in MarkerKind},
            {
                "ttl",
                "led_on",
                "led_off",
                "action_start",
                "action_end",
                "seizure_like",
                "lfp_peak",
            },
        )
        self.assertEqual(MarkerSource.LFP_DETECTION.value, "lfp_detection")

    def test_legacy_ttl_records_migrate_to_markers(self):
        ttl = marker_from_legacy_ttl({"record_time": 2_000_000})

        self.assertEqual(ttl.kind, MarkerKind.TTL)
        self.assertEqual(ttl.position, RecordPosition(2.0))


class MarkerStoreTests(unittest.TestCase):
    def test_store_keeps_app_state_list_as_single_source_of_truth(self):
        state_markers = []
        store = MarkerStore(state_markers)
        marker = Marker(
            kind=MarkerKind.TTL,
            source=MarkerSource.MANUAL,
            position=RecordPosition(1.0),
        )

        store.add(marker)

        self.assertEqual(state_markers, [marker])

    def test_replace_by_source_keeps_other_markers_and_emits_once(self):
        manual = Marker(
            kind=MarkerKind.LED_ON,
            source=MarkerSource.MANUAL,
            position=VideoPosition(1.0, 30),
        )
        detected = Marker(
            kind=MarkerKind.LED_ON,
            source=MarkerSource.LED_DETECTION,
            position=VideoPosition(2.0, 60),
        )
        store = MarkerStore([manual, detected])
        emissions = []
        store.changed.connect(lambda: emissions.append(True))
        replacement = Marker(
            kind=MarkerKind.LED_OFF,
            source=MarkerSource.LED_DETECTION,
            position=VideoPosition(3.0, 90),
        )

        store.replace_by_source(MarkerSource.LED_DETECTION, [replacement])

        self.assertEqual(store.all(), (manual, replacement))
        self.assertEqual(len(emissions), 1)

    def test_updates_and_deletes_use_marker_id(self):
        marker = Marker(
            kind=MarkerKind.ACTION_START,
            source=MarkerSource.MANUAL,
            position=VideoPosition(1.0, 30),
        )
        store = MarkerStore([marker])

        updated = store.update(marker.marker_id, note="changed")
        store.delete(marker.marker_id)

        self.assertEqual(updated.note, "changed")
        self.assertEqual(store.all(), ())


class MarkerIntervalTests(unittest.TestCase):
    def test_interval_pairing_accepts_unified_markers(self):
        markers = [
            Marker(
                kind=MarkerKind.ACTION_START,
                source=MarkerSource.MANUAL,
                position=VideoPosition(5.0, 150),
            ),
            Marker(
                kind=MarkerKind.ACTION_END,
                source=MarkerSource.MANUAL,
                position=VideoPosition(8.0, 240),
            ),
        ]

        intervals = pair_event_intervals(
            markers,
            MarkerKind.ACTION_START,
            MarkerKind.ACTION_END,
            "action",
            2.0,
        )

        self.assertEqual(intervals[0]["video_start_sec"], 5.0)
        self.assertEqual(intervals[0]["video_end_sec"], 8.0)
        self.assertEqual(intervals[0]["event_type"], "action")


if __name__ == "__main__":
    unittest.main()
