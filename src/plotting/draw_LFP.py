from pathlib import Path
from typing import Callable, cast

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from .. import signal_processing as signal_func
from ..data_io import csv_loader as csv_func
from ..data_io import readers as read


class LfpFigure(Figure):
    set_lfp_channel: Callable[[int], None]
    set_lfp_signal_view: Callable[[bool], None]
    set_lfp_xlim: Callable[[float, float], None]
    reset_lfp_x_zoom: Callable[[], None]
    add_lfp_xlim_callback: Callable[[Callable[[tuple[float, float]], None]], None]
    lfp_full_xlim: tuple[float, float]
    lfp_lines: dict[tuple[int, bool], Line2D]
    lfp_channel_numbers: list[int]
    lfp_plot_step: int


TARGET_PLOT_POINTS = 5000


def resolve_plot_step(data_length: int, step: int | None) -> int:
    if step is None:
        return max(data_length // TARGET_PLOT_POINTS, 1)
    return max(int(step), 0)


def LFP(
    channels: int | list[int] | tuple[int, ...] | None = 1,
    step: int | None = None,
    info: dict | None = None,
    filter_settings: signal_func.LfpFilterSettings | None = None,
) -> LfpFigure:
    if info is None:
        raise ValueError("Please provide LFP data information.")

    file_path = info.get("path")
    if file_path is None:
        raise ValueError("LFP path not found in info dictionary.")

    input_file = Path(file_path)
    if not input_file.is_file():
        raise FileNotFoundError(f"LFP CSV file not found: {input_file}")

    data = read.LFP(str(input_file))
    units = csv_func.parse_signal_csv_units(input_file)

    time_s = data["time_us"].to_numpy(dtype=float) / 1e6

    plot_step = resolve_plot_step(len(data), step)
    if plot_step == 0 or len(data) <= plot_step:
        plot_index = slice(None)
    else:
        plot_index = slice(None, None, plot_step)
    x = time_s[plot_index]

    channel_numbers = info.get("channels") or [
        int(column.removeprefix("channel_"))
        for column in data.columns
        if column.startswith("channel_")
    ]
    channel_numbers = [int(channel) for channel in channel_numbers]

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
    ax = fig.add_axes((0.08, 0.30, 0.90, 0.60))

    lines: dict[tuple[int, bool], Line2D] = {}
    show_filtered = bool(filter_settings and filter_settings.show_filtered)

    for channel in channel_numbers:
        sample_rate_hz = signal_func.sample_rate_for_channel(
            info,
            data["time_us"],
            channel,
        )
        raw_values = data[f"channel_{channel}"].to_numpy(dtype=float)
        filtered_settings = signal_func.LfpFilterSettings(
            show_filtered=True,
            bandpass_enabled=bool(filter_settings and filter_settings.bandpass_enabled),
            bandpass_low_hz=(filter_settings.bandpass_low_hz if filter_settings else 1.0),
            bandpass_high_hz=(filter_settings.bandpass_high_hz if filter_settings else 100.0),
            line_noise_hz=(filter_settings.line_noise_hz if filter_settings else None),
            notch_quality=(filter_settings.notch_quality if filter_settings else 30.0),
        )
        filtered_values = signal_func.prepare_lfp_signal(
            raw_values,
            sample_rate_hz,
            filtered_settings,
        )
        for filtered, signal_values in ((False, raw_values), (True, filtered_values)):
            line = ax.plot(
                x,
                signal_values[plot_index],
                linewidth=0.5,
                color="blue",
                visible=(channel == selected_channel and filtered == show_filtered),
            )[0]
            lines[(channel, filtered)] = line

    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.text(
        -0.040,
        0.99,
        format_signal_label(units["value_unit"]),
        fontsize=7,
        ha="right",
        va="top",
        transform=ax.transAxes,
        clip_on=False,
    )
    filter_label = ax.text(
        0.99,
        0.99,
        signal_func.filter_description(filter_settings),
        fontsize=7,
        ha="right",
        va="top",
        transform=ax.transAxes,
        clip_on=False,
    )
    ax.grid(True, linewidth=0.4, alpha=0.35)
    ax.tick_params(axis="both", labelsize=7, pad=1)

    full_xlim = (float(time_s[0]), float(time_s[-1]))
    if full_xlim[0] == full_xlim[1]:
        full_xlim = (full_xlim[0] - 0.5, full_xlim[1] + 0.5)

    ax.set_xlim(full_xlim)
    ax.autoscale(enable=False, axis="x")
    pan_state: dict[str, float] = {}
    xlim_callbacks: list[Callable[[tuple[float, float]], None]] = []

    def clamp_xlim(left: float, right: float) -> tuple[float, float]:
        full_left, full_right = full_xlim
        full_width = full_right - full_left
        width = right - left

        if width >= full_width:
            return full_xlim

        if left < full_left:
            right += full_left - left
            left = full_left

        if right > full_right:
            left -= right - full_right
            right = full_right

        return max(left, full_left), min(right, full_right)

    def reset_lfp_x_zoom() -> None:
        set_lfp_xlim(*full_xlim)

    def set_lfp_xlim(left: float, right: float, *, emit: bool = True) -> None:
        next_xlim = clamp_xlim(left, right)
        ax.set_xlim(next_xlim)

        if emit:
            for callback in xlim_callbacks:
                callback(next_xlim)

        fig.canvas.draw_idle()

    def add_lfp_xlim_callback(
        callback: Callable[[tuple[float, float]], None],
    ) -> None:
        xlim_callbacks.append(callback)

    def event_xdata(event) -> float | None:
        if event.xdata is not None:
            return float(event.xdata)
        if event.x is None or event.y is None:
            return None
        return float(ax.transData.inverted().transform((event.x, event.y))[0])

    def zoom_lfp_x(event) -> None:
        if event.inaxes != ax:
            return

        left, right = ax.get_xlim()
        width = right - left
        if width <= 0:
            return

        full_width = full_xlim[1] - full_xlim[0]
        min_width = max(full_width / 10000, 1e-6)

        if event.button == "up":
            scale = 0.8
        elif event.button == "down":
            scale = 1.25
        else:
            return

        next_width = min(max(width * scale, min_width), full_width)
        center = event.xdata if event.xdata is not None else left + width / 2
        left_fraction = (center - left) / width
        next_left = center - next_width * left_fraction
        next_right = next_left + next_width

        set_lfp_xlim(next_left, next_right)

    def handle_lfp_double_click(event) -> None:
        if event.inaxes == ax and event.dblclick:
            reset_lfp_x_zoom()
            pan_state.clear()

    def start_lfp_x_pan(event) -> None:
        if event.inaxes != ax or event.button != 1 or event.dblclick:
            return

        xdata = event_xdata(event)
        if xdata is None:
            return

        left, right = ax.get_xlim()
        pan_state["x"] = xdata
        pan_state["left"] = left
        pan_state["right"] = right

    def drag_lfp_x_pan(event) -> None:
        if not pan_state:
            return

        xdata = event_xdata(event)
        if xdata is None:
            return

        dx = xdata - pan_state["x"]
        set_lfp_xlim(pan_state["left"] - dx, pan_state["right"] - dx)

    def stop_lfp_x_pan(event) -> None:
        pan_state.clear()

    fig.canvas.mpl_connect("scroll_event", zoom_lfp_x)
    fig.canvas.mpl_connect("button_press_event", handle_lfp_double_click)
    fig.canvas.mpl_connect("button_press_event", start_lfp_x_pan)
    fig.canvas.mpl_connect("motion_notify_event", drag_lfp_x_pan)
    fig.canvas.mpl_connect("button_release_event", stop_lfp_x_pan)

    def set_lfp_channel(channel: int) -> None:
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
        nonlocal show_filtered
        show_filtered = bool(filtered)
        for (item_channel, item_filtered), line in lines.items():
            line.set_visible(
                item_channel == selected_channel and item_filtered == show_filtered
            )
        label_settings = signal_func.LfpFilterSettings(
            show_filtered=show_filtered,
            bandpass_enabled=bool(filter_settings and filter_settings.bandpass_enabled),
            bandpass_low_hz=(filter_settings.bandpass_low_hz if filter_settings else 1.0),
            bandpass_high_hz=(filter_settings.bandpass_high_hz if filter_settings else 100.0),
            line_noise_hz=(filter_settings.line_noise_hz if filter_settings else None),
            notch_quality=(filter_settings.notch_quality if filter_settings else 30.0),
        )
        filter_label.set_text(signal_func.filter_description(label_settings))
        ax.relim(visible_only=True)
        ax.autoscale_view(scalex=False, scaley=True)
        fig.canvas.draw_idle()

    set_lfp_channel(selected_channel)

    fig.set_lfp_channel = set_lfp_channel
    fig.set_lfp_signal_view = set_lfp_signal_view
    fig.set_lfp_xlim = set_lfp_xlim
    fig.reset_lfp_x_zoom = reset_lfp_x_zoom
    fig.add_lfp_xlim_callback = add_lfp_xlim_callback
    fig.lfp_full_xlim = full_xlim
    fig.lfp_lines = lines
    fig.lfp_channel_numbers = channel_numbers
    fig.lfp_plot_step = plot_step

    return fig


def format_signal_label(unit):
    return f"Signal ({unit})" if unit else "Signal"
