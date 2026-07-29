import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from benchmarks.signal_csv_fixture import SignalFixtureConfig, generate_signal_csv
from src.signal_data import (
    LfpDataset,
    LfpFilterSettings,
    filter_padding_samples,
    parse_lfp_csv_info,
    prepare_lfp_signal,
)
from src.signal_data import lfp_dataset as lfp_dataset_module
from src.signal_data.source import CacheBuildCancelled, _SOURCES


class SegmentFilteringTests(unittest.TestCase):
    def setUp(self):
        _SOURCES.clear()
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "filter.csv"
        generate_signal_csv(
            self.path,
            SignalFixtureConfig(
                sample_rate_hz=625,
                duration_s=20,
                channels=(2, 5, 260),
                peak_indices=(),
            ),
        )
        self.info = parse_lfp_csv_info(self.path)
        self.info["_signal_cache_root"] = str(
            Path(self.directory.name) / "signal-cache"
        )
        self.dataset = LfpDataset.from_csv(self.info)

    def tearDown(self):
        _SOURCES.clear()
        self.directory.cleanup()

    @staticmethod
    def settings(low_hz=5.0):
        return LfpFilterSettings(
            show_filtered=True,
            bandpass_enabled=True,
            bandpass_low_hz=low_hz,
            bandpass_high_hz=100.0,
            line_noise_hz=None,
        )

    def test_padding_scales_with_sample_rate_and_lowest_cutoff(self):
        settings = self.settings(5.0)
        self.assertEqual(filter_padding_samples(settings, 625), 375)
        self.assertEqual(filter_padding_samples(settings, 1250), 750)
        self.assertGreater(
            filter_padding_samples(self.settings(1.0), 625),
            filter_padding_samples(settings, 625),
        )

    def test_segment_loads_padding_then_crops_requested_indices(self):
        settings = self.settings()
        left, right = self.dataset.source.segment_indices(
            2, 5_000_000, 10_000_000
        )
        padding = filter_padding_samples(settings, 625)
        with patch.object(
            self.dataset.source,
            "indexed_segment",
            wraps=self.dataset.source.indexed_segment,
        ) as indexed:
            segment = self.dataset.segment(2, 5.0, 10.0, settings)

        indexed.assert_called_once_with(
            2, left - padding, right + padding, None
        )
        self.assertEqual(segment.sample_count, right - left)
        self.assertEqual(segment.time_us[0], 5_000_000)
        self.assertEqual(segment.time_us[-1], 10_000_000)

    def test_padded_segment_matches_full_filter_away_from_edges(self):
        settings = self.settings()
        bounds = self.dataset.source.bounds(2)
        raw = self.dataset.source.segment(2, *bounds)
        full_filtered = prepare_lfp_signal(raw.values, 625, settings)
        segment = self.dataset.segment(2, 5.0, 15.0, settings)
        left, right = self.dataset.source.segment_indices(
            2, 5_000_000, 15_000_000
        )
        edge = 625

        np.testing.assert_allclose(
            segment.values[edge:-edge],
            full_filtered[left + edge : right - edge],
            rtol=2e-3,
            atol=2e-3,
        )

    def test_filter_settings_are_part_of_cache_key(self):
        first = self.settings(5.0)
        second = self.settings(10.0)
        with patch(
            "src.signal_data.lfp_dataset.prepare_lfp_signal",
            wraps=prepare_lfp_signal,
        ) as filtering:
            cached = self.dataset.segment(2, 2.0, 4.0, first)
            repeated = self.dataset.segment(2, 2.0, 4.0, first)
            changed = self.dataset.segment(2, 2.0, 4.0, second)

        self.assertIs(cached, repeated)
        self.assertIsNot(cached, changed)
        self.assertEqual(filtering.call_count, 2)

    def test_playback_preload_covers_all_channels_and_reuses_fine_data(self):
        settings = self.settings()
        self.dataset.update_playback_window(10.0, settings)
        self.assertTrue(self.dataset.wait_for_playback_cache())

        self.assertEqual(
            {key[0] for key in self.dataset._segment_cache},
            {2, 5, 260},
        )
        self.assertEqual(
            {key[1] for key in self.dataset._filtered_segment_cache},
            {2, 5, 260},
        )
        with (
            patch.object(
                self.dataset.source,
                "segment",
                wraps=self.dataset.source.segment,
            ) as raw_read,
            patch.object(
                self.dataset.source,
                "indexed_segment",
                wraps=self.dataset.source.indexed_segment,
            ) as indexed_read,
        ):
            raw = self.dataset.segment(5, 5.0, 10.0, None)
            filtered = self.dataset.segment(5, 5.0, 10.0, settings)

        raw_read.assert_not_called()
        indexed_read.assert_not_called()
        self.assertEqual(raw.sample_count, filtered.sample_count)

    def test_playback_advance_evicts_the_previous_fine_window(self):
        self.dataset.update_playback_window(10.0, None)
        self.assertTrue(self.dataset.wait_for_playback_cache())
        self.assertTrue(self.dataset._segment_cache)

        self.dataset.update_playback_window(100.0, None)
        self.assertTrue(self.dataset.wait_for_playback_cache())

        self.assertFalse(
            any(key[1] == 0 for key in self.dataset._segment_cache)
        )

    def test_visible_range_preloads_manual_zoom_but_skips_large_ranges(self):
        settings = self.settings()
        self.assertTrue(
            self.dataset.update_visible_range(5.0, 10.0, settings)
        )
        self.assertTrue(self.dataset.wait_for_playback_cache())
        self.assertEqual(
            {key[0] for key in self.dataset._segment_cache},
            {2, 5, 260},
        )
        prepared_range = self.dataset._fine_range_s

        self.assertFalse(
            self.dataset.update_visible_range(0.0, 10_000.0, settings)
        )
        self.assertEqual(self.dataset._fine_range_s, prepared_range)

    def test_filtered_segment_lru_has_entry_and_byte_limits(self):
        settings = self.settings()
        with (
            patch.object(
                lfp_dataset_module,
                "FILTERED_SEGMENT_CACHE_MAX_ENTRIES",
                2,
            ),
            patch.object(
                lfp_dataset_module,
                "FILTERED_SEGMENT_CACHE_MAX_BYTES",
                10 * 1024 * 1024,
            ),
        ):
            self.dataset.segment(2, 1.0, 2.0, settings)
            self.dataset.segment(2, 3.0, 4.0, settings)
            self.dataset.segment(2, 5.0, 6.0, settings)

        self.assertEqual(len(self.dataset._filtered_segment_cache), 2)
        self.assertLessEqual(
            self.dataset._filtered_segment_cache_bytes,
            10 * 1024 * 1024,
        )

    def test_large_filter_checks_cancellation_between_blocks(self):
        settings = self.settings()
        cancel = threading.Event()
        progress = []

        def stop_after_first_block(value):
            progress.append(value)
            cancel.set()

        with (
            patch.object(lfp_dataset_module, "FILTER_BLOCK_SAMPLES", 100),
            self.assertRaises(CacheBuildCancelled),
        ):
            self.dataset.segment(
                2,
                0.0,
                10.0,
                settings,
                cancel,
                stop_after_first_block,
            )
        self.assertEqual(len(progress), 1)


if __name__ == "__main__":
    unittest.main()
