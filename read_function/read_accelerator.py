import pandas as pd


def accelerator(file_path: str) -> pd.DataFrame:
    """Read accelerator CSV data and return a normalized DataFrame."""
    try:
        df = pd.read_csv(
            file_path,
            skiprows=5,
            header=None,
            usecols=[0, 4],
            names=[
                "time_us",
                "channel_260",
            ],
        )
        return df
    except FileNotFoundError as error:
        raise FileNotFoundError(f"fail to read file：{file_path}") from error

    except pd.errors.EmptyDataError as error:
        raise ValueError(f".csv file is empty：{file_path}") from error

    except pd.errors.ParserError as error:
        raise ValueError(f"CSV format parsing failed：{file_path}") from error
