import numpy as np

from src.led_detector import (
    LedEvent,
    compute_frame_deltas,
    point_for_frame,
    refine_led_events_from_frame_deltas,
    summarize_frame_deltas,
)


def event_pair_from_deltas(points, on_delta, off_delta):
    start_point = point_for_frame(points, on_delta.frame_index)
    if start_point is None:
        return []

    off_frame_index = max(off_delta.frame_index - 1, start_point.frame_index)
    off_point = point_for_frame(points, off_frame_index)
    if off_point is None:
        return []

    return [
        LedEvent(
            event_type="LED_on",
            video_time_sec=start_point.video_time_sec,
            frame_index=start_point.frame_index,
            brightness=start_point.brightness,
        ),
        LedEvent(
            event_type="LED_off",
            video_time_sec=off_point.video_time_sec,
            frame_index=off_point.frame_index,
            brightness=off_point.brightness,
        ),
    ]


def detect_led_event_pairs_from_frame_deltas(
    points,
    fps=30.0,
    min_duration_sec=0.1,
    min_gap_sec=0.5,
    max_events=20,
):
    if len(points) < 2:
        return [], 0.0, summarize_frame_deltas([])

    deltas = compute_frame_deltas(points)
    stats = summarize_frame_deltas(deltas)
    positive_candidates = sorted(
        [point for point in deltas if point.delta > 0],
        key=lambda point: point.delta,
        reverse=True,
    )
    negative_candidates = sorted(
        [point for point in deltas if point.delta < 0],
        key=lambda point: point.delta,
    )
    abs_values = np.array([abs(point.delta) for point in deltas], dtype=float)
    min_delta = max(float(np.percentile(abs_values, 95)) * 0.5, 0.001)
    min_duration_frames = max(int(min_duration_sec * fps), 1)
    min_gap_frames = max(int(min_gap_sec * fps), 1)
    excluded_ranges = []
    events = []
    selected_pairs = []

    def is_excluded(frame_index):
        return any(start <= frame_index <= end for start, end in excluded_ranges)

    while len(selected_pairs) < max_events:
        best_pair = None
        best_score = 0.0

        for on_delta in positive_candidates:
            if on_delta.delta < min_delta or is_excluded(on_delta.frame_index):
                continue

            for off_delta in negative_candidates:
                if abs(off_delta.delta) < min_delta or is_excluded(off_delta.frame_index):
                    continue

                duration_frames = off_delta.frame_index - on_delta.frame_index
                if duration_frames < min_duration_frames:
                    continue

                pair_score = abs(on_delta.delta) + abs(off_delta.delta)
                if pair_score > best_score:
                    best_pair = (on_delta, off_delta)
                    best_score = pair_score

        if best_pair is None:
            break

        on_delta, off_delta = best_pair
        pair_events = event_pair_from_deltas(points, on_delta, off_delta)
        if not pair_events:
            break

        events.extend(pair_events)
        selected_pairs.append((on_delta, off_delta))
        excluded_ranges.append(
            (
                max(on_delta.frame_index - min_gap_frames, 0),
                off_delta.frame_index + min_gap_frames,
            )
        )

    events.sort(key=lambda event: event.frame_index)
    stats["event_count"] = len(selected_pairs)
    stats["min_delta"] = min_delta
    stats["selected_on_delta"] = selected_pairs[0][0].delta if selected_pairs else 0.0
    stats["selected_on_time_sec"] = (
        selected_pairs[0][0].video_time_sec if selected_pairs else 0.0
    )
    stats["selected_off_delta"] = selected_pairs[0][1].delta if selected_pairs else 0.0
    stats["selected_off_time_sec"] = (
        selected_pairs[0][1].video_time_sec if selected_pairs else 0.0
    )

    return events, min_delta, stats


def refine_led_event_pairs_from_frame_deltas(
    video_path,
    roi,
    coarse_events,
    rotate_180=False,
    using_fps=30.0,
    window_sec=1.0,
    scan_start_frame=0,
    scan_end_frame=None,
    should_stop=None,
):
    refined_events = []
    refined_stats = summarize_frame_deltas([])
    threshold = 0.0
    failed_pairs = 0

    for index in range(0, len(coarse_events), 2):
        if should_stop is not None and should_stop():
            break

        pair = coarse_events[index : index + 2]
        if len(pair) < 2:
            continue

        events, threshold, stats = refine_led_events_from_frame_deltas(
            video_path,
            roi=roi,
            coarse_events=pair,
            rotate_180=rotate_180,
            using_fps=using_fps,
            window_sec=window_sec,
            scan_start_frame=scan_start_frame,
            scan_end_frame=scan_end_frame,
            should_stop=should_stop,
        )
        if events:
            refined_events.extend(events)
            refined_stats.update(stats)
        else:
            failed_pairs += 1

    refined_events.sort(key=lambda event: event.frame_index)
    refined_stats["event_count"] = len(refined_events) // 2
    refined_stats["failed_pair_count"] = failed_pairs
    if refined_events:
        refined_stats["state_validation"] = "passed"
    elif failed_pairs:
        refined_stats["state_validation"] = "failed"
    return refined_events, threshold, refined_stats
