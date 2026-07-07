import sys
from pathlib import Path
from pathlib import Path as PathlibPath

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

sys.path.insert(0, str(PathlibPath(__file__).parent.parent))

import check_function as check
import read_function as read


def accelerator(
    info: dict | None = None,
    compact: bool = False,
) -> Figure:
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

    # Reuse the import metadata so check.check() does not need to parse the
    # file header again to find the path and sample rate.
    check.check(info=info)

    channel_name = "channel_260"
    if channel_name not in data:
        raise ValueError("3-axis CSV must include channel 260")

    fig, ax = plt.subplots(
        figsize=(8, 2.2) if compact else (16, 4),
        constrained_layout=compact,
    )

    # Convert microseconds to seconds for plotting.
    data["time_s"] = data["time_us"] / 1e6

    label = None if compact else "Channel 260"
    ax.plot(data["time_s"], data[channel_name], label=label, linewidth=0.2)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Signal")

    ax.grid(True, linewidth=0.4, alpha=0.35)
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
