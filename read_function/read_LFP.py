import pandas as pd


def LFP(file_path: str) -> pd.DataFrame:
    """Read LFP CSV data and return a normalized DataFrame."""
    try:
        df = pd.read_csv(
            file_path,
            skiprows=5,
            header=None,
            usecols=range(17),
            names=["time_us"] + [f"channel_{i}" for i in range(1, 17)],
        )

        return df

    except FileNotFoundError as error:
        raise FileNotFoundError(f"fail to read file：{file_path}") from error

    except pd.errors.EmptyDataError as error:
        raise ValueError(f".csv file is empty：{file_path}") from error

    except pd.errors.ParserError as error:
        raise ValueError(f"CSV format parsing failed：{file_path}") from error
