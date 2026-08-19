from collections.abc import Callable
from pathlib import Path

import numpy as np
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from .. import signal_data as signal_func
from .chart_helpers import (
    format_signal_label,
    install_x_navigation,
    resolve_plot_step,
)


class LfpFigure(Figure):
    set_lfp_channel: Callable[[int], None]
    set_lfp_signal_view: Callable[[bool], None]
    set_lfp_peak_samples: Callable[
        [int, bool, np.ndarray, np.ndarray], None
    ]
    set_lfp_xlim: Callable[[float, float], None]
    reset_lfp_x_zoom: Callable[[], None]
    add_lfp_xlim_callback: Callable[[Callable[[tuple[float, float]], None]], None]
    lfp_full_xlim: tuple[float, float]
    current_channel: int
    current_view: str
    line: Line2D
    lfp_channel_numbers: list[int]
    lfp_plot_step: int
    refresh_lfp_plot: Callable[..., None]


def _filter_settings_for_view(filter_settings, show_filtered):
    """Return one complete filter configuration for a raw/filtered view."""
    return signal_func.LfpFilterSettings(
        show_filtered=bool(show_filtered),
        bandpass_enabled=bool(filter_settings and filter_settings.bandpass_enabled),
        bandpass_low_hz=(filter_settings.bandpass_low_hz if filter_settings else 1.0),
        bandpass_high_hz=(
            filter_settings.bandpass_high_hz if filter_settings else 100.0
        ),
        line_noise_hz=(filter_settings.line_noise_hz if filter_settings else None),
        notch_quality=(filter_settings.notch_quality if filter_settings else 30.0),
        line_noise_method=(
            filter_settings.line_noise_method if filter_settings else "notch"
        ),
        regression_window_seconds=(
            filter_settings.regression_window_seconds if filter_settings else 4.0
        ),
        regression_overlap=(
            filter_settings.regression_overlap if filter_settings else 0.5
        ),
        regression_harmonics=(
            filter_settings.regression_harmonics if filter_settings else 1
        ),
        regression_all_harmonics=(
            filter_settings.regression_all_harmonics if filter_settings else False
        ),
        line_noise_frequencies_hz=(
            filter_settings.line_noise_frequencies_hz if filter_settings else ()
        ),
    )


