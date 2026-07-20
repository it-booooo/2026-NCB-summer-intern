from dataclasses import dataclass

import numpy as np
from PyEMD import EMD
from scipy import signal


EMD_MAX_SAMPLES = 100_000


@dataclass(frozen=True)
class LfpFilterSettings:
    show_filtered: bool = False
    bandpass_enabled: bool = False
    bandpass_low_hz: float = 1.0
    bandpass_high_hz: float = 100.0
    line_noise_hz: float | None = None
    notch_quality: float = 30.0


@dataclass(frozen=True)
class LfpSegment:
    time_us: np.ndarray
    record_time_s: np.ndarray
    values: np.ndarray
    sample_rate_hz: float

    @property
    def sample_count(self) -> int:
        """Return the number of samples contained in this LFP segment."""
        return int(self.values.size)


@dataclass(frozen=True)
class EmdAnalysis:
    """EMD components and their Hilbert-derived instantaneous properties."""

    imfs: np.ndarray
    residue: np.ndarray
    instantaneous_frequencies_hz: np.ndarray
    instantaneous_power: np.ndarray
    sample_rate_hz: float

    @property
    def imf_count(self) -> int:
        """Return the number of intrinsic mode functions."""
        return int(self.imfs.shape[0])

    @property
    def sample_count(self) -> int:
        """Return the number of samples in each component."""
        return int(self.residue.size)


@dataclass(frozen=True)
class EmdDiagnostics:
    """Numerical checks showing what the EMD decomposition preserves.

    The Welch spectra are a reconstruction diagnostic, not an alternative
    definition of the Hilbert spectrum.
    """

    reconstruction_rmse: float
    relative_reconstruction_error: float
    component_rms: np.ndarray
    residue_rms: float
    welch_frequencies_hz: np.ndarray
    input_welch_psd: np.ndarray
    reconstructed_welch_psd: np.ndarray


def sample_rate_for_channel(
    info: dict | None,
    time_us,
    channel: int | None = None,
) -> float:
    """Provide sample rate for channel functionality.

    Args:
        info: Metadata or state information to store or use.
        time_us: Input used by this operation.
        channel: LFP channel identifier.
    """
    if info is not None:
        channels = [int(item) for item in info.get("channels", [])]
        sample_rates = [
            float(item)
            for item in info.get("sample_rates", [])
            if item is not None and float(item) > 0
        ]
        if sample_rates:
            if channel is not None and channels and channel in channels:
                index = channels.index(int(channel))
                if index < len(sample_rates):
                    return sample_rates[index]
            return sample_rates[0]

    return infer_sample_rate_hz(time_us)


def infer_sample_rate_hz(time_us) -> float:
    """Infer sample rate hz.

    Args:
        time_us: Input used by this operation.
    """
    time_values = np.asarray(time_us, dtype=float)
    if time_values.size < 2:
        raise ValueError("Need at least two samples to infer sample rate.")

    deltas = np.diff(time_values)
    deltas = deltas[np.isfinite(deltas) & (deltas > 0)]
    if deltas.size == 0:
        raise ValueError("Cannot infer sample rate from LFP timestamps.")

    median_delta_us = float(np.median(deltas))
    if median_delta_us <= 0:
        raise ValueError("Cannot infer sample rate from LFP timestamps.")

    return 1_000_000.0 / median_delta_us


def prepare_lfp_signal(
    values,
    sample_rate_hz: float,
    settings: LfpFilterSettings | None,
) -> np.ndarray:
    """Prepare lfp signal.

    Args:
        values: Signal values to process.
        sample_rate_hz: Input used by this operation.
        settings: Configuration settings for this operation.
    """
    signal_values = _finite_signal(values)
    if settings is None or not settings.show_filtered:
        return signal_values

    _validate_sample_rate(sample_rate_hz)
    filtered = signal_values

    if settings.bandpass_enabled:
        filtered = _apply_bandpass(
            filtered,
            sample_rate_hz,
            settings.bandpass_low_hz,
            settings.bandpass_high_hz,
        )

    if settings.line_noise_hz is not None:
        filtered = _apply_notch(
            filtered,
            sample_rate_hz,
            settings.line_noise_hz,
            settings.notch_quality,
        )

    return filtered


