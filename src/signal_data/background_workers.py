"""Cancelable signal computations that never touch QWidget or Matplotlib."""

from __future__ import annotations

import math
import multiprocessing
import os
import sys
import threading
import time
from collections import OrderedDict

import numpy as np
from PySide6.QtCore import QThread, Signal
from scipy.signal import find_peaks, peak_prominences
from scipy.signal._peak_finding_utils import _select_by_peak_distance

from lfp_analysis_process import render_lfp_analysis

from .gpu_backend import (
    chunk_statistics_opencl,
    configured_backend,
    last_peak_operation_error,
    opencl_peak_status,
    peak_candidate_masks_opencl,
    peak_opencl_minimum_samples,
)
from .lfp_processing import (
    LfpSegment,
    filter_padding_samples,
    line_noise_frequencies,
    prepare_lfp_signal,
)
from .peak_display import load_peak_display_samples
from .source import CacheBuildCancelled

MAX_EXPORT_WAVEFORM_POINTS = 200_000
# High DPI keeps the on-screen figure crisp.  The dialog rescales the source
# pixmap only once per resize (not on every paint), so a large image no longer
# stalls the GUI thread -- see ``_HorizontalPixmapScrollArea`` in
# ``src/ui/lfp_analysis.py``.
ANALYSIS_DISPLAY_DPI = 300
_PROCESS_SPAWN_LOCK = threading.Lock()
_PEAK_STATISTICS_CACHE = OrderedDict()
_PEAK_STATISTICS_CACHE_LOCK = threading.RLock()
_PEAK_STATISTICS_CACHE_MAX_ENTRIES = 32


def _normalize_plateau_candidates(values, candidate_mask):
    """Collapse flat local maxima to SciPy's floor-rounded midpoint."""

    signal_values = np.asarray(values, dtype=np.float64)
    mask = np.asarray(candidate_mask, dtype=bool)
    if signal_values.ndim != 1 or mask.shape != signal_values.shape:
        raise ValueError("Peak candidate masks must match a one-dimensional signal.")
    indices = np.flatnonzero(mask)
    if indices.size == 0:
        return np.empty(0, dtype=np.intp)
    breaks = np.flatnonzero(np.diff(indices) > 1)
    group_starts = np.concatenate((np.array([0]), breaks + 1))
    group_ends = np.concatenate((breaks, np.array([indices.size - 1])))
    left_edges = indices[group_starts]
    right_edges = indices[group_ends]
    valid = np.zeros(left_edges.size, dtype=bool)
    interior = np.flatnonzero(
        (left_edges > 0) & (right_edges < signal_values.size - 1)
    )
    valid[interior] = (
        signal_values[left_edges[interior]]
        > signal_values[left_edges[interior] - 1]
    ) & (
        signal_values[right_edges[interior]]
        > signal_values[right_edges[interior] + 1]
    )
    return np.asarray((left_edges[valid] + right_edges[valid]) // 2, dtype=np.intp)


def _finalize_peak_mask(
    values,
    candidate_mask,
    *,
    height,
    prominence,
    distance,
    wlen,
    cancel_check=None,
):
    """Apply SciPy-equivalent plateau, height, distance, and prominence steps."""

    signal_values = np.asarray(values, dtype=np.float64)
    peaks = _normalize_plateau_candidates(signal_values, candidate_mask)
    if peaks.size:
        peaks = peaks[signal_values[peaks] >= float(height)]
    if cancel_check is not None:
        cancel_check()
    if peaks.size > 1:
        keep = _select_by_peak_distance(
            np.ascontiguousarray(peaks, dtype=np.intp),
            np.ascontiguousarray(signal_values[peaks], dtype=np.float64),
            float(distance),
        )
        peaks = peaks[keep]
    if cancel_check is not None:
        cancel_check()
    if peaks.size:
        prominences = peak_prominences(signal_values, peaks, wlen=int(wlen))[0]
        keep = prominences >= float(prominence)
        peaks = peaks[keep]
        prominences = prominences[keep]
    else:
        prominences = np.empty(0, dtype=np.float64)
    if cancel_check is not None:
        cancel_check()
    return peaks, prominences


def _cpu_chunk_statistics(values):
    finite = np.asarray(values)[np.isfinite(values)]
    count = int(finite.size)
    if count == 0:
        return 0, float("nan"), 0.0
    float_values = finite.astype(np.float64, copy=False)
    mean = float(np.mean(float_values, dtype=np.float64))
    m2 = float(np.sum((float_values - mean) ** 2, dtype=np.float64))
    return count, mean, m2


def _merge_statistics(count, mean, m2, right_count, right_mean, right_m2):
    if right_count == 0:
        return count, mean, m2
    combined = count + right_count
    delta = right_mean - mean
    m2 += right_m2 + delta * delta * count * right_count / combined
    mean += delta * right_count / combined
    return combined, mean, m2


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
    notch_display_options=None,
    spectrogram_color_limits_db=None,
    return_metadata=False,
):
    """Run one render process and return its image or complete payload."""
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
            notch_display_options,
            spectrogram_color_limits_db,
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
        # The payload (if any) has already been received above, so the child
        # only needs to run its finalisers and exit.  Bound the wait so a child
        # that fails to terminate can never hang this worker thread forever --
        # the ``finally`` block below force-terminates any lingering process.
        process.join(timeout=10)
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
        return payload if return_metadata else payload["image_png"]
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


