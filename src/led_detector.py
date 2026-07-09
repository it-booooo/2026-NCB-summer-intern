from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class LedEvent:
    event_type: str
    video_time_sec: float
    frame_index: int
    brightness: float


@dataclass
class LedBrightnessPoint:
    frame_index: int
    video_time_sec: float
    brightness: float


@dataclass
class LedChangePoint:
    frame_index: int
    video_time_sec: float
    delta: float


DETECTION_MODE_LABELS = {
    "frame_delta": "Frame delta",
    "frame_delta_mean_brightness": "Frame delta (ROI mean brightness)",
    "brightness": "Brightness",
}


def apply_roi(frame_bgr, roi=None):
    if roi is None:
        return frame_bgr

    x, y, width, height = roi
    return frame_bgr[y : y + height, x : x + width]


def mean_brightness(frame_bgr, roi=None):
    frame_bgr = apply_roi(frame_bgr, roi)

    if frame_bgr.size == 0:
        return 0.0

    frame_bgr = resize_roi_by_scale(frame_bgr, scale=0.5)
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray)) / 255.0


def resize_roi_by_scale(frame_bgr, scale=0.5):
    if scale >= 1.0:
        return frame_bgr

    height, width = frame_bgr.shape[:2]
    resized_width = max(int(width * scale), 1)
    resized_height = max(int(height * scale), 1)

    return cv2.resize(
        frame_bgr,
        (resized_width, resized_height),
        interpolation=cv2.INTER_AREA,
    )


def compute_led_brightness_curve(
    video_path,
    roi=None,
    rotate_180=False,
    using_fps=30.0,
    frame_step=1,
    start_frame=0,
    end_frame=None,
    should_stop=None,
    progress_callback=None,
):
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    fps = float(using_fps or cap.get(cv2.CAP_PROP_FPS) or 30.0)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frame_step = max(int(frame_step), 1)
    start_frame = max(int(start_frame), 0)
    if end_frame is None:
        end_frame = max(total_frames - 1, 0)
    end_frame = min(max(int(end_frame), start_frame), max(total_frames - 1, 0))

    if start_frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    points = []
    frame_index = start_frame

    scan_total_frames = max(end_frame - start_frame + 1, 1)

    if progress_callback is not None:
        progress_callback(0, scan_total_frames)

    while frame_index <= end_frame:
        if should_stop is not None and should_stop():
            break

        success, frame = cap.read()
        if not success:
            break

        if rotate_180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)

        points.append(
            LedBrightnessPoint(
                frame_index=frame_index,
                video_time_sec=frame_index / fps,
                brightness=mean_brightness(frame, roi=roi),
            )
        )

        frame_index += 1

        skipped = 0
        while skipped < frame_step - 1 and frame_index <= end_frame:
            if should_stop is not None and should_stop():
                break
            if not cap.grab():
                frame_index = end_frame + 1
                break
            frame_index += 1
            skipped += 1

        if progress_callback is not None:
            completed_frames = min(max(frame_index - start_frame, 0), scan_total_frames)
            progress_callback(completed_frames, scan_total_frames)

    cap.release()

    if progress_callback is not None:
        completed_frames = min(max(frame_index - start_frame, 0), scan_total_frames)
        progress_callback(completed_frames, scan_total_frames)

    return points


def score_at_frame(points, frame_index):
    if not points:
        return 0.0

    point = point_for_frame(points, frame_index)
    return point.brightness if point is not None else 0.0


def summarize_brightness(points, detection_mode="brightness"):
    if not points:
        return {
            "mode": detection_mode,
            "mode_label": DETECTION_MODE_LABELS.get(detection_mode, detection_mode),
            "min": 0.0,
            "median": 0.0,
            "max": 0.0,
            "dynamic_range": 0.0,
            "peak_frame": 0,
            "peak_time_sec": 0.0,
        }

    values = np.array([point.brightness for point in points], dtype=float)
    peak_index = int(np.argmax(values))
    peak_point = points[peak_index]
    median = float(np.percentile(values, 50))
    maximum = float(values[peak_index])

    return {
        "mode": detection_mode,
        "mode_label": DETECTION_MODE_LABELS.get(detection_mode, detection_mode),
        "min": float(np.min(values)),
        "median": median,
        "max": maximum,
        "dynamic_range": maximum - median,
        "peak_frame": peak_point.frame_index,
        "peak_time_sec": peak_point.video_time_sec,
    }


def compute_frame_deltas(points):
    if len(points) < 2:
        return []

    return [
        LedChangePoint(
            frame_index=points[index].frame_index,
            video_time_sec=points[index].video_time_sec,
            delta=points[index].brightness - points[index - 1].brightness,
        )
        for index in range(1, len(points))
    ]


def summarize_frame_deltas(deltas):
    if not deltas:
        return {
            "max_positive_delta": 0.0,
            "max_positive_frame": 0,
            "max_positive_time_sec": 0.0,
            "max_negative_delta": 0.0,
            "max_negative_frame": 0,
            "max_negative_time_sec": 0.0,
            "reference_delta": 0.0,
        }

    positive = max(deltas, key=lambda point: point.delta)
    negative = min(deltas, key=lambda point: point.delta)
    abs_values = np.array([abs(point.delta) for point in deltas], dtype=float)

    return {
        "max_positive_delta": positive.delta,
        "max_positive_frame": positive.frame_index,
        "max_positive_time_sec": positive.video_time_sec,
        "max_negative_delta": negative.delta,
        "max_negative_frame": negative.frame_index,
        "max_negative_time_sec": negative.video_time_sec,
        "reference_delta": float(np.percentile(abs_values, 99)),
    }


