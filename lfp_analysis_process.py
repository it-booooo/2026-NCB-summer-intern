"""Standalone full-resolution LFP analysis and static rendering process."""

from __future__ import annotations

import io

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from scipy import signal

FINITE_CHECK_BLOCK_SAMPLES = 1_000_000


def render_lfp_analysis(
    connection,
    input_path,
    dtype,
    sample_count,
    sample_rate_hz,
    analysis_type,
    channel,
    start_time_s,
    end_time_s,
    record_time_origin_sec,
    dpi=100,
    annotation=None,
    frequency_range_hz=None,
    notch_display_options=None,
):
    """Compute and render inside a disposable process."""
    figure = None
    values = None
    try:
        values = np.memmap(
            input_path,
            dtype=np.dtype(dtype),
            mode="r",
            shape=(int(sample_count),),
        )
        if analysis_type == "power_spectrum":
            frequencies, power = _compute_power_spectrum(
                values,
                float(sample_rate_hz),
            )
            figure = _power_spectrum_figure(
                channel,
                frequencies,
                power,
                notch_display_options=notch_display_options,
            )
            del frequencies, power
        elif analysis_type == "spectrogram":
            frequencies, times, power = _compute_time_frequency(
                values,
                float(sample_rate_hz),
            )
            figure = _spectrogram_figure(
                channel,
                start_time_s,
                end_time_s,
                frequencies,
                times,
                power,
                record_time_origin_sec,
                frequency_range_hz,
            )
            del frequencies, times, power
        else:
            raise ValueError(f"Unsupported LFP analysis: {analysis_type}")

        if annotation:
            figure.suptitle(str(annotation), fontsize=8)
        figure.set_dpi(float(dpi))
        canvas = FigureCanvasAgg(figure)
        output = io.BytesIO()
        canvas.print_png(output)
        connection.send(
            {
                "ok": True,
                "image_png": output.getvalue(),
            }
        )
    except Exception as error:
        connection.send(
            {
                "ok": False,
                "error": f"{type(error).__name__}: {error}",
            }
        )
    finally:
        if figure is not None:
            canvas = figure.canvas
            figure.clear()
            figure.set_canvas(None)
            if canvas is not None:
                canvas.figure = None
        if values is not None:
            del values
        connection.close()


def _compute_power_spectrum(values, sample_rate_hz):
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


def _compute_time_frequency(values, sample_rate_hz):
    signal_values = _finite_signal(values)
    if signal_values.size < 8:
        raise ValueError("Need at least 8 samples to calculate time-frequency map.")
    nperseg = min(512, signal_values.size)
    return signal.spectrogram(
        signal_values,
        fs=sample_rate_hz,
        window="hann",
        nperseg=nperseg,
        noverlap=nperseg // 2,
        detrend="constant",
        scaling="density",
        mode="psd",
    )


def _finite_signal(values):
    signal_values = np.asarray(values)
    if not np.issubdtype(signal_values.dtype, np.floating):
        signal_values = signal_values.astype(float)
    if signal_values.ndim != 1:
        signal_values = signal_values.reshape(-1)
    if signal_values.size == 0:
        return signal_values.copy()
    all_finite = True
    for start in range(0, signal_values.size, FINITE_CHECK_BLOCK_SAMPLES):
        if not np.isfinite(
            signal_values[start : start + FINITE_CHECK_BLOCK_SAMPLES]
        ).all():
            all_finite = False
            break
    if all_finite:
        # Keep the read-only memmap view.  Welch/spectrogram do not mutate their
        # input, so a full-size RAM copy is unnecessary for the common case.
        return signal_values
    finite_mask = np.isfinite(signal_values)
    if not finite_mask.any():
        return np.zeros(signal_values.shape, dtype=signal_values.dtype)
    indices = np.arange(signal_values.size)
    interpolated = np.interp(
        indices,
        indices[finite_mask],
        signal_values[finite_mask],
    )
    return interpolated.astype(signal_values.dtype, copy=False)


