import unittest
from unittest.mock import patch

import numpy as np

from src.project_format import validate_state
from src.signal_data.lfp_processing import (
    LfpFilterSettings,
    filter_padding_samples,
    parse_line_noise_frequencies,
    prepare_lfp_signal,
    remove_periodic_noise,
)


def _tone_amplitude(values, sample_rate_hz, frequency_hz):
    samples = np.arange(values.shape[-1], dtype=np.float64)
    basis = np.exp(-2j * np.pi * frequency_hz * samples / sample_rate_hz)
    return 2.0 * np.abs(np.asarray(values) @ basis) / values.shape[-1]


def _reduction_db(before, after):
    return 20.0 * np.log10(np.maximum(before, 1e-15) / np.maximum(after, 1e-15))


class PeriodicNoiseRegressionTests(unittest.TestCase):
    sample_rate_hz = 500.0

    def time_values(self, duration_seconds):
        return np.arange(
            int(round(self.sample_rate_hz * duration_seconds)), dtype=np.float64
        ) / self.sample_rate_hz

    def test_stationary_interference_is_removed_without_changing_input(self):
        time_values = self.time_values(12.0)
        clean = np.sin(2 * np.pi * 10.0 * time_values)
        interference = 2.0 * np.sin(2 * np.pi * 60.0 * time_values + 0.3)

        for dtype in (np.float32, np.float64):
            with self.subTest(dtype=dtype):
                source = np.asarray(clean + interference, dtype=dtype)
                original = source.copy()
                result = remove_periodic_noise(
                    source,
                    self.sample_rate_hz,
                    [60.0],
                )

                before_60 = _tone_amplitude(source, self.sample_rate_hz, 60.0)
                after_60 = _tone_amplitude(result, self.sample_rate_hz, 60.0)
                before_10 = _tone_amplitude(source, self.sample_rate_hz, 10.0)
                after_10 = _tone_amplitude(result, self.sample_rate_hz, 10.0)

                self.assertEqual(result.shape, source.shape)
                self.assertEqual(result.dtype, source.dtype)
                np.testing.assert_array_equal(source, original)
                self.assertGreater(_reduction_db(before_60, after_60), 15.0)
                self.assertLess(abs(after_10 / before_10 - 1.0), 0.05)

                first_difference = np.abs(np.diff(result.astype(np.float64)))
                self.assertLess(
                    float(first_difference.max()),
                    max(float(np.percentile(first_difference, 99.9)) * 3.0, 0.2),
                )

    def test_time_varying_interference_is_reduced(self):
        time_values = self.time_values(24.0)
        amplitude = 1.5 + 0.8 * np.sin(2 * np.pi * 0.03 * time_values)
        clean = np.sin(2 * np.pi * 10.0 * time_values)
        source = (
            clean
            + amplitude * np.sin(2 * np.pi * 60.0 * time_values + 0.8)
        )

        result = remove_periodic_noise(
            source,
            self.sample_rate_hz,
            [60.0],
            window_seconds=4.0,
            overlap=0.5,
        )

        self.assertGreater(
            _reduction_db(
                np.sqrt(np.mean((source - clean) ** 2)),
                np.sqrt(np.mean((result - clean) ** 2)),
            ),
            15.0,
        )

    def test_adjacent_tones_are_preserved(self):
        time_values = self.time_values(12.0)
        source = (
            np.sin(2 * np.pi * 58.0 * time_values)
            + 2.0 * np.sin(2 * np.pi * 60.0 * time_values + 0.2)
            + 0.8 * np.sin(2 * np.pi * 62.0 * time_values - 0.4)
        )

        result = remove_periodic_noise(source, self.sample_rate_hz, [60.0])

        for frequency in (58.0, 62.0):
            before = _tone_amplitude(source, self.sample_rate_hz, frequency)
            after = _tone_amplitude(result, self.sample_rate_hz, frequency)
            self.assertLess(abs(after / before - 1.0), 0.05)

    def test_multiple_custom_frequencies_are_removed_jointly(self):
        time_values = self.time_values(12.0)
        source = (
            np.sin(2 * np.pi * 10.0 * time_values)
            + 2.0 * np.sin(2 * np.pi * 60.0 * time_values + 0.2)
            + 1.5 * np.sin(2 * np.pi * 90.0 * time_values - 0.6)
        )

        result = remove_periodic_noise(
            source,
            self.sample_rate_hz,
            [60.0, 90.0],
        )

        for frequency in (60.0, 90.0):
            self.assertGreater(
                _reduction_db(
                    _tone_amplitude(source, self.sample_rate_hz, frequency),
                    _tone_amplitude(result, self.sample_rate_hz, frequency),
                ),
                15.0,
            )
        self.assertLess(
            abs(
                _tone_amplitude(result, self.sample_rate_hz, 10.0)
                / _tone_amplitude(source, self.sample_rate_hz, 10.0)
                - 1.0
            ),
            0.05,
        )

    def test_multiple_channels_use_independent_amplitude_and_phase(self):
        time_values = self.time_values(12.0)
        base = np.sin(2 * np.pi * 10.0 * time_values)
        source = np.vstack(
            (
                base + 0.5 * np.sin(2 * np.pi * 60.0 * time_values),
                base + 2.0 * np.sin(2 * np.pi * 60.0 * time_values + 1.1),
                base + 4.0 * np.sin(2 * np.pi * 60.0 * time_values - 0.7),
            )
        ).astype(np.float32)
        original = source.copy()

        result = remove_periodic_noise(source, self.sample_rate_hz, [60.0])

        self.assertEqual(result.shape, source.shape)
        np.testing.assert_array_equal(source, original)
        for channel in range(source.shape[0]):
            self.assertGreater(
                _reduction_db(
                    _tone_amplitude(source[channel], self.sample_rate_hz, 60.0),
                    _tone_amplitude(result[channel], self.sample_rate_hz, 60.0),
                ),
                15.0,
            )

    def test_signal_shorter_than_window_is_supported(self):
        time_values = self.time_values(1.0)
        source = (
            np.sin(2 * np.pi * 10.0 * time_values)
            + 2.0 * np.sin(2 * np.pi * 60.0 * time_values + 0.4)
        )

        result = remove_periodic_noise(
            source,
            self.sample_rate_hz,
            [60.0],
            window_seconds=4.0,
        )

        self.assertEqual(result.shape, source.shape)
        self.assertGreater(
            _reduction_db(
                _tone_amplitude(source, self.sample_rate_hz, 60.0),
                _tone_amplitude(result, self.sample_rate_hz, 60.0),
            ),
            15.0,
        )

    def test_invalid_parameters_and_nonfinite_values_are_rejected(self):
        source = np.ones(1000, dtype=np.float64)
        for invalid_sample_rate in (0.0, -1.0, np.nan):
            with self.subTest(sample_rate=invalid_sample_rate):
                with self.assertRaisesRegex(ValueError, "Sample rate"):
                    remove_periodic_noise(source, invalid_sample_rate, [60.0])

        with self.assertRaisesRegex(ValueError, "Nyquist"):
            remove_periodic_noise(source, 100.0, [60.0])
        for invalid_overlap in (-0.01, 1.0, 1.2, np.nan):
            with self.subTest(overlap=invalid_overlap):
                with self.assertRaisesRegex(ValueError, "overlap"):
                    remove_periodic_noise(
                        source,
                        self.sample_rate_hz,
                        [60.0],
                        overlap=invalid_overlap,
                    )
        nonfinite = source.copy()
        nonfinite[10] = np.nan
        with self.assertRaisesRegex(ValueError, "NaN or infinity"):
            remove_periodic_noise(nonfinite, self.sample_rate_hz, [60.0])

        with self.assertRaisesRegex(ValueError, "Unsupported LFP compute backend"):
            remove_periodic_noise(
                source,
                self.sample_rate_hz,
                [60.0],
                backend="invalid",
            )

    def test_regression_dispatches_to_the_optional_opencl_backend(self):
        source = np.arange(1000, dtype=np.float32)
        expected = np.full_like(source, 7.0)
        original = source.copy()
        with patch(
            "src.signal_data.gpu_backend.periodic_noise_regression_opencl",
            return_value=expected,
        ) as gpu_regression:
            result = remove_periodic_noise(
                source,
                self.sample_rate_hz,
                [60.0],
                backend="opencl",
            )

        np.testing.assert_array_equal(result, expected)
        np.testing.assert_array_equal(source, original)
        gpu_regression.assert_called_once()

    def test_pipeline_dispatches_regression_and_retains_notch(self):
        time_values = self.time_values(8.0)
        source = (
            np.sin(2 * np.pi * 10.0 * time_values)
            + 2.0 * np.sin(2 * np.pi * 60.0 * time_values)
        ).astype(np.float32)
        regression = LfpFilterSettings(
            show_filtered=True,
            line_noise_hz=60.0,
            line_noise_method="regression",
            regression_window_seconds=4.0,
            regression_overlap=0.5,
            regression_harmonics=2,
        )
        notch = LfpFilterSettings(
            show_filtered=True,
            line_noise_hz=60.0,
            line_noise_method="notch",
            notch_quality=30.0,
        )

        regression_result = prepare_lfp_signal(
            source, self.sample_rate_hz, regression
        )
        notch_result = prepare_lfp_signal(source, self.sample_rate_hz, notch)

        self.assertGreater(
            _reduction_db(
                _tone_amplitude(source, self.sample_rate_hz, 60.0),
                _tone_amplitude(regression_result, self.sample_rate_hz, 60.0),
            ),
            15.0,
        )
        self.assertGreater(
            _reduction_db(
                _tone_amplitude(source, self.sample_rate_hz, 60.0),
                _tone_amplitude(notch_result, self.sample_rate_hz, 60.0),
            ),
            15.0,
        )
        self.assertEqual(
            filter_padding_samples(regression, self.sample_rate_hz),
            2000,
        )

    def test_pipeline_supports_multiple_regression_and_notch_frequencies(self):
        time_values = self.time_values(12.0)
        source = (
            np.sin(2 * np.pi * 10.0 * time_values)
            + 2.0 * np.sin(2 * np.pi * 60.0 * time_values)
            + 1.5 * np.sin(2 * np.pi * 90.0 * time_values + 0.7)
        )
        common = {
            "show_filtered": True,
            "line_noise_hz": 60.0,
            "line_noise_frequencies_hz": (60.0, 90.0),
        }

        for method in ("regression", "notch"):
            with self.subTest(method=method):
                result = prepare_lfp_signal(
                    source,
                    self.sample_rate_hz,
                    LfpFilterSettings(line_noise_method=method, **common),
                )
                for frequency in (60.0, 90.0):
                    self.assertGreater(
                        _reduction_db(
                            _tone_amplitude(
                                source, self.sample_rate_hz, frequency
                            ),
                            _tone_amplitude(
                                result, self.sample_rate_hz, frequency
                            ),
                        ),
                        15.0,
                    )

    def test_all_harmonics_below_nyquist_are_removed_jointly(self):
        time_values = self.time_values(12.0)
        harmonic_frequencies = (60.0, 90.0, 120.0, 180.0, 240.0)
        source = np.sin(2 * np.pi * 10.0 * time_values)
        for index, frequency in enumerate(harmonic_frequencies, start=1):
            source = source + (2.0 / index) * np.sin(
                2 * np.pi * frequency * time_values + index * 0.2
            )
        settings = LfpFilterSettings(
            show_filtered=True,
            line_noise_method="regression",
            line_noise_frequencies_hz=(60.0, 90.0),
            regression_all_harmonics=True,
        )

        result = prepare_lfp_signal(source, self.sample_rate_hz, settings)

        for frequency in harmonic_frequencies:
            self.assertGreater(
                _reduction_db(
                    _tone_amplitude(source, self.sample_rate_hz, frequency),
                    _tone_amplitude(result, self.sample_rate_hz, frequency),
                ),
                15.0,
            )
        self.assertLess(
            abs(
                _tone_amplitude(result, self.sample_rate_hz, 10.0)
                / _tone_amplitude(source, self.sample_rate_hz, 10.0)
                - 1.0
            ),
            0.05,
        )

    def test_legacy_second_harmonic_setting_migrates_to_all_harmonics(self):
        time_values = self.time_values(12.0)
        source = (
            np.sin(2 * np.pi * 10.0 * time_values)
            + np.sin(2 * np.pi * 60.0 * time_values)
            + np.sin(2 * np.pi * 180.0 * time_values + 0.4)
        )
        legacy_settings = LfpFilterSettings(
            show_filtered=True,
            line_noise_method="regression",
            line_noise_frequencies_hz=(60.0,),
            regression_harmonics=2,
        )

        result = prepare_lfp_signal(
            source,
            self.sample_rate_hz,
            legacy_settings,
        )

        self.assertGreater(
            _reduction_db(
                _tone_amplitude(source, self.sample_rate_hz, 180.0),
                _tone_amplitude(result, self.sample_rate_hz, 180.0),
            ),
            15.0,
        )

    def test_frequency_text_parser_accepts_lists_and_rejects_bad_values(self):
        self.assertEqual(
            parse_line_noise_frequencies("60, 90 120; 60"),
            (60.0, 90.0, 120.0),
        )
        with self.assertRaisesRegex(ValueError, "Invalid filter frequency"):
            parse_line_noise_frequencies("60, invalid")
        with self.assertRaisesRegex(ValueError, "positive finite"):
            parse_line_noise_frequencies("60, -1")

    def test_pipeline_skips_automatic_harmonics_at_or_above_nyquist(self):
        sample_rate_hz = 200.0
        time_values = np.arange(1600, dtype=np.float64) / sample_rate_hz
        source = (
            np.sin(2 * np.pi * 10.0 * time_values)
            + 2.0 * np.sin(2 * np.pi * 60.0 * time_values)
        )
        settings = LfpFilterSettings(
            show_filtered=True,
            line_noise_hz=60.0,
            line_noise_method="regression",
            regression_all_harmonics=True,
        )

        result = prepare_lfp_signal(source, sample_rate_hz, settings)

        self.assertGreater(
            _reduction_db(
                _tone_amplitude(source, sample_rate_hz, 60.0),
                _tone_amplitude(result, sample_rate_hz, 60.0),
            ),
            15.0,
        )

    def test_padded_block_alignment_matches_a_single_pass(self):
        time_values = self.time_values(20.0)
        amplitude = 1.0 + 0.4 * np.sin(2 * np.pi * 0.05 * time_values)
        source = (
            np.sin(2 * np.pi * 10.0 * time_values)
            + amplitude * np.sin(2 * np.pi * 60.0 * time_values + 0.5)
        )
        full = remove_periodic_noise(source, self.sample_rate_hz, [60.0])
        core_left = 3000
        core_right = 7000
        padding = int(4.0 * self.sample_rate_hz)
        loaded_left = max(core_left - padding, 0)
        loaded_right = min(core_right + padding, source.size)

        block = remove_periodic_noise(
            source[loaded_left:loaded_right],
            self.sample_rate_hz,
            [60.0],
            sample_offset=loaded_left,
        )
        block_core = block[
            core_left - loaded_left : core_right - loaded_left
        ]

        np.testing.assert_allclose(
            block_core,
            full[core_left:core_right],
            rtol=1e-12,
            atol=1e-12,
        )

    def test_project_state_accepts_and_validates_regression_parameters(self):
        state = {
            "data": {
                "lfp_filter_settings": {
                    "show_filtered": True,
                    "line_noise_method": "regression",
                    "line_noise_hz": 60.0,
                    "line_noise_frequencies_hz": [60.0, 90.0],
                    "notch_quality": 30.0,
                    "regression_window_seconds": 4.0,
                    "regression_overlap": 0.5,
                    "regression_harmonics": 1,
                    "regression_all_harmonics": True,
                }
            }
        }
        self.assertIs(validate_state(state), state)

        invalid = {
            "data": {
                "lfp_filter_settings": {
                    **state["data"]["lfp_filter_settings"],
                    "regression_overlap": 1.0,
                }
            }
        }
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_state(invalid)

        invalid_all_harmonics = {
            "data": {
                "lfp_filter_settings": {
                    **state["data"]["lfp_filter_settings"],
                    "regression_all_harmonics": "yes",
                }
            }
        }
        with self.assertRaisesRegex(ValueError, "all-harmonics"):
            validate_state(invalid_all_harmonics)


if __name__ == "__main__":
    unittest.main()
