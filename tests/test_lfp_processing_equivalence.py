import unittest

import numpy as np
from scipy import signal

from lfp_analysis_process import (
    _compute_power_spectrum as process_power_spectrum,
)
from lfp_analysis_process import (
    _compute_time_frequency as process_time_frequency,
)
from src.signal_data.lfp_processing import (
    compute_power_spectrum,
    compute_time_frequency,
)


class LfpProcessingEquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.values = np.random.default_rng(42).standard_normal(
            50_000
        ).astype(np.float32)

    def test_power_spectrum_matches_original_scipy_call(self):
        expected_frequencies, expected_power = signal.welch(
            self.values.copy(),
            fs=1000.0,
            window="hann",
            nperseg=4096,
            noverlap=2048,
            detrend="constant",
            scaling="density",
        )

        frequencies, power = compute_power_spectrum(
            self.values,
            1000.0,
        )

        np.testing.assert_array_equal(frequencies, expected_frequencies)
        np.testing.assert_array_equal(power, expected_power)
        process_frequencies, process_power = process_power_spectrum(
            self.values,
            1000.0,
        )
        np.testing.assert_array_equal(
            process_frequencies,
            expected_frequencies,
        )
        np.testing.assert_array_equal(process_power, expected_power)

    def test_spectrogram_matches_original_scipy_call_at_full_resolution(self):
        expected = signal.spectrogram(
            self.values.copy(),
            fs=1000.0,
            window="hann",
            nperseg=512,
            noverlap=256,
            detrend="constant",
            scaling="density",
            mode="psd",
        )

        actual = compute_time_frequency(self.values, 1000.0)

        for actual_array, expected_array in zip(actual, expected):
            np.testing.assert_array_equal(actual_array, expected_array)
        process_result = process_time_frequency(self.values, 1000.0)
        for process_array, expected_array in zip(
            process_result,
            expected,
        ):
            np.testing.assert_array_equal(
                process_array,
                expected_array,
            )
        self.assertEqual(actual[2].shape, (257, 194))


if __name__ == "__main__":
    unittest.main()
