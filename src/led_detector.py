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


def compute_led_brightness_curve(
    video_path,
    roi=None,
    rotate_180=False,
    using_fps=30.0,
    should_stop=None,
):
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    fps = float(using_fps or cap.get(cv2.CAP_PROP_FPS) or 30.0)
    points = []
    frame_index = 0

    while True:
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

    cap.release()
    return points


def score_at_frame(points, frame_index):
    if not points:
        return 0.0

    frame_index = max(0, min(int(frame_index), len(points) - 1))
    return points[frame_index].brightness


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


def summarize_brightness(points):
    if not points:
        return {
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
        "min": float(np.min(values)),
        "median": median,
        "max": maximum,
        "dynamic_range": maximum - median,
        "peak_frame": peak_point.frame_index,
        "peak_time_sec": peak_point.video_time_sec,
    }


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