class LfpPeakDisplayWorker(SignalWorker):
    """Prepare bounded LFP peak plot samples outside the GUI thread."""

    def __init__(
        self,
        request_id,
        dataset,
        channel,
        peak_records,
        settings,
        *,
        context_sec,
        maximum_points,
        maximum_interval_sec,
    ):
        super().__init__(request_id, dataset)
        self.channel = int(channel)
        self.peak_records = tuple(peak_records)
        self.settings = settings
        self.context_sec = float(context_sec)
        self.maximum_points = int(maximum_points)
        self.maximum_interval_sec = float(maximum_interval_sec)

    def execute(self):
        times, values = load_peak_display_samples(
            self.dataset,
            self.channel,
            self.peak_records,
            self.settings,
            context_sec=self.context_sec,
            maximum_points=self.maximum_points,
            maximum_interval_sec=self.maximum_interval_sec,
            cancel_event=self.cancel_event,
        )
        self.check_cancel()
        return {
            "channel": self.channel,
            "filtered": bool(self.settings and self.settings.show_filtered),
            "times": times,
            "values": values,
        }


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
        spectrogram_color_limits_db=None,
    ):
        super().__init__(request_id, dataset)
        self.channel = int(channel)
        self.start_s = float(start_s)
        self.end_s = float(end_s)
        self.settings = settings
        self.analysis_type = analysis_type
        self.record_time_origin_sec = record_time_origin_sec
        self.spectrogram_color_limits_db = spectrogram_color_limits_db

    def execute(self):
        self.report(5)
        with self.dataset.analysis_values_file(
            self.channel,
            self.start_s,
            self.end_s,
            self.settings,
            self.cancel_event,
            lambda value: self.report(5 + round(value * 45)),
        ) as prepared:
            self.check_cancel()
            self.report(55)
            render_result = self._render_in_process(
                prepared.path,
                prepared.dtype,
                prepared.sample_count,
                prepared.sample_rate_hz,
                prepared.start_time_s,
                prepared.end_time_s,
            )
            self.report(100)
            result = {
                "sample_count": prepared.sample_count,
                "sample_rate_hz": prepared.sample_rate_hz,
                "start_time_s": prepared.start_time_s,
                "end_time_s": prepared.end_time_s,
                "image_png": render_result["image_png"],
            }
            if "spectrogram_color_limits_db" in render_result:
                result["spectrogram_color_limits_db"] = render_result[
                    "spectrogram_color_limits_db"
                ]
            return result

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
            frequency_range_hz=_frequency_plot_range(self.settings),
            notch_display_options=_notch_spectrum_display_options(self.settings),
            spectrogram_color_limits_db=self.spectrogram_color_limits_db,
            return_metadata=True,
        )


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
        spectrogram_color_limits_db=None,
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
        self.spectrogram_color_limits_db = spectrogram_color_limits_db

    def execute(self):
        self.report(5)
        with self.dataset.analysis_values_file(
            self.channel,
            self.start_s,
            self.end_s,
            self.settings,
            self.cancel_event,
            lambda value: self.report(5 + round(value * 55)),
        ) as prepared:
            sample_count = prepared.sample_count
            sample_rate_hz = prepared.sample_rate_hz
            start_time_s = prepared.start_time_s
            end_time_s = prepared.end_time_s
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
                    prepared.path,
                    dtype=np.dtype(prepared.dtype),
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
                    input_path=prepared.path,
                    dtype=prepared.dtype,
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
                    frequency_range_hz=_frequency_plot_range(
                        self.settings
                    ),
                    notch_display_options=_notch_spectrum_display_options(
                        self.settings
                    ),
                    spectrogram_color_limits_db=(
                        self.spectrogram_color_limits_db
                        if image_type == "spectrogram"
                        else None
                    ),
                )
                self.report(
                    65 + round(35 * (index + 1) / len(spectral_types))
                )
            if rendered_images:
                result["rendered_images"] = rendered_images
            self.report(100)
            return result


