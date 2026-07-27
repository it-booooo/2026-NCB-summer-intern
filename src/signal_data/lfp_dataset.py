"""Reusable LFP data with lazy, per-channel CSV loading."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from .lfp_processing import (
    LfpFilterSettings,
    LfpSegment,
    prepare_lfp_segment,
    prepare_lfp_signal,
    sample_rate_for_channel,
)
from .source import SignalDataSource, signal_data_source


@dataclass
class LfpDataset:
    """Lazily loaded LFP samples and reusable processed-signal cache."""

    info: dict
    source: SignalDataSource
    _active_channel: int | None = field(default=None, init=False, repr=False)
    _signal_cache: dict[tuple[int, LfpFilterSettings | None], np.ndarray] = field(
        default_factory=dict,
        init=False,
        repr=False,
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

    def _channel_data(self, channel: int):
        channel = int(channel)
        self._active_channel = channel
        return self.source.channel(channel)

    @property
    def time_us(self) -> np.ndarray:
        channel = self._active_channel
        if channel is None:
            configured = self.channels
            if not configured:
                return np.asarray([], dtype=float)
            channel = configured[0]
        return self._channel_data(channel)["time_us"].to_numpy(dtype=float)

    @property
    def record_time_s(self) -> np.ndarray:
        return self.time_us / 1_000_000.0

    @property
    def channels(self) -> list[int]:
        configured = self.info.get("channels") or []
        if configured:
            return [int(channel) for channel in configured]
        return [
            int(channel) for channel in self.info.get("metadata", {}).get("channels", [])
        ]

    def sample_rate_hz(self, channel: int) -> float:
        return sample_rate_for_channel(self.info, self.time_us, int(channel))

    def signal_values(
        self,
        channel: int,
        settings: LfpFilterSettings | None = None,
    ) -> np.ndarray:
        """Return a full-resolution raw or processed channel signal."""
        channel = int(channel)
        column = f"channel_{channel}"
        data = self._channel_data(channel)
        if column not in data:
            raise ValueError(f"LFP CSV does not include channel {channel}.")

        effective_settings = settings if settings and settings.show_filtered else None
        cache_key = (channel, effective_settings)
        if cache_key not in self._signal_cache:
            raw_values = data[column].to_numpy(dtype=float)
            self._signal_cache[cache_key] = prepare_lfp_signal(
                raw_values,
                self.sample_rate_hz(channel),
                effective_settings,
            )
        return self._signal_cache[cache_key]

    def segment(
        self,
        channel: int,
        start_s: float,
        end_s: float,
        settings: LfpFilterSettings | None,
    ) -> LfpSegment:
        """Return a full-resolution time selection from a cached signal."""
        channel = int(channel)
        values = self.signal_values(channel, settings)
        return prepare_lfp_segment(
            self.time_us,
            values,
            self.sample_rate_hz(channel),
            start_s,
            end_s,
            None,
        )
