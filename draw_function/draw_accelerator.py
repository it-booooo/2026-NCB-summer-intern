# pyright: reportUnknownMemberType=false

from pathlib import Path

import matplotlib.pyplot as plt

import read_function as read


def accelerator(file_path: str | Path) -> None:
    data = read.accelerator(str(file_path))

    # 微秒轉換成分鐘
    data["time_min"] = data["time_us"] / 1e6/60

    plt.plot(
        data["time_min"],
        data["channel_260"],
        label="acceleration",
        linewidth=0.8,
    )

    plt.title("Accelerator Signal Waveform")
    plt.xlabel("Time (min)")
    plt.ylabel("Signal Value")

    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()