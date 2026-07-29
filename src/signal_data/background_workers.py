"""Cancelable signal computations that never touch QWidget or Matplotlib."""

from __future__ import annotations

import threading

import numpy as np
from PySide6.QtCore import QThread, Signal
from scipy.signal import find_peaks

from .lfp_processing import compute_power_spectrum, compute_time_frequency
from .source import CacheBuildCancelled


class SignalWorker(QThread):
    """Base class carrying immutable request and source identities."""

    progress = Signal(object, int)
    completed = Signal(object, object, object)
    failed = Signal(object, object, str)
    canceled = Signal(object, object)

    def __init__(self, request_id, dataset):
        super().__init__()
        self.request_id = request_id
        self.dataset = dataset
        self.source_identity = dataset.source.identity_token()
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def check_cancel(self):
        if self.cancel_event.is_set():
            raise CacheBuildCancelled("Signal operation was cancelled.")

    def report(self, value):
        self.progress.emit(self.request_id, max(0, min(int(value), 100)))

    def execute(self):
        raise NotImplementedError

    def run(self):
        try:
            self.check_cancel()
            result = self.execute()
            self.check_cancel()
        except CacheBuildCancelled:
            self.canceled.emit(self.request_id, self.source_identity)
            return
        except Exception as error:
            self.failed.emit(
                self.request_id,
                self.source_identity,
                str(error),
            )
            return
        self.completed.emit(self.request_id, self.source_identity, result)


class LfpAnalysisWorker(SignalWorker):
    """Load/filter one segment and calculate spectrum data."""

    def __init__(
        self,
        request_id,
        dataset,
        channel,
        start_s,
        end_s,
        settings,
        analysis_type,
    ):
        super().__init__(request_id, dataset)
        self.channel = int(channel)
        self.start_s = float(start_s)
        self.end_s = float(end_s)
        self.settings = settings
        self.analysis_type = analysis_type

    def execute(self):
        self.report(5)
        segment = self.dataset.segment(
            self.channel,
            self.start_s,
            self.end_s,
            self.settings,
            self.cancel_event,
            lambda value: self.report(5 + round(value * 50)),
        )
        self.check_cancel()
        self.report(60)
        if self.analysis_type == "power_spectrum":
            frequencies, power = compute_power_spectrum(
                segment.values,
                segment.sample_rate_hz,
            )
            result = {
                "segment": segment,
                "frequencies": frequencies,
                "power": power,
            }
        elif self.analysis_type == "spectrogram":
            frequencies, times, power = compute_time_frequency(
                segment.values,
                segment.sample_rate_hz,
            )
            result = {
                "segment": segment,
                "frequencies": frequencies,
                "times": times,
                "power": power,
            }
        else:
            raise ValueError(f"Unsupported LFP analysis: {self.analysis_type}")
        self.report(100)
        return result


class LfpSegmentWorker(SignalWorker):
    """Load/filter a segment for a later GUI-side export."""

    def __init__(
        self,
        request_id,
        dataset,
        channel,
        start_s,
        end_s,
        settings,
    ):
        super().__init__(request_id, dataset)
        self.channel = int(channel)
        self.start_s = float(start_s)
        self.end_s = float(end_s)
        self.settings = settings

    def execute(self):
        self.report(5)
        segment = self.dataset.segment(
            self.channel,
            self.start_s,
            self.end_s,
            self.settings,
            self.cancel_event,
            lambda value: self.report(round(value * 100)),
        )
        self.report(100)
        return segment


class LfpExportDataWorker(SignalWorker):
    """Prepare the numeric inputs required by an LFP image export."""

    def __init__(
        self,
        request_id,
        dataset,
        channel,
        start_s,
        end_s,
        settings,
        image_types,
    ):
        super().__init__(request_id, dataset)
        self.channel = int(channel)
        self.start_s = float(start_s)
        self.end_s = float(end_s)
        self.settings = settings
        self.image_types = frozenset(image_types)

    def execute(self):
        self.report(5)
        segment = self.dataset.segment(
            self.channel,
            self.start_s,
            self.end_s,
            self.settings,
            self.cancel_event,
            lambda value: self.report(5 + round(value * 55)),
        )
        result = {"segment": segment}
        self.check_cancel()
        if "power_spectrum" in self.image_types:
            result["power_spectrum"] = compute_power_spectrum(
                segment.values,
                segment.sample_rate_hz,
            )
        self.check_cancel()
        self.report(80)
        if "spectrogram" in self.image_types:
            result["spectrogram"] = compute_time_frequency(
                segment.values,
                segment.sample_rate_hz,
            )
        self.check_cancel()
        self.report(100)
        return result


class PeakDetectionWorker(SignalWorker):
    """Filter a requested interval and return pure peak records."""

    def __init__(
        self,
        request_id,
        dataset,
        channel,
        start_s,
        end_s,
        settings,
        *,
        height_sigma,
        prominence_sigma,
        min_distance_sec,
    ):
        super().__init__(request_id, dataset)
        self.channel = int(channel)
        self.start_s = float(start_s)
        self.end_s = float(end_s)
        self.settings = settings
        self.height_sigma = float(height_sigma)
        self.prominence_sigma = float(prominence_sigma)
        self.min_distance_sec = float(min_distance_sec)

    def execute(self):
        self.report(5)
        segment = self.dataset.segment(
            self.channel,
            self.start_s,
            self.end_s,
            self.settings,
            self.cancel_event,
            lambda value: self.report(5 + round(value * 55)),
        )
        self.check_cancel()
        self.report(65)
        visible = segment.values
        baseline = float(np.nanmedian(visible))
        mad = float(np.nanmedian(np.abs(visible - baseline)))
        sigma = 1.4826 * mad
        if not np.isfinite(sigma) or sigma <= 0.0:
            sigma = float(np.nanstd(visible))
        if not np.isfinite(sigma) or sigma <= 0.0:
            sigma = np.finfo(float).eps
        distance = max(
            1,
            round(segment.sample_rate_hz * self.min_distance_sec),
        )
        prominence = self.prominence_sigma * sigma
        height_delta = self.height_sigma * sigma
        positive, _ = find_peaks(
            visible,
            height=baseline + height_delta,
            prominence=prominence,
            distance=distance,
        )
        self.check_cancel()
        negative, _ = find_peaks(
            -visible,
            height=-baseline + height_delta,
            prominence=prominence,
            distance=distance,
        )
        indices = np.sort(np.concatenate((positive, negative)))
        records = [
            {
                "record_time_s": float(segment.record_time_s[index]),
                "value": float(visible[index]),
                "negative": bool(visible[index] < baseline),
            }
            for index in indices
        ]
        self.report(100)
        return {
            "channel": self.channel,
            "records": records,
        }


class LfpCoarseWorker(SignalWorker):
    """Build an all-channel coarse cache without blocking the GUI."""

    def __init__(self, request_id, dataset, channel, step, settings):
        super().__init__(request_id, dataset)
        self.channel = int(channel)
        self.step = max(int(step), 1)
        self.settings = settings

    def execute(self):
        result = self.dataset.source.coarse(
            self.channel,
            self.step,
            self.settings,
            cancel_event=self.cancel_event,
            progress_callback=lambda value: self.report(round(value * 100)),
        )
        return {
            "channel": self.channel,
            "step": self.step,
            "settings": self.settings,
            "time_us": np.asarray(result.time_us),
            "values": np.asarray(result.values),
        }
