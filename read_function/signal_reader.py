import pandas as pd

import csv_function as csv_func


def read_signal_csv(file_path: str, requested_channels=None) -> pd.DataFrame:
    """Read normalized signal columns while preserving the project CSV format."""
    try:
        metadata = csv_func.parse_signal_csv_metadata(file_path)
        header_row = metadata["header_row"]
        available_channels = metadata["channels"]
        data_column_count = metadata["data_column_count"]

        if header_row is None:
            raise ValueError("CSV missing Time[us] header row")

        if requested_channels is None:
            selected_channels = list(available_channels)
            if not selected_channels:
                if data_column_count is None or data_column_count < 2:
                    raise ValueError("CSV missing channel metadata")
                selected_channels = list(range(1, data_column_count))
            usecols = list(range(len(selected_channels) + 1))
        else:
            selected_channels = [int(channel) for channel in requested_channels]
            for channel in selected_channels:
                if channel not in available_channels:
                    raise ValueError(f"CSV does not include channel {channel}")
            usecols = [0] + [
                available_channels.index(channel) + 1
                for channel in selected_channels
            ]

        return pd.read_csv(
            file_path,
            skiprows=header_row + 1,
            header=None,
            usecols=usecols,
            names=["time_us"]
            + [f"channel_{channel}" for channel in selected_channels],
        )
    except FileNotFoundError as error:
        raise FileNotFoundError(f"fail to read file: {file_path}") from error
    except pd.errors.EmptyDataError as error:
        raise ValueError(f".csv file is empty: {file_path}") from error
    except pd.errors.ParserError as error:
        raise ValueError(f"CSV format parsing failed: {file_path}") from error
