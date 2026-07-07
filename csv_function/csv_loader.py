import csv
from pathlib import Path


def read_csv_preview(path, max_rows=8):
    rows = []

    with open(path, "r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.reader(csv_file)

        for index, row in enumerate(reader):
            rows.append(row)

            if index + 1 >= max_rows:
                break

    return rows


def parse_lfp_csv_info(path):
    rows = read_csv_preview(path, max_rows=6)

    channel_row = rows[2] if len(rows) > 2 else []
    sample_rate_row = rows[3] if len(rows) > 3 else []

    channels = channel_row[1:] if channel_row and channel_row[0] == "Channels" else []
    sample_rates = sample_rate_row[1:] if sample_rate_row and sample_rate_row[0].startswith("Sample Rate") else []

    return {
        "path": path,
        "filename": Path(path).name,
        "channels": channels,
        "sample_rates": sample_rates,
        "channel_count": len(channels),
    }


def parse_time_marker_csv_info(path):
    rows = read_csv_preview(path, max_rows=5)

    if len(rows) < 2:
        return {
            "path": path,
            "filename": Path(path).name,
            "marker_count": 0,
            "first_marker_us": None,
            "first_marker_sec": None,
        }

    header = rows[0]
    first_data = rows[1]

    time_column_name = None

    for column in header:
        if column.endswith("_time(us)"):
            time_column_name = column
            break

    first_marker_us = None

    if time_column_name is not None:
        column_index = header.index(time_column_name)

        if column_index < len(first_data):
            first_marker_us = float(first_data[column_index])

    first_marker_sec = first_marker_us / 1_000_000 if first_marker_us is not None else None

    return {
        "path": path,
        "filename": Path(path).name,
        "marker_count": max(len(rows) - 1, 0),
        "time_column_name": time_column_name,
        "first_marker_us": first_marker_us,
        "first_marker_sec": first_marker_sec,
    }