def _interpolate_notch_gaps_db(
    frequencies,
    power_db,
    notch_frequencies_hz,
    quality_factor,
):
    """Interpolate notch regions in a dB display copy without changing PSD data."""

    frequency_values = np.asarray(frequencies, dtype=np.float64)
    display_values = np.array(power_db, dtype=np.float64, copy=True)
    if (
        frequency_values.ndim != 1
        or display_values.ndim != 1
        or frequency_values.shape != display_values.shape
        or frequency_values.size < 3
    ):
        return display_values
    quality_factor = float(quality_factor)
    if not np.isfinite(quality_factor) or quality_factor <= 0:
        return display_values

    positive_steps = np.diff(frequency_values)
    positive_steps = positive_steps[
        np.isfinite(positive_steps) & (positive_steps > 0)
    ]
    if positive_steps.size == 0:
        return display_values
    frequency_resolution = float(np.median(positive_steps))
    gap_mask = np.zeros(frequency_values.shape, dtype=bool)
    for notch_frequency in notch_frequencies_hz or ():
        notch_frequency = float(notch_frequency)
        if not np.isfinite(notch_frequency) or notch_frequency <= 0:
            continue
        # iirnotch defines Q as centre frequency / total -3 dB bandwidth.
        # Keep at least two PSD bins on either side in low-resolution plots.
        half_width_hz = max(
            notch_frequency / (2.0 * quality_factor),
            2.0 * frequency_resolution,
        )
        gap_mask |= np.abs(frequency_values - notch_frequency) <= half_width_hz

    if not gap_mask.any():
        return display_values
    padded = np.pad(gap_mask, (1, 1), constant_values=False)
    transitions = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(transitions == 1)
    ends = np.flatnonzero(transitions == -1) - 1
    for start, end in zip(starts, ends):
        left = int(start) - 1
        right = int(end) + 1
        if left < 0 or right >= display_values.size:
            continue
        if not (
            np.isfinite(display_values[left])
            and np.isfinite(display_values[right])
        ):
            continue
        display_values[start : end + 1] = np.interp(
            frequency_values[start : end + 1],
            (frequency_values[left], frequency_values[right]),
            (display_values[left], display_values[right]),
        )
    return display_values


def _power_spectrum_figure(
    channel,
    frequencies,
    power,
    notch_display_options=None,
):
    figure = Figure(figsize=(7.6, 4.4), constrained_layout=True)
    ax = figure.add_subplot(111)
    power_db = np.array(power, copy=True)
    tiny = np.finfo(power_db.dtype).tiny
    np.maximum(power_db, tiny, out=power_db)
    np.log10(power_db, out=power_db)
    power_db *= 10.0
    interpolated = bool(notch_display_options)
    if interpolated:
        power_db = _interpolate_notch_gaps_db(
            frequencies,
            power_db,
            notch_display_options.get("frequencies_hz", ()),
            notch_display_options.get("quality_factor", 30.0),
        )
    ax.plot(frequencies, power_db, linewidth=0.8, color="#1f77b4")
    title = f"LFP Power Spectrum - Channel {channel}"
    if interpolated:
        title += " (notch gaps display-interpolated)"
    ax.set_title(title)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("PSD (dB/Hz)")
    ax.grid(True, linewidth=0.4, alpha=0.35)
    return figure


def _spectrogram_figure(
    channel,
    start_time_s,
    end_time_s,
    frequencies,
    times,
    power,
    record_time_origin_sec,
    frequency_range_hz=None,
):
    duration_sec = abs(float(end_time_s) - float(start_time_s))
    figure_width = min(24.0, 8.0 + duration_sec / 120.0)
    figure = Figure(figsize=(figure_width, 4.8), constrained_layout=True)
    ax = figure.add_subplot(111)
    display_start_s = float(start_time_s)
    if record_time_origin_sec is not None:
        display_start_s -= float(record_time_origin_sec)
    plot_times = times + display_start_s
    power_db = np.array(power, copy=True)
    tiny = np.finfo(power_db.dtype).tiny
    np.maximum(power_db, tiny, out=power_db)
    np.log10(power_db, out=power_db)
    power_db *= 10.0
    mesh = ax.pcolormesh(
        plot_times,
        frequencies,
        power_db,
        shading="auto",
        cmap="viridis",
    )
    figure.colorbar(mesh, ax=ax, label="PSD (dB/Hz)")
    ax.set_title(f"LFP Spectrogram - Channel {channel}")
    time_mode = (
        "sync time" if record_time_origin_sec is not None else "time"
    )
    ax.set_xlabel(f"{time_mode} (s)")
    ax.set_ylabel("Frequency (Hz)")
    if frequency_range_hz is not None:
        low_hz, high_hz = map(float, frequency_range_hz)
        ax.set_ylim(low_hz, high_hz)
    return figure
