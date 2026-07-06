from dataclasses import dataclass
from pathlib import Path

import cv2


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


def open_video(path):
    cap = cv2.VideoCapture(path)

    if not cap.isOpened():
        return None

    return cap


def parse_video_metadata(path, using_fps=30.0):
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


def format_time(seconds):
    total_ms = int(round(seconds * 1000))

    minutes = total_ms // 60000
    remaining_ms = total_ms % 60000
    sec = remaining_ms // 1000
    ms = remaining_ms % 1000

    return f"{minutes:02d}:{sec:02d}.{ms:03d}"