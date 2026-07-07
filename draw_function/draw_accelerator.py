import sys
from pathlib import Path
from pathlib import Path as PathlibPath

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

sys.path.insert(0, str(PathlibPath(__file__).parent.parent))

import check_function as check
import read_function as read


def accelerator(file_path: str | Path | None = None, channel: int = 260) -> Figure:
    """Read/check accelerator data, draw waveform, and save the output image.

    Args:
        file_path: CSV file or base directory containing input CSV files. Defaults to input_data.
        channel: Accelerator channel to plot. Valid channels are 257, 258, 259, and 260.

    Returns:
        Generated Matplotlib figure object.
    """
    if file_path is None:
        input_file = Path(__file__).parent.parent / "input_data" / "accelerator.csv"
    else:
        file_path = Path(file_path)
        input_file = file_path if file_path.is_file() else file_path / "accelerator.csv"

    output_dir = Path(__file__).parent.parent / "output_data"
    output_dir.mkdir(parents=True, exist_ok=True)

    data = read.accelerator(str(input_file))
    check.check(str(input_file))

    channel_name = f"channel_{channel}"
    if channel_name not in data:
        raise ValueError("Accelerator channel must be one of 257, 258, 259, or 260")

    fig, ax = plt.subplots(figsize=(16, 4))

    # Convert microseconds to seconds for plotting.
    data["time_s"] = data["time_us"] / 1e6

    ax.plot(
        data["time_s"],
        data[channel_name],
        label=f"Channel {channel}",
        linewidth=0.2,
    )

    ax.set_title(f"Accelerator Signal Waveform - Channel {channel}")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Signal Value")

    ax.grid()
    ax.legend()
    fig.savefig(
        str(output_dir / "acceleration_output.png"),
        dpi=300,
    )
    return fig
