import csv


def export_markers_csv(path, markers):
    """Export video-domain markers as CSV.

    Args:
        path: File path to read from or write to.
        markers: Serializable marker rows.
    """
    # 使用 utf-8-sig，讓含有非 ASCII 內容的 CSV 可由 Excel 正確辨識。
    fieldnames = ["marker_type", "video_time_sec", "frame_index", "note"]
    with open(path, "w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for marker in markers:
            writer.writerow(
                {
                    "marker_type": marker.get("marker_type", ""),
                    "video_time_sec": (
                        f"{float(marker.get('video_time_sec', 0)):.6f}"
                    ),
                    "frame_index": int(marker.get("frame_index", 0)),
                    "note": marker.get("note", ""),
                }
            )


def export_markers_excel(path, markers):
    """Export video-domain markers as an Excel workbook.

    Args:
        path: File path to read from or write to.
        markers: Serializable marker rows.
    """
    from openpyxl import Workbook
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Markers"
    sheet.append(["marker_type", "video_time_sec", "frame_index", "note"])
    for marker in markers:
        sheet.append(
            [
                marker.get("marker_type", ""),
                float(marker.get("video_time_sec", 0)),
                int(marker.get("frame_index", 0)),
                marker.get("note", ""),
            ]
        )
    workbook.save(path)


def ttl_marker_rows(markers):
    """Return stable, serializable rows for TTL marker exports."""
    rows = []
    for index, marker in enumerate(markers, start=1):
        local_time = marker.get("local_time")
        local_time_text = (
            local_time.isoformat()
            if local_time is not None and hasattr(local_time, "isoformat")
            else str(local_time or "")
        )
        record_time_us = int(marker.get("record_time", 0))
        record_time_text = (
            f"{int(marker.get('record_hours', 0)):02d}:"
            f"{int(marker.get('record_minutes', 0)):02d}:"
            f"{int(marker.get('record_seconds', 0)):02d}."
            f"{int(marker.get('record_microseconds', 0)):06d}"
        )
        rows.append(
            {
                "marker_index": index,
                "local_time(us)": marker.get("local_time_us"),
                "local_time": local_time_text,
                "record_time(us)": record_time_us,
                "record_time": record_time_text,
            }
        )
    return rows


def export_ttl_markers_csv(path, markers):
    """Export TTL markers as a UTF-8 CSV file."""
    fieldnames = [
        "marker_index",
        "local_time(us)",
        "local_time",
        "record_time(us)",
        "record_time",
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(ttl_marker_rows(markers))


def export_ttl_markers_excel(path, markers):
    """Export TTL markers as an Excel workbook."""
    from openpyxl import Workbook

    fieldnames = [
        "marker_index",
        "local_time(us)",
        "local_time",
        "record_time(us)",
        "record_time",
    ]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "TTL Markers"
    sheet.append(fieldnames)
    for row in ttl_marker_rows(markers):
        sheet.append([row[fieldname] for fieldname in fieldnames])
    workbook.save(path)