def compute_emd(
    values,
    sample_rate_hz: float,
    max_samples: int | None = EMD_MAX_SAMPLES,
) -> EmdAnalysis:
    """Decompose an LFP signal into IMFs and calculate Hilbert properties.

    Args:
        values: Signal values to process.
        sample_rate_hz: Signal sample rate in Hz.
        max_samples: Safety limit for synchronous UI analysis; ``None`` disables it.
    """
    _validate_sample_rate(sample_rate_hz)
    signal_values = _finite_signal(values)

    if signal_values.size < 8:
        raise ValueError("Need at least 8 samples to calculate an EMD decomposition.")
    if max_samples is not None and signal_values.size > int(max_samples):
        duration = float(max_samples) / float(sample_rate_hz)
        raise ValueError(
            f"EMD analysis is limited to {int(max_samples):,} samples "
            f"({duration:g} s at {sample_rate_hz:g} Hz). "
            "Select a shorter LFP time range."
        )

    times = np.arange(signal_values.size, dtype=float) / float(sample_rate_hz)
    emd = EMD()
    emd.emd(signal_values, times)
    imfs, residue = emd.get_imfs_and_residue()
    imfs = np.asarray(imfs, dtype=float).reshape((-1, signal_values.size))
    residue = np.asarray(residue, dtype=float).reshape(signal_values.shape)

    if imfs.shape[0] == 0:
        instantaneous_frequencies_hz = np.empty_like(imfs)
        instantaneous_power = np.empty_like(imfs)
    else:
        analytic_signal = signal.hilbert(imfs, axis=1)
        amplitude = np.abs(analytic_signal)
        phase = np.unwrap(np.angle(analytic_signal), axis=1)
        instantaneous_frequencies_hz = (
            np.diff(phase, axis=1) * float(sample_rate_hz) / (2.0 * np.pi)
        )
        instantaneous_frequencies_hz = np.concatenate(
            (instantaneous_frequencies_hz, instantaneous_frequencies_hz[:, -1:]),
            axis=1,
        )
        # For a real, locally narrow-band IMF the analytic-signal envelope
        # squared is twice its mean-square power (for example A*cos(wt) has
        # power A**2/2).  Store signal-unit squared instantaneous power here.
        instantaneous_power = amplitude**2 / 2.0

        amplitude_floor = np.max(amplitude, axis=1, keepdims=True) * 1e-6
        nyquist_hz = float(sample_rate_hz) / 2.0
        valid = (
            np.isfinite(instantaneous_frequencies_hz)
            & (instantaneous_frequencies_hz >= 0.0)
            & (instantaneous_frequencies_hz <= nyquist_hz)
            & (amplitude > amplitude_floor)
        )
        instantaneous_frequencies_hz = np.where(
            valid, instantaneous_frequencies_hz, np.nan
        )
        instantaneous_power = np.where(valid, instantaneous_power, 0.0)

    return EmdAnalysis(
        imfs=imfs,
        residue=residue,
        instantaneous_frequencies_hz=instantaneous_frequencies_hz,
        instantaneous_power=instantaneous_power,
        sample_rate_hz=float(sample_rate_hz),
    )


