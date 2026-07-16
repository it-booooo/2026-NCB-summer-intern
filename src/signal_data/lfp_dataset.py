"""Reusable, full-resolution LFP data loaded from one CSV file."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .lfp_processing import (
    LfpFilterSettings,
    LfpSegment,
    prepare_lfp_segment,
    prepare_lfp_signal,
    sample_rate_for_channel,
)
from .readers import read_signal_csv


@dataclass
class LfpDataset:
    """Full-resolution LFP samples and reusable processed-signal cache."""

    info: dict
    data: pd.DataFrame
    _signal_cache: dict[tuple[int, LfpFilterSettings | None], np.ndarray] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    @classmethod
    def from_csv(cls, info: dict) -> "LfpDataset":
        path = info.get("path")
        if not path:
            raise ValueError("LFP path not found in info dictionary.")
        return cls(info=info, data=read_signal_csv(path))

    @property
    def time_us(self) -> np.ndarray:
        return self.data["time_us"].to_numpy(dtype=float)

    @property
    def record_time_s(self) -> np.ndarray:
        return self.time_us / 1_000_000.0

    @property
    def channels(self) -> list[int]:
        configured = self.info.get("channels") or []
        if configured:
            return [int(channel) for channel in configured]
        return [
            int(column.removeprefix("channel_"))
            for column in self.data.columns
            if column.startswith("channel_")
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
        if column not in self.data:
            raise ValueError(f"LFP CSV does not include channel {channel}.")

        effective_settings = settings if settings and settings.show_filtered else None
        cache_key = (channel, effective_settings)
        if cache_key not in self._signal_cache:
            raw_values = self.data[column].to_numpy(dtype=float)
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
