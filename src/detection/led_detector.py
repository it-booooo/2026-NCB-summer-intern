from dataclasses import dataclass

import cv2
import numpy as np
from ..video.video_utils import open_video_capture


DETECTION_MODE = "frame_delta_mean_brightness"
DETECTION_MODE_LABEL = "Frame delta"
MIN_THRESHOLD = 1e-6


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


def apply_roi(frame_bgr, roi=None):
    """Apply roi.

    Args:
        frame_bgr: Input used by this operation.
        roi: LED region of interest as (x, y, width, height).
    """
    if roi is None:
        return frame_bgr

    x, y, width, height = roi
    return frame_bgr[y : y + height, x : x + width]


def resize_roi_by_scale(frame_bgr, scale=0.5):
    """Resize roi by scale.

    Args:
        frame_bgr: Input used by this operation.
        scale: Input used by this operation.
    """
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


def mean_brightness(frame_bgr, roi=None):
    """Provide mean brightness functionality.

    Args:
        frame_bgr: Input used by this operation.
        roi: LED region of interest as (x, y, width, height).
    """
    frame_bgr = apply_roi(frame_bgr, roi)

    if frame_bgr.size == 0:
        return 0.0

    frame_bgr = resize_roi_by_scale(frame_bgr, scale=0.5)
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray)) / 255.0


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
    acceleration_info=None,
):
    """Compute led brightness curve.

    Args:
        video_path: Path of the video being processed.
        roi: LED region of interest as (x, y, width, height).
        rotate_180: Input used by this operation.
        using_fps: Frame rate used for time conversion.
        frame_step: Input used by this operation.
        start_frame: First video frame to process.
        end_frame: Last video frame to process.
        should_stop: Callback that returns true when processing should stop.
        progress_callback: Callback receiving scan progress updates.
        acceleration_info: Input used by this operation.
    """
    if acceleration_info is not None:
        acceleration_info.clear()

    try:
        from .led_opencl import compute_led_brightness_curve_opencl

        opencl_points = compute_led_brightness_curve_opencl(
            video_path,
            roi=roi,
            rotate_180=rotate_180,
            using_fps=using_fps,
            frame_step=frame_step,
            start_frame=start_frame,
            end_frame=end_frame,
            should_stop=should_stop,
            progress_callback=progress_callback,
            acceleration_info=acceleration_info,
        )
        return [
            LedBrightnessPoint(
                frame_index=frame_index,
                video_time_sec=video_time_sec,
                brightness=brightness,
            )
            for frame_index, video_time_sec, brightness in opencl_points
        ]
    except Exception as error:
        if acceleration_info is not None:
            acceleration_info.update(
                {
                    "brightness_backend": "cpu",
                    "opencl_fallback_reason": str(error),
                }
            )

    cap, decode_backend, decode_fallback_reason = open_video_capture(cv2, video_path)

    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")
    if acceleration_info is not None:
        acceleration_info.update(
            {
                "video_decode_backend": decode_backend,
                "video_decode_fallback_reason": decode_fallback_reason,
            }
        )

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

    if acceleration_info is not None:
        acceleration_info.setdefault("brightness_backend", "cpu")

    if progress_callback is not None:
        completed_frames = min(max(frame_index - start_frame, 0), scan_total_frames)
        progress_callback(completed_frames, scan_total_frames)

    return points


def compute_frame_deltas(points):
    """Compute frame deltas.

    Args:
        points: Brightness or analysis points used by the operation.
    """
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


def point_for_frame(points, frame_index):
    """Provide point for frame functionality.

    Args:
        points: Brightness or analysis points used by the operation.
        frame_index: Zero-based video frame index.
    """
    if not points:
        return None

    frame_index = int(frame_index)
    return min(points, key=lambda point: abs(point.frame_index - frame_index))


def _overlaps_ranges(start_frame, end_frame, ranges):
    return any(
        start_frame <= range_end and end_frame >= range_start
        for range_start, range_end in ranges
    )


