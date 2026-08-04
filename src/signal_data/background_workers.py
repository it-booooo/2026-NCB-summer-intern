"""Cancelable signal computations that never touch QWidget or Matplotlib."""

from __future__ import annotations

import math
import multiprocessing
import os
import sys
import tempfile
import threading

import numpy as np
from PySide6.QtCore import QThread, Signal
from scipy.signal import find_peaks

from .lfp_processing import (
    LfpSegment,
    filter_padding_samples,
    prepare_lfp_signal,
)
from lfp_analysis_process import render_lfp_analysis
from .source import CacheBuildCancelled


MAX_EXPORT_WAVEFORM_POINTS = 200_000
ANALYSIS_DISPLAY_DPI = 300
_PROCESS_SPAWN_LOCK = threading.Lock()


def _render_analysis_file(
    *,
    input_path,
    dtype,
    sample_count,
    sample_rate_hz,
    analysis_type,
    channel,
    start_time_s,
    end_time_s,
    record_time_origin_sec,
    cancel_event,
    dpi=100,
    annotation=None,
    frequency_range_hz=None,
):
    """Run one render process and return only its encoded static image."""
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=render_lfp_analysis,
        args=(
            sender,
            input_path,
            dtype,
            sample_count,
            sample_rate_hz,
            analysis_type,
            channel,
            start_time_s,
            end_time_s,
            record_time_origin_sec,
            dpi,
            annotation,
            frequency_range_hz,
        ),
        name=f"lfp-{analysis_type}",
        daemon=True,
    )
    payload = None
    try:
        with _PROCESS_SPAWN_LOCK:
            original_sys_path = list(sys.path)
            sys.path[:] = [
                entry
                for entry in original_sys_path
                if os.path.basename(
                    os.path.normpath(str(entry))
                ).lower()
                != "cv2"
            ]
            try:
                process.start()
            finally:
                sys.path[:] = original_sys_path
        sender.close()
        while process.is_alive():
            if cancel_event.is_set():
                process.terminate()
                process.join(timeout=5)
                raise CacheBuildCancelled("LFP analysis was cancelled.")
            if receiver.poll(0.05):
                try:
                    payload = receiver.recv()
                except EOFError:
                    payload = None
                break
        process.join()
        if payload is None and receiver.poll():
            try:
                payload = receiver.recv()
            except EOFError:
                payload = None
        if payload is None:
            raise RuntimeError(
                "LFP analysis process exited without a result "
                f"(exit code {process.exitcode})."
            )
        if not payload.get("ok"):
            raise RuntimeError(
                payload.get("error", "LFP analysis process failed.")
            )
        return payload["image_png"]
    finally:
        sender.close()
        receiver.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)


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
        del result


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
        record_time_origin_sec=None,
    ):
        super().__init__(request_id, dataset)
        self.channel = int(channel)
        self.start_s = float(start_s)
        self.end_s = float(end_s)
        self.settings = settings
        self.analysis_type = analysis_type
        self.record_time_origin_sec = record_time_origin_sec

    def execute(self):
        self.report(5)
        descriptor, input_path = tempfile.mkstemp(
            prefix="lfp-analysis-",
            suffix=".bin",
        )
        os.close(descriptor)
        try:
            (
                sample_count,
                sample_rate_hz,
                start_time_s,
                end_time_s,
                dtype,
            ) = self.dataset.write_analysis_values(
                input_path,
                self.channel,
                self.start_s,
                self.end_s,
                self.settings,
                self.cancel_event,
                lambda value: self.report(5 + round(value * 45)),
            )
            self.check_cancel()
            self.report(55)
            image_png = self._render_in_process(
                input_path,
                dtype,
                sample_count,
                sample_rate_hz,
                start_time_s,
                end_time_s,
            )
            self.report(100)
            return {
                "sample_count": sample_count,
                "sample_rate_hz": sample_rate_hz,
                "start_time_s": start_time_s,
                "end_time_s": end_time_s,
                "image_png": image_png,
            }
        finally:
            try:
                os.unlink(input_path)
            except FileNotFoundError:
                pass

    def _render_in_process(
        self,
        input_path,
        dtype,
        sample_count,
        sample_rate_hz,
        start_time_s,
        end_time_s,
    ):
        return _render_analysis_file(
            input_path=input_path,
            dtype=dtype,
            sample_count=sample_count,
            sample_rate_hz=sample_rate_hz,
            analysis_type=self.analysis_type,
            channel=self.channel,
            start_time_s=start_time_s,
            end_time_s=end_time_s,
            record_time_origin_sec=self.record_time_origin_sec,
            cancel_event=self.cancel_event,
            dpi=ANALYSIS_DISPLAY_DPI,
            frequency_range_hz=_spectrogram_frequency_range(self.settings),
        )


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
        record_time_origin_sec=None,
        image_dpi=300,
        annotation=None,
    ):
        super().__init__(request_id, dataset)
        self.channel = int(channel)
        self.start_s = float(start_s)
        self.end_s = float(end_s)
        self.settings = settings
        self.image_types = frozenset(image_types)
        self.record_time_origin_sec = record_time_origin_sec
        self.image_dpi = int(image_dpi)
        self.annotation = annotation

    def execute(self):
        self.report(5)
        descriptor, input_path = tempfile.mkstemp(
            prefix="lfp-export-",
            suffix=".bin",
        )
        os.close(descriptor)
        try:
            (
                sample_count,
                sample_rate_hz,
                start_time_s,
                end_time_s,
                dtype,
            ) = self.dataset.write_analysis_values(
                input_path,
                self.channel,
                self.start_s,
                self.end_s,
                self.settings,
                self.cancel_event,
                lambda value: self.report(5 + round(value * 55)),
            )
            result = {
                "sample_count": sample_count,
                "sample_rate_hz": sample_rate_hz,
                "start_time_s": start_time_s,
                "end_time_s": end_time_s,
            }
            self.check_cancel()
            if "waveform" in self.image_types:
                stride = max(
                    1,
                    math.ceil(
                        sample_count / MAX_EXPORT_WAVEFORM_POINTS
                    ),
                )
                sampled = self.dataset.source.sampled_segment(
                    self.channel,
                    round(self.start_s * 1_000_000.0),
                    round(self.end_s * 1_000_000.0),
                    stride,
                    self.cancel_event,
                )
                values = np.memmap(
                    input_path,
                    dtype=np.dtype(dtype),
                    mode="r",
                    shape=(sample_count,),
                )
                waveform_values = np.asarray(
                    values[::stride],
                    dtype="<f4",
                ).copy()
                del values
                usable = min(
                    sampled.time_us.size,
                    waveform_values.size,
                )
                result["waveform"] = LfpSegment(
                    time_us=np.asarray(sampled.time_us[:usable]),
                    record_time_s=np.asarray(
                        sampled.time_us[:usable] / 1_000_000.0
                    ),
                    values=waveform_values[:usable],
                    sample_rate_hz=sample_rate_hz,
                )
                del sampled, waveform_values

            rendered_images = {}
            spectral_types = [
                image_type
                for image_type in ("power_spectrum", "spectrogram")
                if image_type in self.image_types
            ]
            for index, image_type in enumerate(spectral_types):
                self.check_cancel()
                rendered_images[image_type] = _render_analysis_file(
                    input_path=input_path,
                    dtype=dtype,
                    sample_count=sample_count,
                    sample_rate_hz=sample_rate_hz,
                    analysis_type=image_type,
                    channel=self.channel,
                    start_time_s=start_time_s,
                    end_time_s=end_time_s,
                    record_time_origin_sec=self.record_time_origin_sec,
                    cancel_event=self.cancel_event,
                    dpi=self.image_dpi,
                    annotation=self.annotation,
                    frequency_range_hz=_spectrogram_frequency_range(
                        self.settings
                    ),
                )
                self.report(
                    65 + round(35 * (index + 1) / len(spectral_types))
                )
            if rendered_images:
                result["rendered_images"] = rendered_images
            self.report(100)
            return result
        finally:
            try:
                os.unlink(input_path)
            except FileNotFoundError:
                pass


def _spectrogram_frequency_range(settings):
    """Return the active bandpass bounds used by a filtered spectrogram."""
    if (
        settings is None
        or not settings.show_filtered
        or not settings.bandpass_enabled
    ):
        return None
    return (
        float(settings.bandpass_low_hz),
        float(settings.bandpass_high_hz),
    )


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
            sample_offset=loaded_left,
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
