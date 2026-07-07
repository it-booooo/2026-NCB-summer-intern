import sys
from pathlib import Path
from typing import Callable, cast

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

sys.path.insert(0, str(Path(__file__).parent.parent))

import check_function as check
import read_function as read


class LfpFigure(Figure):
    set_lfp_channel: Callable[[int], None]
    lfp_lines: dict[int, Line2D]
    lfp_channel_numbers: list[int]


def LFP(
    channels: int | list[int] | tuple[int, ...] | None = 1,
    step: int = 100,
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
    check.check(info=info)

    data["time_s"] = data["time_us"] / 1e6

    if step == 0:
        x = data["time_s"]
        plot_data = data
    else:
        x = data["time_s"][::step]
        plot_data = data.iloc[::step]

    channel_numbers = info.get("channels") or list(range(1, 17))
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
            constrained_layout=True,
            FigureClass=LfpFigure,
        ),
    )
    ax = fig.add_subplot(111)

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
    
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Signal Value")
    ax.grid(True)

    def set_lfp_channel(channel: int) -> None:
        nonlocal selected_channel

        channel = int(channel)

        if channel not in channel_numbers:
            raise ValueError(f"Invalid LFP channel: {channel}")

        selected_channel = channel

        for item_channel, line in lines.items():
            line.set_visible(item_channel == selected_channel)

        ax.relim(visible_only=True)
        ax.autoscale_view()
        fig.canvas.draw_idle()

    set_lfp_channel(selected_channel)

    fig.set_lfp_channel = set_lfp_channel
    fig.lfp_lines = lines
    fig.lfp_channel_numbers = channel_numbers

    return fig


def format_signal_label(unit):
    return f"Signal ({unit})" if unit else "Signal"
