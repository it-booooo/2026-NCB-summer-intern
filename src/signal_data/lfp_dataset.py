"""Reusable LFP data with lazy, per-channel CSV loading."""

from __future__ import annotations

import threading
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


@dataclass
class LfpDataset(SignalDataset):
    """Lazily loaded LFP samples and reusable processed-signal cache."""

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

    def segment(
        self,
        channel: int,
        start_s: float,
        end_s: float,
        settings: LfpFilterSettings | None,
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
            channel, start_us, end_us
        )
        if right_index - left_index < 2:
            raise ValueError("Selected time range is too short for analysis.")

        effective_settings = (
            settings if settings is not None and settings.show_filtered else None
        )
        if effective_settings is None:
            raw = self._raw_segment(channel, start_s, end_s)
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
            cached = self._filtered_segment_cache.get(cache_key)
            if cached is not None:
                self._filtered_segment_cache.move_to_end(cache_key)
                return cached

        sample_rate_hz = self.sample_rate_hz(channel)
        padding = filter_padding_samples(effective_settings, sample_rate_hz)
        loaded_left = max(left_index - padding, 0)
        loaded_right = min(
            right_index + padding,
            self.source.sample_count(channel),
        )
        loaded = self.source.indexed_segment(channel, loaded_left, loaded_right)
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

        raw = self.source.segment(
            int(channel),
            key[1],
            key[2],
            cancel_event=cancel_event,
        )
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
