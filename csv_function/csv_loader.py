import csv
import re
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


def parse_signal_csv_metadata(path):
    channels = []
    sample_rates = []
    header_row = None
    data_column_count = None

    with open(path, "r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.reader(csv_file)

        for row_num, row in enumerate(reader):
            row_values = [value.strip() for value in row]
            if not row_values:
                continue

            row_name = row_values[0]
            if row_name == "Channels":
                channels = [int(channel) for channel in row_values[1:] if channel]
            elif row_name.startswith("Sample Rate"):
                sample_rates = [
                    float(sample_rate) for sample_rate in row_values[1:] if sample_rate
                ]
            elif row_name == "Time[us]":
                header_row = row_num
                data_column_count = sum(bool(value) for value in row_values)
                break

    return {
        "channels": channels,
        "sample_rates": sample_rates,
        "header_row": header_row,
        "data_column_count": data_column_count,
    }


def parse_lfp_csv_info(path):
    metadata = parse_signal_csv_metadata(path)
    channels = metadata["channels"]

    return {
        "path": path,
        "filename": Path(path).name,
        "channels": channels,
        "sample_rates": metadata["sample_rates"],
        "channel_count": len(channels),
        "header_row": metadata["header_row"],
        "data_column_count": metadata["data_column_count"],
    }


def parse_signal_csv_units(path):
    rows = read_csv_preview(path, max_rows=8)
    value_unit = ""

    for row in rows:
        if not row:
            continue

        row_name = row[0].strip().lower()
        if row_name in {"unit", "units"}:
            units = [value.strip() for value in row[1:] if value.strip()]
            if units:
                value_unit = units[0]
                break

    return {
        "time_unit": "s",
        "value_unit": normalize_unit(value_unit),
    }


def normalize_unit(unit):
    unit = unit.strip()
    if not unit:
        return ""

    replacements = {
        "uV": "uV",
        "uv": "uV",
        "μV": "uV",
        "µV": "uV",
    }
    return replacements.get(unit, re.sub(r"\s+", " ", unit))


def parse_time_marker_csv_info(path):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.reader(csv_file))

    if len(rows) < 2:
        return {
            "path": path,
            "filename": Path(path).name,
            "marker_count": 0,
            "markers": [],
            "first_marker_us": None,
            "first_marker_sec": None,
        }

    header = rows[0]

    time_column_name = None

    for column in header:
        if column.endswith("_time(us)"):
            time_column_name = column
            break

    markers = []

    if time_column_name is not None:
        column_index = header.index(time_column_name)

        for row in rows[1:]:
            if column_index >= len(row) or not row[column_index]:
                continue

            marker_us = float(row[column_index])
            markers.append(
                {
                    "time_us": marker_us,
                    "time_sec": marker_us / 1_000_000,
                }
            )

    first_marker_us = markers[0]["time_us"] if markers else None
    first_marker_sec = first_marker_us / 1_000_000 if first_marker_us is not None else None

    return {
        "path": path,
        "filename": Path(path).name,
        "marker_count": len(markers),
        "markers": markers,
        "time_column_name": time_column_name,
        "first_marker_us": first_marker_us,
        "first_marker_sec": first_marker_sec,
    }
