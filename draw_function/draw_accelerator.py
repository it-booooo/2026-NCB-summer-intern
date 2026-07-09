import sys
from pathlib import Path
from pathlib import Path as PathlibPath
from typing import Callable, cast

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

sys.path.insert(0, str(PathlibPath(__file__).parent.parent))

import csv_function as csv_func
import read_function as read


class AcceleratorFigure(Figure):
    set_axis_xlim: Callable[[float, float], None]
    reset_axis_x_zoom: Callable[[], None]
    add_axis_xlim_callback: Callable[[Callable[[tuple[float, float]], None]], None]
    axis_full_xlim: tuple[float, float]
    axis_plot_step: int


TARGET_PLOT_POINTS = 5000


def resolve_plot_step(data_length: int, step: int | None) -> int:
    if step is None:
        return max(data_length // TARGET_PLOT_POINTS, 1)
    return max(int(step), 0)


def accelerator(
    info: dict | None = None,
    compact: bool = False,
    step: int | None = None,
) -> AcceleratorFigure:
    """Read accelerator data and draw waveform.

    Args:
        info: CSV metadata returned by csv_function.parse_lfp_csv_info().
            Required keys:
            - path: CSV file path selected from the GUI import action.
            - sample_rates: Sample rate values used when exporting check results.
            Optional keys such as filename, channels, and channel_count are
            kept with the same structure as LFP imports.
        compact: Draw only the axes and waveform for embedding in the main GUI.
        step: Plot every nth sample. Use None for automatic step or 0 to draw every sample.

    Returns:
        Generated Matplotlib figure object.
    """
    if info is None:
        raise ValueError("Please import a 3-axis CSV file first.")

    file_path = info.get("path")
    if file_path is None:
        raise ValueError("3-axis path not found in info dictionary.")

    input_file = Path(file_path)
    if not input_file.is_file():
        raise FileNotFoundError(f"3-axis CSV file not found: {input_file}")

    data = read.accelerator(str(input_file))
    units = csv_func.parse_signal_csv_units(input_file)

    channel_name = "channel_260"
    if channel_name not in data:
        raise ValueError("3-axis CSV must include channel 260")

    fig = cast(
        AcceleratorFigure,
        plt.figure(
            figsize=(8, 2.2) if compact else (16, 4),
            constrained_layout=False,
            FigureClass=AcceleratorFigure,
        ),
    )
    if compact:
        ax = fig.add_axes((0.10, 0.30, 0.88, 0.60))
    else:
        ax = fig.add_subplot(111)

    # Convert microseconds to seconds for plotting.
    data["time_s"] = data["time_us"] / 1e6
    plot_step = resolve_plot_step(len(data), step)
    if plot_step == 0 or len(data) <= plot_step:
        plot_data = data
    else:
        plot_data = data.iloc[::plot_step]

    label = None if compact else "Channel 260"
    ax.plot(
        plot_data["time_s"],
        plot_data[channel_name],
        label=label,
        linewidth=0.2,
    )

    y_label = format_signal_label(units["value_unit"])
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.text(
        -0.075,
        1.00,
        y_label,
        fontsize=7,
        ha="right",
        va="center",
        transform=ax.transAxes,
        clip_on=False,
    )
    ax.text(
        -0.075,
        -0.16,
        f"Time ({units['time_unit']})",
        fontsize=7,
        ha="right",
        va="center",
        transform=ax.transAxes,
        clip_on=False,
    )
    ax.tick_params(axis="both", labelsize=7, pad=1)

    ax.grid(True, linewidth=0.4, alpha=0.35)
    full_xlim = (float(data["time_s"].iloc[0]), float(data["time_s"].iloc[-1]))
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

    def set_axis_xlim(left: float, right: float, *, emit: bool = True) -> None:
        next_xlim = clamp_xlim(left, right)
        ax.set_xlim(next_xlim)

        if emit:
            for callback in xlim_callbacks:
                callback(next_xlim)

        fig.canvas.draw_idle()

    def reset_axis_x_zoom() -> None:
        set_axis_xlim(*full_xlim)

    def add_axis_xlim_callback(
        callback: Callable[[tuple[float, float]], None],
    ) -> None:
        xlim_callbacks.append(callback)

    def event_xdata(event) -> float | None:
        if event.xdata is not None:
            return float(event.xdata)
        if event.x is None or event.y is None:
            return None
        return float(ax.transData.inverted().transform((event.x, event.y))[0])

    def zoom_axis_x(event) -> None:
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

        set_axis_xlim(next_left, next_right)

    def handle_axis_double_click(event) -> None:
        if event.inaxes == ax and event.dblclick:
            reset_axis_x_zoom()
            pan_state.clear()

    def start_axis_x_pan(event) -> None:
        if event.inaxes != ax or event.button != 1 or event.dblclick:
            return

        xdata = event_xdata(event)
        if xdata is None:
            return

        left, right = ax.get_xlim()
        pan_state["x"] = xdata
        pan_state["left"] = left
        pan_state["right"] = right

    def drag_axis_x_pan(event) -> None:
        if not pan_state:
            return

        xdata = event_xdata(event)
        if xdata is None:
            return

        dx = xdata - pan_state["x"]
        set_axis_xlim(pan_state["left"] - dx, pan_state["right"] - dx)

    def stop_axis_x_pan(event) -> None:
        pan_state.clear()

    fig.canvas.mpl_connect("scroll_event", zoom_axis_x)
    fig.canvas.mpl_connect("button_press_event", handle_axis_double_click)
    fig.canvas.mpl_connect("button_press_event", start_axis_x_pan)
    fig.canvas.mpl_connect("motion_notify_event", drag_axis_x_pan)
    fig.canvas.mpl_connect("button_release_event", stop_axis_x_pan)

    fig.set_axis_xlim = set_axis_xlim
    fig.reset_axis_x_zoom = reset_axis_x_zoom
    fig.add_axis_xlim_callback = add_axis_xlim_callback
    fig.axis_full_xlim = full_xlim
    fig.axis_plot_step = plot_step

    if not compact:
        ax.set_title("3-axis Vector Magnitude - Channel 260")
        ax.legend()

    return fig


def format_signal_label(unit):
    return f"Signal ({unit})" if unit else "Signal"
