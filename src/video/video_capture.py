import os


def open_video_capture(cv2, video_path):
    if _hw_decode_disabled():
        return cv2.VideoCapture(video_path), "opencv_cpu", "disabled"

    if _has_hw_decode_api(cv2):
        try:
            cap = cv2.VideoCapture(
                video_path,
                cv2.CAP_FFMPEG,
                [
                    cv2.CAP_PROP_HW_ACCELERATION,
                    cv2.VIDEO_ACCELERATION_ANY,
                ],
            )
            if cap.isOpened():
                return cap, "opencv_hw", ""
            cap.release()
        except Exception as error:
            fallback_reason = str(error)
        else:
            fallback_reason = "hardware decode capture did not open"

        cap = cv2.VideoCapture(video_path)
        return cap, "opencv_cpu", fallback_reason

    cap = cv2.VideoCapture(video_path)
    return cap, "opencv_cpu", "OpenCV hardware decode API is unavailable"


def _hw_decode_disabled():
    value = os.environ.get("PIG_LED_HW_DECODE", "1").strip().lower()
    return value in {"0", "false", "no", "off"}


def _has_hw_decode_api(cv2):
    return all(
        hasattr(cv2, name)
        for name in (
            "CAP_FFMPEG",
            "CAP_PROP_HW_ACCELERATION",
            "VIDEO_ACCELERATION_ANY",
        )
    )