def LFP(
    channels: int | list[int] | tuple[int, ...] | None = 1,
    step: int | None = None,
    info: dict | None = None,
    filter_settings: signal_func.LfpFilterSettings | None = None,
    dataset: signal_func.LfpDataset | None = None,
) -> LfpFigure:
    """Initialize the LFP plotting component.

    Args:
        channels: Available LFP channel identifiers.
    """
    if dataset is None:
        if info is None:
            raise ValueError("Please provide an LFP dataset or data information.")
        dataset = signal_func.LfpDataset.from_csv(info)
    info = dataset.info

    file_path = info.get("path")
    if file_path is None:
        raise ValueError("LFP path not found in info dictionary.")

    input_file = Path(file_path)
    if not input_file.is_file():
        raise FileNotFoundError(f"LFP CSV file not found: {input_file}")

    channel_numbers = dataset.channels

    if channels is None:
        selected_channel = channel_numbers[0]
    elif isinstance(channels, int):
        selected_channel = channels
    else:
        if len(channels) == 0:
            raise ValueError("channels cannot be empty.")
        selected_channel = int(channels[0])

    if selected_channel not in channel_numbers:
        raise ValueError(f"Invalid LFP channel: {selected_channel}")

    show_filtered = bool(filter_settings and filter_settings.show_filtered)

    fig = LfpFigure(
        figsize=(16, 5),
        constrained_layout=False,
    )
    ax = fig.add_axes((0.08, 0.22, 0.90, 0.62))

    base_times = np.asarray([], dtype=float)
    base_values = np.asarray([], dtype=float)
    line = ax.plot(base_times, base_values, linewidth=0.5, color="blue")[0]

    ax.set_xlabel("")
    ax.set_ylabel("")
    fig.text(
        0.055,
        0.855,
        format_signal_label(info["value_unit"]),
        fontsize=7,
        ha="right",
        va="top",
    )
    fig.text(
        0.055,
        0.055,
        f"Time ({info['time_unit']})",
        fontsize=7,
        ha="right",
        va="bottom",
    )
    filter_label = fig.text(
        0.97,
        0.88,
        "",
        fontsize=7,
        ha="right",
        va="bottom",
    )
    ax.grid(True, linewidth=0.4, alpha=0.35)
    ax.tick_params(axis="both", labelsize=7, pad=1)

    def describe_filter(settings) -> str:
        """Label the filter with the backend the whole-record build will use."""
        try:
            sample_count = dataset.source.sample_count(selected_channel)
        except (AttributeError, KeyError, OSError, ValueError):
            sample_count = None
        return signal_func.filter_description(settings, sample_count)

    full_xlim = dataset.record_bounds_s(selected_channel)
    if full_xlim[0] == full_xlim[1]:
        full_xlim = (full_xlim[0] - 0.5, full_xlim[1] + 0.5)

    navigation = install_x_navigation(fig, ax, full_xlim)
    resolved_auto_stride: int | None = None
    partial_chunks = {}

    def refresh_lfp_plot(*, recalculate_auto: bool = False) -> None:
        """Rebuild the fixed full-range plot data with the configured step."""
        nonlocal base_times, base_values, resolved_auto_stride
        settings = _filter_settings_for_view(filter_settings, show_filtered)
        effective_step = step
        if step is None and resolved_auto_stride is not None and not recalculate_auto:
            effective_step = resolved_auto_stride
        sample_count = dataset.source.sample_count(selected_channel)
        actual_stride = max(resolve_plot_step(sample_count, effective_step), 1)
        coarse_times, values = dataset.coarse_values(
            selected_channel,
            actual_stride,
            settings,
        )
        times = coarse_times / 1_000_000.0
        if step is None:
            resolved_auto_stride = actual_stride
        filter_label.set_text(signal_func.filter_description(settings, sample_count))
        base_times = np.asarray(times, dtype=float)
        base_values = np.asarray(values, dtype=float)
        line.set_data(base_times, base_values)
        fig.current_channel = selected_channel
        fig.current_view = "filtered" if show_filtered else "raw"
        fig.lfp_plot_step = actual_stride
        ax.relim()
        ax.autoscale_view(scalex=False, scaley=True)
        fig.canvas.draw_idle()

    def set_lfp_channel(channel: int) -> None:
        """Set lfp channel.

        Args:
            channel: LFP channel identifier.
        """
        nonlocal selected_channel

        channel = int(channel)

        if channel not in channel_numbers:
            raise ValueError(f"Invalid LFP channel: {channel}")

        selected_channel = channel
        refresh_lfp_plot()

    def set_lfp_signal_view(filtered: bool) -> None:
        """Set lfp signal view."""
        nonlocal show_filtered
        show_filtered = bool(filtered)
        refresh_lfp_plot()
        label_settings = _filter_settings_for_view(filter_settings, show_filtered)
        filter_label.set_text(describe_filter(label_settings))
        fig.canvas.draw_idle()

    def set_lfp_filter_settings(settings) -> None:
        """Replace the settings used by subsequent full or partial refreshes."""
        nonlocal filter_settings
        filter_settings = settings
        label_settings = _filter_settings_for_view(filter_settings, show_filtered)
        filter_label.set_text(describe_filter(label_settings))

    def begin_lfp_partial_filtered() -> None:
        """Clear the line so completed filtered chunks can be drawn incrementally."""
        nonlocal show_filtered, partial_chunks, base_times, base_values
        show_filtered = True
        partial_chunks = {}
        base_times = np.asarray([], dtype=float)
        base_values = np.asarray([], dtype=float)
        line.set_data([], [])
        fig.current_view = "filtered"
        filter_label.set_text(describe_filter(filter_settings))
        fig.canvas.draw_idle()

    def draw_partial_filtered() -> None:
        """Show every chunk the running filter build has produced so far."""
        nonlocal base_times, base_values
        ordered = [(key, *partial_chunks[key]) for key in sorted(partial_chunks)]
        display_times = []
        display_values = []
        previous_end = None
        for start, end, chunk_times, chunk_values in ordered:
            if previous_end is not None and start > previous_end:
                display_times.append(np.asarray([np.nan]))
                display_values.append(np.asarray([np.nan]))
            display_times.append(chunk_times)
            display_values.append(chunk_values)
            previous_end = end
        if display_times:
            base_times = np.concatenate(display_times)
            base_values = np.concatenate(display_values)
        else:
            base_times = np.asarray([], dtype=float)
            base_values = np.asarray([], dtype=float)
        line.set_data(base_times, base_values)
        ax.relim()
        ax.autoscale_view(scalex=False, scaley=True)
        fig.canvas.draw_idle()

    def append_lfp_partial_filtered(point_start, times, values) -> None:
        """Add one completed filtered overview chunk to the visible line."""
        nonlocal partial_chunks
        if not show_filtered:
            return
        start = int(point_start)
        partial_chunks[start] = (
            start + np.asarray(values).size,
            np.asarray(times, dtype=float) / 1_000_000.0,
            np.asarray(values, dtype=float),
        )
        draw_partial_filtered()

    def restore_lfp_partial_filtered() -> None:
        """Return to a build still running for the newly reselected channel."""
        nonlocal show_filtered
        show_filtered = True
        fig.current_view = "filtered"
        filter_label.set_text(describe_filter(filter_settings))
        draw_partial_filtered()

    def set_lfp_peak_samples(
        channel: int,
        filtered: bool,
        times: np.ndarray,
        values: np.ndarray,
    ) -> None:
        """Merge exact peak-neighborhood samples into one displayed LFP line."""
        if int(channel) != selected_channel or bool(filtered) != show_filtered:
            raise ValueError(f"Invalid LFP line: channel={channel}, filtered={filtered}")

        extra_times = np.asarray(times, dtype=float).reshape(-1)
        extra_values = np.asarray(values, dtype=float).reshape(-1)
        if extra_times.shape != extra_values.shape:
            raise ValueError("LFP peak sample times and values must match.")

        finite = np.isfinite(extra_times) & np.isfinite(extra_values)
        if np.any(finite):
            merged_times = np.concatenate((base_times, extra_times[finite]))
            merged_values = np.concatenate((base_values, extra_values[finite]))
            order = np.argsort(merged_times, kind="stable")
            merged_times = merged_times[order]
            merged_values = merged_values[order]
            # Prefer exact full-resolution samples when a time also exists in the
            # step-downsampled base line.
            keep = np.r_[merged_times[1:] != merged_times[:-1], True]
            merged_times = merged_times[keep]
            merged_values = merged_values[keep]
        else:
            merged_times = base_times
            merged_values = base_values

        line.set_data(merged_times, merged_values)
        ax.relim()
        ax.autoscale_view(scalex=False, scaley=True)
        fig.canvas.draw_idle()

    filter_label.set_text(
        describe_filter(_filter_settings_for_view(filter_settings, show_filtered))
    )
    refresh_lfp_plot(recalculate_auto=True)

    fig.set_lfp_channel = set_lfp_channel
    fig.set_lfp_signal_view = set_lfp_signal_view
    fig.set_lfp_filter_settings = set_lfp_filter_settings
    fig.begin_lfp_partial_filtered = begin_lfp_partial_filtered
    fig.append_lfp_partial_filtered = append_lfp_partial_filtered
    fig.restore_lfp_partial_filtered = restore_lfp_partial_filtered
    fig.set_lfp_peak_samples = set_lfp_peak_samples
    fig.set_lfp_xlim = navigation.set_xlim
    fig.reset_lfp_x_zoom = navigation.reset_x_zoom
    fig.add_lfp_xlim_callback = navigation.add_xlim_callback
    fig.lfp_full_xlim = full_xlim
    fig.line = line
    fig.current_channel = selected_channel
    fig.current_view = "filtered" if show_filtered else "raw"
    fig.lfp_channel_numbers = channel_numbers
    fig.refresh_lfp_plot = refresh_lfp_plot

    return fig
