"""Cancelable signal computations that never touch QWidget or Matplotlib."""

from __future__ import annotations

import threading

import numpy as np
from PySide6.QtCore import QThread, Signal
from scipy.signal import find_peaks

from .lfp_processing import (
    compute_power_spectrum,
    compute_time_frequency,
    filter_padding_samples,
    prepare_lfp_signal,
)
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
    """Detect peaks with two bounded-memory passes over overlapping chunks."""

    DEFAULT_CHUNK_SAMPLES = 250_000
    PROMINENCE_CONTEXT_SEC = 2.0

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
        chunk_samples=None,
    ):
        super().__init__(request_id, dataset)
        self.channel = int(channel)
        self.start_s = float(start_s)
        self.end_s = float(end_s)
        self.settings = settings
        self.height_sigma = float(height_sigma)
        self.prominence_sigma = float(prominence_sigma)
        self.min_distance_sec = float(min_distance_sec)
        self.chunk_samples = max(
            int(chunk_samples or self.DEFAULT_CHUNK_SAMPLES),
            2,
        )

    def execute(self):
        self.report(5)
        source = self.dataset.source
        left_index, right_index = source.segment_indices(
            self.channel,
            round(self.start_s * 1_000_000.0),
            round(self.end_s * 1_000_000.0),
            self.cancel_event,
        )
        if right_index - left_index < 3:
            raise ValueError("Selected time range is too short for peak detection.")
        sample_rate_hz = float(self.dataset.sample_rate_hz(self.channel))
        distance = max(1, round(sample_rate_hz * self.min_distance_sec))
        prominence_context = max(
            distance,
            round(sample_rate_hz * self.PROMINENCE_CONTEXT_SEC),
        )
        prominence_wlen = 2 * prominence_context + 1

        baseline, sigma = self._global_mean_std(
            left_index,
            right_index,
            sample_rate_hz,
            prominence_context,
        )
        self.check_cancel()
        if not np.isfinite(sigma) or sigma <= 0.0:
            sigma = np.finfo(float).eps
        prominence = self.prominence_sigma * sigma
        height_delta = self.height_sigma * sigma
        candidates = []
        total = right_index - left_index
        for core_left in range(left_index, right_index, self.chunk_samples):
            self.check_cancel()
            core_right = min(core_left + self.chunk_samples, right_index)
            loaded_left = max(core_left - prominence_context, left_index)
            loaded_right = min(core_right + prominence_context, right_index)
            times, values = self._processed_indices(
                loaded_left,
                loaded_right,
                sample_rate_hz,
            )
            positive, positive_properties = find_peaks(
                values,
                height=baseline + height_delta,
                prominence=prominence,
                distance=distance,
                wlen=prominence_wlen,
            )
            negative, negative_properties = find_peaks(
                -values,
                height=-baseline + height_delta,
                prominence=prominence,
                distance=distance,
                wlen=prominence_wlen,
            )
            self._append_owned_candidates(
                candidates,
                positive,
                positive_properties["prominences"],
                values,
                times,
                loaded_left,
                core_left,
                core_right,
                False,
            )
            self._append_owned_candidates(
                candidates,
                negative,
                negative_properties["prominences"],
                values,
                times,
                loaded_left,
                core_left,
                core_right,
                True,
            )
            completed = core_right - left_index
            self.report(50 + round(45 * completed / total))

        accepted = self._deduplicate_candidates(candidates, distance)
        records = [
            {
                "record_time_s": candidate["record_time_s"],
                "value": candidate["value"],
                "negative": candidate["negative"],
            }
            for candidate in accepted
        ]
        self.report(100)
        return {
            "channel": self.channel,
            "records": records,
        }

    def _global_mean_std(
        self,
        left_index,
        right_index,
        sample_rate_hz,
        context_samples,
    ):
        """Merge per-chunk count/mean/M2 values into one global baseline."""

        count = 0
        mean = 0.0
        m2 = 0.0
        total = right_index - left_index
        for core_left in range(left_index, right_index, self.chunk_samples):
            self.check_cancel()
            core_right = min(core_left + self.chunk_samples, right_index)
            loaded_left = max(core_left - context_samples, left_index)
            loaded_right = min(core_right + context_samples, right_index)
            _, loaded_values = self._processed_indices(
                loaded_left,
                loaded_right,
                sample_rate_hz,
            )
            crop_left = core_left - loaded_left
            crop_right = crop_left + (core_right - core_left)
            values = loaded_values[crop_left:crop_right]
            finite = values[np.isfinite(values)]
            chunk_count = int(finite.size)
            if chunk_count:
                chunk_mean = float(np.mean(finite, dtype=np.float64))
                delta = chunk_mean - mean
                combined = count + chunk_count
                chunk_m2 = float(
                    np.sum(
                        (finite.astype(np.float64) - chunk_mean) ** 2,
                        dtype=np.float64,
                    )
                )
                m2 += chunk_m2 + delta * delta * count * chunk_count / combined
                mean += delta * chunk_count / combined
                count = combined
            completed = core_right - left_index
            self.report(5 + round(40 * completed / total))
        if count == 0:
            raise ValueError("Selected signal contains no finite samples.")
        return mean, float(np.sqrt(m2 / count))

    def _processed_indices(self, left_index, right_index, sample_rate_hz):
        effective_settings = (
            self.settings
            if self.settings is not None and self.settings.show_filtered
            else None
        )
        filter_padding = filter_padding_samples(
            effective_settings,
            sample_rate_hz,
        )
        source_count = self.dataset.source.sample_count(self.channel)
        loaded_left = max(left_index - filter_padding, 0)
        loaded_right = min(right_index + filter_padding, source_count)
        raw = self.dataset.source.indexed_segment(
            self.channel,
            loaded_left,
            loaded_right,
            self.cancel_event,
        )
        values = prepare_lfp_signal(
            raw.values,
            sample_rate_hz,
            effective_settings,
        )
        crop_left = left_index - loaded_left
        crop_right = crop_left + (right_index - left_index)
        return (
            np.asarray(raw.time_us[crop_left:crop_right]),
            np.asarray(values[crop_left:crop_right]),
        )

    @staticmethod
    def _append_owned_candidates(
        output,
        local_indices,
        prominences,
        values,
        times,
        loaded_left,
        core_left,
        core_right,
        negative,
    ):
        for local_index, prominence in zip(local_indices, prominences):
            global_index = loaded_left + int(local_index)
            if not core_left <= global_index < core_right:
                continue
            output.append(
                {
                    "index": global_index,
                    "record_time_s": float(times[local_index] / 1_000_000.0),
                    "value": float(values[local_index]),
                    "negative": bool(negative),
                    "prominence": float(prominence),
                }
            )

    @staticmethod
    def _deduplicate_candidates(candidates, distance):
        """Keep the strongest candidate within each global distance window."""

        accepted = []
        buckets = {}
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                -candidate["prominence"],
                -abs(candidate["value"]),
                candidate["index"],
            ),
        )
        for candidate in ordered:
            index = candidate["index"]
            bucket = index // distance
            is_close = any(
                abs(index - accepted_candidate["index"]) < distance
                for nearby_bucket in (bucket - 1, bucket, bucket + 1)
                for accepted_candidate in buckets.get(nearby_bucket, ())
            )
            if is_close:
                continue
            buckets.setdefault(bucket, []).append(candidate)
            accepted.append(candidate)
        return sorted(accepted, key=lambda candidate: candidate["index"])


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
