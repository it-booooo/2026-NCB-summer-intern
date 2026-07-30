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

    def test_release_analysis_segment_is_precise_and_updates_bytes(self):
        settings = self.settings()
        other_settings = self.settings(10.0)
        self.dataset.segment(2, 2.0, 4.0, None)
        self.dataset.segment(2, 2.0, 4.0, settings)
        self.dataset.segment(2, 6.0, 8.0, None)
        self.dataset.segment(2, 6.0, 8.0, settings)
        self.dataset.segment(2, 2.0, 4.0, other_settings)
        self.dataset.segment(5, 2.0, 4.0, None)
        self.dataset.segment(5, 2.0, 4.0, settings)
        disk_entries = set(Path(self.info["_signal_cache_root"]).rglob("*"))

        self.dataset.release_analysis_segment(2, 2.0, 4.0, settings)

        target_raw = self.dataset._segment_key(2, 2.0, 4.0)
        self.assertNotIn(target_raw, self.dataset._segment_cache)
        self.assertTrue(
            any(key[0] == 2 and key[1] == 6_000_000
                for key in self.dataset._segment_cache)
        )
        self.assertTrue(
            any(key[0] == 5 for key in self.dataset._segment_cache)
        )
        self.assertFalse(
            any(
                key[1] == 2
                and key[4] == settings
                and key[2] <= 2 * 625
                and key[3] >= 4 * 625 + 1
                for key in self.dataset._filtered_segment_cache
            )
        )
        self.assertTrue(
            any(
                key[1] == 2 and key[4] == other_settings
                for key in self.dataset._filtered_segment_cache
            )
        )
        self.assertEqual(
            self.dataset._segment_cache_bytes,
            sum(
                item.time_us.nbytes + item.values.nbytes
                for item in self.dataset._segment_cache.values()
            ),
        )
        self.assertEqual(
            self.dataset._filtered_segment_cache_bytes,
            sum(
                self.dataset._lfp_segment_bytes(item)
                for item in self.dataset._filtered_segment_cache.values()
            ),
        )
        self.assertEqual(
            set(Path(self.info["_signal_cache_root"]).rglob("*")),
            disk_entries,
        )

    def test_analysis_values_avoids_timestamp_arrays_and_ram_caches(self):
        with (
            patch.object(
                self.dataset.source,
                "indexed_segment",
                wraps=self.dataset.source.indexed_segment,
            ) as indexed_segment,
            patch.object(
                self.dataset.source,
                "indexed_values",
                wraps=self.dataset.source.indexed_values,
            ) as indexed_values,
        ):
            values, count, rate, start_s, end_s = (
                self.dataset.analysis_values(2, 2.0, 4.0, None)
            )

        indexed_segment.assert_not_called()
        indexed_values.assert_called_once()
        self.assertEqual(values.dtype, np.float32)
        self.assertEqual(values.size, count)
        self.assertEqual(rate, 625.0)
        self.assertEqual(start_s, 2.0)
        self.assertEqual(end_s, 4.0)
        self.assertFalse(self.dataset._segment_cache)
        self.assertFalse(self.dataset._filtered_segment_cache)
        self.assertEqual(self.dataset._segment_cache_bytes, 0)
        self.assertEqual(self.dataset._filtered_segment_cache_bytes, 0)

    def test_analysis_values_preserves_existing_playback_caches(self):
        settings = self.settings()
        self.dataset.update_playback_window(10.0, settings)
        self.assertTrue(self.dataset.wait_for_playback_cache())
        raw_keys = list(self.dataset._segment_cache)
        filtered_keys = list(self.dataset._filtered_segment_cache)
        raw_bytes = self.dataset._segment_cache_bytes
        filtered_bytes = self.dataset._filtered_segment_cache_bytes

        values, count, *_metadata = self.dataset.analysis_values(
            2,
            5.0,
            10.0,
            settings,
        )

        self.assertEqual(values.size, count)
        self.assertEqual(list(self.dataset._segment_cache), raw_keys)
        self.assertEqual(
            list(self.dataset._filtered_segment_cache),
            filtered_keys,
        )
        self.assertEqual(self.dataset._segment_cache_bytes, raw_bytes)
        self.assertEqual(
            self.dataset._filtered_segment_cache_bytes,
            filtered_bytes,
        )

    def test_filtered_analysis_values_match_regular_segment(self):
        settings = self.settings()
        expected = self.dataset.segment(2, 5.0, 10.0, settings)

        values, count, rate, start_s, end_s = (
            self.dataset.analysis_values(2, 5.0, 10.0, settings)
        )

        self.assertEqual(count, expected.sample_count)
        self.assertEqual(rate, expected.sample_rate_hz)
        self.assertEqual(start_s, float(expected.record_time_s[0]))
        self.assertEqual(end_s, float(expected.record_time_s[-1]))
        np.testing.assert_allclose(
            values,
            expected.values,
            rtol=1e-5,
            atol=1e-5,
        )

    def test_analysis_file_matches_regular_segment_without_new_cache(self):
        settings = self.settings()
        expected = self.dataset.segment(2, 5.0, 10.0, settings)
        raw_keys = list(self.dataset._segment_cache)
        filtered_keys = list(self.dataset._filtered_segment_cache)
        output_path = Path(self.directory.name) / "analysis-values.bin"

        count, rate, start_s, end_s, dtype = (
            self.dataset.write_analysis_values(
                output_path,
                2,
                5.0,
                10.0,
                settings,
            )
        )
        actual = np.memmap(
            output_path,
            dtype=np.dtype(dtype),
            mode="r",
            shape=(count,),
        )
        try:
            np.testing.assert_array_equal(actual, expected.values)
        finally:
            del actual

        self.assertEqual(rate, expected.sample_rate_hz)
        self.assertEqual(start_s, float(expected.record_time_s[0]))
        self.assertEqual(end_s, float(expected.record_time_s[-1]))
        self.assertEqual(list(self.dataset._segment_cache), raw_keys)
        self.assertEqual(
            list(self.dataset._filtered_segment_cache),
            filtered_keys,
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
