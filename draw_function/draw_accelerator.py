import sys
from pathlib import Path
from pathlib import Path as PathlibPath
from typing import Callable, cast

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

sys.path.insert(0, str(PathlibPath(__file__).parent.parent))

import check_function as check
import csv_function as csv_func
import read_function as read


class AcceleratorFigure(Figure):
    set_axis_xlim: Callable[[float, float], None]
    reset_axis_x_zoom: Callable[[], None]
    add_axis_xlim_callback: Callable[[Callable[[tuple[float, float]], None]], None]
    axis_full_xlim: tuple[float, float]


def accelerator(
    info: dict | None = None,
    compact: bool = False,
) -> AcceleratorFigure:
    """Read/check accelerator data, draw waveform, and save the output image.

    Args:
        info: CSV metadata returned by csv_function.parse_lfp_csv_info().
            Required keys:
            - path: CSV file path selected from the GUI import action.
            - sample_rates: Sample rate values used by check.check().
            Optional keys such as filename, channels, and channel_count are
            kept with the same structure as LFP imports.
        compact: Draw only the axes and waveform for embedding in the main GUI.

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
    check.check(info=info)
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
        ax = fig.add_axes((0.06, 0.22, 0.92, 0.68))
    else:
        ax = fig.add_subplot(111)

    # Convert microseconds to seconds for plotting.
    data["time_s"] = data["time_us"] / 1e6

    label = None if compact else "Channel 260"
    ax.plot(data["time_s"], data[channel_name], label=label, linewidth=0.2)

    y_label = format_signal_label(units["value_unit"])
    if not compact:
        ax.set_xlabel(f"Time ({units['time_unit']})", fontsize=8, labelpad=2)
    ax.set_ylabel(y_label, fontsize=8, rotation=0, labelpad=18)
    ax.yaxis.set_label_coords(-0.04, 1.02)
    ax.tick_params(axis="both", labelsize=8, pad=1)

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

    if compact:
        return fig

    output_dir = Path(__file__).parent.parent / "output_data"
    output_dir.mkdir(parents=True, exist_ok=True)

    ax.set_title("3-axis Vector Magnitude - Channel 260")
    ax.legend()
    fig.savefig(
        str(output_dir / "acceleration_output.png"),
        dpi=300,
    )
    return fig


def format_signal_label(unit):
    return f"Signal ({unit})" if unit else "Signal"
