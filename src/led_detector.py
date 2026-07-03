from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class LedEvent:
    event_type: str
    video_time_sec: float
    frame_index: int
    red_score: float


def red_score(frame_bgr, roi=None):
    """
    Calculate the ratio of red pixels inside a frame or ROI.

    roi format:
        (x, y, width, height)
    """

    if roi is not None:
        x, y, width, height = roi
        frame_bgr = frame_bgr[y : y + height, x : x + width]

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


def detect_led_events(video_path, roi=None, threshold=0.05, min_gap_sec=0.2):
    """
    Detect LED-on events from a video.

    Parameters:
        video_path:
            MP4 path.
        roi:
            Optional LED area, format (x, y, width, height).
            If None, the whole frame is scanned.
        threshold:
            Red pixel ratio threshold.
        min_gap_sec:
            Minimum time gap between LED events.

    Returns:
        list[LedEvent]
    """

    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)

    if fps <= 0:
        fps = 30.0

    min_gap_frames = max(int(min_gap_sec * fps), 1)

    events = []
    previous_is_on = False
    last_event_frame = -min_gap_frames
    frame_index = 0

    while True:
        success, frame = cap.read()

        if not success:
            break

        score = red_score(frame, roi=roi)
        is_on = score >= threshold

        if is_on and not previous_is_on and frame_index - last_event_frame >= min_gap_frames:
            events.append(
                LedEvent(
                    event_type="LED_on",
                    video_time_sec=frame_index / fps,
                    frame_index=frame_index,
                    red_score=score,
                )
            )

            last_event_frame = frame_index

        previous_is_on = is_on
        frame_index += 1

    cap.release()

    return events