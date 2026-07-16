from dataclasses import dataclass

import numpy as np
from scipy import signal


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


def sample_rate_for_channel(
    info: dict | None,
    time_us,
    channel: int | None = None,
) -> float:
    """Describe sample_rate_for_channel.

    Args:
        info: Input accepted by this function.
        time_us: Input accepted by this function.
        channel: Input accepted by this function.

    Returns:
        The value produced by this function, if any.
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
    """Describe infer_sample_rate_hz.

    Args:
        time_us: Input accepted by this function.

    Returns:
        The value produced by this function, if any.
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
    """Describe prepare_lfp_signal.

    Args:
        values: Input accepted by this function.
        sample_rate_hz: Input accepted by this function.
        settings: Input accepted by this function.

    Returns:
        The value produced by this function, if any.
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


def compute_power_spectrum(
    values,
    sample_rate_hz: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Describe compute_power_spectrum.

    Args:
        values: Input accepted by this function.
        sample_rate_hz: Input accepted by this function.

    Returns:
        The value produced by this function, if any.
    """
    _validate_sample_rate(sample_rate_hz)
    signal_values = _finite_signal(values)

    if signal_values.size < 2:
        raise ValueError("Need at least two samples to calculate power spectrum.")

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


def compute_time_frequency(
    values,
    sample_rate_hz: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Describe compute_time_frequency.

    Args:
        values: Input accepted by this function.
        sample_rate_hz: Input accepted by this function.

    Returns:
        The value produced by this function, if any.
    """
    _validate_sample_rate(sample_rate_hz)
    signal_values = _finite_signal(values)

    if signal_values.size < 8:
        raise ValueError("Need at least 8 samples to calculate time-frequency map.")

    nperseg = min(512, signal_values.size)
    noverlap = nperseg // 2
    return signal.spectrogram(
        signal_values,
        fs=sample_rate_hz,
        window="hann",
        nperseg=nperseg,
        noverlap=noverlap,
        detrend="constant",
        scaling="density",
        mode="psd",
    )


def prepare_lfp_segment(
    time_us,
    values,
    sample_rate_hz: float,
    start_s: float,
    end_s: float,
    settings: LfpFilterSettings | None,
) -> LfpSegment:
    """Describe prepare_lfp_segment.

    Args:
        time_us: Input accepted by this function.
        values: Input accepted by this function.
        sample_rate_hz: Input accepted by this function.
        start_s: Input accepted by this function.
        end_s: Input accepted by this function.
        settings: Input accepted by this function.

    Returns:
        The value produced by this function, if any.
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
    """Describe filter_description.

    Args:
        settings: Input accepted by this function.

    Returns:
        The value produced by this function, if any.
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
