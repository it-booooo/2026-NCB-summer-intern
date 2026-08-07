import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from benchmarks.signal_csv_fixture import SignalFixtureConfig, generate_signal_csv
from lfp_analysis_process import _finite_signal
from src.signal_data import (
    LfpAnalysisWorker,
    LfpDataset,
    LfpFilterSettings,
    parse_lfp_csv_info,
)
from src.signal_data import lfp_dataset as lfp_dataset_module
from src.signal_data.source import (
    _SOURCES,
    ANALYSIS_FILTER_CACHE_PREFIX,
    CacheBuildCancelled,
    cleanup_signal_cache,
)


class FilteredAnalysisCacheTests(unittest.TestCase):
    def setUp(self):
        _SOURCES.clear()
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.path = root / "analysis-cache.csv"
        generate_signal_csv(
            self.path,
            SignalFixtureConfig(
                sample_rate_hz=625,
                duration_s=20,
                channels=(2, 5, 260),
                peak_indices=(),
            ),
        )
        info = parse_lfp_csv_info(self.path)
        self.cache_root = root / "signal-cache"
        info["_signal_cache_root"] = str(self.cache_root)
        self.dataset = LfpDataset.from_csv(info)

    def tearDown(self):
        self.dataset.close(wait=True)
        _SOURCES.clear()
        self.directory.cleanup()

    @staticmethod
    def settings(low_hz=5.0):
        return LfpFilterSettings(
            show_filtered=True,
            bandpass_enabled=True,
            bandpass_low_hz=low_hz,
            bandpass_high_hz=100.0,
            line_noise_method="none",
        )

    def cache_directories(self):
        return list(self.cache_root.glob(f"{ANALYSIS_FILTER_CACHE_PREFIX}*"))

    def test_identical_filtered_requests_reuse_one_persistent_file(self):
        settings = self.settings()
        equivalent = self.settings()
        with patch.object(
            self.dataset,
            "write_analysis_values",
            wraps=self.dataset.write_analysis_values,
        ) as writer:
            with self.dataset.analysis_values_file(
                2, 2.0, 8.0, settings
            ) as first:
                first_path = Path(first.path)
                self.assertTrue(first_path.is_file())
                self.assertTrue(first.persistent)
                self.assertFalse(first.cache_hit)
            with self.dataset.analysis_values_file(
                2, 2.0, 8.0, equivalent
            ) as second:
                self.assertEqual(Path(second.path), first_path)
                self.assertTrue(second.persistent)
                self.assertTrue(second.cache_hit)

        self.assertEqual(writer.call_count, 1)
        self.assertIsNot(settings, equivalent)
        self.assertEqual(settings, equivalent)
        self.assertTrue(first_path.is_file())
        self.assertEqual(len(self.cache_directories()), 1)

    def test_filter_settings_are_part_of_the_cache_identity(self):
        paths = []
        for settings in (self.settings(5.0), self.settings(6.0)):
            with self.dataset.analysis_values_file(
                2, 2.0, 8.0, settings
            ) as prepared:
                paths.append(Path(prepared.path))

        self.assertNotEqual(paths[0], paths[1])
        self.assertEqual(len(self.cache_directories()), 2)

    def test_power_spectrum_and_spectrogram_workers_share_filtered_values(self):
        settings = self.settings()
        with (
            patch.object(
                self.dataset,
                "write_analysis_values",
                wraps=self.dataset.write_analysis_values,
            ) as writer,
            patch.object(
                LfpAnalysisWorker,
                "_render_in_process",
                return_value=b"png",
            ),
        ):
            power = LfpAnalysisWorker(
                "power",
                self.dataset,
                2,
                2.0,
                8.0,
                settings,
                "power_spectrum",
            ).execute()
            spectrogram = LfpAnalysisWorker(
                "spectrogram",
                self.dataset,
                2,
                2.0,
                8.0,
                settings,
                "spectrogram",
            ).execute()

        self.assertEqual(writer.call_count, 1)
        self.assertEqual(power["sample_count"], spectrogram["sample_count"])
        self.assertEqual(power["image_png"], b"png")
        self.assertEqual(spectrogram["image_png"], b"png")

    def test_raw_and_oversized_filtered_requests_remain_temporary(self):
        with self.dataset.analysis_values_file(
            2,
            2.0,
            8.0,
            LfpFilterSettings(show_filtered=False),
        ) as raw:
            raw_path = Path(raw.path)
            self.assertTrue(raw_path.is_file())
            self.assertFalse(raw.persistent)
        self.assertFalse(raw_path.exists())

        with patch.object(
            lfp_dataset_module,
            "filtered_analysis_cache_max_bytes",
            return_value=1,
        ):
            with self.dataset.analysis_values_file(
                2, 2.0, 8.0, self.settings()
            ) as filtered:
                filtered_path = Path(filtered.path)
                self.assertTrue(filtered_path.is_file())
                self.assertFalse(filtered.persistent)
            self.assertFalse(filtered_path.exists())

        self.assertFalse(self.cache_directories())

    def test_analysis_cache_disk_budget_evicts_the_oldest_entry(self):
        with patch.object(
            lfp_dataset_module,
            "filtered_analysis_cache_max_bytes",
            return_value=50_000,
        ):
            with self.dataset.analysis_values_file(
                2, 0.0, 4.0, self.settings()
            ) as first:
                first_directory = Path(first.path).parent
            with self.dataset.analysis_values_file(
                2, 8.0, 12.0, self.settings()
            ) as second:
                second_directory = Path(second.path).parent

        self.assertNotEqual(first_directory, second_directory)
        self.assertFalse(first_directory.exists())
        self.assertTrue(second_directory.exists())
        self.assertEqual(self.cache_directories(), [second_directory])

    def test_in_use_cache_is_protected_from_cleanup(self):
        with self.dataset.analysis_values_file(
            2, 2.0, 8.0, self.settings()
        ) as prepared:
            cache_directory = Path(prepared.path).parent
            cleanup_signal_cache(
                self.cache_root,
                max_bytes=0,
                cache_prefixes=(ANALYSIS_FILTER_CACHE_PREFIX,),
            )
            self.assertTrue(cache_directory.exists())

        cleanup_signal_cache(
            self.cache_root,
            max_bytes=0,
            cache_prefixes=(ANALYSIS_FILTER_CACHE_PREFIX,),
        )
        self.assertFalse(cache_directory.exists())

    def test_cancelled_build_removes_partial_cache(self):
        cancel = threading.Event()

        def cancel_after_first_block(_value):
            cancel.set()

        with (
            patch.object(lfp_dataset_module, "FILTER_BLOCK_SAMPLES", 100),
            self.assertRaises(CacheBuildCancelled),
            self.dataset.analysis_values_file(
                2,
                0.0,
                10.0,
                self.settings(),
                cancel,
                cancel_after_first_block,
            ),
        ):
            pass

        self.assertFalse(self.cache_directories())
        self.assertFalse(list(self.cache_root.glob(".*.tmp")))


class AnalysisMemmapTests(unittest.TestCase):
    def test_finite_memmap_is_not_copied_into_a_full_ram_array(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "values.bin"
            values = np.memmap(path, dtype="<f8", mode="w+", shape=(2048,))
            values[:] = np.linspace(-1.0, 1.0, values.size)
            values.flush()
            actual = _finite_signal(values)
            try:
                self.assertTrue(np.shares_memory(actual, values))
                np.testing.assert_array_equal(actual, values)
            finally:
                del actual, values


if __name__ == "__main__":
    unittest.main()
