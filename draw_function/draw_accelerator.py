import sys
from pathlib import Path
from pathlib import Path as PathlibPath

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

sys.path.insert(0, str(PathlibPath(__file__).parent.parent))

import check_function as check
import read_function as read


def accelerator(
    file_path: str | Path | None = None,
    compact: bool = False,
) -> Figure:
    """Read/check accelerator data, draw waveform, and save the output image.

    Args:
        file_path: CSV file selected from the GUI import action.
        compact: Draw only the axes and waveform for embedding in the main GUI.

    Returns:
        Generated Matplotlib figure object.
    """
    if file_path is None:
        raise ValueError("Please import a 3-axis CSV file first.")

    input_file = Path(file_path)
    if not input_file.is_file():
        raise FileNotFoundError(f"3-axis CSV file not found: {input_file}")

    data = read.accelerator(str(input_file))
    check.check(str(input_file))

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
