import re
from dataclasses import dataclass

import numpy as np
from scipy import signal

from ..lfp_settings import LfpFilterSettings

FILTER_PADDING_CYCLES = 3.0
MAX_LINE_NOISE_FREQUENCIES = 64
MAX_REGRESSION_FREQUENCIES = 256


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


def filter_padding_samples(
    settings: LfpFilterSettings | None,
    sample_rate_hz: float,
) -> int:
    """Calculate per-side context from filter order and slowest active frequency."""
    if settings is None or not settings.show_filtered:
        return 0

    _validate_sample_rate(sample_rate_hz)
    active_frequencies: list[float] = []
    structural_pad = 0
    if settings.bandpass_enabled:
        active_frequencies.append(float(settings.bandpass_low_hz))
        # The fourth-order bandpass implementation produces four SOS sections.
        structural_pad = max(structural_pad, 3 * (2 * 4 + 1))
    line_frequencies = line_noise_frequencies(settings)
    if settings.line_noise_method == "notch" and line_frequencies:
        active_frequencies.extend(line_frequencies)
        structural_pad = max(structural_pad, 3 * 3)
    if settings.line_noise_method == "regression":
        _validate_regression_settings(settings, sample_rate_hz)
        structural_pad = max(
            structural_pad,
            int(round(settings.regression_window_seconds * sample_rate_hz)),
        )
    if not active_frequencies:
        return structural_pad

    lowest_hz = min(active_frequencies)
    if lowest_hz <= 0:
        raise ValueError("Filter frequencies must be greater than 0 Hz.")
    transient_pad = int(
        np.ceil(FILTER_PADDING_CYCLES * float(sample_rate_hz) / lowest_hz)
    )
    return max(structural_pad, transient_pad)


def sample_rate_for_channel(
    info: dict | None,
    time_us,
    channel: int | None = None,
) -> float:
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
    """Infer sample rate hz."""
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
    *,
    sample_offset: int = 0,
    dispatch_sample_count: int | None = None,
) -> np.ndarray:
    """Prepare lfp signal.

    Args:
        values: Signal values to process.
    """
    if (
        settings is not None
        and settings.show_filtered
        and settings.line_noise_method == "regression"
        and not np.isfinite(np.asarray(values)).all()
    ):
        raise ValueError(
            "Sinusoidal regression cannot process signal values containing NaN or infinity."
        )

    signal_values = _finite_signal(values)
    if settings is None or not settings.show_filtered:
        return signal_values

    _validate_sample_rate(sample_rate_hz)
    _validate_line_noise_method(settings.line_noise_method)
    filtered = signal_values

    if settings.bandpass_enabled:
        filtered = _apply_bandpass(
            filtered,
            sample_rate_hz,
            settings.bandpass_low_hz,
            settings.bandpass_high_hz,
        )

    line_frequencies = line_noise_frequencies(settings)
    if settings.line_noise_method == "notch" and line_frequencies:
        for frequency_hz in line_frequencies:
            filtered = _apply_notch(
                filtered,
                sample_rate_hz,
                frequency_hz,
                settings.notch_quality,
            )
    elif settings.line_noise_method == "regression":
        frequencies = _regression_frequencies(settings, sample_rate_hz)
        filtered = remove_periodic_noise(
            filtered,
            sample_rate_hz,
            frequencies,
            window_seconds=settings.regression_window_seconds,
            overlap=settings.regression_overlap,
            sample_offset=sample_offset,
            dispatch_sample_count=dispatch_sample_count,
        )

    return filtered


