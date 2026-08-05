import unittest

import numpy as np
from scipy import signal

from lfp_analysis_process import (
    _compute_power_spectrum as process_power_spectrum,
)
from lfp_analysis_process import (
    _compute_time_frequency as process_time_frequency,
)
from lfp_analysis_process import _spectrogram_figure
from lfp_analysis_process import (
    _interpolate_notch_gaps_db,
    _power_spectrum_figure,
)
from src.signal_data.background_workers import (
    _notch_spectrum_display_options,
    _spectrogram_frequency_range,
)
from src.signal_data.lfp_processing import (
    LfpFilterSettings,
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

    def test_notch_gap_interpolation_changes_only_the_display_copy(self):
        frequencies = np.linspace(0.0, 200.0, 2001)
        baseline_db = 20.0 - 0.03 * frequencies
        notched_db = baseline_db.copy()
        for notch_frequency in (60.0, 120.0):
            notched_db[np.abs(frequencies - notch_frequency) <= 1.0] -= 50.0
        original = notched_db.copy()

        displayed = _interpolate_notch_gaps_db(
            frequencies,
            notched_db,
            (60.0, 120.0),
            30.0,
        )

        np.testing.assert_array_equal(notched_db, original)
        np.testing.assert_allclose(
            displayed[np.isclose(frequencies, 60.0)],
            baseline_db[np.isclose(frequencies, 60.0)],
            atol=1e-12,
        )
        np.testing.assert_allclose(
            displayed[np.isclose(frequencies, 120.0)],
            baseline_db[np.isclose(frequencies, 120.0)],
            atol=1e-12,
        )
        outside = (frequencies < 58.0) | (frequencies > 124.0)
        np.testing.assert_array_equal(displayed[outside], original[outside])

    def test_power_figure_labels_display_interpolation_without_changing_psd(self):
        frequencies = np.linspace(0.0, 100.0, 1001)
        power = np.ones(frequencies.shape, dtype=np.float64)
        power[np.abs(frequencies - 60.0) <= 1.0] = 1e-12
        original = power.copy()
        options = {"frequencies_hz": (60.0,), "quality_factor": 30.0}

        figure = _power_spectrum_figure(
            2,
            frequencies,
            power,
            notch_display_options=options,
        )

        np.testing.assert_array_equal(power, original)
        displayed_db = figure.axes[0].lines[0].get_ydata()
        self.assertGreater(displayed_db[np.argmin(np.abs(frequencies - 60.0))], -1.0)
        self.assertIn("display-interpolated", figure.axes[0].get_title())
        figure.clear()

    def test_notch_display_options_apply_only_to_filtered_notch_psd(self):
        notch = LfpFilterSettings(
            show_filtered=True,
            line_noise_method="notch",
            line_noise_frequencies_hz=(60.0, 120.0),
            notch_quality=40.0,
        )
        options = _notch_spectrum_display_options(notch)
        self.assertEqual(options["frequencies_hz"], (60.0, 120.0))
        self.assertEqual(options["quality_factor"], 40.0)
        self.assertIsNone(
            _notch_spectrum_display_options(
                LfpFilterSettings(
                    show_filtered=True,
                    line_noise_method="regression",
                    line_noise_frequencies_hz=(60.0,),
                )
            )
        )
        self.assertIsNone(
            _notch_spectrum_display_options(
                LfpFilterSettings(
                    show_filtered=False,
                    line_noise_method="notch",
                    line_noise_frequencies_hz=(60.0,),
                )
            )
        )

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