def _frequency_plot_range(settings):
    """Return the active bandpass bounds used by filtered frequency plots."""
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


def _notch_spectrum_display_options(settings):
    """Return display-only PSD interpolation parameters for an active notch."""

    if (
        settings is None
        or not settings.show_filtered
        or settings.line_noise_method != "notch"
    ):
        return None
    frequencies = line_noise_frequencies(settings)
    if not frequencies:
        return None
    return {
        "frequencies_hz": tuple(float(value) for value in frequencies),
        "quality_factor": float(settings.notch_quality),
    }


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
        backend=None,
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
        self.backend = configured_backend(backend)
        self._fallback_reasons = []
        self._acceleration = None

    def execute(self):
        started = time.perf_counter()
        self._acceleration = {
            "backend": "cpu",
            "statistics_backend": "cpu",
            "candidate_backend": "cpu",
            "gpu_statistics_chunks": 0,
            "gpu_candidate_chunks": 0,
            "cpu_statistics_chunks": 0,
            "cpu_candidate_chunks": 0,
            "elapsed_sec": 0.0,
            "opencl_status": {"checked": False},
            "fallback_reason": None,
            "statistics_cache_hit": False,
            "segment_lookup_sec": 0.0,
            "processed_indices_sec": 0.0,
            "raw_read_sec": 0.0,
            "filtering_sec": 0.0,
            "statistics_sec": 0.0,
            "candidate_stage_sec": 0.0,
            "candidate_mask_sec": 0.0,
            "scipy_peak_sec": 0.0,
            "cpu_peak_finalization_sec": 0.0,
            "candidate_collection_sec": 0.0,
            "deduplicate_sec": 0.0,
            "record_construction_sec": 0.0,
            "finalize_sec": 0.0,
        }
        self.report(5)
        source = self.dataset.source
        lookup_started = time.perf_counter()
        left_index, right_index = source.segment_indices(
            self.channel,
            round(self.start_s * 1_000_000.0),
            round(self.end_s * 1_000_000.0),
            self.cancel_event,
        )
        self._acceleration["segment_lookup_sec"] = (
            time.perf_counter() - lookup_started
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

        statistics_started = time.perf_counter()
        baseline, sigma = self._global_mean_std(
            left_index,
            right_index,
            sample_rate_hz,
            prominence_context,
        )
        self._acceleration["statistics_sec"] = (
            time.perf_counter() - statistics_started
        )
        self.check_cancel()
        if not np.isfinite(sigma) or sigma <= 0.0:
            sigma = np.finfo(float).eps
        prominence = self.prominence_sigma * sigma
        height_delta = self.height_sigma * sigma
        candidates = []
        total = right_index - left_index
        use_opencl_candidates = (
            self.backend == "opencl"
            or (
                self.backend == "auto"
                and total >= peak_opencl_minimum_samples()
            )
        )
        candidate_stage_started = time.perf_counter()
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
            positive_threshold = baseline + height_delta
            negative_threshold = baseline - height_delta
            masks = None
            if use_opencl_candidates:
                try:
                    mask_started = time.perf_counter()
                    masks = peak_candidate_masks_opencl(
                        values,
                        positive_threshold,
                        negative_threshold,
                        requested="opencl",
                    )
                    self._acceleration["candidate_mask_sec"] += (
                        time.perf_counter() - mask_started
                    )
                    self.check_cancel()
                except Exception as error:
                    if self.backend == "opencl":
                        raise
                    self._add_fallback(error)
                    use_opencl_candidates = False
            if masks is None:
                self.check_cancel()
                scipy_started = time.perf_counter()
                positive, positive_properties = find_peaks(
                    values,
                    height=positive_threshold,
                    prominence=prominence,
                    distance=distance,
                    wlen=prominence_wlen,
                )
                self.check_cancel()
                negative, negative_properties = find_peaks(
                    -values,
                    height=-negative_threshold,
                    prominence=prominence,
                    distance=distance,
                    wlen=prominence_wlen,
                )
                self._acceleration["scipy_peak_sec"] += (
                    time.perf_counter() - scipy_started
                )
                self.check_cancel()
                positive_prominences = positive_properties["prominences"]
                negative_prominences = negative_properties["prominences"]
                self._acceleration["cpu_candidate_chunks"] += 1
            else:
                finalization_started = time.perf_counter()
                positive, positive_prominences = _finalize_peak_mask(
                    values,
                    masks[0],
                    height=positive_threshold,
                    prominence=prominence,
                    distance=distance,
                    wlen=prominence_wlen,
                    cancel_check=self.check_cancel,
                )
                negative, negative_prominences = _finalize_peak_mask(
                    -values,
                    masks[1],
                    height=-negative_threshold,
                    prominence=prominence,
                    distance=distance,
                    wlen=prominence_wlen,
                    cancel_check=self.check_cancel,
                )
                self._acceleration["cpu_peak_finalization_sec"] += (
                    time.perf_counter() - finalization_started
                )
                self._acceleration["gpu_candidate_chunks"] += 1
            collection_started = time.perf_counter()
            self._append_owned_candidates(
                candidates,
                positive,
                positive_prominences,
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
                negative_prominences,
                values,
                times,
                loaded_left,
                core_left,
                core_right,
                True,
            )
            self._acceleration["candidate_collection_sec"] += (
                time.perf_counter() - collection_started
            )
            completed = core_right - left_index
            self.report(40 + round(45 * completed / total))

        self.check_cancel()
        self._acceleration["candidate_stage_sec"] = (
            time.perf_counter() - candidate_stage_started
        )
        deduplicate_started = time.perf_counter()
        accepted = self._deduplicate_candidates(candidates, distance)
        self._acceleration["deduplicate_sec"] = (
            time.perf_counter() - deduplicate_started
        )
        self.report(88)
        self.check_cancel()
        records_started = time.perf_counter()
        records = [
            {
                "record_time_s": candidate["record_time_s"],
                "value": candidate["value"],
                "negative": candidate["negative"],
            }
            for candidate in accepted
        ]
        self._acceleration["record_construction_sec"] = (
            time.perf_counter() - records_started
        )
        self._acceleration["finalize_sec"] = (
            self._acceleration["deduplicate_sec"]
            + self._acceleration["record_construction_sec"]
        )
        self._finalize_acceleration(started)
        self.report(92)
        return {
            "channel": self.channel,
            "records": records,
            "acceleration": self._acceleration,
        }

    def _global_mean_std(
        self,
        left_index,
        right_index,
        sample_rate_hz,
        context_samples,
    ):
        """Merge per-chunk count/mean/M2 values into one global baseline."""

        cache_key = None
        if self.backend == "cpu":
            effective_settings = (
                self.settings
                if self.settings is not None and self.settings.show_filtered
                else None
            )
            cache_key = (
                self.source_identity,
                self.channel,
                int(left_index),
                int(right_index),
                float(sample_rate_hz),
                effective_settings,
            )
            with _PEAK_STATISTICS_CACHE_LOCK:
                cached = _PEAK_STATISTICS_CACHE.get(cache_key)
                if cached is not None:
                    _PEAK_STATISTICS_CACHE.move_to_end(cache_key)
                    self._acceleration["statistics_cache_hit"] = True
                    return cached

        count = 0
        mean = 0.0
        m2 = 0.0
        total = right_index - left_index
        use_opencl_statistics = (
            self.backend == "opencl"
            or (
                self.backend == "auto"
                and total >= peak_opencl_minimum_samples()
            )
        )
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
            chunk_statistics = None
            if use_opencl_statistics:
                try:
                    chunk_statistics = chunk_statistics_opencl(
                        values,
                        requested="opencl",
                    )
                    self.check_cancel()
                except Exception as error:
                    if self.backend == "opencl":
                        raise
                    self._add_fallback(error)
                    use_opencl_statistics = False
            if chunk_statistics is None:
                chunk_statistics = _cpu_chunk_statistics(values)
                self._acceleration["cpu_statistics_chunks"] += 1
            else:
                self._acceleration["gpu_statistics_chunks"] += 1
            chunk_count, chunk_mean, chunk_m2 = chunk_statistics
            count, mean, m2 = _merge_statistics(
                count,
                mean,
                m2,
                chunk_count,
                chunk_mean,
                chunk_m2,
            )
            completed = core_right - left_index
            self.report(5 + round(35 * completed / total))
        if count == 0:
            raise ValueError("Selected signal contains no finite samples.")
        result = mean, float(np.sqrt(m2 / count))
        if cache_key is not None:
            with _PEAK_STATISTICS_CACHE_LOCK:
                _PEAK_STATISTICS_CACHE[cache_key] = result
                _PEAK_STATISTICS_CACHE.move_to_end(cache_key)
                while len(_PEAK_STATISTICS_CACHE) > _PEAK_STATISTICS_CACHE_MAX_ENTRIES:
                    _PEAK_STATISTICS_CACHE.popitem(last=False)
        return result

    def _add_fallback(self, error):
        reason = str(error or last_peak_operation_error() or "OpenCL peak operation failed")
        if reason and reason not in self._fallback_reasons:
            self._fallback_reasons.append(reason)

    def _finalize_acceleration(self, started):
        metadata = self._acceleration

        def stage_backend(gpu_key, cpu_key):
            gpu_chunks = metadata[gpu_key]
            cpu_chunks = metadata[cpu_key]
            if gpu_chunks and cpu_chunks:
                return "hybrid"
            return "opencl" if gpu_chunks else "cpu"

        metadata["statistics_backend"] = stage_backend(
            "gpu_statistics_chunks", "cpu_statistics_chunks"
        )
        metadata["candidate_backend"] = stage_backend(
            "gpu_candidate_chunks", "cpu_candidate_chunks"
        )
        stages = {metadata["statistics_backend"], metadata["candidate_backend"]}
        metadata["backend"] = stages.pop() if len(stages) == 1 else "hybrid"
        if metadata["backend"] == "hybrid" or "hybrid" in (
            metadata["statistics_backend"],
            metadata["candidate_backend"],
        ):
            metadata["backend"] = "hybrid"
        metadata["elapsed_sec"] = float(time.perf_counter() - started)
        metadata["fallback_reason"] = (
            "; ".join(self._fallback_reasons) if self._fallback_reasons else None
        )
        if (
            metadata["gpu_statistics_chunks"]
            or metadata["gpu_candidate_chunks"]
            or self._fallback_reasons
        ):
            metadata["opencl_status"] = opencl_peak_status()

    def _processed_indices(self, left_index, right_index, sample_rate_hz):
        processed_started = time.perf_counter()
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
        read_started = time.perf_counter()
        raw = self.dataset.source.indexed_segment(
            self.channel,
            loaded_left,
            loaded_right,
            self.cancel_event,
        )
        self._acceleration["raw_read_sec"] += time.perf_counter() - read_started
        filtering_started = time.perf_counter()
        values = prepare_lfp_signal(
            raw.values,
            sample_rate_hz,
            effective_settings,
            sample_offset=loaded_left,
        )
        self._acceleration["filtering_sec"] += (
            time.perf_counter() - filtering_started
        )
        crop_left = left_index - loaded_left
        crop_right = crop_left + (right_index - left_index)
        result = (
            np.asarray(raw.time_us[crop_left:crop_right]),
            np.asarray(values[crop_left:crop_right]),
        )
        self._acceleration["processed_indices_sec"] += (
            time.perf_counter() - processed_started
        )
        return result

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

    range_completed = Signal(object, object)
    channels_published = Signal(object, object)

    def __init__(
        self, request_id, dataset, channel, step, settings, current_time_s=None
    ):
        super().__init__(request_id, dataset)
        self.channel = int(channel)
        self.step = max(int(step), 1)
        self.settings = settings
        self.current_time_s = current_time_s
        self._priority_channel = int(channel)

    def set_priority_channel(self, channel) -> None:
        """Point the remaining groups at whichever channel is on screen now.

        Called from the GUI thread while the build runs, so this only assigns
        one integer that the worker reads between groups.
        """
        self._priority_channel = int(channel)

    def execute(self):
        priority_index = None
        if self.current_time_s is not None:
            time_us = int(round(float(self.current_time_s) * 1_000_000.0))
            priority_index = self.dataset.source.segment_indices(
                self.channel,
                time_us,
                time_us + 1,
                self.cancel_event,
            )[0]

        def report_range(channel, point_start, point_end, time_us, values):
            self.range_completed.emit(
                self.request_id,
                {
                    "channel": int(channel),
                    "point_start": int(point_start),
                    "point_end": int(point_end),
                    "time_us": np.asarray(time_us),
                    "values": np.asarray(values),
                },
            )

        def report_published(channels):
            self.channels_published.emit(
                self.request_id, [int(channel) for channel in channels]
            )

        result = self.dataset.source.coarse(
            self.channel,
            self.step,
            self.settings,
            cancel_event=self.cancel_event,
            progress_callback=lambda value: self.report(round(value * 100)),
            range_callback=report_range,
            priority_sample_index=priority_index,
            published_callback=report_published,
            priority_channel_provider=lambda: self._priority_channel,
        )
        return {
            "channel": self.channel,
            "step": self.step,
            "settings": self.settings,
            "time_us": np.asarray(result.time_us),
            "values": np.asarray(result.values),
        }


class LfpDisplaySegmentWorker(SignalWorker):
    """Filter one display interval so Qt can repaint before the next interval."""

    def __init__(
        self, request_id, dataset, channel, start_s, end_s, step, settings
    ):
        super().__init__(request_id, dataset)
        self.channel = int(channel)
        self.start_s = float(start_s)
        self.end_s = float(end_s)
        self.step = max(int(step), 1)
        self.settings = settings

    def execute(self):
        left_index, _ = self.dataset.source.segment_indices(
            self.channel,
            int(round(self.start_s * 1_000_000.0)),
            int(round(self.end_s * 1_000_000.0)),
            self.cancel_event,
        )
        segment = self.dataset.segment(
            self.channel,
            self.start_s,
            self.end_s,
            self.settings,
            self.cancel_event,
            dispatch_sample_count=self.dataset.source.sample_count(self.channel),
        )
        self.check_cancel()
        return {
            "point_start": left_index // self.step,
            "time_us": np.asarray(segment.time_us[:: self.step]).copy(),
            "values": np.asarray(segment.values[:: self.step]).copy(),
            "start_s": self.start_s,
            "end_s": self.end_s,
        }
