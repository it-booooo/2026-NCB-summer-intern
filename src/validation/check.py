import csv
from pathlib import Path

import pandas as pd


def check(info: dict, output_path: str | Path | None = None) -> Path:
    """Validate CSV timestamps/data integrity and output a check report CSV."""
    path = info.get("path")
    if not path:
        raise ValueError("Path not provided in info dict")

    file_path = Path(path)
    output_file = default_output_path(file_path) if output_path is None else Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    sample_rate = first_sample_rate(info)
    header_row, data_column_count = find_data_header(file_path)
    df = pd.read_csv(
        file_path,
        skiprows=header_row,
        header=0,
        usecols=range(data_column_count),
        low_memory=False,
    )

    expected_interval = round(1_000_000 / sample_rate)
    times = pd.to_numeric(df.iloc[:, 0], errors="coerce")
    missing_count = int(df.isna().sum().sum())
    intervals = times.diff()

    duplicate_timestamp_mask = intervals.notna() & (intervals == 0)
    discontinuous_mask = (
        intervals.notna() & (intervals != 0) & (intervals != expected_interval)
    )

    results = [
        {"Type": "Summary", "File": str(file_path), "Value": ""},
        {"Type": "Sample rate", "File": "", "Value": f"{sample_rate} Hz"},
        {
            "Type": "Expected interval",
            "File": "",
            "Value": f"{expected_interval} us",
        },
        {"Type": "Missing values", "File": "", "Value": str(missing_count)},
        {
            "Type": "Duplicate timestamps",
            "File": "",
            "Value": str(int(duplicate_timestamp_mask.sum())),
        },
        {
            "Type": "Discontinuous timestamps",
            "File": "",
            "Value": str(int(discontinuous_mask.sum())),
        },
    ]

    channels = [int(channel) for channel in info.get("channels", [])]
    for row_index, column_index in zip(*df.isna().to_numpy().nonzero()):
        csv_line = header_row + 2 + row_index
        time_value = times.iloc[row_index]
        time_text = "missing" if pd.isna(time_value) else f"{int(time_value)} us"
        channel_text = channel_label(column_index, channels, df.columns[column_index])

        results.append(
            {
                "Type": "Missing value",
                "File": f"line {csv_line}",
                "Value": f"time={time_text}, channel={channel_text}",
            }
        )

    anomaly_mask = duplicate_timestamp_mask | discontinuous_mask
    for current_index, has_anomaly in enumerate(anomaly_mask.to_numpy()):
        if not has_anomaly:
            continue

        previous_value = times.iloc[current_index - 1]
        current_value = times.iloc[current_index]
        if pd.isna(previous_value) or pd.isna(current_value):
            continue

        previous_time = int(previous_value)
        current_time = int(current_value)
        actual_interval = current_time - previous_time
        csv_line = header_row + 2 + current_index
        result_type = (
            "Duplicate timestamp"
            if duplicate_timestamp_mask.iloc[current_index]
            else "Time discontinuity"
        )

        results.append(
            {
                "Type": result_type,
                "File": f"line {csv_line}",
                "Value": (
                    f"{previous_time} -> {current_time} us "
                    f"(actual: {actual_interval} us, expected: {expected_interval} us)"
                ),
            }
        )

    with output_file.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Type", "File", "Value"])
        writer.writeheader()
        writer.writerows(results)

    print(f"Report saved to: {output_file}")
    return output_file


def default_output_path(file_path: Path) -> Path:
    """Provide default output path functionality.

    Args:
        file_path: Input used by this operation.
    """
    output_dir = file_path.parent.parent / "output_data"
    return output_dir / f"{file_path.stem}_check_report.csv"


def first_sample_rate(info: dict) -> float:
    """Provide first sample rate functionality.

    Args:
        info: Metadata or state information to store or use.
    """
    sample_rate = info.get("sample_rates", [None])[0]
    if sample_rate is None:
        raise ValueError("Sample Rate not found")
    return float(sample_rate)


def channel_label(column_index: int, channels: list[int], column_name: str) -> str:
    """Provide channel label functionality.

    Args:
        column_index: Input used by this operation.
        channels: Available LFP channel identifiers.
        column_name: Input used by this operation.
    """
    if column_index == 0:
        return "Time[us]"

    channel_index = column_index - 1
    if 0 <= channel_index < len(channels):
        return str(channels[channel_index])

    return str(column_name)


def find_data_header(file_path: Path) -> tuple[int, int]:
    """Find data header.

    Args:
        file_path: Input used by this operation.
    """
    with file_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        for row_num, row in enumerate(reader):
            row_values = [value.strip() for value in row]
            if row_values and row_values[0] == "Time[us]":
                data_column_count = sum(bool(value) for value in row_values)
                return row_num, data_column_count

    raise ValueError("Time[us] header not found")
