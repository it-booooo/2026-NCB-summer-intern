import sys
from pathlib import Path
from pathlib import Path as PathlibPath

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.widgets import CheckButtons

sys.path.insert(0, str(PathlibPath(__file__).parent.parent))

import check_function as check
import read_function as read


def LFP(
    channels: int | list[int] | tuple[int, ...] | None = 1,
    step: int = 100,
    file_path: str | Path | None = None,
) -> Figure:
    """Read/check LFP data, draw waveform, and save the output image.

    Args:
        channels: Initial visible channel or channels. Default is 1. Use None to show all 16 channels.
        step: Downsampling interval for plotting. Use 0 to plot all points. Default is 100.
        file_path: Base directory containing input CSV files. Defaults to input_data.

    Returns:
        Generated Matplotlib figure object.
    """
    if file_path is None:
        file_path = Path(__file__).parent.parent / "input_data"
    else:
        file_path = Path(file_path)

    output_dir = Path(__file__).parent.parent / "output_data"
    output_dir.mkdir(parents=True, exist_ok=True)

    input_file = file_path / "LFP.csv"
    data = read.LFP(str(input_file))
    check.check(str(input_file))

    fig = plt.figure(figsize=(16, 5),constrained_layout=True)
    grid = fig.add_gridspec(1, 3, width_ratios=(7, 1, 1.35))
    ax = fig.add_subplot(grid[0, 0])
    check_ax = fig.add_subplot(grid[0, 1])
    legend_ax = fig.add_subplot(grid[0, 2])

    # Convert microseconds to seconds for plotting.
    data["time_s"] = data["time_us"] / 1e6
    if step == 0:
        x = data["time_s"]
        plot_data = data
    else:
        x = data["time_s"][::step]
        plot_data = data.iloc[::step]

    channel_numbers = list(range(1, 17))
    if channels is None:
        initial_channels = set(channel_numbers)
    elif isinstance(channels, int):
        initial_channels = {channels}
    else:
        initial_channels = set(channels)

    invalid_channels = sorted(initial_channels - set(channel_numbers))
    if invalid_channels:
        raise ValueError(f"LFP channels must be between 1 and 16: {invalid_channels}")

    lines = {}
    for channel in channel_numbers:
        line = ax.plot(
            x,
            plot_data[f"channel_{channel}"],
            label=f"Channel {channel}",
            linewidth=0.5,
            visible=channel in initial_channels,
        )[0]
        lines[str(channel)] = line

    ax.set_title("LFP Signal Waveform")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Signal Value")
    ax.grid()

    ax.relim(visible_only=True)
    ax.autoscale_view()

    labels = [str(channel) for channel in channel_numbers]
    visibility = [channel in initial_channels for channel in channel_numbers]
    channel_selector = CheckButtons(check_ax, labels, visibility)
    check_ax.set_title("Channels")
    check_ax.set_anchor("N")

    for channel, label in zip(channel_numbers, channel_selector.labels):
        label.set_color(lines[str(channel)].get_color())

    legend_ax.axis("off")

    def refresh_legend() -> None:
        legend_ax.clear()
        legend_ax.axis("off")
        visible_channels = [
            channel for channel in channel_numbers if lines[str(channel)].get_visible()
        ]
        if not visible_channels:
            fig.canvas.draw_idle()
            return

        legend_handles = [
            Line2D(
                [0],
                [0],
                color=lines[str(channel)].get_color(),
                linewidth=1.2,
                label=f"Channel {channel}",
            )
            for channel in visible_channels
        ]
        legend_ax.legend(
            handles=legend_handles,
            loc="upper left",
            frameon=True,
            borderaxespad=0,
        )

    refresh_legend()

    def update_channel(label: str | None) -> None:
        if label is None:
            return

        line = lines[label]
        line.set_visible(not line.get_visible())
        if any(item.get_visible() for item in lines.values()):
            ax.relim(visible_only=True)
            ax.autoscale_view()
        refresh_legend()
        fig.canvas.draw_idle()

    channel_selector.on_clicked(update_channel)
    setattr(fig, "channel_selector", channel_selector)

    output_fig, output_ax = plt.subplots(figsize=(16, 5), constrained_layout=True)
    for channel in channel_numbers:
        if channel not in initial_channels:
            continue

        output_ax.plot(
            x,
            plot_data[f"channel_{channel}"],
            label=f"Channel {channel}",
            linewidth=0.5,
            color=lines[str(channel)].get_color(),
        )

    output_ax.set_title("LFP Signal Waveform")
    output_ax.set_xlabel("Time (s)")
    output_ax.set_ylabel("Signal Value")
    output_ax.grid()
    output_ax.legend()
    output_fig.savefig(
        str(output_dir / "LFP_output.png"),
        dpi=300,
    )
    plt.close(output_fig)
    return fig