def event_pair_from_deltas(points, on_delta, off_delta):
    """Provide event pair from deltas functionality.

    Args:
        points: Brightness or analysis points used by the operation.
        on_delta: Input used by this operation.
        off_delta: Input used by this operation.
    """
    on_point = point_for_frame(points, on_delta.frame_index)
    off_point = point_for_frame(points, off_delta.frame_index)

    if on_point is None or off_point is None:
        return []

    return [
        LedEvent(
            event_type="LED_on",
            video_time_sec=on_point.video_time_sec,
            frame_index=on_point.frame_index,
            brightness=on_point.brightness,
        ),
        LedEvent(
            event_type="LED_off",
            video_time_sec=off_point.video_time_sec,
            frame_index=off_point.frame_index,
            brightness=off_point.brightness,
        ),
    ]


def _detection_stats(
    threshold,
    event_count,
    points_count,
    expected_duration_sec,
    min_duration_sec,
    max_duration_sec,
):
    return {
        "mode": DETECTION_MODE,
        "mode_label": DETECTION_MODE_LABEL,
        "threshold": threshold,
        "event_count": event_count,
        "points_count": points_count,
        "expected_duration_sec": expected_duration_sec,
        "min_duration_sec": min_duration_sec,
        "max_duration_sec": max_duration_sec,
    }


