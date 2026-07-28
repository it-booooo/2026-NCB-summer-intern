"""Reusable LFP data with bounded disk and rolling RAM caches."""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np

from ..plot_steps import resolve_visible_plot_step
from .lfp_processing import (
    LfpFilterSettings,
    LfpSegment,
    filter_padding_samples,
    prepare_lfp_signal,
)
from .signal_dataset import SignalDataset
from .source import RawSignalSegment

SEGMENT_CACHE_MAX_BYTES = 128 * 1024 * 1024
FILTERED_SEGMENT_CACHE_MAX_BYTES = 128 * 1024 * 1024
FILTERED_SEGMENT_CACHE_MAX_ENTRIES = 32
PLAYBACK_WINDOW_SECONDS = 30.0
MAX_FINE_PREFETCH_SECONDS = 120.0


@dataclass
class LfpDataset(SignalDataset):
    """Expose full-range coarse data and exact cached analysis segments."""

    data_label = "LFP"
    _segment_cache: OrderedDict[
        tuple[int, int, int], RawSignalSegment
    ] = field(default_factory=OrderedDict, init=False, repr=False)
    _segment_cache_bytes: int = field(default=0, init=False, repr=False)
    _segment_lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )
    _filtered_segment_cache: OrderedDict[tuple, LfpSegment] = field(
        default_factory=OrderedDict, init=False, repr=False
    )
    _filtered_segment_cache_bytes: int = field(
        default=0, init=False, repr=False
    )
    _playback_generation: int = field(default=0, init=False, repr=False)
    _fine_range_s: tuple[float, float] | None = field(
        default=None, init=False, repr=False
    )
    _playback_settings: LfpFilterSettings | None = field(
        default=None, init=False, repr=False
    )
    _playback_cancel: threading.Event | None = field(
        default=None, init=False, repr=False
    )
    _playback_threads: list[threading.Thread] = field(
        default_factory=list, init=False, repr=False
    )

    @property
    def time_us(self) -> np.ndarray:
        configured = self.channels
        if not configured:
            return np.asarray([], dtype=float)
        left, right = self.source.bounds(configured[0])
        return np.asarray([left, right], dtype=float)

    def overview_values(
        self,
        channel: int,
        settings: LfpFilterSettings | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return a navigation-only filtered approximation of coarse samples."""
        overview = self.overview(channel)
        values = prepare_lfp_signal(
            overview.values,
            self.sample_rate_hz(channel),
            settings,
        )
        return np.asarray(overview.time_us), values

    def coarse_values(
        self,
        channel: int,
        step: int,
        settings: LfpFilterSettings | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return raw or correctly filter-then-sampled full-range navigation data."""
        effective_settings = (
            settings if settings is not None and settings.show_filtered else None
        )
        coarse = self.source.coarse(int(channel), int(step), effective_settings)
        return np.asarray(coarse.time_us), np.asarray(coarse.values)

    def segment(
        self,
        channel: int,
        start_s: float,
        end_s: float,
        settings: LfpFilterSettings | None,
        cancel_event: threading.Event | None = None,
    ) -> LfpSegment:
        """Filter a padded raw interval, then crop to the exact requested indices."""
        channel = int(channel)
        start_s, end_s = sorted((float(start_s), float(end_s)))
        if not np.isfinite(start_s) or not np.isfinite(end_s):
            raise ValueError("Selected time range must be finite.")
        if start_s == end_s:
            raise ValueError("Selected time range is too short.")

        start_us = int(round(start_s * 1_000_000.0))
        end_us = int(round(end_s * 1_000_000.0))
        left_index, right_index = self.source.segment_indices(
            channel, start_us, end_us, cancel_event
        )
        if right_index - left_index < 2:
            raise ValueError("Selected time range is too short for analysis.")

        effective_settings = (
            settings if settings is not None and settings.show_filtered else None
        )
        if effective_settings is None:
            raw = self._raw_segment(channel, start_s, end_s, cancel_event)
            raw_values = prepare_lfp_signal(
                raw.values,
                self.sample_rate_hz(channel),
                None,
            )
            return LfpSegment(
                time_us=np.asarray(raw.time_us, dtype="<f8").copy(),
                record_time_s=np.asarray(
                    raw.time_us / 1_000_000.0, dtype="<f8"
                ).copy(),
                values=np.asarray(raw_values, dtype="<f4").copy(),
                sample_rate_hz=float(self.sample_rate_hz(channel)),
            )

        cache_key = (
            self.source.identity_token(),
            channel,
            left_index,
            right_index,
            effective_settings,
        )
        with self._segment_lock:
            cached = self._cached_filtered_segment(
                channel,
                left_index,
                right_index,
                effective_settings,
            )
            if cached is not None:
                return cached

        sample_rate_hz = self.sample_rate_hz(channel)
        padding = filter_padding_samples(effective_settings, sample_rate_hz)
        loaded_left = max(left_index - padding, 0)
        loaded_right = min(
            right_index + padding,
            self.source.sample_count(channel),
        )
        loaded = self.source.indexed_segment(
            channel, loaded_left, loaded_right, cancel_event
        )
        filtered_values = prepare_lfp_signal(
            loaded.values,
            sample_rate_hz,
            effective_settings,
        )
        crop_left = left_index - loaded_left
        crop_right = crop_left + (right_index - left_index)
        result = LfpSegment(
            time_us=np.asarray(
                loaded.time_us[crop_left:crop_right], dtype=float
            ).copy(),
            record_time_s=np.asarray(
                loaded.time_us[crop_left:crop_right] / 1_000_000.0,
                dtype=float,
            ).copy(),
            values=np.asarray(
                filtered_values[crop_left:crop_right], dtype=float
            ).copy(),
            sample_rate_hz=float(sample_rate_hz),
        )
        self._store_filtered_segment(cache_key, result)
        return result

    def update_playback_window(
        self,
        record_time_s: float,
        settings: LfpFilterSettings | None,
    ) -> None:
        """Keep previous/current/next aligned windows warm for all channels."""
        record_time_s = float(record_time_s)
        if not np.isfinite(record_time_s):
            return
        window_index = math.floor(record_time_s / PLAYBACK_WINDOW_SECONDS)
        self._schedule_fine_range(
            max((window_index - 1) * PLAYBACK_WINDOW_SECONDS, 0.0),
            (window_index + 2) * PLAYBACK_WINDOW_SECONDS,
            settings,
        )

    def update_visible_range(
        self,
        start_s: float,
        end_s: float,
        settings: LfpFilterSettings | None,
    ) -> bool:
        """Preload all channels around a reasonably sized visible interval."""
        start_s, end_s = sorted((float(start_s), float(end_s)))
        width = end_s - start_s
        if (
            not np.isfinite(start_s)
            or not np.isfinite(end_s)
            or width <= 0
            or width > MAX_FINE_PREFETCH_SECONDS
        ):
            return False
        bounds = self.record_bounds_s(self.channels[0])
        self._schedule_fine_range(
            max(start_s - width, bounds[0]),
            min(end_s + width, bounds[1]),
            settings,
        )
        return True

    def _schedule_fine_range(
        self,
        start_s: float,
        end_s: float,
        settings: LfpFilterSettings | None,
    ) -> None:
        """Replace the rolling all-channel fine cache in a daemon worker."""
        effective_settings = (
            settings if settings is not None and settings.show_filtered else None
        )
        with self._segment_lock:
            if (
                self._fine_range_s is not None
                and self._fine_range_s[0] <= start_s
                and self._fine_range_s[1] >= end_s
                and self._playback_settings == effective_settings
            ):
                return
            if self._playback_cancel is not None:
                self._playback_cancel.set()
            cancel = threading.Event()
            self._playback_cancel = cancel
            self._playback_generation += 1
            generation = self._playback_generation
            self._fine_range_s = (start_s, end_s)
            self._playback_settings = effective_settings

        windows = [(start_s, end_s)]
        self._evict_outside_playback_windows(windows, effective_settings)

        def preload() -> None:
            completed = False
            try:
                for start_s, end_s in windows:
                    for channel in self.channels:
                        if cancel.is_set():
                            return
                        self._raw_segment(
                            channel, start_s, end_s, cancel
                        )
                        if effective_settings is not None:
                            self.segment(
                                channel,
                                start_s,
                                end_s,
                                effective_settings,
                                cancel,
                            )
                completed = True
            except (OSError, RuntimeError, ValueError):
                return
            finally:
                with self._segment_lock:
                    if generation == self._playback_generation:
                        self._playback_cancel = None
                        if not completed:
                            self._fine_range_s = None
                            self._playback_settings = None

        worker = threading.Thread(
            target=preload,
            name="lfp-playback-cache",
            daemon=True,
        )
        with self._segment_lock:
            self._playback_threads = [
                item for item in self._playback_threads if item.is_alive()
            ]
            self._playback_threads.append(worker)
        worker.start()

    def _evict_outside_playback_windows(
        self,
        windows: list[tuple[float, float]],
        settings: LfpFilterSettings | None,
    ) -> None:
        allowed_us = {
            (
                int(round(start * 1_000_000.0)),
                int(round(end * 1_000_000.0)),
            )
            for start, end in windows
        }
        allowed_filtered = set()
        if settings is not None:
            for channel in self.channels:
                for start_s, end_s in windows:
                    left, right = self.source.segment_indices(
                        channel,
                        start_s * 1_000_000.0,
                        end_s * 1_000_000.0,
                    )
                    allowed_filtered.add(
                        (int(channel), left, right, settings)
                    )
        with self._segment_lock:
            for key in list(self._segment_cache):
                if (key[1], key[2]) not in allowed_us:
                    removed = self._segment_cache.pop(key)
                    self._segment_cache_bytes -= int(
                        removed.time_us.nbytes + removed.values.nbytes
                    )
            for key in list(self._filtered_segment_cache):
                if (key[1], key[2], key[3], key[4]) not in allowed_filtered:
                    removed = self._filtered_segment_cache.pop(key)
                    self._filtered_segment_cache_bytes -= (
                        self._lfp_segment_bytes(removed)
                    )

    def close(self, *, wait: bool = False) -> None:
        with self._segment_lock:
            if self._playback_cancel is not None:
                self._playback_cancel.set()
                self._playback_cancel = None
            self._playback_generation += 1
            self._fine_range_s = None
            self._playback_settings = None
            threads = list(self._playback_threads)
        if wait:
            for thread in threads:
                if thread is not threading.current_thread():
                    thread.join(timeout=10)
        with self._segment_lock:
            self._playback_threads = [
                thread for thread in self._playback_threads if thread.is_alive()
            ]

    def wait_for_playback_cache(self, timeout: float = 10.0) -> bool:
        """Wait for current preloading without cancelling it (mainly for tests)."""
        deadline = time.monotonic() + max(float(timeout), 0.0)
        with self._segment_lock:
            threads = list(self._playback_threads)
        for thread in threads:
            remaining = max(deadline - time.monotonic(), 0.0)
            thread.join(timeout=remaining)
        return not any(thread.is_alive() for thread in threads)

    def clear_memory_cache(self) -> None:
        """Drop raw and filtered RAM segments without touching disk memmaps."""
        with self._segment_lock:
            self._segment_cache.clear()
            self._segment_cache_bytes = 0
            self._filtered_segment_cache.clear()
            self._filtered_segment_cache_bytes = 0

    def _store_filtered_segment(self, key: tuple, segment: LfpSegment) -> None:
        size = int(
            segment.time_us.nbytes
            + segment.record_time_s.nbytes
            + segment.values.nbytes
        )
        if size > FILTERED_SEGMENT_CACHE_MAX_BYTES:
            return
        with self._segment_lock:
            existing = self._filtered_segment_cache.pop(key, None)
            if existing is not None:
                self._filtered_segment_cache_bytes -= self._lfp_segment_bytes(
                    existing
                )
            self._filtered_segment_cache[key] = segment
            self._filtered_segment_cache_bytes += size
            while self._filtered_segment_cache and (
                len(self._filtered_segment_cache)
                > FILTERED_SEGMENT_CACHE_MAX_ENTRIES
                or self._filtered_segment_cache_bytes
                > FILTERED_SEGMENT_CACHE_MAX_BYTES
            ):
                _, removed = self._filtered_segment_cache.popitem(last=False)
                self._filtered_segment_cache_bytes -= self._lfp_segment_bytes(
                    removed
                )

    def _cached_filtered_segment(
        self,
        channel: int,
        left_index: int,
        right_index: int,
        settings: LfpFilterSettings,
    ) -> LfpSegment | None:
        """Return an exact cache hit or a view cropped from a covering entry."""
        identity = self.source.identity_token()
        exact_key = (identity, channel, left_index, right_index, settings)
        exact = self._filtered_segment_cache.get(exact_key)
        if exact is not None:
            self._filtered_segment_cache.move_to_end(exact_key)
            return exact

        for key in list(reversed(self._filtered_segment_cache)):
            if (
                key[0] == identity
                and key[1] == channel
                and key[2] <= left_index
                and key[3] >= right_index
                and key[4] == settings
            ):
                cached = self._filtered_segment_cache[key]
                self._filtered_segment_cache.move_to_end(key)
                crop_left = left_index - key[2]
                crop_right = crop_left + (right_index - left_index)
                return LfpSegment(
                    time_us=cached.time_us[crop_left:crop_right],
                    record_time_s=cached.record_time_s[crop_left:crop_right],
                    values=cached.values[crop_left:crop_right],
                    sample_rate_hz=cached.sample_rate_hz,
                )
        return None

    @staticmethod
    def _lfp_segment_bytes(segment: LfpSegment) -> int:
        return int(
            segment.time_us.nbytes
            + segment.record_time_s.nbytes
            + segment.values.nbytes
        )

    def plot_segment(
        self,
        channel: int,
        start_s: float,
        end_s: float,
        configured_step: int | None,
        plot_width_px: float,
        settings: LfpFilterSettings | None,
    ) -> tuple[np.ndarray, np.ndarray, int]:
        """Return plot-ready samples while preserving full-resolution filtering."""
        channel = int(channel)
        start_s, end_s = sorted((float(start_s), float(end_s)))
        start_us = int(round(start_s * 1_000_000.0))
        end_us = int(round(end_s * 1_000_000.0))
        left, right = self.source.segment_indices(channel, start_us, end_us)
        stride = resolve_visible_plot_step(
            right - left, configured_step, plot_width_px
        )

        if settings is not None and settings.show_filtered:
            full = self.segment(channel, start_s, end_s, settings)
            return (
                np.asarray(full.record_time_s[::stride]),
                np.asarray(full.values[::stride]),
                stride,
            )

        raw = self.source.sampled_segment(
            channel, start_us, end_us, stride
        )
        return raw.time_us / 1_000_000.0, raw.values, stride

    @staticmethod
    def _segment_key(channel: int, start_s: float, end_s: float):
        return (
            int(channel),
            int(round(start_s * 1_000_000.0)),
            int(round(end_s * 1_000_000.0)),
        )

    def _raw_segment(
        self,
        channel: int,
        start_s: float,
        end_s: float,
        cancel_event: threading.Event | None = None,
    ) -> RawSignalSegment:
        start_s, end_s = sorted((float(start_s), float(end_s)))
        key = self._segment_key(channel, start_s, end_s)
        with self._segment_lock:
            cached = self._segment_cache.get(key)
            if cached is not None:
                self._segment_cache.move_to_end(key)
                return cached
            for cached_key in list(reversed(self._segment_cache)):
                if (
                    cached_key[0] == int(channel)
                    and cached_key[1] <= key[1]
                    and cached_key[2] >= key[2]
                ):
                    covering = self._segment_cache[cached_key]
                    self._segment_cache.move_to_end(cached_key)
                    left = int(
                        np.searchsorted(
                            covering.time_us, key[1], side="left"
                        )
                    )
                    right = int(
                        np.searchsorted(
                            covering.time_us, key[2], side="right"
                        )
                    )
                    return RawSignalSegment(
                        time_us=covering.time_us[left:right],
                        values=covering.values[left:right],
                        left_index=covering.left_index + left,
                        right_index=covering.left_index + right,
                    )

        raw = self.source.segment(
            int(channel),
            key[1],
            key[2],
            cancel_event=cancel_event,
        )
        if raw.values.size == 0:
            return raw
        size = int(raw.time_us.nbytes + raw.values.nbytes)
        if size > SEGMENT_CACHE_MAX_BYTES:
            return raw
        with self._segment_lock:
            existing = self._segment_cache.get(key)
            if existing is not None:
                self._segment_cache.move_to_end(key)
                return existing
            self._segment_cache[key] = raw
            self._segment_cache_bytes += size
            while (
                self._segment_cache
                and self._segment_cache_bytes > SEGMENT_CACHE_MAX_BYTES
            ):
                _, removed = self._segment_cache.popitem(last=False)
                self._segment_cache_bytes -= int(
                    removed.time_us.nbytes + removed.values.nbytes
                )
        return raw
