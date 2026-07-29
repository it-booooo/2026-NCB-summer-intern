import csv
import os
import threading
import uuid
from pathlib import Path

import pandas as pd

from ..signal_data.source import CacheBuildCancelled


def check(
    info: dict,
    output_path: str | Path | None = None,
    *,
    cancel_event: threading.Event | None = None,
    progress_callback=None,
    chunk_rows: int = 250_000,
) -> Path:
    """Validate CSV timestamps/data integrity and output a check report CSV."""
    path = info.get("path")
    if not path:
        raise ValueError("Path not provided in info dict")

    file_path = Path(path)
    output_file = default_output_path(file_path) if output_path is None else Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    sample_rate = first_sample_rate(info)
    header_row, data_column_count = find_data_header(file_path)
    expected_interval = round(1_000_000 / sample_rate)
    fieldnames = ["Type", "File", "Value"]
    token = uuid.uuid4().hex
    detail_path = output_file.with_name(f".{output_file.name}.{token}.details.tmp")
    final_temp = output_file.with_name(f".{output_file.name}.{token}.tmp")
    missing_count = 0
    duplicate_count = 0
    discontinuous_count = 0
    row_offset = 0
    previous_time = None
    processed_bytes = 0
    source_size = max(file_path.stat().st_size, 1)
    channels = [int(channel) for channel in info.get("channels", [])]
    try:
        with detail_path.open("w", encoding="utf-8", newline="") as detail_stream:
            detail_writer = csv.DictWriter(detail_stream, fieldnames=fieldnames)
            detail_writer.writeheader()
            reader = pd.read_csv(
                file_path,
                skiprows=header_row,
                header=0,
                usecols=range(data_column_count),
                chunksize=max(int(chunk_rows), 1),
                low_memory=False,
            )
            try:
                for frame in reader:
                    _check_cancel(cancel_event)
                    times = pd.to_numeric(frame.iloc[:, 0], errors="coerce")
                    missing_mask = frame.isna()
                    missing_count += int(missing_mask.sum().sum())
                    intervals = times.diff()
                    if len(times) and previous_time is not None:
                        current = times.iloc[0]
                        if pd.notna(current) and pd.notna(previous_time):
                            intervals.iloc[0] = current - previous_time

                    duplicate_mask = intervals.notna() & (intervals == 0)
                    discontinuous_mask = (
                        intervals.notna()
                        & (intervals != 0)
                        & (intervals != expected_interval)
                    )
                    duplicate_count += int(duplicate_mask.sum())
                    discontinuous_count += int(discontinuous_mask.sum())

                    for local_row, column_index in zip(
                        *missing_mask.to_numpy().nonzero()
                    ):
                        csv_line = header_row + 2 + row_offset + local_row
                        time_value = times.iloc[local_row]
                        time_text = (
                            "missing"
                            if pd.isna(time_value)
                            else f"{int(time_value)} us"
                        )
                        detail_writer.writerow(
                            {
                                "Type": "Missing value",
                                "File": f"line {csv_line}",
                                "Value": (
                                    f"time={time_text}, channel="
                                    f"{channel_label(column_index, channels, frame.columns[column_index])}"
                                ),
                            }
                        )

                    anomaly_mask = duplicate_mask | discontinuous_mask
                    for local_row, has_anomaly in enumerate(
                        anomaly_mask.to_numpy()
                    ):
                        if not has_anomaly:
                            continue
                        current_value = times.iloc[local_row]
                        if local_row:
                            previous_value = times.iloc[local_row - 1]
                        else:
                            previous_value = previous_time
                        if pd.isna(previous_value) or pd.isna(current_value):
                            continue
                        previous_us = int(previous_value)
                        current_us = int(current_value)
                        actual_interval = current_us - previous_us
                        csv_line = header_row + 2 + row_offset + local_row
                        detail_writer.writerow(
                            {
                                "Type": (
                                    "Duplicate timestamp"
                                    if duplicate_mask.iloc[local_row]
                                    else "Time discontinuity"
                                ),
                                "File": f"line {csv_line}",
                                "Value": (
                                    f"{previous_us} -> {current_us} us "
                                    f"(actual: {actual_interval} us, "
                                    f"expected: {expected_interval} us)"
                                ),
                            }
                        )
                    if len(times):
                        previous_time = times.iloc[-1]
                    row_offset += len(frame)
                    processed_bytes += int(frame.memory_usage(deep=True).sum())
                    if progress_callback is not None:
                        progress_callback(
                            min(0.95, processed_bytes / source_size)
                        )
            finally:
                reader.close()
            detail_stream.flush()
            os.fsync(detail_stream.fileno())

        _check_cancel(cancel_event)
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
            "Value": str(duplicate_count),
        },
        {
            "Type": "Discontinuous timestamps",
            "File": "",
            "Value": str(discontinuous_count),
        },
        ]
        with (
            final_temp.open("w", encoding="utf-8-sig", newline="") as output,
            detail_path.open("r", encoding="utf-8", newline="") as details,
        ):
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
            writer.writerows(csv.DictReader(details))
            output.flush()
            os.fsync(output.fileno())
        _check_cancel(cancel_event)
        os.replace(final_temp, output_file)
        if progress_callback is not None:
            progress_callback(1.0)
        return output_file
    finally:
        detail_path.unlink(missing_ok=True)
        final_temp.unlink(missing_ok=True)


def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise CacheBuildCancelled("Data validation was cancelled.")


def default_output_path(file_path: Path) -> Path:
    output_dir = file_path.parent.parent / "output_data"
    return output_dir / f"{file_path.stem}_check_report.csv"


def first_sample_rate(info: dict) -> float:
    sample_rate = info.get("sample_rates", [None])[0]
    if sample_rate is None:
        raise ValueError("Sample Rate not found")
    return float(sample_rate)


def channel_label(column_index: int, channels: list[int], column_name: str) -> str:
    if column_index == 0:
        return "Time[us]"

    channel_index = column_index - 1
    if 0 <= channel_index < len(channels):
        return str(channels[channel_index])

    return str(column_name)


def find_data_header(file_path: Path) -> tuple[int, int]:
    """Find data header."""
    with file_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        for row_num, row in enumerate(reader):
            row_values = [value.strip() for value in row]
            if row_values and row_values[0] == "Time[us]":
                data_column_count = sum(bool(value) for value in row_values)
                return row_num, data_column_count

    raise ValueError("Time[us] header not found")
