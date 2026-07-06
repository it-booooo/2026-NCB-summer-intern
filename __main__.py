from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

import draw_function as draw

PROJECT_ROOT = Path(__file__).resolve().parent

ORIGIN_DATA_DIR = PROJECT_ROOT / "origin_data"


def main() -> None:
    acceleration_fig: Figure = draw.accelerator(ORIGIN_DATA_DIR)
    lfp_fig: Figure = draw.LFP(ORIGIN_DATA_DIR)
    acceleration_fig.savefig(
        str(ORIGIN_DATA_DIR / "acceleration_output.png"),
        dpi=300,
    )

    lfp_fig.savefig(
        str(ORIGIN_DATA_DIR / "LFP_output.png"),
        dpi=300,
    )
    plt.show()


if __name__ == "__main__":
    main()
