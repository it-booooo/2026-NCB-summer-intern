import pandas as pd

def accelerator(file_path: str)-> pd.DataFrame:
    """
    Reads an accelerator data file and returns a pandas DataFrame.

    Parameters:
    file_path (str): The path to the accelerator data file.

    Returns:
    pd.DataFrame: A DataFrame containing the data from the CSV file.
    """
    try:
        df = pd.read_csv(
        file_path,
        skiprows=5,
        header=None,
        usecols=[0, 1, 2, 3, 4],
        names=[
            "time_us",
            "channel_257",
            "channel_258",
            "channel_259",
            "channel_260",
        ],
        )
        return df
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"找不到檔案：{file_path}"
        ) from error

    except pd.errors.EmptyDataError as error:
        raise ValueError(
            f"CSV 檔案是空的：{file_path}"
        ) from error

    except pd.errors.ParserError as error:
        raise ValueError(
            f"CSV 格式解析失敗：{file_path}"
        ) from error