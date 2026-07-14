import sys
from pathlib import Path
from typing import Callable, cast

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

sys.path.insert(0, str(Path(__file__).parent.parent))

import read_function as read
import csv_function as csv_func
from .plot_utils import format_signal_label, install_x_navigation, resolve_plot_step


class LfpFigure(Figure):
    set_lfp_channel: Callable[[int], None]
    set_lfp_xlim: Callable[[float, float], None]
    reset_lfp_x_zoom: Callable[[], None]
    add_lfp_xlim_callback: Callable[[Callable[[tuple[float, float]], None]], None]
    lfp_full_xlim: tuple[float, float]
    lfp_lines: dict[int, Line2D]
    lfp_channel_numbers: list[int]
    lfp_plot_step: int


def LFP(
    channels: int | list[int] | tuple[int, ...] | None = 1,
    step: int | None = None,
    info: dict | None = None,
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

    data["time_s"] = data["time_us"] / 1e6

    plot_step = resolve_plot_step(len(data), step)
    if plot_step == 0 or len(data) <= plot_step:
        plot_data = data
    else:
        plot_data = data.iloc[::plot_step]
    x = plot_data["time_s"]

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

    lines: dict[int, Line2D] = {}

    for channel in channel_numbers:
        line = ax.plot(
            x,
            plot_data[f"channel_{channel}"],
            linewidth=0.5,
            color="blue",
            visible=(channel == selected_channel),
        )[0]
        lines[channel] = line
    
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
    ax.text(
        -0.012,
        -0.23,
        "Time (s)",
        fontsize=7,
        ha="right",
        va="top",
        transform=ax.transAxes,
        clip_on=False,
    )
    ax.grid(True, linewidth=0.4, alpha=0.35)
    ax.tick_params(axis="both", labelsize=7, pad=1)

    full_xlim = (float(data["time_s"].iloc[0]), float(data["time_s"].iloc[-1]))
    if full_xlim[0] == full_xlim[1]:
        full_xlim = (full_xlim[0] - 0.5, full_xlim[1] + 0.5)

    navigation = install_x_navigation(fig, ax, full_xlim)

    def set_lfp_channel(channel: int) -> None:
        nonlocal selected_channel

        channel = int(channel)

        if channel not in channel_numbers:
            raise ValueError(f"Invalid LFP channel: {channel}")

        selected_channel = channel

        for item_channel, line in lines.items():
            line.set_visible(item_channel == selected_channel)

        ax.relim(visible_only=True)
        ax.autoscale_view(scalex=False, scaley=True)
        fig.canvas.draw_idle()

    set_lfp_channel(selected_channel)

    fig.set_lfp_channel = set_lfp_channel
    fig.set_lfp_xlim = navigation.set_xlim
    fig.reset_lfp_x_zoom = navigation.reset_x_zoom
    fig.add_lfp_xlim_callback = navigation.add_xlim_callback
    fig.lfp_full_xlim = full_xlim
    fig.lfp_lines = lines
    fig.lfp_channel_numbers = channel_numbers
    fig.lfp_plot_step = plot_step

    return fig
