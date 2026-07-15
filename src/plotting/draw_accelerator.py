from pathlib import Path
from typing import Callable, cast

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from ..data_io import csv_loader as csv_func
from ..data_io import readers as read
from .plot_utils import format_signal_label, install_x_navigation, resolve_plot_step


class AcceleratorFigure(Figure):
    set_axis_xlim: Callable[[float, float], None]
    reset_axis_x_zoom: Callable[[], None]
    add_axis_xlim_callback: Callable[[Callable[[tuple[float, float]], None]], None]
    axis_full_xlim: tuple[float, float]
    axis_plot_step: int


def accelerator(
    info: dict | None = None,
    compact: bool = False,
    step: int | None = None,
) -> AcceleratorFigure:
    """Read accelerator data and draw waveform.

    Args:
        info: CSV metadata returned by data_io.parse_lfp_csv_info().
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

    data = read.read_signal_csv(str(input_file), requested_channels=[260])
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
        ax = fig.add_axes((0.08, 0.24, 0.90, 0.68))
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
    fig.text(
        0.055,
        0.91,
        y_label,
        fontsize=7,
        ha="right",
        va="top",
    )
    fig.text(
        0.055,
        0.07,
        f"Time ({units['time_unit']})",
        fontsize=7,
        ha="right",
        va="bottom",
    )
    ax.tick_params(axis="both", labelsize=7, pad=1)

    ax.grid(True, linewidth=0.4, alpha=0.35)
    full_xlim = (float(data["time_s"].iloc[0]), float(data["time_s"].iloc[-1]))
    if full_xlim[0] == full_xlim[1]:
        full_xlim = (full_xlim[0] - 0.5, full_xlim[1] + 0.5)

    navigation = install_x_navigation(fig, ax, full_xlim)

    fig.set_axis_xlim = navigation.set_xlim
    fig.reset_axis_x_zoom = navigation.reset_x_zoom
    fig.add_axis_xlim_callback = navigation.add_xlim_callback
    fig.axis_full_xlim = full_xlim
    fig.axis_plot_step = plot_step

    if not compact:
        ax.set_title("3-axis Vector Magnitude - Channel 260")
        ax.legend()

    return fig
