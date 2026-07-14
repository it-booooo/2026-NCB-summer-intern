import pandas as pd

from .signal_reader import read_signal_csv


def LFP(file_path: str) -> pd.DataFrame:
    """Read LFP CSV data and return a normalized DataFrame."""
    return read_signal_csv(file_path)
