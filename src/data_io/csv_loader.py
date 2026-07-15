import csv
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pyqtgraph import units

from ..time_utils import record_time_parts


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
    units = parse_signal_csv_units(path)

    return {
        "path": path,
        "filename": Path(path).name,
        "channels": channels,
        "sample_rates": metadata["sample_rates"],
        "channel_count": len(channels),
        "header_row": metadata["header_row"],
        "data_column_count": metadata["data_column_count"],
        "time_unit": units["time_unit"],
        "value_unit": units["value_unit"],
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


def _time_marker_info(path, time_column_name=None, markers=None):
    markers = list(markers or [])
    return {
        "path": path,
        "filename": Path(path).name,
        "time_column_name": time_column_name,
        "marker_count": len(markers),
        "markers": markers,
        "first_marker_sec": (
            markers[0]["record_time"] / 1_000_000.0 if markers else None
        ),
    }


def parse_time_marker_csv_info(path):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.reader(csv_file))

    if len(rows) < 2:
        return _time_marker_info(path)

    header = [column.strip() for column in rows[0]]

    abs_time_column_index = None
    record_time_column_index = None
    time_column_name = None

    for index, column in enumerate(header):
        lower_column = column.lower()

        if abs_time_column_index is None and column.endswith("_time(us)"):
            abs_time_column_index = index
            time_column_name = column

        if record_time_column_index is None and (
            lower_column == "record_time(us)"
            or lower_column == "recording_time(us)"
            or lower_column == "record time(us)"
        ):
            record_time_column_index = index

    # Fall back to the first two columns for legacy marker CSV files.
    if abs_time_column_index is None and len(header) >= 1:
        abs_time_column_index = 0
        time_column_name = header[0]

    if record_time_column_index is None and len(header) >= 2:
        record_time_column_index = 1

    markers = []

    if abs_time_column_index is None or record_time_column_index is None:
        return _time_marker_info(path, time_column_name)

    for row in rows[1:]:
        if (
            abs_time_column_index >= len(row)
            or record_time_column_index >= len(row)
            or not row[abs_time_column_index].strip()
            or not row[record_time_column_index].strip()
        ):
            continue

        try:
            local_time_us = int(Decimal(row[abs_time_column_index].strip()))
            record_time = int(Decimal(row[record_time_column_index].strip()))
        except (InvalidOperation, ValueError):
            continue

        local_time = datetime.fromtimestamp(
            local_time_us / 1_000_000.0,
            tz=timezone(timedelta(hours=8)),
        )

        markers.append(
            {
                "local_time_us": local_time_us,
                "local_time": local_time,
                "record_time": record_time,
                **record_time_parts(record_time),
            }
        )

    return _time_marker_info(path, time_column_name, markers)
