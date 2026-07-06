import csv
from pathlib import Path

import pandas as pd


def check(file_path: str | Path) -> None:
    file_path = Path(file_path)

    sample_rate: float | None = None
    header_row: int | None = None
    data_column_count: int | None = None

    # 先用 csv.reader 讀取前面的儀器資訊
    with file_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.reader(file)

        for row_num, row in enumerate(reader):
            # 去除每一格前後空白
            row_values = [value.strip() for value in row]

            if not row_values:
                continue

            # 找 Sample Rate
            if row_values[0] == "Sample Rate (per channel)":
                if len(row_values) < 2:
                    raise ValueError("Sample Rate 後面沒有數值")

                sample_rate = float(row_values[1])

            # 找真正的資料標題列
            if row_values[0] == "Time[us]":
                header_row = row_num

                # 排除最後因逗號產生的空欄位
                data_column_count = sum(bool(value) for value in row_values)
                break

    if sample_rate is None:
        raise ValueError("找不到 Sample Rate")

    if header_row is None:
        raise ValueError("找不到 Time[us]")

    if data_column_count is None:
        raise ValueError("無法判斷資料欄位數量")

    # 現在才交給 Pandas 讀取真正的資料表
    df = pd.read_csv(
        file_path,
        skiprows=header_row,
        header=0,
        usecols=range(data_column_count),
        low_memory=False,
    )

    expected_interval = round(1_000_000 / sample_rate)

    # 第一欄是時間
    times = pd.to_numeric(
        df.iloc[:, 0],
        errors="coerce",
    )

    # 檢查所有資料欄位的缺值
    missing_count = int(df.isna().sum().sum())

    # 檢查重複時間
    duplicate_mask = times.duplicated(keep=False)

    # 計算相鄰時間差
    intervals = times.diff()

    # 找出非正常時間間隔
    discontinuous_mask = intervals.notna() & (intervals != expected_interval)

    print(f"{file_path}")
    print(f"Sample rate: {sample_rate} Hz")
    print(f"Expected interval: {expected_interval} us")
    print(f"Missing values: {missing_count}")
    print(f"Duplicate timestamps: {int(duplicate_mask.sum())}")
    print(f"Discontinuous timestamps: {int(discontinuous_mask.sum())}")

    # 使用 enumerate，確保 current_index 是 int
    for current_index, is_discontinuous in enumerate(discontinuous_mask.to_numpy()):
        if not is_discontinuous:
            continue

        previous_value = times.iloc[current_index - 1]
        current_value = times.iloc[current_index]

        if pd.isna(previous_value) or pd.isna(current_value):
            continue

        previous_time = int(previous_value)
        current_time = int(current_value)

        actual_interval = current_time - previous_time

        # DataFrame 第 0 列對應
        # Time[us] 下一列，也就是實際 CSV 資料列
        csv_line = header_row + 2 + current_index

        print(
            f"line {csv_line}: "
            f"Time discontinuity, "
            f"{previous_time} → "
            f"{current_time} us, "
            f"Actual interval {actual_interval} us, "
            f"Expected interval {expected_interval} us"
        )