def point_for_frame(points, frame_index):
    if not points:
        return None

    frame_index = int(frame_index)
    return min(points, key=lambda point: abs(point.frame_index - frame_index))


def detect_led_events_from_frame_deltas(points, fps=30.0, min_duration_sec=0.1):
    if len(points) < 2:
        return [], 0.0, summarize_frame_deltas([])

    deltas = compute_frame_deltas(points)
    positive_candidates = sorted(
        [point for point in deltas if point.delta > 0],
        key=lambda point: point.delta,
        reverse=True,
    )[:30]
    negative_candidates = sorted(
        [point for point in deltas if point.delta < 0],
        key=lambda point: point.delta,
    )[:30]
    min_duration_frames = max(int(min_duration_sec * fps), 1)
    best_pair = None
    best_score = 0.0

    for on_delta in positive_candidates:
        for off_delta in negative_candidates:
            duration_frames = off_delta.frame_index - on_delta.frame_index
            if duration_frames < min_duration_frames:
                continue

            pair_score = abs(on_delta.delta) + abs(off_delta.delta)
            if pair_score > best_score:
                best_pair = (on_delta, off_delta)
                best_score = pair_score

    stats = summarize_frame_deltas(deltas)
    if best_pair is None:
        return [], stats["reference_delta"], stats

    on_delta, off_delta = best_pair
    start_point = point_for_frame(points, on_delta.frame_index)
    off_frame_index = max(off_delta.frame_index - 1, start_point.frame_index)
    off_point = point_for_frame(points, off_frame_index)

    if start_point is None or off_point is None:
        return [], stats["reference_delta"], stats

    stats["selected_on_delta"] = on_delta.delta
    stats["selected_on_frame"] = on_delta.frame_index
    stats["selected_on_time_sec"] = on_delta.video_time_sec
    stats["selected_off_delta"] = off_delta.delta
    stats["selected_off_frame"] = off_delta.frame_index
    stats["selected_off_time_sec"] = off_delta.video_time_sec

    events = [
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

    return events, stats["reference_delta"], stats


def mean_points_between(points, start_frame, end_frame):
    values = [
        point.brightness
        for point in points
        if start_frame <= point.frame_index <= end_frame
    ]
    if not values:
        return None

    return float(np.mean(values))


def validate_led_state_change(
    points,
    events,
    fps=30.0,
    window_sec=0.2,
    min_state_delta=0.002,
):
    if len(events) < 2:
        return False, {
            "state_validation": "failed",
            "state_delta_on": 0.0,
            "state_delta_off": 0.0,
        }

    on_event, off_event = events[0], events[1]
    window_frames = max(int(window_sec * fps), 1)

    on_before = mean_points_between(
        points,
        on_event.frame_index - window_frames,
        on_event.frame_index - 1,
    )
    on_after = mean_points_between(
        points,
        on_event.frame_index,
        on_event.frame_index + window_frames,
    )
    off_before = mean_points_between(
        points,
        off_event.frame_index - window_frames,
        off_event.frame_index,
    )
    off_after = mean_points_between(
        points,
        off_event.frame_index + 1,
        off_event.frame_index + window_frames,
    )

    if None in [on_before, on_after, off_before, off_after]:
        return False, {
            "state_validation": "insufficient data",
            "state_delta_on": 0.0,
            "state_delta_off": 0.0,
        }

    state_delta_on = on_after - on_before
    state_delta_off = off_before - off_after
    is_valid = (
        state_delta_on >= min_state_delta
        and state_delta_off >= min_state_delta
    )

    return is_valid, {
        "state_validation": "passed" if is_valid else "failed",
        "state_delta_on": state_delta_on,
        "state_delta_off": state_delta_off,
    }


def refine_led_events_from_frame_deltas(
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
    if len(coarse_events) < 2:
        return [], 0.0, summarize_frame_deltas([])

    fps = float(using_fps or 30.0)
    window_frames = max(int(window_sec * fps), 1)
    start_frame = max(coarse_events[0].frame_index - window_frames, scan_start_frame, 0)
    end_frame = coarse_events[1].frame_index + window_frames
    if scan_end_frame is not None:
        end_frame = min(end_frame, scan_end_frame)

    points = compute_led_brightness_curve(
        video_path,
        roi=roi,
        rotate_180=rotate_180,
        using_fps=fps,
        frame_step=1,
        start_frame=start_frame,
        end_frame=end_frame,
        should_stop=should_stop,
    )

    events, threshold, stats = detect_led_events_from_frame_deltas(
        points,
        fps=fps,
        min_duration_sec=0.1,
    )
    is_valid, validation_stats = validate_led_state_change(
        points,
        events,
        fps=fps,
    )
    stats.update(validation_stats)

    if not is_valid:
        return [], threshold, stats

    return events, threshold, stats


