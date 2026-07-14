from dataclasses import dataclass
import os
from pathlib import Path


@dataclass
class VideoMetadata:
    path: str
    filename: str
    file_format: str
    codec: str
    width: int
    height: int
    detected_fps: float
    using_fps: float
    total_frames: int
    detected_duration_sec: float
    duration_sec: float


def open_video_capture(cv2, video_path):
    """Open a capture with hardware decoding when supported, then fall back to CPU."""
    disabled = os.environ.get("PIG_LED_HW_DECODE", "1").strip().lower()
    if disabled in {"0", "false", "no", "off"}:
        return cv2.VideoCapture(video_path), "opencv_cpu", "disabled"

    hw_names = ("CAP_FFMPEG", "CAP_PROP_HW_ACCELERATION", "VIDEO_ACCELERATION_ANY")
    if all(hasattr(cv2, name) for name in hw_names):
        try:
            cap = cv2.VideoCapture(
                video_path,
                cv2.CAP_FFMPEG,
                [cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY],
            )
            if cap.isOpened():
                return cap, "opencv_hw", ""
            cap.release()
            fallback_reason = "hardware decode capture did not open"
        except Exception as error:
            fallback_reason = str(error)

        return cv2.VideoCapture(video_path), "opencv_cpu", fallback_reason

    return (
        cv2.VideoCapture(video_path),
        "opencv_cpu",
        "OpenCV hardware decode API is unavailable",
    )


def open_video(path):
    import cv2

    cap = cv2.VideoCapture(path)

    if not cap.isOpened():
        return None

    return cap


def parse_video_metadata(path, using_fps=None):
    import cv2

    cap = open_video(path)

    if cap is None:
        raise ValueError(f"Could not open video: {path}")

    video_path = Path(path)

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    detected_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    fourcc_value = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
    codec = fourcc_to_string(fourcc_value)

    detected_duration_sec = (
        total_frames / detected_fps
        if detected_fps
        else 0.0
    )

    if using_fps is None:
        using_fps = round(detected_fps) if detected_fps else 30.0

    duration_sec = (
        total_frames / using_fps
        if using_fps
        else detected_duration_sec
    )

    cap.release()

    return VideoMetadata(
        path=str(video_path),
        filename=video_path.name,
        file_format=video_path.suffix.lower().replace(".", ""),
        codec=codec,
        width=width,
        height=height,
        detected_fps=detected_fps,
        using_fps=using_fps,
        total_frames=total_frames,
        detected_duration_sec=detected_duration_sec,
        duration_sec=duration_sec,
    )


def fourcc_to_string(fourcc_value):
    if not fourcc_value:
        return "unknown"

    chars = [
        chr((fourcc_value >> 8 * index) & 0xFF)
        for index in range(4)
    ]

    codec = "".join(chars).strip()

    return codec or "unknown"


def read_frame(cap, frame_index):
    import cv2

    if cap is None or not cap.isOpened():
        return False, None

    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    return cap.read()


def frame_to_time_sec(frame_index, fps):
    if not fps:
        return 0.0

    return frame_index / fps


def time_sec_to_frame(time_sec, fps, total_frames=None):
    if not fps:
        return 0

    frame_index = int(round(time_sec * fps))

    if total_frames is not None:
        frame_index = max(0, min(frame_index, total_frames - 1))

    return frame_index


def parse_time_input(text):
    """Parse seconds, MM:SS, or HH:MM:SS text into seconds."""
    text = text.strip()
    if not text:
        return None

    try:
        if ":" not in text:
            return float(text)

        parts = [float(part) for part in text.split(":")]
        if len(parts) == 2:
            minutes, seconds = parts
            return minutes * 60 + seconds

        if len(parts) == 3:
            hours, minutes, seconds = parts
            return hours * 3600 + minutes * 60 + seconds
    except ValueError:
        return None

    return None


def format_time(seconds):
    total_ms = int(round(seconds * 1000))

    minutes = total_ms // 60000
    remaining_ms = total_ms % 60000
    sec = remaining_ms // 1000
    ms = remaining_ms % 1000

    return f"{minutes:02d}:{sec:02d}.{ms:03d}"
