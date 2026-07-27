"""Streaming, deterministic signal CSV fixture generation."""

from __future__ import annotations

import csv
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class SignalFixtureConfig:
    sample_rate_hz: int = 1_000
    duration_s: float = 30.0
    channels: tuple[int, ...] = (2, 5, 260)
    missing_sample_indices: tuple[int, ...] = ()
    duplicate_timestamp_indices: tuple[int, ...] = ()
    discontinuity_after_indices: tuple[int, ...] = ()
    discontinuity_us: int = 2_000_000
    peak_indices: tuple[int, ...] = (2_500, 12_500)
    peak_amplitude: float = 10.0

    @property
    def sample_count(self) -> int:
        return int(round(self.sample_rate_hz * self.duration_s))


def _rows(config: SignalFixtureConfig) -> Iterable[list[str]]:
    missing = set(config.missing_sample_indices)
    duplicates = set(config.duplicate_timestamp_indices)
    discontinuities = set(config.discontinuity_after_indices)
    peaks = set(config.peak_indices)
    step_us = 1_000_000.0 / config.sample_rate_hz
    offset_us = 0
    previous_timestamp = 0

    for index in range(config.sample_count):
        timestamp = int(round(index * step_us)) + offset_us
        if index in duplicates and index:
            timestamp = previous_timestamp

        values = []
        for channel_index, channel in enumerate(config.channels):
            frequency_hz = channel_index + 1
            value = math.sin(2.0 * math.pi * frequency_hz * index / config.sample_rate_hz)
            if index in peaks:
                value += config.peak_amplitude * (channel_index + 1)
            values.append("" if index in missing else f"{value:.8f}")

        yield [str(timestamp), *values]
        previous_timestamp = timestamp
        if index in discontinuities:
            offset_us += config.discontinuity_us


def generate_signal_csv(
    path: str | Path,
    config: SignalFixtureConfig = SignalFixtureConfig(),
    cancel_event: threading.Event | None = None,
) -> int:
    """Write rows incrementally and return the number of data rows written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["Channels", *config.channels])
        writer.writerow(["Sample Rate[Hz]", *([config.sample_rate_hz] * len(config.channels))])
        writer.writerow(["Unit", *(["uV"] * len(config.channels))])
        writer.writerow(["Time[us]", *[f"Channel {channel}" for channel in config.channels]])
        for row in _rows(config):
            if cancel_event is not None and cancel_event.is_set():
                break
            writer.writerow(row)
            written += 1
    return written
