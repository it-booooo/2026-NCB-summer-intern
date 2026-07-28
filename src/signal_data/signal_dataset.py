"""Shared lazy dataset abstraction for signal CSV files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Self

import numpy as np

from .lfp_processing import sample_rate_for_channel
from .source import SignalDataSource, SignalOverview, signal_data_source


@dataclass
class SignalDataset:
    """Own metadata and one shared lazy source for a signal CSV."""

    info: dict
    source: SignalDataSource
    data_label: ClassVar[str] = "Signal"

    @classmethod
    def from_csv(cls, info: dict) -> Self:
        path = info.get("path")
        if not path:
            raise ValueError(f"{cls.data_label} path not found in info dictionary.")
        metadata = info.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError(f"{cls.data_label} metadata not found in info dictionary.")
        return cls(info=info, source=signal_data_source(info))

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

    def overview(self, channel: int) -> SignalOverview:
        return self.source.overview(int(channel))

    def record_bounds_s(self, channel: int) -> tuple[float, float]:
        left, right = self.source.bounds(int(channel))
        return left / 1_000_000.0, right / 1_000_000.0
