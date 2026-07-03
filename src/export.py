import csv


def export_events_csv(path, events):
    fieldnames = ["event_type", "video_time_sec", "frame_index", "note"]

    with open(path, "w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()

        for event in events:
            writer.writerow(
                {
                    "event_type": event.get("event_type", ""),
                    "video_time_sec": f"{float(event.get('video_time_sec', 0)):.6f}",
                    "frame_index": int(event.get("frame_index", 0)),
                    "note": event.get("note", ""),
                }
            )