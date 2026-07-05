from pathlib import Path

from draw_function.draw_accelerator import draw_accelerator


PROJECT_ROOT = Path(__file__).resolve().parent

ACCELERATOR_CSV_PATH = (
    PROJECT_ROOT
    / "origin_data"
    / "accelerator.csv"
)


def main() -> None:
    draw_accelerator(ACCELERATOR_CSV_PATH)


if __name__ == "__main__":
    main()