"""LED detection algorithms and background workers.

Detection algorithms are intentionally imported from ``led_detector`` by callers
that need them so importing the UI does not eagerly load OpenCV.
"""

from .led_worker import LedDetectionWorker

__all__ = ["LedDetectionWorker"]
