import pandas as pd

sample_rate = None
start_index = None


def check(file_path: str):

    # 直接讀取文件來找到 Sample Rate（避免 pandas 解析元數據行時出錯）
    sample_rate = None
    with open(file_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            if "Sample Rate (per channel)" in line:
                # 從這一行提取 sample rate 值
                parts = line.strip().split(",")
                for i, part in enumerate(parts):
                    if part.strip() == "Sample Rate (per channel)" and i + 1 < len(
                        parts
                    ):
                        try:
                            sample_rate = float(parts[i + 1])
                        except ValueError:
                            sample_rate = float(parts[i + 2])
                break

    # 現在讀取實際資料（跳過前 5 行元數據）
    df = pd.read_csv(file_path, skiprows=5, header=None)
    start_index = 0

    if sample_rate is None:
        raise ValueError("Sample Rate not found in the file.")
    expected_interval = 1_000_000 / sample_rate

    print(f"Sample rate: {sample_rate} Hz")
    print(f"Expected time interval: {expected_interval} us")
    print(f"file path: {file_path}")

    previous_time: int | None = None
    seen_times: set[int] = set()

    for row_num in range(start_index, len(df)):
        current_time_value = pd.to_numeric(
            df.iloc[row_num, 0],
            errors="coerce",
        )

        # 檢查時間缺值或不是數字
        if pd.isna(current_time_value):
            print(f"Row {row_num}: Missing or invalid time format")
            continue

        current_time = int(current_time_value)

        # 檢查重複時間
        if current_time in seen_times:
            print(f"Row {row_num}: Duplicate time {current_time} us")

        seen_times.add(current_time)

        # 檢查時間連續性
        if previous_time is not None:
            interval = current_time - previous_time

            if interval != expected_interval:
                print(
                    f"Row {row_num}: Time discontinuity detected, "
                    f"{previous_time} → {current_time} us, "
                    f"actual interval {interval} us, "
                    f"expected interval {expected_interval} us"
                )

        previous_time = current_time
