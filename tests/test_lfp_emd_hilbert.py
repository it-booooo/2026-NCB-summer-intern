import unittest
import importlib.util
from pathlib import Path
import sys

import numpy as np

_MODULE_PATH = Path(__file__).parents[1] / "src" / "signal_data" / "lfp_processing.py"
_SPEC = importlib.util.spec_from_file_location("lfp_processing_under_test", _MODULE_PATH)
lfp_processing = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = lfp_processing
_SPEC.loader.exec_module(lfp_processing)

from lfp_processing_under_test import (  # noqa: E402
    EmdAnalysis,
    compute_emd,
    compute_emd_diagnostics,
    compute_hilbert_marginal_spectrum,
    compute_hilbert_spectrum,
)


def _analysis(frequencies, powers, sample_rate=200.0):
    frequencies = np.asarray(frequencies, dtype=float)
    powers = np.asarray(powers, dtype=float)
    return EmdAnalysis(
        imfs=np.zeros_like(frequencies),
        residue=np.zeros(frequencies.shape[1]),
        instantaneous_frequencies_hz=frequencies,
        instantaneous_power=powers,
        sample_rate_hz=sample_rate,
    )


class HilbertDensityTests(unittest.TestCase):
    def test_marginal_density_does_not_grow_with_duration(self):
        short = _analysis(np.full((1, 100), 20.0), np.full((1, 100), 2.0))
        long = _analysis(np.full((1, 400), 20.0), np.full((1, 400), 2.0))

        _, short_psd = compute_hilbert_marginal_spectrum(short, 100)
        _, long_psd = compute_hilbert_marginal_spectrum(long, 100)

        np.testing.assert_allclose(short_psd, long_psd)

    def test_frequency_integral_is_independent_of_bin_count(self):
        frequencies = np.vstack(
            (np.full(500, 20.0), np.full(500, 37.0))
        )
        powers = np.vstack((np.full(500, 2.0), np.full(500, 0.5)))
        analysis = _analysis(frequencies, powers)

        for bin_count in (50, 100, 400):
            frequency, psd = compute_hilbert_marginal_spectrum(
                analysis, bin_count
            )
            bin_width = frequency[1] - frequency[0]
            self.assertAlmostEqual(float(np.sum(psd) * bin_width), 2.5, places=12)

    def test_default_resolution_preserves_a_narrow_periodic_peak(self):
        sample_count = 4096
        rng = np.random.default_rng(7)
        instantaneous_frequency = 30.0 + rng.normal(0.0, 0.03, sample_count)
        analysis = _analysis(
            instantaneous_frequency[None, :],
            np.ones((1, sample_count)),
            sample_rate=200.0,
        )

        frequency, psd = compute_hilbert_marginal_spectrum(analysis)

        self.assertLess(abs(float(frequency[np.argmax(psd)]) - 30.0), 0.06)
        self.assertEqual(frequency.size, 2048)

    def test_time_frequency_columns_integrate_to_local_mean_power(self):
        powers = np.vstack(
            (np.ones(100), np.concatenate((np.ones(50), np.full(50, 3.0))))
        )
        analysis = _analysis(
            np.vstack((np.full(100, 10.0), np.full(100, 30.0))), powers
        )

        frequency, _, density = compute_hilbert_spectrum(
            analysis, time_bin_count=2, frequency_bin_count=100
        )
        bin_width = frequency[1] - frequency[0]
        integrated = np.sum(density, axis=0) * bin_width

        np.testing.assert_allclose(integrated, [2.0, 4.0])


class EmdDiagnosticTests(unittest.TestCase):
    def test_imfs_plus_residue_reconstruct_input_and_welch_psd(self):
        sample_rate = 200.0
        time = np.arange(1000) / sample_rate
        values = np.sin(2 * np.pi * 12.0 * time) + 0.3 * np.sin(
            2 * np.pi * 50.0 * time
        )

        analysis = compute_emd(values, sample_rate)
        diagnostics = compute_emd_diagnostics(values, analysis)

        self.assertLess(diagnostics.relative_reconstruction_error, 1e-10)
        np.testing.assert_allclose(
            diagnostics.input_welch_psd,
            diagnostics.reconstructed_welch_psd,
            rtol=1e-9,
            atol=1e-12,
        )
        self.assertEqual(diagnostics.component_rms.size, analysis.imf_count)


if __name__ == "__main__":
    unittest.main()
