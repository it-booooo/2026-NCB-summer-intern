"""Reusable LFP data with lazy, per-channel CSV loading."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import threading

import numpy as np
from .lfp_processing import (
    LfpFilterSettings,
    LfpSegment,
    prepare_lfp_segment,
    prepare_lfp_signal,
    sample_rate_for_channel,
)
from .source import RawSignalSegment, SignalDataSource, signal_data_source

SEGMENT_CACHE_MAX_BYTES = 128 * 1024 * 1024


@dataclass
class LfpDataset:
    """Lazily loaded LFP samples and reusable processed-signal cache."""

    info: dict
    source: SignalDataSource
    _segment_cache: OrderedDict[
        tuple[int, int, int], RawSignalSegment
    ] = field(default_factory=OrderedDict, init=False, repr=False)
    _segment_cache_bytes: int = field(default=0, init=False, repr=False)
    _segment_lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )
    @classmethod
    def from_csv(cls, info: dict) -> LfpDataset:
        path = info.get("path")
        if not path:
            raise ValueError("LFP path not found in info dictionary.")
        metadata = info.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("LFP metadata not found in info dictionary.")
        return cls(info=info, source=signal_data_source(info))

    @property
    def time_us(self) -> np.ndarray:
        configured = self.channels
        if not configured:
            return np.asarray([], dtype=float)
        left, right = self.source.bounds(configured[0])
        return np.asarray([left, right], dtype=float)

    @property
    def channels(self) -> list[int]:
        configured = self.info.get("channels") or []
        if configured:
            return [int(channel) for channel in configured]
        return [
            int(channel) for channel in self.info.get("metadata", {}).get("channels", [])
        ]

    def sample_rate_hz(self, channel: int) -> float:
        return sample_rate_for_channel(
            self.info,
            np.asarray([], dtype=float),
            int(channel),
        )

    def overview_values(
        self,
        channel: int,
        settings: LfpFilterSettings | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        overview = self.source.overview(int(channel))
        values = prepare_lfp_signal(
            overview.values,
            self.sample_rate_hz(channel),
            settings,
        )
        return np.asarray(overview.time_us), values

    def record_bounds_s(self, channel: int) -> tuple[float, float]:
        left, right = self.source.bounds(int(channel))
        return left / 1_000_000.0, right / 1_000_000.0

    def segment(
        self,
        channel: int,
        start_s: float,
        end_s: float,
        settings: LfpFilterSettings | None,
    ) -> LfpSegment:
        """Return a full-resolution time selection from a cached signal."""
        channel = int(channel)
        start_s, end_s = sorted((float(start_s), float(end_s)))
        raw = self._raw_segment(channel, start_s, end_s)
        return prepare_lfp_segment(
            raw.time_us,
            raw.values,
            self.sample_rate_hz(channel),
            start_s,
            end_s,
            settings,
        )

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