def parse_line_noise_frequencies(values) -> tuple[float, ...]:
    """Normalize a frequency sequence or comma/space-separated GUI value."""
    if values is None:
        return ()
    if isinstance(values, str):
        stripped = values.strip()
        if not stripped:
            return ()
        items = [item for item in re.split(r"[,;\s]+", stripped) if item]
    elif np.isscalar(values):
        items = [values]
    else:
        try:
            items = list(values)
        except TypeError as error:
            raise ValueError("Filter frequencies must be a numeric sequence.") from error

    if len(items) > MAX_LINE_NOISE_FREQUENCIES:
        raise ValueError(
            f"At most {MAX_LINE_NOISE_FREQUENCIES} filter frequencies are supported."
        )
    frequencies: list[float] = []
    for item in items:
        if isinstance(item, bool):
            raise ValueError("Filter frequencies must be positive finite numbers.")
        try:
            frequency_hz = float(item)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Invalid filter frequency: {item!r}. Use values such as 60, 120."
            ) from error
        if not np.isfinite(frequency_hz) or frequency_hz <= 0:
            raise ValueError("Filter frequencies must be positive finite numbers.")
        if frequency_hz not in frequencies:
            frequencies.append(frequency_hz)
    return tuple(frequencies)


def line_noise_frequencies(settings: LfpFilterSettings | None) -> tuple[float, ...]:
    """Return explicit frequencies, falling back to the legacy scalar field."""
    if settings is None:
        return ()
    explicit = parse_line_noise_frequencies(settings.line_noise_frequencies_hz)
    if explicit:
        return explicit
    return parse_line_noise_frequencies(settings.line_noise_hz)


