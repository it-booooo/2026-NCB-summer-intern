import unittest
from unittest.mock import patch

import numpy as np

from src.signal_data.gpu_backend import (
    opencl_status,
    periodic_noise_regression_opencl,
    select_backend,
)
from src.lfp_settings import LfpFilterSettings
from src.signal_data.lfp_processing import (
    filter_backend,
    filter_description,
    remove_periodic_noise,
)


class GpuBackendTests(unittest.TestCase):
    def test_status_is_safe_when_opencl_is_optional(self):
        status = opencl_status()
        self.assertIn("available", status)
        self.assertIn("backend", status)

    def test_backend_label_uses_the_real_job_size(self):
        settings = LfpFilterSettings(
            show_filtered=True,
            line_noise_method="regression",
            line_noise_frequencies_hz=(60.0,),
        )
        # Automatic selection keeps small jobs on the CPU, so a description
        # built from a guessed size would name the wrong backend.
        with patch(
            "src.signal_data.gpu_backend._opencl_runtime",
            return_value=({"device_name": "test"}, None),
        ):
            self.assertEqual(filter_backend(settings, 50_000_000), "opencl")
            self.assertEqual(filter_backend(settings, 1_000), "cpu")
            self.assertIn("OpenCL GPU", filter_description(settings, 50_000_000))
            self.assertIn(
                "NumPy CPU fallback", filter_description(settings, 1_000)
            )

    def test_description_omits_the_backend_when_the_size_is_unknown(self):
        settings = LfpFilterSettings(
            show_filtered=True,
            line_noise_method="regression",
            line_noise_frequencies_hz=(60.0,),
        )
        description = filter_description(settings)

        self.assertIn("sinusoidal regression", description)
        self.assertNotIn("OpenCL", description)
        self.assertNotIn("CPU", description)

    def test_backend_question_does_not_apply_without_regression(self):
        notch = LfpFilterSettings(
            show_filtered=True,
            line_noise_method="notch",
            line_noise_frequencies_hz=(60.0,),
        )

        self.assertIsNone(filter_backend(notch, 50_000_000))
        self.assertIsNone(filter_backend(None, 50_000_000))

    def test_cpu_backend_can_be_forced(self):
        self.assertEqual(select_backend(1_000_000, requested="cpu"), "cpu")

    def test_small_auto_work_does_not_initialize_opencl(self):
        with patch(
            "src.signal_data.gpu_backend._opencl_runtime",
            side_effect=AssertionError("small arrays should remain on CPU"),
        ):
            self.assertEqual(select_backend(1000, requested="auto"), "cpu")

    def test_auto_falls_back_when_runtime_is_unavailable(self):
        with patch(
            "src.signal_data.gpu_backend._opencl_runtime",
            return_value=(None, "missing"),
        ):
            self.assertEqual(select_backend(1_000_000, requested="auto"), "cpu")

    def test_blocked_regression_dispatches_from_total_workload_size(self):
        values = np.ones(10_000, dtype=np.float32)
        with patch(
            "src.signal_data.gpu_backend.select_backend",
            return_value="cpu",
        ) as selector:
            result = periodic_noise_regression_opencl(
                values,
                1000.0,
                [60.0],
                4000,
                2000,
                0,
                np.float32,
                dispatch_sample_count=250_000,
            )

        self.assertIsNone(result)
        selector.assert_called_once_with(250_000, None)

    def test_forced_opencl_reports_an_unavailable_runtime(self):
        with patch(
            "src.signal_data.gpu_backend._opencl_runtime",
            return_value=(None, "missing"),
        ):
            with self.assertRaisesRegex(RuntimeError, "missing"):
                select_backend(1_000_000, requested="opencl")

    def test_forced_opencl_rejects_unsupported_float_dtype(self):
        values = np.ones(1000, dtype=np.float16)
        with self.assertRaisesRegex(TypeError, "float32 and float64"):
            remove_periodic_noise(
                values,
                500.0,
                [60.0],
                backend="opencl",
            )

    def test_opencl_matches_cpu_for_multichannel_float_inputs(self):
        status = opencl_status()
        if not status["available"]:
            self.skipTest(status.get("reason", "OpenCL unavailable"))

        sample_rate_hz = 500.0
        time_values = np.arange(6000, dtype=np.float64) / sample_rate_hz
        source = np.vstack(
            (
                np.sin(2 * np.pi * 10.0 * time_values)
                + 2.0 * np.sin(2 * np.pi * 60.0 * time_values + 0.2)
                + 0.4 * np.sin(2 * np.pi * 120.0 * time_values),
                0.5 * np.sin(2 * np.pi * 20.0 * time_values)
                + 3.0 * np.sin(2 * np.pi * 60.0 * time_values - 0.8)
                + 0.7 * np.sin(2 * np.pi * 120.0 * time_values + 0.4),
            )
        )
        for dtype, tolerance in ((np.float32, 2e-5), (np.float64, 1e-9)):
            with self.subTest(dtype=dtype):
                values = source.astype(dtype)
                cpu = remove_periodic_noise(
                    values,
                    sample_rate_hz,
                    [60.0, 120.0],
                    sample_offset=431,
                    backend="cpu",
                )
                gpu = remove_periodic_noise(
                    values,
                    sample_rate_hz,
                    [60.0, 120.0],
                    sample_offset=431,
                    backend="opencl",
                )
                self.assertEqual(gpu.shape, values.shape)
                self.assertEqual(gpu.dtype, values.dtype)
                np.testing.assert_allclose(gpu, cpu, rtol=tolerance, atol=tolerance)

    def test_opencl_short_partial_window_matches_cpu(self):
        status = opencl_status()
        if not status["available"]:
            self.skipTest(status.get("reason", "OpenCL unavailable"))

        sample_rate_hz = 500.0
        time_values = np.arange(700, dtype=np.float64) / sample_rate_hz
        values = (
            np.sin(2 * np.pi * 10.0 * time_values)
            + 2.0 * np.sin(2 * np.pi * 60.0 * time_values + 0.2)
        ).astype(np.float32)
        cpu = remove_periodic_noise(
            values,
            sample_rate_hz,
            [60.0],
            sample_offset=217,
            backend="cpu",
        )
        gpu = remove_periodic_noise(
            values,
            sample_rate_hz,
            [60.0],
            sample_offset=217,
            backend="opencl",
        )
        np.testing.assert_allclose(gpu, cpu, rtol=2e-5, atol=2e-5)


if __name__ == "__main__":
    unittest.main()
