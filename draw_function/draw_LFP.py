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
    set_lfp_xlim: Callable[[float, float], None]
    reset_lfp_x_zoom: Callable[[], None]
    add_lfp_xlim_callback: Callable[[Callable[[tuple[float, float]], None]], None]
    lfp_full_xlim: tuple[float, float]
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
            constrained_layout=False,
            FigureClass=LfpFigure,
        ),
    )
    ax = fig.add_axes((0.06, 0.18, 0.92, 0.74))

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
    
    ax.set_ylabel("Signal Value")
    ax.grid(True)
    ax.tick_params(axis="both", labelsize=8, pad=2)

    full_xlim = (float(x.iloc[0]), float(x.iloc[-1]))
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

        for item_channel, line in lines.items():
            line.set_visible(item_channel == selected_channel)

        ax.relim(visible_only=True)
        ax.autoscale_view(scalex=False, scaley=True)
        fig.canvas.draw_idle()

    set_lfp_channel(selected_channel)

    fig.set_lfp_channel = set_lfp_channel
    fig.set_lfp_xlim = set_lfp_xlim
    fig.reset_lfp_x_zoom = reset_lfp_x_zoom
    fig.add_lfp_xlim_callback = add_lfp_xlim_callback
    fig.lfp_full_xlim = full_xlim
    fig.lfp_lines = lines
    fig.lfp_channel_numbers = channel_numbers

    return fig


def format_signal_label(unit):
    return f"Signal ({unit})" if unit else "Signal"