def remove_periodic_noise(
    values,
    sample_rate_hz: float,
    frequencies,
    window_seconds: float = 4.0,
    overlap: float = 0.5,
    *,
    sample_offset: int = 0,
    backend: str | None = None,
    dispatch_sample_count: int | None = None,
) -> np.ndarray:
    """Remove fixed-frequency sinusoids with overlapping local regressions.

    The sample axis is last, so accepted shapes are ``(samples,)`` and
    ``(channels, samples)``.  Every window jointly estimates all supplied
    frequencies plus a constant and linear trend.  Only the fitted sine and
    cosine terms are overlap-added and subtracted.  The input is never changed.

    ``sample_offset`` aligns windows when a larger recording is processed in
    padded blocks; ordinary callers should leave it at zero.

    ``backend`` accepts ``"auto"``, ``"cpu"`` or ``"opencl"``.  The default
    uses OpenCL for large workloads when a compatible GPU is available and
    otherwise preserves the NumPy implementation. ``dispatch_sample_count``
    lets a large job that is processed in smaller UI or I/O blocks select its
    backend from the total workload instead of incorrectly treating each block
    as an independent small job.
    """
    _validate_sample_rate(sample_rate_hz)
    window_seconds = float(window_seconds)
    overlap = float(overlap)
    if not np.isfinite(window_seconds) or window_seconds <= 0:
        raise ValueError("Regression window length must be greater than 0 seconds.")
    if not np.isfinite(overlap) or overlap < 0 or overlap >= 1:
        raise ValueError("Regression overlap must be at least 0 and lower than 1.")
    if isinstance(sample_offset, bool) or int(sample_offset) != sample_offset:
        raise ValueError("Regression sample offset must be a non-negative integer.")
    sample_offset = int(sample_offset)
    if sample_offset < 0:
        raise ValueError("Regression sample offset must be a non-negative integer.")

    input_values = np.asarray(values)
    if input_values.ndim not in (1, 2):
        raise ValueError(
            "Sinusoidal regression expects (samples,) or (channels, samples)."
        )
    if not np.issubdtype(input_values.dtype, np.number):
        raise ValueError("Sinusoidal regression requires numeric signal values.")
    if not np.isfinite(input_values).all():
        raise ValueError(
            "Sinusoidal regression cannot process signal values containing NaN or infinity."
        )

    frequency_values = np.asarray(frequencies, dtype=np.float64)
    if frequency_values.ndim == 0:
        frequency_values = frequency_values.reshape(1)
    elif frequency_values.ndim != 1:
        raise ValueError("Regression frequencies must be a one-dimensional sequence.")
    if frequency_values.size == 0:
        return input_values.copy()
    if not np.isfinite(frequency_values).all() or np.any(frequency_values <= 0):
        raise ValueError("Regression frequencies must be positive finite numbers.")
    nyquist_hz = float(sample_rate_hz) / 2.0
    invalid = frequency_values[frequency_values >= nyquist_hz]
    if invalid.size:
        raise ValueError(
            f"Regression frequency {invalid[0]:g} Hz must be lower than Nyquist "
            f"({nyquist_hz:g} Hz)."
        )
    frequency_values = np.unique(frequency_values)

    output_dtype = (
        input_values.dtype
        if np.issubdtype(input_values.dtype, np.floating)
        else np.dtype(np.float64)
    )
    channels_first = (
        input_values.reshape(1, -1)
        if input_values.ndim == 1
        else input_values
    )
    sample_count = int(channels_first.shape[-1])
    if sample_count == 0:
        return input_values.astype(output_dtype, copy=True)

    window_samples = int(round(window_seconds * float(sample_rate_hz)))
    design_columns = 2 * int(frequency_values.size) + 2
    if window_samples < design_columns:
        raise ValueError(
            "Regression window is too short for the requested frequencies and trend terms."
        )
    if sample_count < design_columns:
        raise ValueError(
            f"Sinusoidal regression needs at least {design_columns} samples."
        )
    hop_samples = max(int(round(window_samples * (1.0 - overlap))), 1)

    from .gpu_backend import periodic_noise_regression_opencl

    gpu_result = periodic_noise_regression_opencl(
        input_values,
        sample_rate_hz,
        frequency_values,
        window_samples,
        hop_samples,
        sample_offset,
        output_dtype,
        requested=backend,
        dispatch_sample_count=dispatch_sample_count,
    )
    if gpu_result is not None:
        return gpu_result

    # Excluding the zero-valued endpoints keeps even the first and last sample
    # covered while retaining Hann overlap-add tapering.
    full_weight = np.hanning(window_samples + 2)[1:-1]
    accumulated_noise = np.zeros(channels_first.shape, dtype=output_dtype)
    accumulated_weight = np.zeros(sample_count, dtype=np.float64)

    first_window = max(
        0,
        ((sample_offset - window_samples + 1 + hop_samples - 1) // hop_samples)
        * hop_samples,
    )
    input_end = sample_offset + sample_count
    for window_start in range(first_window, input_end, hop_samples):
        local_start = max(window_start - sample_offset, 0)
        local_end = min(window_start + window_samples - sample_offset, sample_count)
        local_count = local_end - local_start
        if local_count < design_columns:
            continue

        weight_start = local_start - (window_start - sample_offset)
        weights = full_weight[weight_start : weight_start + local_count]
        local_time = np.arange(local_count, dtype=np.float64) / float(sample_rate_hz)
        angular_time = 2.0 * np.pi * local_time[:, np.newaxis] * frequency_values
        sinusoid_design = np.empty(
            (local_count, 2 * frequency_values.size), dtype=np.float64
        )
        sinusoid_design[:, 0::2] = np.sin(angular_time)
        sinusoid_design[:, 1::2] = np.cos(angular_time)
        trend = np.linspace(-1.0, 1.0, local_count, dtype=np.float64)
        design = np.column_stack(
            (sinusoid_design, np.ones(local_count, dtype=np.float64), trend)
        )
        coefficients, *_unused = np.linalg.lstsq(
            design,
            channels_first[:, local_start:local_end].T,
            rcond=None,
        )
        fitted_noise = sinusoid_design @ coefficients[: sinusoid_design.shape[1]]
        accumulated_noise[:, local_start:local_end] += (
            fitted_noise.T * weights
        ).astype(output_dtype, copy=False)
        accumulated_weight[local_start:local_end] += weights

    uncovered = accumulated_weight <= np.finfo(np.float64).eps
    if uncovered.any():
        accumulated_noise[:, uncovered] = 0
        accumulated_weight[uncovered] = 1.0
    accumulated_noise /= accumulated_weight[np.newaxis, :]
    np.subtract(
        channels_first,
        accumulated_noise,
        out=accumulated_noise,
        casting="unsafe",
    )
    return accumulated_noise[0] if input_values.ndim == 1 else accumulated_noise


def compute_power_spectrum(
    values,
    sample_rate_hz: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute power spectrum.

    Args:
        values: Signal values to process.
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


def compute_spectrogram(
    values,
    sample_rate_hz: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute a spectrogram.

    Args:
        values: Signal values to process.
    """
    _validate_sample_rate(sample_rate_hz)
    signal_values = _finite_signal(values)

    if signal_values.size < 8:
        raise ValueError("Need at least 8 samples to calculate a spectrogram.")

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
    *,
    record_time_s=None,
    values_prepared: bool = False,
) -> LfpSegment:
    """Prepare lfp segment.

    Args:
        values: Signal values to process.
        start_s: Start time of the selected range, in seconds.
        end_s: End time of the selected range, in seconds.
    """
    start_s = float(start_s)
    end_s = float(end_s)
    if not np.isfinite(start_s) or not np.isfinite(end_s):
        raise ValueError("Selected time range must be finite.")
    if start_s == end_s:
        raise ValueError("Selected time range is too short.")
    if start_s > end_s:
        start_s, end_s = end_s, start_s

    time_us_values = np.asarray(time_us, dtype=np.float64)
    if record_time_s is None:
        record_time_values = time_us_values / 1_000_000.0
    else:
        record_time_values = np.asarray(record_time_s, dtype=np.float64)
        if record_time_values.shape != time_us_values.shape:
            raise ValueError("Record-time and timestamp arrays must have equal length.")
    signal_values = (
        np.asarray(values)
        if values_prepared
        else prepare_lfp_signal(values, sample_rate_hz, settings)
    )
    if signal_values.shape != time_us_values.shape:
        raise ValueError("Signal and timestamp arrays must have equal length.")
    mask = (record_time_values >= start_s) & (record_time_values <= end_s)

    if int(mask.sum()) < 2:
        raise ValueError("Selected time range is too short for analysis.")

    return LfpSegment(
        time_us=time_us_values[mask],
        record_time_s=record_time_values[mask],
        values=signal_values[mask],
        sample_rate_hz=float(sample_rate_hz),
    )


def filter_description(settings: LfpFilterSettings | None) -> str:
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

    frequencies = line_noise_frequencies(settings)
    frequency_label = ", ".join(f"{frequency:g}" for frequency in frequencies)
    if settings.line_noise_method == "notch" and frequencies:
        line_noise_description = (
            f"notch {frequency_label} Hz (Q={settings.notch_quality:g})"
        )
    elif settings.line_noise_method == "regression" and frequencies:
        from .gpu_backend import select_backend

        harmonic_label = (
            "all harmonics below Nyquist"
            if _uses_all_regression_harmonics(settings)
            else "fundamental only"
        )
        try:
            selected_backend = select_backend(100_000)
        except RuntimeError:
            selected_backend = "cpu"
        backend_label = (
            "OpenCL GPU"
            if selected_backend == "opencl"
            else "NumPy CPU fallback"
        )
        line_noise_description = (
            f"sinusoidal regression {frequency_label} Hz, "
            f"{settings.regression_window_seconds:g} s, "
            f"{settings.regression_overlap * 100:g}% overlap, {harmonic_label}, "
            f"{backend_label}"
        )
    else:
        line_noise_description = "line-noise removal off"

    return f"Filtered: {bandpass_description}, {line_noise_description}"


def _finite_signal(values) -> np.ndarray:
    signal_values = np.asarray(values)
    if not np.issubdtype(signal_values.dtype, np.floating):
        signal_values = signal_values.astype(float)
    if signal_values.ndim != 1:
        signal_values = signal_values.reshape(-1)

    if signal_values.size == 0:
        return signal_values.copy()

    finite_mask = np.isfinite(signal_values)
    if finite_mask.all():
        return signal_values.copy()

    if not finite_mask.any():
        return np.zeros(signal_values.shape, dtype=signal_values.dtype)

    indices = np.arange(signal_values.size)
    interpolated = np.interp(
        indices,
        indices[finite_mask],
        signal_values[finite_mask],
    )
    return interpolated.astype(signal_values.dtype, copy=False)


def _validate_sample_rate(sample_rate_hz: float) -> None:
    if not np.isfinite(sample_rate_hz) or sample_rate_hz <= 0:
        raise ValueError("Sample rate must be a positive number.")


def _validate_line_noise_method(method: str) -> None:
    if method not in {"none", "notch", "regression"}:
        raise ValueError(f"Unsupported line-noise removal method: {method!r}.")


def _validate_regression_settings(
    settings: LfpFilterSettings,
    sample_rate_hz: float,
) -> None:
    if not line_noise_frequencies(settings):
        raise ValueError("Sinusoidal regression requires at least one frequency.")
    _validate_regression_harmonic_options(settings)
    _regression_frequencies(settings, sample_rate_hz)
    window_seconds = float(settings.regression_window_seconds)
    overlap = float(settings.regression_overlap)
    if not np.isfinite(window_seconds) or window_seconds <= 0:
        raise ValueError("Regression window length must be greater than 0 seconds.")
    if not np.isfinite(overlap) or overlap < 0 or overlap >= 1:
        raise ValueError("Regression overlap must be at least 0 and lower than 1.")


def _regression_frequencies(
    settings: LfpFilterSettings,
    sample_rate_hz: float,
) -> list[float]:
    _validate_sample_rate(sample_rate_hz)
    _validate_regression_harmonic_options(settings)
    base_frequencies = line_noise_frequencies(settings)
    if not base_frequencies:
        raise ValueError("Sinusoidal regression requires at least one frequency.")
    nyquist_hz = float(sample_rate_hz) / 2.0
    for base_hz in base_frequencies:
        if base_hz >= nyquist_hz:
            raise ValueError(
                f"Line-noise frequency {base_hz:g} Hz must be lower than Nyquist "
                f"({nyquist_hz:g} Hz)."
            )
    use_all_harmonics = _uses_all_regression_harmonics(settings)
    frequencies: list[float] = []
    seen: set[float] = set()
    for base_hz in base_frequencies:
        if use_all_harmonics:
            highest_harmonic = int(
                np.floor(np.nextafter(nyquist_hz, -np.inf) / base_hz)
            )
        else:
            highest_harmonic = 1
        for harmonic in range(1, highest_harmonic + 1):
            frequency = base_hz * harmonic
            key = round(frequency, 12)
            if frequency < nyquist_hz and key not in seen:
                seen.add(key)
                frequencies.append(frequency)
                if len(frequencies) > MAX_REGRESSION_FREQUENCIES:
                    raise ValueError(
                        "Automatic harmonic removal would create more than "
                        f"{MAX_REGRESSION_FREQUENCIES} regression frequencies. "
                        "Use a higher base frequency or disable all harmonics."
                    )
    return frequencies


def _uses_all_regression_harmonics(settings: LfpFilterSettings) -> bool:
    """Treat the former 2nd-harmonic selection as all harmonics after migration."""
    return bool(
        settings.regression_all_harmonics or settings.regression_harmonics > 1
    )


def _validate_regression_harmonic_options(settings: LfpFilterSettings) -> None:
    if not isinstance(settings.regression_all_harmonics, bool):
        raise ValueError("Regression all-harmonics setting must be true or false.")
    harmonic_count = settings.regression_harmonics
    if (
        isinstance(harmonic_count, bool)
        or int(harmonic_count) != harmonic_count
        or int(harmonic_count) < 1
    ):
        raise ValueError("Regression harmonics must be a positive integer.")


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
