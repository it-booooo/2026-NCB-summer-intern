import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy.signal import find_peaks

from benchmarks.signal_csv_fixture import SignalFixtureConfig, generate_signal_csv
from src.signal_data import LfpDataset, LfpFilterSettings, parse_lfp_csv_info
from src.signal_data.background_workers import (
    PeakDetectionWorker,
    _PEAK_STATISTICS_CACHE,
    _cpu_chunk_statistics,
    _finalize_peak_mask,
)
from src.signal_data.gpu_backend import (
    chunk_statistics_opencl,
    opencl_peak_status,
    peak_candidate_masks_cpu,
    peak_candidate_masks_opencl,
    select_peak_candidate_backend,
    select_peak_statistics_backend,
)
from src.signal_data.source import CacheBuildCancelled, _SOURCES


def _fake_peak_runtime(*, fp64=False):
    return {
        "peak_supports_fp64": bool(fp64),
        "supports_fp64": bool(fp64),
        "device_name": "Mock GPU",
        "device_vendor": "Mock Vendor",
        "platform_name": "Mock Platform",
        "selected_reason": "test",
    }


class PeakBackendSelectionTests(unittest.TestCase):
    def test_cpu_and_small_auto_do_not_initialize_opencl(self):
        with patch(
            "src.signal_data.gpu_backend._opencl_peak_runtime",
            side_effect=AssertionError("OpenCL must not initialize"),
        ):
            self.assertEqual(
                select_peak_candidate_backend(1_000_000, np.float32, "cpu"),
                "cpu",
            )
            self.assertEqual(
                select_peak_statistics_backend(10, np.float32, "auto"),
                "cpu",
            )

    def test_large_float32_work_selects_opencl_without_fp64(self):
        runtime = _fake_peak_runtime(fp64=False)
        with patch(
            "src.signal_data.gpu_backend._opencl_peak_runtime",
            return_value=(runtime, None),
        ):
            self.assertEqual(
                select_peak_candidate_backend(20_000_000, np.float32, "auto"),
                "opencl",
            )
            self.assertEqual(
                select_peak_statistics_backend(20_000_000, np.float32, "auto"),
                "opencl",
            )
            self.assertEqual(
                select_peak_candidate_backend(20_000_000, np.float64, "auto"),
                "cpu",
            )

    def test_auto_fallback_and_forced_error_are_distinct(self):
        with patch(
            "src.signal_data.gpu_backend._opencl_peak_runtime",
            return_value=(None, "missing driver"),
        ):
            self.assertEqual(
                select_peak_candidate_backend(20_000_000, np.float32, "auto"),
                "cpu",
            )
            with self.assertRaisesRegex(RuntimeError, "missing driver"):
                select_peak_candidate_backend(20_000_000, np.float32, "opencl")

    def test_invalid_backend_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported LFP compute backend"):
            select_peak_candidate_backend(1_000_000, np.float32, "invalid")

    def test_periodic_regression_and_peak_capabilities_are_separate(self):
        runtime = _fake_peak_runtime(fp64=False)
        with patch(
            "src.signal_data.gpu_backend._opencl_peak_runtime",
            return_value=(runtime, None),
        ):
            status = opencl_peak_status()
        self.assertTrue(status["peak_candidates_f32"])
        self.assertTrue(status["peak_statistics_f32"])
        self.assertFalse(status["peak_candidates_f64"])
        self.assertFalse(status["periodic_regression"])

    def test_statistics_failure_does_not_disable_candidates(self):
        runtime = _fake_peak_runtime(fp64=False)
        expected = (
            np.array([0, 1, 0], dtype=np.uint8),
            np.zeros(3, dtype=np.uint8),
        )
        with (
            patch(
                "src.signal_data.gpu_backend._opencl_peak_runtime",
                return_value=(runtime, None),
            ),
            patch(
                "src.signal_data.gpu_backend._chunk_statistics_opencl",
                side_effect=RuntimeError("statistics failed"),
            ),
            patch(
                "src.signal_data.gpu_backend._peak_candidate_masks_opencl",
                return_value=expected,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "statistics failed"):
                chunk_statistics_opencl(
                    np.ones(3, dtype=np.float32), requested="opencl"
                )
            actual = peak_candidate_masks_opencl(
                np.array([0, 2, 0], dtype=np.float32),
                1.0,
                -1.0,
                requested="opencl",
            )
        np.testing.assert_array_equal(actual[0], expected[0])
        np.testing.assert_array_equal(actual[1], expected[1])


class PeakCandidateReferenceTests(unittest.TestCase):
    def test_positive_negative_threshold_and_edges(self):
        values = np.array([9, 0, 2, 0, -3, 0, 9], dtype=np.float32)
        positive, negative = peak_candidate_masks_cpu(values, 2.0, -3.0)
        np.testing.assert_array_equal(np.flatnonzero(positive), [2])
        np.testing.assert_array_equal(np.flatnonzero(negative), [4])
        self.assertEqual(positive[0], 0)
        self.assertEqual(positive[-1], 0)

    def test_threshold_just_above_value_excludes_candidate(self):
        values = np.array([0, 2, 0], dtype=np.float32)
        positive, _ = peak_candidate_masks_cpu(
            values, float(np.nextafter(2.0, 3.0)), -10.0
        )
        self.assertFalse(positive.any())

    def test_nonfinite_neighbours_and_centres_are_ignored(self):
        for nonfinite in (np.nan, np.inf, -np.inf):
            for position in range(3):
                with self.subTest(nonfinite=nonfinite, position=position):
                    values = np.array([0.0, 2.0, 0.0])
                    values[position] = nonfinite
                    positive, negative = peak_candidate_masks_cpu(values, 1.0, -1.0)
                    self.assertFalse(positive.any())
                    self.assertFalse(negative.any())

    def test_short_equal_and_monotonic_inputs(self):
        for values in (
            [],
            [1],
            [1, 2],
            [1, 1, 1, 1],
            [1, 2, 3, 4],
            [4, 3, 2, 1],
        ):
            with self.subTest(values=values):
                positive, negative = peak_candidate_masks_cpu(values, 0.0, 0.0)
                self.assertEqual(positive.dtype, np.uint8)
                self.assertEqual(negative.dtype, np.uint8)
                self.assertEqual(positive.size, len(values))

    def test_input_is_not_modified(self):
        values = np.array([0, 2, 0, -2, 0], dtype=np.float32)
        original = values.copy()
        peak_candidate_masks_cpu(values, 1.0, -1.0)
        np.testing.assert_array_equal(values, original)

    def test_opencl_kernel_matches_reference_when_available(self):
        status = opencl_peak_status()
        if not status["peak_candidates_f32"]:
            self.skipTest(status.get("reason", "OpenCL peak candidates unavailable"))
        rng = np.random.default_rng(417)
        dtypes = [np.float32]
        if status["peak_candidates_f64"]:
            dtypes.append(np.float64)
        for dtype in dtypes:
            with self.subTest(dtype=dtype):
                values = rng.normal(size=10_001).astype(dtype)
                values[[11, 99, 500]] = [np.nan, np.inf, -np.inf]
                expected = peak_candidate_masks_cpu(values, 1.2, -1.1)
                actual = peak_candidate_masks_opencl(
                    values, 1.2, -1.1, requested="opencl"
                )
                np.testing.assert_array_equal(actual[0], expected[0])
                np.testing.assert_array_equal(actual[1], expected[1])


class PeakCpuFinalizationTests(unittest.TestCase):
    def _compare_positive(self, values, **conditions):
        positive, _ = peak_candidate_masks_cpu(
            values, conditions["height"], -1e30
        )
        actual, actual_prominence = _finalize_peak_mask(
            values, positive, **conditions
        )
        expected, properties = find_peaks(values, **conditions)
        np.testing.assert_array_equal(actual, expected)
        np.testing.assert_allclose(actual_prominence, properties["prominences"])

    def test_odd_even_and_multiple_plateaus_match_scipy(self):
        for values in (
            [1, 3, 5, 5, 5, 3, 1],
            [1, 3, 5, 5, 3, 1],
            [0, 3, 3, 0, 0, 4, 4, 4, 4, 0],
            [5, 5, 3, 1],
            [1, 3, 5, 5],
        ):
            with self.subTest(values=values):
                self._compare_positive(
                    np.asarray(values, dtype=float),
                    height=2.0,
                    prominence=0.0,
                    distance=1,
                    wlen=9,
                )

    def test_distance_height_priority_and_ties_match_scipy(self):
        for values in (
            [0, 4, 0, 5, 0],
            [0, 5, 0, 5, 0],
            [0, 4, 0, 5, 0, 3, 0],
        ):
            with self.subTest(values=values):
                self._compare_positive(
                    np.asarray(values, dtype=float),
                    height=1.0,
                    prominence=0.0,
                    distance=3,
                    wlen=7,
                )

    def test_prominence_and_random_signal_match_scipy(self):
        rng = np.random.default_rng(20260805)
        values = rng.normal(size=4000)
        values[100:104] = 4.0
        self._compare_positive(
            values,
            height=0.5,
            prominence=0.75,
            distance=11,
            wlen=101,
        )


class PeakStatisticsTests(unittest.TestCase):
    def test_cpu_statistics_ignore_nonfinite_values(self):
        values = np.array([1.0, 2.0, np.nan, np.inf, -np.inf, 4.0])
        count, mean, m2 = _cpu_chunk_statistics(values)
        self.assertEqual(count, 3)
        np.testing.assert_allclose(mean, 7.0 / 3.0)
        np.testing.assert_allclose(m2, np.sum((np.array([1, 2, 4]) - mean) ** 2))

    def test_cpu_statistics_are_stable_for_large_offset(self):
        values = 1e12 + np.linspace(-0.5, 0.5, 10001)
        count, mean, m2 = _cpu_chunk_statistics(values)
        self.assertEqual(count, values.size)
        np.testing.assert_allclose(mean, np.mean(values), rtol=0, atol=1e-4)
        np.testing.assert_allclose(m2, np.var(values) * values.size, rtol=1e-8)

    def test_opencl_statistics_match_cpu_when_available(self):
        status = opencl_peak_status()
        if not status["peak_statistics_f32"]:
            self.skipTest(status.get("reason", "OpenCL peak statistics unavailable"))
        rng = np.random.default_rng(42)
        values = rng.normal(size=200_003).astype(np.float32)
        values[[5, 77]] = [np.nan, np.inf]
        expected = _cpu_chunk_statistics(values)
        actual = chunk_statistics_opencl(values, requested="opencl")
        self.assertEqual(actual[0], expected[0])
        np.testing.assert_allclose(actual[1:], expected[1:], rtol=2e-5, atol=2e-5)


class PeakWorkerOpenClOrchestrationTests(unittest.TestCase):
    def setUp(self):
        _SOURCES.clear()
        _PEAK_STATISTICS_CACHE.clear()
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        path = root / "signal.csv"
        generate_signal_csv(
            path,
            SignalFixtureConfig(
                sample_rate_hz=100,
                duration_s=2,
                channels=(2,),
                peak_indices=(50, 150),
                peak_amplitude=20.0,
            ),
        )
        info = parse_lfp_csv_info(path)
        info["_signal_cache_root"] = str(root / "cache")
        self.dataset = LfpDataset.from_csv(info)

    def tearDown(self):
        self.dataset.close(wait=True)
        _SOURCES.clear()
        _PEAK_STATISTICS_CACHE.clear()
        self.directory.cleanup()

    def _worker(self, backend, chunk_samples=37, settings=None):
        return PeakDetectionWorker(
            f"peaks-{backend}",
            self.dataset,
            2,
            0.0,
            1.9,
            settings or LfpFilterSettings(show_filtered=False),
            height_sigma=2.0,
            prominence_sigma=1.0,
            min_distance_sec=0.1,
            chunk_samples=chunk_samples,
            backend=backend,
        )

    @staticmethod
    def _mock_status():
        return {
            "device_available": True,
            "supports_fp64": True,
            "periodic_regression": True,
            "peak_statistics_f32": True,
            "peak_statistics_f64": True,
            "peak_candidates_f32": True,
            "peak_candidates_f64": True,
            "device_name": "Mock GPU",
            "device_vendor": "Mock Vendor",
            "platform": "Mock Platform",
            "reason": None,
        }

    def test_forced_cpu_never_calls_opencl_peak_operations(self):
        with (
            patch(
                "src.signal_data.background_workers.chunk_statistics_opencl",
                side_effect=AssertionError("statistics OpenCL called"),
            ),
            patch(
                "src.signal_data.background_workers.peak_candidate_masks_opencl",
                side_effect=AssertionError("candidate OpenCL called"),
            ),
        ):
            result = self._worker("cpu").execute()
        self.assertEqual(result["acceleration"]["backend"], "cpu")
        self.assertEqual(result["acceleration"]["opencl_status"], {"checked": False})

    def test_cpu_statistics_cache_is_range_scoped(self):
        first = self._worker("cpu").execute()
        second = self._worker("cpu").execute()
        shorter = PeakDetectionWorker(
            "peaks-shorter",
            self.dataset,
            2,
            0.0,
            1.5,
            LfpFilterSettings(show_filtered=False),
            height_sigma=2.0,
            prominence_sigma=1.0,
            min_distance_sec=0.1,
            chunk_samples=37,
            backend="cpu",
        ).execute()
        self.assertEqual(first["records"], second["records"])
        self.assertFalse(first["acceleration"]["statistics_cache_hit"])
        self.assertTrue(second["acceleration"]["statistics_cache_hit"])
        self.assertEqual(second["acceleration"]["cpu_statistics_chunks"], 0)
        self.assertFalse(shorter["acceleration"]["statistics_cache_hit"])

    def test_mock_opencl_worker_matches_cpu_records_and_metadata(self):
        cpu = self._worker("cpu").execute()

        def candidate_masks(values, positive, negative, **_kwargs):
            return peak_candidate_masks_cpu(values, positive, negative)

        with (
            patch(
                "src.signal_data.background_workers.chunk_statistics_opencl",
                side_effect=lambda values, **_kwargs: _cpu_chunk_statistics(values),
            ),
            patch(
                "src.signal_data.background_workers.peak_candidate_masks_opencl",
                side_effect=candidate_masks,
            ),
            patch(
                "src.signal_data.background_workers.opencl_peak_status",
                side_effect=self._mock_status,
            ),
        ):
            gpu = self._worker("opencl").execute()
        self.assertEqual(gpu["records"], cpu["records"])
        self.assertEqual(gpu["acceleration"]["backend"], "opencl")
        self.assertGreater(gpu["acceleration"]["gpu_statistics_chunks"], 1)
        self.assertGreater(gpu["acceleration"]["gpu_candidate_chunks"], 1)

    def test_real_opencl_worker_matches_cpu_when_available(self):
        status = opencl_peak_status()
        if not (status["peak_statistics_f32"] and status["peak_candidates_f32"]):
            self.skipTest(status.get("reason", "OpenCL peak pipeline unavailable"))
        cpu = self._worker("cpu", chunk_samples=73).execute()
        gpu = self._worker("opencl", chunk_samples=73).execute()
        self.assertEqual(gpu["records"], cpu["records"])
        self.assertEqual(gpu["acceleration"]["backend"], "opencl")
        self.assertIsNone(gpu["acceleration"]["fallback_reason"])

    def test_real_opencl_worker_preserves_existing_filter_results(self):
        status = opencl_peak_status()
        if not (status["peak_statistics_f64"] and status["peak_candidates_f64"]):
            self.skipTest(status.get("reason", "OpenCL float64 peak pipeline unavailable"))
        settings_cases = (
            LfpFilterSettings(
                show_filtered=True,
                bandpass_enabled=True,
                bandpass_low_hz=2.0,
                bandpass_high_hz=30.0,
                line_noise_method="notch",
                line_noise_frequencies_hz=(20.0,),
            ),
            LfpFilterSettings(
                show_filtered=True,
                bandpass_enabled=False,
                line_noise_method="regression",
                line_noise_frequencies_hz=(20.0,),
                regression_window_seconds=1.0,
                regression_overlap=0.5,
            ),
        )
        for settings in settings_cases:
            with self.subTest(line_noise_method=settings.line_noise_method):
                cpu = self._worker("cpu", chunk_samples=73, settings=settings).execute()
                gpu = self._worker("opencl", chunk_samples=73, settings=settings).execute()
                self.assertEqual(gpu["records"], cpu["records"])

    def test_statistics_fallback_keeps_opencl_candidates(self):
        cpu = self._worker("cpu").execute()

        def candidate_masks(values, positive, negative, **_kwargs):
            return peak_candidate_masks_cpu(values, positive, negative)

        with (
            patch(
                "src.signal_data.background_workers.peak_opencl_minimum_samples",
                return_value=1,
            ),
            patch(
                "src.signal_data.background_workers.chunk_statistics_opencl",
                side_effect=RuntimeError("mock statistics failure"),
            ),
            patch(
                "src.signal_data.background_workers.peak_candidate_masks_opencl",
                side_effect=candidate_masks,
            ),
            patch(
                "src.signal_data.background_workers.opencl_peak_status",
                side_effect=self._mock_status,
            ),
        ):
            hybrid = self._worker("auto").execute()
        self.assertEqual(hybrid["records"], cpu["records"])
        self.assertEqual(hybrid["acceleration"]["statistics_backend"], "cpu")
        self.assertEqual(hybrid["acceleration"]["candidate_backend"], "opencl")
        self.assertIn("mock statistics failure", hybrid["acceleration"]["fallback_reason"])

    def test_candidate_fallback_keeps_opencl_statistics(self):
        cpu = self._worker("cpu").execute()
        with (
            patch(
                "src.signal_data.background_workers.peak_opencl_minimum_samples",
                return_value=1,
            ),
            patch(
                "src.signal_data.background_workers.chunk_statistics_opencl",
                side_effect=lambda values, **_kwargs: _cpu_chunk_statistics(values),
            ),
            patch(
                "src.signal_data.background_workers.peak_candidate_masks_opencl",
                side_effect=RuntimeError("mock candidate failure"),
            ),
            patch(
                "src.signal_data.background_workers.opencl_peak_status",
                side_effect=self._mock_status,
            ),
        ):
            hybrid = self._worker("auto").execute()
        self.assertEqual(hybrid["records"], cpu["records"])
        self.assertEqual(hybrid["acceleration"]["statistics_backend"], "opencl")
        self.assertEqual(hybrid["acceleration"]["candidate_backend"], "cpu")
        self.assertIn("mock candidate failure", hybrid["acceleration"]["fallback_reason"])

    def test_forced_opencl_error_is_not_swallowed(self):
        with patch(
            "src.signal_data.background_workers.chunk_statistics_opencl",
            side_effect=RuntimeError("forced statistics failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "forced statistics failure"):
                self._worker("opencl").execute()

    def test_cancellation_after_kernel_prevents_candidate_pass(self):
        worker = self._worker("opencl", chunk_samples=17)

        def cancel_after_statistics(values, **_kwargs):
            worker.cancel_event.set()
            return _cpu_chunk_statistics(values)

        with (
            patch(
                "src.signal_data.background_workers.chunk_statistics_opencl",
                side_effect=cancel_after_statistics,
            ),
            patch(
                "src.signal_data.background_workers.peak_candidate_masks_opencl"
            ) as candidate_mock,
        ):
            with self.assertRaises(CacheBuildCancelled):
                worker.execute()
        candidate_mock.assert_not_called()

    def test_cancellation_after_candidate_kernel_returns_no_partial_result(self):
        worker = self._worker("opencl", chunk_samples=17)

        def cancel_after_candidates(values, positive, negative, **_kwargs):
            worker.cancel_event.set()
            return peak_candidate_masks_cpu(values, positive, negative)

        with (
            patch(
                "src.signal_data.background_workers.chunk_statistics_opencl",
                side_effect=lambda values, **_kwargs: _cpu_chunk_statistics(values),
            ),
            patch(
                "src.signal_data.background_workers.peak_candidate_masks_opencl",
                side_effect=cancel_after_candidates,
            ),
        ):
            with self.assertRaises(CacheBuildCancelled):
                worker.execute()


if __name__ == "__main__":
    unittest.main()
