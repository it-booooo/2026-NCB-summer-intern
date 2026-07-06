from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

import check_function as check
import read_function as read


def accelerator(file_path: str | Path) -> Figure:
    file_path = Path(file_path)
    data = read.accelerator(str(file_path / "accelerator.csv"))
    check.check(str(file_path / "accelerator.csv"))

    fig, ax = plt.subplots(figsize=(16, 4))

    # 微秒轉換成秒
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
        str(file_path / "acceleration_output.png"),
        dpi=300,
    )
    return fig
