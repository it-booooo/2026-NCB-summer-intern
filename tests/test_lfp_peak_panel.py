import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QProgressDialog

# Loading this focused module must not import every optional UI feature (notably
# OpenCV) through src.ui.__init__.
ui_package = types.ModuleType("src.ui")
ui_package.__path__ = [str(Path(__file__).parents[1] / "src" / "ui")]
sys.modules.setdefault("src.ui", ui_package)

from src.markers import MarkerStore, peak_records_to_markers
from src.ui.lfp_peak_panel import (
    PEAK_TYPE_NEGATIVE,
    PEAK_TYPE_POSITIVE,
    SORT_BY_TIME,
    SORT_BY_VALUE,
    LfpPeakPanel,
    filter_sort_peak_markers,
)


def peak_marker(channel, record_time_s, value, negative):
    return peak_records_to_markers(
        channel,
        [
            {
                "record_time_s": record_time_s,
                "value": value,
                "negative": negative,
            }
        ],
    )[0]


class FakeLfpService:
    def __init__(self):
        self.source = SimpleNamespace(identity_token=lambda: "source-1")
        self._dataset = SimpleNamespace(source=self.source)

    def available_channels(self):
        return [2, 5]

    def selected_channel(self):
        return 2

    def dataset(self):
        return self._dataset


class LfpPeakFilteringTests(unittest.TestCase):
    def setUp(self):
        self.markers = (
            peak_marker(2, 3.0, -300.0, True),
            peak_marker(2, 1.0, 50.0, False),
            peak_marker(2, 4.0, 200.0, False),
            peak_marker(2, 2.0, -100.0, True),
            peak_marker(5, 0.5, 999.0, False),
        )

    def values(self, **options):
        return [
            marker.payload["value"]
            for marker in filter_sort_peak_markers(
                self.markers,
                channel=2,
                **options,
            )
        ]

    def test_all_positive_and_negative_filters(self):
        self.assertEqual(self.values(), [50.0, -100.0, -300.0, 200.0])
        self.assertEqual(
            self.values(peak_type=PEAK_TYPE_POSITIVE),
            [50.0, 200.0],
        )
        self.assertEqual(
            self.values(peak_type=PEAK_TYPE_NEGATIVE),
            [-100.0, -300.0],
        )

    def test_time_ascending_and_descending(self):
        self.assertEqual(
            self.values(sort_by=SORT_BY_TIME),
            [50.0, -100.0, -300.0, 200.0],
        )
        self.assertEqual(
            self.values(sort_by=SORT_BY_TIME, descending=True),
            [200.0, -300.0, -100.0, 50.0],
        )

    def test_signed_peak_value_ascending_and_descending(self):
        self.assertEqual(
            self.values(sort_by=SORT_BY_VALUE),
            [-300.0, -100.0, 50.0, 200.0],
        )
        self.assertEqual(
            self.values(sort_by=SORT_BY_VALUE, descending=True),
            [200.0, 50.0, -100.0, -300.0],
        )

    def test_polarity_filter_and_value_sort_share_one_pipeline(self):
        self.assertEqual(
            self.values(
                peak_type=PEAK_TYPE_NEGATIVE,
                sort_by=SORT_BY_VALUE,
                descending=True,
            ),
            [-100.0, -300.0],
        )


class LfpPeakPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.markers = [
            peak_marker(2, 3.0, -300.0, True),
            peak_marker(2, 1.0, 50.0, False),
            peak_marker(2, 4.0, 200.0, False),
            peak_marker(2, 2.0, -100.0, True),
        ]
        self.store = MarkerStore(self.markers)
        self.service = FakeLfpService()
        self.panel = LfpPeakPanel(
            self.store,
            self.service,
            SimpleNamespace(time_offset_sec=0.5, video_time_origin_sec=None),
            SimpleNamespace(metadata=SimpleNamespace(duration_sec=10.0)),
            SimpleNamespace(has_video=lambda: True),
            SimpleNamespace(),
        )

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()

    def displayed_ids(self):
        return [
            self.panel.table.item(row, 0).data(self.panel.MARKER_ID_ROLE)
            for row in range(self.panel.table.rowCount())
        ]

    def select_combo_data(self, combo, value):
        index = combo.findData(value)
        self.assertGreaterEqual(index, 0)
        combo.setCurrentIndex(index)

    def test_defaults_and_peak_table_columns(self):
        self.assertEqual(self.panel.peak_type_selector.currentData(), "all")
        self.assertEqual(self.panel.sort_by_selector.currentData(), SORT_BY_TIME)
        self.assertFalse(self.panel.order_selector.currentData())
        self.assertEqual(self.panel.table.columnCount(), 4)
        self.assertEqual(self.panel.table.item(0, 0).text(), "Positive")
        self.assertEqual(self.panel.table.item(0, 2).text(), "50")

    def test_sorting_then_delete_uses_visible_marker_id(self):
        self.select_combo_data(self.panel.sort_by_selector, SORT_BY_VALUE)
        self.panel.order_selector.setCurrentIndex(1)
        expected_id = self.displayed_ids()[0]
        self.panel.table.selectRow(0)

        self.panel.delete_selected_peak()

        with self.assertRaises(KeyError):
            self.store.get(expected_id)
        self.assertEqual(len(self.store.all()), 3)

    def test_filtering_then_delete_uses_visible_marker_id(self):
        self.select_combo_data(self.panel.peak_type_selector, PEAK_TYPE_NEGATIVE)
        expected_id = self.displayed_ids()[0]
        self.panel.table.selectRow(0)

        self.panel.delete_selected_peak()

        with self.assertRaises(KeyError):
            self.store.get(expected_id)
        self.assertTrue(
            all(marker.marker_id != expected_id for marker in self.store.all())
        )

    def test_note_item_updates_the_canonical_marker(self):
        marker_id = self.displayed_ids()[0]

        self.panel.table.item(0, 3).setText("reviewed")

        self.assertEqual(self.store.get(marker_id).note, "reviewed")

    def test_progress_reaches_100_only_after_table_is_ready(self):
        request_id = "request-1"
        self.panel._peak_request_id = request_id
        progress = QProgressDialog("Working", "Cancel", 0, 100, self.panel)
        progress.setAutoClose(False)
        self.panel._peak_progress = progress
        events = []
        original_update = self.panel._update_peak_progress

        def record_progress(result_id, value):
            events.append(("progress", value, self.panel.table.rowCount()))
            original_update(result_id, value)

        self.panel._update_peak_progress = record_progress
        self.store.changed.connect(
            lambda: events.append(("store_changed", None, self.panel.table.rowCount()))
        )
        result = {
            "channel": 2,
            "records": [
                {"record_time_s": 7.0, "value": -8.0, "negative": True}
            ],
            "acceleration": {},
        }

        self.panel._finish_peak_detection(request_id, "source-1", result)

        progress_100 = next(
            index
            for index, event in enumerate(events)
            if event[0:2] == ("progress", 100)
        )
        store_changed = next(
            index for index, event in enumerate(events) if event[0] == "store_changed"
        )
        self.assertLess(store_changed, progress_100)
        self.assertEqual(events[progress_100][2], 1)
        self.assertIsNone(self.panel._peak_progress)


if __name__ == "__main__":
    unittest.main()
