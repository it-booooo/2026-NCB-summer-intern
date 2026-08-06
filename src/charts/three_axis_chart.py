from collections.abc import Callable
from pathlib import Path

from matplotlib.figure import Figure

from ..signal_data import SignalDataset
from .chart_helpers import format_signal_label, install_x_navigation, resolve_plot_step


class ThreeAxisFigure(Figure):
    set_three_axis_xlim: Callable[[float, float], None]
    reset_three_axis_x_zoom: Callable[[], None]
    add_three_axis_xlim_callback: Callable[[Callable[[tuple[float, float]], None]], None]
    three_axis_full_xlim: tuple[float, float]
    three_axis_plot_step: int


def create_three_axis_figure(
    info: dict | None = None,
    dataset: SignalDataset | None = None,
    compact: bool = False,
    step: int | None = None,
) -> ThreeAxisFigure:
    """Read three-axis sensor data and draw its waveform.

    Args:
        info: CSV metadata returned by parse_signal_csv_info().
            Required keys:
            - path: CSV file path selected from the GUI import action.
            - sample_rates: Sample rate values used when exporting check results.
            Optional keys such as filename, channels, and channel_count are
            kept with the same structure as LFP imports.
        dataset: Prepared shared dataset. When provided, its metadata is
            authoritative and ``info`` is ignored.
        compact: Draw only the axes and waveform for embedding in the main GUI.
        step: Plot every nth sample. Use None for automatic step or 0 to draw every sample.

    Returns:
        Generated Matplotlib figure object.
    """
    if dataset is None:
        if info is None:
            raise ValueError("Please import a 3-axis CSV file first.")
        dataset = SignalDataset.from_csv(info)
    info = dataset.info

    file_path = info.get("path")
    if file_path is None:
        raise ValueError("3-axis path not found in info dictionary.")

    input_file = Path(file_path)
    if not input_file.is_file():
        raise FileNotFoundError(f"3-axis CSV file not found: {input_file}")

    overview = dataset.overview(260)

    fig = ThreeAxisFigure(
        figsize=(8, 2.2) if compact else (16, 4),
        constrained_layout=False,
    )
    if compact:
        ax = fig.add_axes((0.08, 0.24, 0.90, 0.68))
    else:
        ax = fig.add_subplot(111)

    # Convert microseconds to seconds for charts.
    time_s = overview.time_us / 1e6
    values = overview.values
    plot_step = resolve_plot_step(len(values), step)
    if plot_step == 0 or len(values) <= plot_step:
        plot_index = slice(None)
    else:
        plot_index = slice(None, None, plot_step)

    label = None if compact else "Channel 260"
    ax.plot(
        time_s[plot_index],
        values[plot_index],
        label=label,
        linewidth=0.2,
    )

    y_label = format_signal_label(info["value_unit"])
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
        f"Time ({info['time_unit']})",
        fontsize=7,
        ha="right",
        va="bottom",
    )
    ax.tick_params(axis="both", labelsize=7, pad=1)

    ax.grid(True, linewidth=0.4, alpha=0.35)
    full_xlim = dataset.record_bounds_s(260)
    if full_xlim[0] == full_xlim[1]:
        full_xlim = (full_xlim[0] - 0.5, full_xlim[1] + 0.5)

    navigation = install_x_navigation(fig, ax, full_xlim)

    fig.set_three_axis_xlim = navigation.set_xlim
    fig.reset_three_axis_x_zoom = navigation.reset_x_zoom
    fig.add_three_axis_xlim_callback = navigation.add_xlim_callback
    fig.three_axis_full_xlim = full_xlim
    fig.three_axis_plot_step = plot_step

    if not compact:
        ax.set_title("3-axis Vector Magnitude - Channel 260")
        ax.legend()

    return fig
