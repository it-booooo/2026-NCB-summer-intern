import unittest
from unittest.mock import patch

from src.signal_data.gpu_backend import cupy_status, select_backend


class GpuBackendTests(unittest.TestCase):
    def test_status_is_safe_when_cupy_is_optional(self):
        status = cupy_status()
        self.assertIn("available", status)
        self.assertIn("backend", status)

    def test_cpu_backend_can_be_forced(self):
        self.assertEqual(select_backend(1_000_000, requested="cpu"), "cpu")

    def test_small_auto_work_does_not_initialize_cupy(self):
        with patch(
            "src.signal_data.gpu_backend._cupy_runtime",
            side_effect=AssertionError("small arrays should remain on CPU"),
        ):
            self.assertEqual(select_backend(1000, requested="auto"), "cpu")

    def test_auto_falls_back_when_runtime_is_unavailable(self):
        with patch(
            "src.signal_data.gpu_backend._cupy_runtime",
            return_value=(None, "missing"),
        ):
            self.assertEqual(select_backend(1_000_000, requested="auto"), "cpu")

    def test_forced_cupy_reports_an_unavailable_runtime(self):
        with patch(
            "src.signal_data.gpu_backend._cupy_runtime",
            return_value=(None, "missing"),
        ):
            with self.assertRaisesRegex(RuntimeError, "missing"):
                select_backend(1_000_000, requested="cupy")


if __name__ == "__main__":
    unittest.main()
