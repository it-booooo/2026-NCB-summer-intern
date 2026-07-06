from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

import read_function as read
import check_function as check


def LFP(file_path: str | Path, step: int = 100) -> Figure:
    """
    default step = 100
    """

    file_path = Path(file_path)
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
        str(file_path / "LFP_output.png"),
        dpi=300,
    )
    return fig
