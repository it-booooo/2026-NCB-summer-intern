# pyright: reportUnknownMemberType=false

from pathlib import Path

import matplotlib.pyplot as plt

from read_function import read_accelerator


def draw_accelerator(file_path: str | Path) -> None:
    data = read_accelerator(file_path)

    # 微秒轉換成秒
    data["time_s"] = data["time_us"] / 1e6

    plt.plot(
        data["time_s"],
        data["channel_260"],
        label="Channel 260",
        linewidth=0.8,
    )

    plt.title("Accelerator Signal Waveform")
    plt.xlabel("Time (s)")
    plt.ylabel("Signal Value")

    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()