def detect_led_event_pairs_from_frame_deltas(
    points,
    fps=30.0,
    expected_duration_sec=1.0,
    min_duration_sec=0.6,
    max_duration_sec=1.5,
    min_gap_sec=0.5,
    max_events=1,
    duration_weight=0.1,
):
    """Detect led event pairs from frame deltas.

    Args:
        points: Brightness or analysis points used by the operation.
        fps: Video frame rate in frames per second.
        expected_duration_sec: Input used by this operation.
        min_duration_sec: Input used by this operation.
        max_duration_sec: Input used by this operation.
        min_gap_sec: Input used by this operation.
        max_events: Input used by this operation.
        duration_weight: Input used by this operation.
    """
    deltas = compute_frame_deltas(points)
    if not deltas:
        stats = _detection_stats(
            threshold=0.0,
            event_count=0,
            points_count=len(points),
            expected_duration_sec=expected_duration_sec,
            min_duration_sec=min_duration_sec,
            max_duration_sec=max_duration_sec,
        )
        return [], 0.0, stats

    abs_delta_mean = float(np.mean([abs(point.delta) for point in deltas]))
    threshold = max(3.0 * abs_delta_mean, MIN_THRESHOLD)
    on_candidates = [point for point in deltas if point.delta > threshold]
    off_candidates = [point for point in deltas if point.delta < -threshold]
    max_events = max(int(max_events), 0)
    fps = max(float(fps or 30.0), MIN_THRESHOLD)
    min_gap_frames = max(int(min_gap_sec * fps), 1)
    excluded_ranges = []
    selected_pairs = []

    while len(selected_pairs) < max_events:
        best_pair = None
        best_score = None

        for on_delta in on_candidates:
            for off_delta in off_candidates:
                if off_delta.frame_index <= on_delta.frame_index:
                    continue

                if _overlaps_ranges(
                    on_delta.frame_index, off_delta.frame_index, excluded_ranges
                ):
                    continue

                duration_sec = off_delta.video_time_sec - on_delta.video_time_sec
                if not (min_duration_sec <= duration_sec <= max_duration_sec):
                    continue

                pair_score = (
                    abs(on_delta.delta)
                    + abs(off_delta.delta)
                    - duration_weight * abs(duration_sec - expected_duration_sec)
                )
                if best_score is None or pair_score > best_score:
                    best_pair = (on_delta, off_delta)
                    best_score = pair_score

        if best_pair is None:
            break

        on_delta, off_delta = best_pair
        selected_pairs.append(best_pair)
        excluded_ranges.append(
            (
                max(on_delta.frame_index - min_gap_frames, 0),
                off_delta.frame_index + min_gap_frames,
            )
        )

    events = []
    for on_delta, off_delta in selected_pairs:
        events.extend(event_pair_from_deltas(points, on_delta, off_delta))

    events.sort(key=lambda event: event.frame_index)
    event_count = len(events) // 2
    stats = _detection_stats(
        threshold=threshold,
        event_count=event_count,
        points_count=len(points),
        expected_duration_sec=expected_duration_sec,
        min_duration_sec=min_duration_sec,
        max_duration_sec=max_duration_sec,
    )
    return events, threshold, stats


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
    expected_duration_sec=1.0,
    min_duration_sec=0.6,
    max_duration_sec=1.5,
    min_gap_sec=0.5,
    max_events=1,
    duration_weight=0.1,
    acceleration_info=None,
):
    """Refine led event pairs from frame deltas.

    Args:
        video_path: Path of the video being processed.
        roi: LED region of interest as (x, y, width, height).
        coarse_events: Input used by this operation.
        rotate_180: Input used by this operation.
        using_fps: Frame rate used for time conversion.
        window_sec: Input used by this operation.
        scan_start_frame: Input used by this operation.
        scan_end_frame: Input used by this operation.
        should_stop: Callback that returns true when processing should stop.
        expected_duration_sec: Input used by this operation.
        min_duration_sec: Input used by this operation.
        max_duration_sec: Input used by this operation.
        min_gap_sec: Input used by this operation.
        max_events: Input used by this operation.
        duration_weight: Input used by this operation.
        acceleration_info: Input used by this operation.
    """
    max_events = max(int(max_events), 0)
    if not coarse_events or max_events == 0:
        return [], 0.0, _detection_stats(
            threshold=0.0,
            event_count=0,
            points_count=0,
            expected_duration_sec=expected_duration_sec,
            min_duration_sec=min_duration_sec,
            max_duration_sec=max_duration_sec,
        )

    fps = max(float(using_fps or 30.0), MIN_THRESHOLD)
    window_frames = max(int(window_sec * fps), 1)
    min_gap_frames = max(int(min_gap_sec * fps), 1)
    refined_events = []
    thresholds = []
    excluded_ranges = []

    for index in range(0, len(coarse_events), 2):
        if len(refined_events) // 2 >= max_events:
            break

        if should_stop is not None and should_stop():
            break

        pair = coarse_events[index : index + 2]
        if len(pair) < 2:
            continue

        on_event, off_event = pair
        start_frame = max(on_event.frame_index - window_frames, scan_start_frame, 0)
        end_frame = off_event.frame_index + window_frames
        if scan_end_frame is not None:
            end_frame = min(end_frame, scan_end_frame)
        if start_frame >= end_frame:
            continue

        fine_points = compute_led_brightness_curve(
            video_path,
            roi=roi,
            rotate_180=rotate_180,
            using_fps=fps,
            frame_step=1,
            start_frame=start_frame,
            end_frame=end_frame,
            should_stop=should_stop,
            acceleration_info=acceleration_info,
        )
        events, threshold, _ = detect_led_event_pairs_from_frame_deltas(
            fine_points,
            fps=fps,
            expected_duration_sec=expected_duration_sec,
            min_duration_sec=min_duration_sec,
            max_duration_sec=max_duration_sec,
            min_gap_sec=min_gap_sec,
            max_events=1,
            duration_weight=duration_weight,
        )
        if len(events) < 2:
            continue

        refined_start = events[0].frame_index
        refined_end = events[1].frame_index
        if _overlaps_ranges(refined_start, refined_end, excluded_ranges):
            continue

        refined_events.extend(events[:2])
        thresholds.append(threshold)
        excluded_ranges.append(
            (
                max(refined_start - min_gap_frames, 0),
                refined_end + min_gap_frames,
            )
        )

    refined_events.sort(key=lambda event: event.frame_index)
    threshold = float(np.mean(thresholds)) if thresholds else 0.0
    stats = _detection_stats(
        threshold=threshold,
        event_count=len(refined_events) // 2,
        points_count=0,
        expected_duration_sec=expected_duration_sec,
        min_duration_sec=min_duration_sec,
        max_duration_sec=max_duration_sec,
    )
    return refined_events, threshold, stats
