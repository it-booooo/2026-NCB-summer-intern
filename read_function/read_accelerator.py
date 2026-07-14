import pandas as pd

from .signal_reader import read_signal_csv


def accelerator(file_path: str, channel: int = 260) -> pd.DataFrame:
    """Read accelerator CSV data and return a normalized DataFrame."""
    return read_signal_csv(file_path, requested_channels=[channel])
