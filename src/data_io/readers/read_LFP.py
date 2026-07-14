import pandas as pd

from .. import csv_loader as csv_func


def LFP(file_path: str) -> pd.DataFrame:
    """Read LFP CSV data and return a normalized DataFrame."""
    try:
        metadata = csv_func.parse_signal_csv_metadata(file_path)
        header_row = metadata["header_row"]
        channels = metadata["channels"]
        data_column_count = metadata["data_column_count"]

        if header_row is None:
            raise ValueError("CSV missing Time[us] header row")

        if not channels:
            if data_column_count is None or data_column_count < 2:
                raise ValueError("CSV missing channel metadata")
            channels = list(range(1, data_column_count))

        column_count = len(channels) + 1
        df = pd.read_csv(
            file_path,
            skiprows=header_row + 1,
            header=None,
            usecols=range(column_count),
            names=["time_us"] + [f"channel_{channel}" for channel in channels],
        )

        return df

    except FileNotFoundError as error:
        raise FileNotFoundError(f"fail to read file: {file_path}") from error

    except pd.errors.EmptyDataError as error:
        raise ValueError(f".csv file is empty: {file_path}") from error

    except pd.errors.ParserError as error:
        raise ValueError(f"CSV format parsing failed: {file_path}") from error
