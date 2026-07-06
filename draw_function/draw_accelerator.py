import sys
from pathlib import Path
from pathlib import Path as PathlibPath

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

sys.path.insert(0, str(PathlibPath(__file__).parent.parent))

import check_function as check
import read_function as read


def accelerator(file_path: str | Path | None = None) -> Figure:
    """Read/check accelerator data, draw waveform, and save the output image.

    Args:
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

    input_file = file_path / "accelerator.csv"
    data = read.accelerator(str(input_file))
    check.check(str(input_file))

    fig, ax = plt.subplots(figsize=(16, 4))

    # Convert microseconds to seconds for plotting.
    data["time_s"] = data["time_us"] / 1e6

    ax.plot(
        data["time_s"],
        data["channel_260"],
        label="acceleration",
        linewidth=0.2,
    )

    ax.set_title("Accelerator Signal Waveform")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Signal Value")

    ax.grid()
    ax.legend()
    fig.savefig(
        str(output_dir / "acceleration_output.png"),
        dpi=300,
    )
    return fig
