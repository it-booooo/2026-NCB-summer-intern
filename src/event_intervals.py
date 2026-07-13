def pair_event_intervals(events, start_type, end_type, interval_type):
    """Pair matching start/end point markers in table order.

    Existing point markers remain unchanged. Orphaned end markers and starts
    without a later end marker are ignored, so incomplete marking does not
    affect the rest of the application.
    """
    intervals = []
    pending_start = None

    for event in events:
        event_type = event.get("event_type")

        if event_type == start_type:
            pending_start = event
            continue

        if event_type != end_type or pending_start is None:
            continue

        start_sec = float(pending_start.get("video_time_sec", 0.0))
        end_sec = float(event.get("video_time_sec", 0.0))
        if end_sec <= start_sec:
            continue

        intervals.append(
            {
                "event_type": interval_type,
                "video_start_sec": start_sec,
                "video_end_sec": end_sec,
                "start_frame": int(pending_start.get("frame_index", 0)),
                "end_frame": int(event.get("frame_index", 0)),
            }
        )
        pending_start = None

    return intervals


def pair_behavior_intervals(events):
    return pair_event_intervals(
        events,
        start_type="behavior_start",
        end_type="behavior_end",
        interval_type="behavior",
    )


def pair_led_intervals(events):
    return pair_event_intervals(
        events,
        start_type="LED_on",
        end_type="LED_off",
        interval_type="led",
    )
