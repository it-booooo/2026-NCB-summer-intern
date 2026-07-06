import sys
from pathlib import Path
from pathlib import Path as PathlibPath

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

sys.path.insert(0, str(PathlibPath(__file__).parent.parent))

import check_function as check
import read_function as read


def LFP(file_path: str | Path | None = None, step: int = 100) -> Figure:
    """
    default step = 100
    """

    if file_path is None:
        # Default to origin_data directory
        file_path = Path(__file__).parent.parent / "origin_data"
    else:
        file_path = Path(file_path)

    # Prepare output directory
    output_dir = Path(__file__).parent.parent / "output_data"
    output_dir.mkdir(parents=True, exist_ok=True)

    data = read.LFP(str(file_path / "LFP.csv"))
    check.check(str(file_path / "LFP.csv"))

    fig, ax = plt.subplots(figsize=(16, 4))

    # 微秒轉換成秒
    data["time_s"] = data["time_us"] / 1e6

    if step == 0:
        x = data["time_s"]
        y = data["channel_1"]
    else:
        x = data["time_s"][::step]
        y = data["channel_1"][::step]

    ax.plot(
        x,
        y,
        label="LFP",
        linewidth=0.5,
    )

    ax.set_title("LFP Signal Waveform")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Signal Value")

    ax.grid()
    ax.legend()
    fig.savefig(
        str(output_dir / "LFP_output.png"),
        dpi=300,
    )
    return fig
