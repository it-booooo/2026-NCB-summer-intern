from pathlib import Path
from typing import Callable, cast

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from .. import signal_data as signal_func
from .chart_helpers import format_signal_label, install_x_navigation, resolve_plot_step


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
    lfp_lines: dict[tuple[int, bool], Line2D]
    lfp_channel_numbers: list[int]
    lfp_plot_step: int


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
        step: Input used by this operation.
        info: Metadata or state information to store or use.
        filter_settings: Input used by this operation.
    """
    if info is None:
        raise ValueError("Please provide LFP data information.")

    file_path = info.get("path")
    if file_path is None:
        raise ValueError("LFP path not found in info dictionary.")

    input_file = Path(file_path)
    if not input_file.is_file():
        raise FileNotFoundError(f"LFP CSV file not found: {input_file}")

    if dataset is None:
        dataset = signal_func.LfpDataset.from_csv(info)
    data = dataset.data

    time_s = data["time_us"].to_numpy(dtype=float) / 1e6

    plot_step = resolve_plot_step(len(data), step)
    if plot_step == 0 or len(data) <= plot_step:
        plot_index = slice(None)
    else:
        plot_index = slice(None, None, plot_step)
    x = time_s[plot_index]

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

    fig = cast(
        LfpFigure,
        plt.figure(
            figsize=(16, 5),
            constrained_layout=False,
            FigureClass=LfpFigure,
        ),
    )
    ax = fig.add_axes((0.08, 0.22, 0.90, 0.62))

    lines: dict[tuple[int, bool], Line2D] = {}
    base_line_data: dict[tuple[int, bool], tuple[np.ndarray, np.ndarray]] = {}
    show_filtered = bool(filter_settings and filter_settings.show_filtered)

    for channel in channel_numbers:
        raw_values = dataset.signal_values(channel)
        filtered_settings = _filter_settings_for_view(filter_settings, True)
        filtered_values = dataset.signal_values(channel, filtered_settings)
        for filtered, signal_values in ((False, raw_values), (True, filtered_values)):
            line = ax.plot(
                x,
                signal_values[plot_index],
                linewidth=0.5,
                color="blue",
                visible=(channel == selected_channel and filtered == show_filtered),
            )[0]
            lines[(channel, filtered)] = line
            base_line_data[(channel, filtered)] = (
                np.asarray(x, dtype=float),
                np.asarray(signal_values[plot_index], dtype=float),
            )

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
        signal_func.filter_description(filter_settings),
        fontsize=7,
        ha="right",
        va="bottom",
    )
    ax.grid(True, linewidth=0.4, alpha=0.35)
    ax.tick_params(axis="both", labelsize=7, pad=1)

    full_xlim = (float(time_s[0]), float(time_s[-1]))
    if full_xlim[0] == full_xlim[1]:
        full_xlim = (full_xlim[0] - 0.5, full_xlim[1] + 0.5)

    navigation = install_x_navigation(fig, ax, full_xlim)

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

        for (item_channel, filtered), line in lines.items():
            line.set_visible(
                item_channel == selected_channel and filtered == show_filtered
            )

        ax.relim(visible_only=True)
        ax.autoscale_view(scalex=False, scaley=True)
        fig.canvas.draw_idle()

    def set_lfp_signal_view(filtered: bool) -> None:
        """Set lfp signal view.

        Args:
            filtered: Input used by this operation.
        """
        nonlocal show_filtered
        show_filtered = bool(filtered)
        for (item_channel, item_filtered), line in lines.items():
            line.set_visible(
                item_channel == selected_channel and item_filtered == show_filtered
            )
        label_settings = _filter_settings_for_view(filter_settings, show_filtered)
        filter_label.set_text(signal_func.filter_description(label_settings))
        ax.relim(visible_only=True)
        ax.autoscale_view(scalex=False, scaley=True)
        fig.canvas.draw_idle()

    def set_lfp_peak_samples(
        channel: int,
        filtered: bool,
        times: np.ndarray,
        values: np.ndarray,
    ) -> None:
        """Merge exact peak-neighborhood samples into one displayed LFP line."""
        key = (int(channel), bool(filtered))
        if key not in lines:
            raise ValueError(f"Invalid LFP line: channel={channel}, filtered={filtered}")

        base_times, base_values = base_line_data[key]
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

        lines[key].set_data(merged_times, merged_values)
        if lines[key].get_visible():
            ax.relim(visible_only=True)
            ax.autoscale_view(scalex=False, scaley=True)
        fig.canvas.draw_idle()

    set_lfp_channel(selected_channel)

    fig.set_lfp_channel = set_lfp_channel
    fig.set_lfp_signal_view = set_lfp_signal_view
    fig.set_lfp_peak_samples = set_lfp_peak_samples
    fig.set_lfp_xlim = navigation.set_xlim
    fig.reset_lfp_x_zoom = navigation.reset_x_zoom
    fig.add_lfp_xlim_callback = navigation.add_xlim_callback
    fig.lfp_full_xlim = full_xlim
    fig.lfp_lines = lines
    fig.lfp_channel_numbers = channel_numbers
    fig.lfp_plot_step = plot_step

    return fig
