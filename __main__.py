from pathlib import Path

import draw_function as draw


PROJECT_ROOT = Path(__file__).resolve().parent

ACCELERATOR_CSV_PATH = (
    PROJECT_ROOT
    / "origin_data"
    / "accelerator.csv"
)


def main() -> None:
    draw.accelerator(ACCELERATOR_CSV_PATH)


if __name__ == "__main__":
    main()