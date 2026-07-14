import csv


def export_events_csv(path, events):
    # 使用 utf-8-sig，讓含有非 ASCII 內容的 CSV 可由 Excel 正確辨識。
    fieldnames = ["event_type", "video_time_sec", "frame_index", "note"]
    with open(path, "w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for event in events:
            writer.writerow({
                "event_type": event.get("event_type", ""),
                "video_time_sec": f"{float(event.get('video_time_sec', 0)):.6f}",
                "frame_index": int(event.get("frame_index", 0)),
                "note": event.get("note", ""),
            })


def export_events_excel(path, events):
    from openpyxl import Workbook
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Markers"
    sheet.append(["event_type", "video_time_sec", "frame_index", "note"])
    for event in events:
        sheet.append([
            event.get("event_type", ""), float(event.get("video_time_sec", 0)),
            int(event.get("frame_index", 0)), event.get("note", ""),
        ])
    workbook.save(path)
