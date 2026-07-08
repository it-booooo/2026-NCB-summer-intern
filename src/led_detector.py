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
    "max_brightness": "Max brightness",
    "brightness": "Brightness",
    "red_score": "Red score",
    "saturation": "Saturation",
}


def apply_roi(frame_bgr, roi=None):
    if roi is None:
        return frame_bgr

    x, y, width, height = roi
    return frame_bgr[y : y + height, x : x + width]


def red_score(frame_bgr, roi=None):
    frame_bgr = apply_roi(frame_bgr, roi)

    if frame_bgr.size == 0:
        return 0.0

    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)

    lower_red_1 = np.array([0, 80, 80])
    upper_red_1 = np.array([10, 255, 255])

    lower_red_2 = np.array([170, 80, 80])
    upper_red_2 = np.array([180, 255, 255])

    mask_1 = cv2.inRange(hsv, lower_red_1, upper_red_1)
    mask_2 = cv2.inRange(hsv, lower_red_2, upper_red_2)
    mask = cv2.bitwise_or(mask_1, mask_2)

    return float(np.count_nonzero(mask)) / float(mask.size)


def mean_brightness(frame_bgr, roi=None):
    frame_bgr = apply_roi(frame_bgr, roi)

    if frame_bgr.size == 0:
        return 0.0

    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray)) / 255.0


def top_percent_mean(values, top_percent=5.0):
    flat_values = values.reshape(-1)
    if flat_values.size == 0:
        return 0.0

    count = max(int(flat_values.size * float(top_percent) / 100.0), 1)
    top_values = np.partition(flat_values, -count)[-count:]
    return float(np.mean(top_values)) / 255.0


def max_brightness(frame_bgr, roi=None, top_percent=5.0):
    frame_bgr = apply_roi(frame_bgr, roi)

    if frame_bgr.size == 0:
        return 0.0

    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return top_percent_mean(gray, top_percent=top_percent)


def saturation_score(frame_bgr, roi=None):
    frame_bgr = apply_roi(frame_bgr, roi)

    if frame_bgr.size == 0:
        return 0.0

    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    return top_percent_mean(hsv[:, :, 1], top_percent=5.0)


def led_feature_score(frame_bgr, roi=None, detection_mode="max_brightness"):
    if detection_mode == "brightness":
        return mean_brightness(frame_bgr, roi=roi)

    if detection_mode == "red_score":
        return red_score(frame_bgr, roi=roi)

    if detection_mode == "saturation":
        return saturation_score(frame_bgr, roi=roi)

    return max_brightness(frame_bgr, roi=roi)


def compute_led_brightness_curve(
    video_path,
    roi=None,
    rotate_180=False,
    using_fps=30.0,
    detection_mode="max_brightness",
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

    if progress_callback is not None:
        progress_callback(start_frame, total_frames)

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
                brightness=led_feature_score(
                    frame,
                    roi=roi,
                    detection_mode=detection_mode,
                ),
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

        if progress_callback is not None and (
            len(points) == 1 or len(points) % 20 == 0 or frame_index > end_frame
        ):
            progress_callback(min(frame_index, total_frames), total_frames)

    cap.release()

    if progress_callback is not None:
        progress_callback(frame_index, total_frames)

    return points


def score_at_frame(points, frame_index):
    if not points:
        return 0.0

    point = point_for_frame(points, frame_index)
    return point.brightness if point is not None else 0.0


def auto_threshold(points, baseline_score=None, margin=0.02):
    if not points:
        return 1.0

    values = np.array([point.brightness for point in points], dtype=float)
    background = float(np.percentile(values, 50))
    peak = float(np.max(values))
    dynamic_range = peak - background

    if dynamic_range <= 0.005:
        return min(max(peak + margin, 0.0), 1.0)

    distribution_threshold = background + dynamic_range * 0.35

    if baseline_score is None:
        return min(max(distribution_threshold, 0.0), 1.0)

    baseline_threshold = baseline_score + (peak - baseline_score) * 0.35
    if baseline_score <= distribution_threshold and peak > baseline_score:
        threshold = min(distribution_threshold, baseline_threshold)
    else:
        threshold = distribution_threshold

    return min(max(threshold, 0.0), 1.0)


def summarize_brightness(points, detection_mode="max_brightness"):
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


def refine_led_events_from_frame_deltas(
    video_path,
    roi,
    coarse_events,
    rotate_180=False,
    using_fps=30.0,
    window_sec=1.0,
    should_stop=None,
):
    if len(coarse_events) < 2:
        return [], 0.0, summarize_frame_deltas([])

    fps = float(using_fps or 30.0)
    window_frames = max(int(window_sec * fps), 1)
    start_frame = max(coarse_events[0].frame_index - window_frames, 0)
    end_frame = coarse_events[1].frame_index + window_frames

    points = compute_led_brightness_curve(
        video_path,
        roi=roi,
        rotate_180=rotate_180,
        using_fps=fps,
        detection_mode="max_brightness",
        frame_step=1,
        start_frame=start_frame,
        end_frame=end_frame,
        should_stop=should_stop,
    )

    return detect_led_events_from_frame_deltas(
        points,
        fps=fps,
        min_duration_sec=0.1,
    )


def detect_led_events_from_curve(
    points,
    threshold,
    min_duration_sec=0.03,
    min_gap_sec=0.2,
    fps=30.0,
):
    """
    Detect LED ON intervals.

    This function records only the start and end of each LED flash.
    Output events:
        LED_on
        LED_off
    """

    if not points:
        return []

    min_duration_frames = max(int(min_duration_sec * fps), 1)
    min_gap_frames = max(int(min_gap_sec * fps), 1)

    events = []
    in_event = False
    start_point = None
    previous_point = None
    peak_score = 0.0
    last_end_frame = -min_gap_frames

    for point in points:
        is_on = point.brightness >= threshold

        if is_on and not in_event:
            if point.frame_index - last_end_frame >= min_gap_frames:
                in_event = True
                start_point = point
                peak_score = point.brightness

        elif is_on and in_event:
            peak_score = max(peak_score, point.brightness)

        elif not is_on and in_event:
            end_point = previous_point or start_point
            duration_frames = end_point.frame_index - start_point.frame_index + 1

            if duration_frames >= min_duration_frames:
                events.append(
                    LedEvent(
                        event_type="LED_on",
                        video_time_sec=start_point.video_time_sec,
                        frame_index=start_point.frame_index,
                        brightness=start_point.brightness,
                    )
                )
                events.append(
                    LedEvent(
                        event_type="LED_off",
                        video_time_sec=end_point.video_time_sec,
                        frame_index=end_point.frame_index,
                        brightness=peak_score,
                    )
                )

                last_end_frame = end_point.frame_index

            in_event = False
            start_point = None
            peak_score = 0.0

        previous_point = point

    if in_event and start_point is not None:
        end_point = points[-1]
        duration_frames = end_point.frame_index - start_point.frame_index + 1

        if duration_frames >= min_duration_frames:
            events.append(
                LedEvent(
                    event_type="LED_on",
                    video_time_sec=start_point.video_time_sec,
                    frame_index=start_point.frame_index,
                    brightness=start_point.brightness,
                )
            )
            events.append(
                LedEvent(
                    event_type="LED_off",
                    video_time_sec=end_point.video_time_sec,
                    frame_index=end_point.frame_index,
                    brightness=peak_score,
                )
            )

    return events
