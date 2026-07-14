import pandas as pd

from .. import csv_loader as csv_func


def accelerator(file_path: str, channel: int = 260) -> pd.DataFrame:
    """Read accelerator CSV data and return a normalized DataFrame."""
    try:
        metadata = csv_func.parse_signal_csv_metadata(file_path)
        header_row = metadata["header_row"]
        channels = metadata["channels"]

        if header_row is None:
            raise ValueError("CSV missing Time[us] header row")

        if channel not in channels:
            raise ValueError(f"CSV does not include channel {channel}")

        value_column_index = channels.index(channel) + 1
        df = pd.read_csv(
            file_path,
            skiprows=header_row + 1,
            header=None,
            usecols=[0, value_column_index],
            names=[
                "time_us",
                f"channel_{channel}",
            ],
        )
        return df
    except FileNotFoundError as error:
        raise FileNotFoundError(f"fail to read file: {file_path}") from error

    except pd.errors.EmptyDataError as error:
        raise ValueError(f".csv file is empty: {file_path}") from error

    except pd.errors.ParserError as error:
        raise ValueError(f"CSV format parsing failed: {file_path}") from error
