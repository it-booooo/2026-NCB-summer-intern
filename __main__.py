from pathlib import Path

import matplotlib.pyplot as plt

import draw_function as draw

PROJECT_ROOT = Path(__file__).resolve().parent

ORIGIN_DATA_DIR = PROJECT_ROOT / "origin_data"


def main() -> None:
    draw.accelerator(ORIGIN_DATA_DIR)
    draw.LFP(ORIGIN_DATA_DIR)
    plt.show()


if __name__ == "__main__":
    main()
