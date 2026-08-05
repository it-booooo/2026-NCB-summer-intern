import unittest

import numpy as np
from scipy import signal

from lfp_analysis_process import (
    _compute_power_spectrum as process_power_spectrum,
)
from lfp_analysis_process import (
    _compute_spectrogram as process_spectrogram,
)
from lfp_analysis_process import _spectrogram_figure
from src.signal_data.background_workers import _spectrogram_frequency_range
from src.signal_data.lfp_processing import (
    LfpFilterSettings,
    compute_power_spectrum,
    compute_spectrogram,
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

        actual = compute_spectrogram(self.values, 1000.0)

        for actual_array, expected_array in zip(actual, expected):
            np.testing.assert_array_equal(actual_array, expected_array)
        process_result = process_spectrogram(self.values, 1000.0)
        for process_array, expected_array in zip(
            process_result,
            expected,
        ):
            np.testing.assert_array_equal(
                process_array,
                expected_array,
            )
        self.assertEqual(actual[2].shape, (257, 194))

    def test_filtered_spectrogram_uses_active_bandpass_range(self):
        settings = LfpFilterSettings(
            show_filtered=True,
            bandpass_enabled=True,
            bandpass_low_hz=5.0,
            bandpass_high_hz=40.0,
        )
        frequency_range = _spectrogram_frequency_range(settings)
        figure = _spectrogram_figure(
            2,
            0.0,
            1.0,
            np.array([0.0, 25.0, 50.0]),
            np.array([0.25, 0.75]),
            np.ones((3, 2)),
            None,
            frequency_range,
        )

        self.assertEqual(frequency_range, (5.0, 40.0))
        self.assertEqual(figure.axes[0].get_ylim(), (5.0, 40.0))

    def test_raw_spectrogram_keeps_full_frequency_range(self):
        settings = LfpFilterSettings(
            show_filtered=False,
            bandpass_enabled=True,
            bandpass_low_hz=5.0,
            bandpass_high_hz=40.0,
        )

        self.assertIsNone(_spectrogram_frequency_range(settings))


if __name__ == "__main__":
    unittest.main()
