import unittest
from unittest.mock import Mock, patch

import numpy as np

from src.led_detection.led_detector import compute_led_brightness_curve


class LedVideoResourceTests(unittest.TestCase):
    def test_cpu_scan_releases_capture_when_frame_processing_fails(self):
        capture = Mock()
        capture.isOpened.return_value = True
        capture.get.side_effect = lambda key: 30.0 if key == 5 else 1
        capture.read.return_value = (True, np.zeros((2, 2, 3), dtype=np.uint8))

        with (
            patch(
                "src.led_detection.led_opencl.compute_led_brightness_curve_opencl",
                side_effect=RuntimeError("use CPU"),
            ),
            patch(
                "src.led_detection.led_detector.open_video_capture",
                return_value=(capture, "cpu", None),
            ),
            patch(
                "src.led_detection.led_detector.mean_brightness",
                side_effect=RuntimeError("frame failed"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "frame failed"):
                compute_led_brightness_curve("video.mp4", end_frame=0)

        capture.release.assert_called_once_with()

    def test_failed_capture_is_released_before_error(self):
        capture = Mock()
        capture.isOpened.return_value = False

        with (
            patch(
                "src.led_detection.led_opencl.compute_led_brightness_curve_opencl",
                side_effect=RuntimeError("use CPU"),
            ),
            patch(
                "src.led_detection.led_detector.open_video_capture",
                return_value=(capture, "cpu", None),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "Could not open video"):
                compute_led_brightness_curve("video.mp4")

        capture.release.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