def compute_hilbert_spectrum(
    analysis: EmdAnalysis,
    time_bin_count: int = 512,
    frequency_bin_count: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return a time-local Hilbert power spectral density estimate.

    Each cell is the mean instantaneous IMF power in its time interval divided
    by the frequency-bin width.  Its units are signal-unit squared/Hz, so
    integrating a time column over frequency gives the mean IMF power in that
    interval.  It is an EMD/Hilbert density and is not mathematically identical
    to a windowed Fourier spectrogram.

    Args:
        analysis: Result returned by :func:`compute_emd`.
        time_bin_count: Maximum number of time bins.
        frequency_bin_count: Number of bins from 0 Hz to Nyquist. ``None``
            uses the frequency resolution of a ``min(4096, sample_count)``
            Fourier segment, matching the scale used by the Welch reference.
    """
    if analysis.sample_count < 2:
        raise ValueError("Need at least two EMD samples for a Hilbert spectrum.")

    time_bin_count = min(max(int(time_bin_count), 1), analysis.sample_count)
    frequency_bin_count = _resolve_frequency_bin_count(
        analysis.sample_count, frequency_bin_count
    )
    duration_s = analysis.sample_count / analysis.sample_rate_hz
    nyquist_hz = analysis.sample_rate_hz / 2.0
    time_edges = np.linspace(0.0, duration_s, time_bin_count + 1)
    frequency_edges = np.linspace(0.0, nyquist_hz, frequency_bin_count + 1)

    times = np.arange(analysis.sample_count, dtype=float) / analysis.sample_rate_hz
    sample_times = np.broadcast_to(times, analysis.instantaneous_frequencies_hz.shape)
    valid = (
        np.isfinite(analysis.instantaneous_frequencies_hz)
        & np.isfinite(analysis.instantaneous_power)
        & (analysis.instantaneous_power > 0.0)
    )
    spectrum, _, _ = np.histogram2d(
        sample_times[valid],
        analysis.instantaneous_frequencies_hz[valid],
        bins=(time_edges, frequency_edges),
        weights=analysis.instantaneous_power[valid],
    )

    # Average within each time interval and convert per-bin power to density.
    # Counts use signal samples (not valid IMF observations), so a bin is not
    # biased upward merely because EMD returned more components.
    sample_counts, _ = np.histogram(times, bins=time_edges)
    frequency_widths = np.diff(frequency_edges)
    denominator = sample_counts[:, None] * frequency_widths[None, :]
    spectrum = np.divide(
        spectrum,
        denominator,
        out=np.zeros_like(spectrum),
        where=denominator > 0,
    )

    time_centers = (time_edges[:-1] + time_edges[1:]) / 2.0
    frequency_centers = (frequency_edges[:-1] + frequency_edges[1:]) / 2.0
    return frequency_centers, time_centers, spectrum.T


def compute_hilbert_marginal_spectrum(
    analysis: EmdAnalysis,
    frequency_bin_count: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return the time-averaged Hilbert marginal power spectral density.

    The histogram is normalized by sample count and frequency-bin width.  Its
    units are signal-unit squared/Hz; consequently its frequency integral is
    the time-averaged power carried by the valid IMFs and does not grow with
    record duration or change when only the bin width changes.  The estimate
    can be compared with Welch PSD in trend and peak location, but the two use
    different decompositions and estimators and need not have identical values.

    Args:
        analysis: Result returned by :func:`compute_emd`.
        frequency_bin_count: Number of bins from 0 Hz to Nyquist. ``None``
            uses the frequency resolution of a ``min(4096, sample_count)``
            Welch segment.
    """
    if analysis.sample_count < 1:
        raise ValueError("Need at least one EMD sample for a marginal spectrum.")
    frequency_bin_count = _resolve_frequency_bin_count(
        analysis.sample_count, frequency_bin_count
    )
    frequency_edges = np.linspace(
        0.0,
        analysis.sample_rate_hz / 2.0,
        frequency_bin_count + 1,
    )
    valid = (
        np.isfinite(analysis.instantaneous_frequencies_hz)
        & np.isfinite(analysis.instantaneous_power)
        & (analysis.instantaneous_power > 0.0)
    )
    marginal_power, _ = np.histogram(
        analysis.instantaneous_frequencies_hz[valid],
        bins=frequency_edges,
        weights=analysis.instantaneous_power[valid],
    )
    marginal_power = marginal_power / (
        float(analysis.sample_count) * np.diff(frequency_edges)
    )
    frequency_centers = (frequency_edges[:-1] + frequency_edges[1:]) / 2.0
    return frequency_centers, marginal_power


def compute_welch_psd(values, sample_rate_hz: float) -> tuple[np.ndarray, np.ndarray]:
    """Compute the Hann-window Welch PSD used as an EMD diagnostic reference."""
    _validate_sample_rate(sample_rate_hz)
    signal_values = _finite_signal(values)
    if signal_values.size < 2:
        raise ValueError("Need at least two samples to calculate a Welch PSD.")
    if signal_values.size < 8:
        return signal.periodogram(
            signal_values,
            fs=sample_rate_hz,
            detrend="constant",
            scaling="density",
        )
    nperseg = min(4096, signal_values.size)
    return signal.welch(
        signal_values,
        fs=sample_rate_hz,
        window="hann",
        nperseg=nperseg,
        noverlap=nperseg // 2,
        detrend="constant",
        scaling="density",
    )


def compute_emd_diagnostics(values, analysis: EmdAnalysis) -> EmdDiagnostics:
    """Check EMD reconstruction and compare input/reconstruction Welch PSDs.

    A small reconstruction error demonstrates that EMD has represented the
    supplied signal as IMFs plus residue; it does not claim that any particular
    component is physiological or that EMD removes interference automatically.
    """
    original = _finite_signal(values)
    if original.size != analysis.sample_count:
        raise ValueError("Diagnostic signal and EMD analysis lengths must match.")
    reconstructed = analysis.residue + np.sum(analysis.imfs, axis=0)
    error = original - reconstructed
    reconstruction_rmse = float(np.sqrt(np.mean(error**2)))
    reference_rms = float(np.sqrt(np.mean(original**2)))
    relative_error = (
        reconstruction_rmse / reference_rms
        if reference_rms > 0
        else reconstruction_rmse
    )
    frequencies, input_psd = compute_welch_psd(original, analysis.sample_rate_hz)
    reconstructed_frequencies, reconstructed_psd = compute_welch_psd(
        reconstructed, analysis.sample_rate_hz
    )
    if not np.array_equal(frequencies, reconstructed_frequencies):
        raise RuntimeError("Welch diagnostic frequency grids do not match.")
    component_rms = np.sqrt(np.mean(analysis.imfs**2, axis=1))
    return EmdDiagnostics(
        reconstruction_rmse=reconstruction_rmse,
        relative_reconstruction_error=float(relative_error),
        component_rms=component_rms,
        residue_rms=float(np.sqrt(np.mean(analysis.residue**2))),
        welch_frequencies_hz=frequencies,
        input_welch_psd=input_psd,
        reconstructed_welch_psd=reconstructed_psd,
    )


def _resolve_frequency_bin_count(
    sample_count: int, frequency_bin_count: int | None
) -> int:
    if frequency_bin_count is None:
        return max(1, min(4096, int(sample_count)) // 2)
    return max(1, int(frequency_bin_count))


def prepare_lfp_segment(
    time_us,
    values,
    sample_rate_hz: float,
    start_s: float,
    end_s: float,
    settings: LfpFilterSettings | None,
) -> LfpSegment:
    """Prepare lfp segment.

    Args:
        time_us: Input used by this operation.
        values: Signal values to process.
        sample_rate_hz: Input used by this operation.
        start_s: Start time of the selected range, in seconds.
        end_s: End time of the selected range, in seconds.
        settings: Configuration settings for this operation.
    """
    start_s = float(start_s)
    end_s = float(end_s)
    if not np.isfinite(start_s) or not np.isfinite(end_s):
        raise ValueError("Selected time range must be finite.")
    if start_s == end_s:
        raise ValueError("Selected time range is too short.")
    if start_s > end_s:
        start_s, end_s = end_s, start_s

    time_us_values = np.asarray(time_us, dtype=float)
    record_time_s = time_us_values / 1_000_000.0
    signal_values = prepare_lfp_signal(values, sample_rate_hz, settings)
    mask = (record_time_s >= start_s) & (record_time_s <= end_s)

    if int(mask.sum()) < 2:
        raise ValueError("Selected time range is too short for analysis.")

    return LfpSegment(
        time_us=time_us_values[mask],
        record_time_s=record_time_s[mask],
        values=signal_values[mask],
        sample_rate_hz=float(sample_rate_hz),
    )


def filter_description(settings: LfpFilterSettings | None) -> str:
    """Provide filter description functionality.

    Args:
        settings: Configuration settings for this operation.
    """
    if settings is None or not settings.show_filtered:
        return "Raw"

    low_hz = f"{settings.bandpass_low_hz:g}"
    high_hz = f"{settings.bandpass_high_hz:g}"
    if settings.bandpass_enabled:
        bandpass_description = f"bandpass {low_hz}-{high_hz} Hz"
    else:
        bandpass_description = (
            f"bandpass off (low {low_hz} Hz, high {high_hz} Hz)"
        )

    if settings.line_noise_hz is not None:
        notch_description = f"notch {settings.line_noise_hz:g} Hz"
    else:
        notch_description = "notch off"

    return f"Filtered: {bandpass_description}, {notch_description}"


def _finite_signal(values) -> np.ndarray:
    signal_values = np.asarray(values, dtype=float)
    if signal_values.ndim != 1:
        signal_values = signal_values.reshape(-1)

    if signal_values.size == 0:
        return signal_values.copy()

    finite_mask = np.isfinite(signal_values)
    if finite_mask.all():
        return signal_values.copy()

    if not finite_mask.any():
        return np.zeros(signal_values.shape, dtype=float)

    indices = np.arange(signal_values.size)
    return np.interp(indices, indices[finite_mask], signal_values[finite_mask])


def _validate_sample_rate(sample_rate_hz: float) -> None:
    if not np.isfinite(sample_rate_hz) or sample_rate_hz <= 0:
        raise ValueError("Sample rate must be a positive number.")


def _apply_bandpass(
    values: np.ndarray,
    sample_rate_hz: float,
    low_hz: float,
    high_hz: float,
) -> np.ndarray:
    nyquist_hz = sample_rate_hz / 2.0
    low_hz = float(low_hz)
    high_hz = float(high_hz)

    if low_hz <= 0:
        raise ValueError("Bandpass low cutoff must be greater than 0 Hz.")
    if high_hz <= low_hz:
        raise ValueError("Bandpass high cutoff must be higher than low cutoff.")
    if high_hz >= nyquist_hz:
        raise ValueError(
            f"Bandpass high cutoff must be lower than Nyquist ({nyquist_hz:g} Hz)."
        )

    sos = signal.butter(
        4,
        [low_hz, high_hz],
        btype="bandpass",
        fs=sample_rate_hz,
        output="sos",
    )
    return _apply_filter(
        values,
        padlen=3 * (2 * sos.shape[0] + 1),
        causal_filter=lambda data: signal.sosfilt(sos, data),
        zero_phase_filter=lambda data: signal.sosfiltfilt(sos, data),
    )


def _apply_notch(
    values: np.ndarray,
    sample_rate_hz: float,
    line_noise_hz: float,
    quality: float,
) -> np.ndarray:
    nyquist_hz = sample_rate_hz / 2.0
    line_noise_hz = float(line_noise_hz)
    quality = float(quality)

    if line_noise_hz <= 0:
        raise ValueError("Line-noise frequency must be greater than 0 Hz.")
    if line_noise_hz >= nyquist_hz:
        raise ValueError(
            f"Line-noise frequency must be lower than Nyquist ({nyquist_hz:g} Hz)."
        )
    if quality <= 0:
        raise ValueError("Notch quality factor must be greater than 0.")

    b, a = signal.iirnotch(line_noise_hz, quality, fs=sample_rate_hz)
    return _apply_filter(
        values,
        padlen=3 * max(len(a), len(b)),
        causal_filter=lambda data: signal.lfilter(b, a, data),
        zero_phase_filter=lambda data: signal.filtfilt(b, a, data),
    )


def _apply_filter(
    values: np.ndarray,
    padlen: int,
    causal_filter,
    zero_phase_filter,
) -> np.ndarray:
    """Use zero-phase filtering when possible and a causal short-signal fallback."""
    if values.size < 2:
        return values.copy()

    if values.size <= padlen:
        return causal_filter(values)

    return zero_phase_filter(values)
