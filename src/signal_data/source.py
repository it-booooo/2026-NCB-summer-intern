"""Lazy, channel-addressed access to signal CSV files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .readers import read_signal_csv


@dataclass
class SignalDataSource:
    """Read and retain only channels requested by their channel ID."""

    path: str
    metadata: dict
    _channels: dict[int, pd.DataFrame] = field(default_factory=dict, init=False)

    def channel(self, channel_id: int) -> pd.DataFrame:
        channel_id = int(channel_id)
        if channel_id not in self._channels:
            self._channels[channel_id] = read_signal_csv(
                self.path,
                requested_channels=[channel_id],
                metadata=self.metadata,
            )
        return self._channels[channel_id]


_SOURCES: dict[tuple[str, int, int], SignalDataSource] = {}


def signal_data_source(info: dict) -> SignalDataSource:
    """Return the shared source for the current version of a signal file."""
    path = Path(info["path"]).resolve()
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    source = _SOURCES.get(key)
    if source is None:
        metadata = info.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("Signal metadata not found in info dictionary.")
        source = SignalDataSource(str(path), metadata)
        # Discard stale versions of the same path without affecting other files.
        for old_key in [item for item in _SOURCES if item[0] == str(path)]:
            del _SOURCES[old_key]
        _SOURCES[key] = source
    return source
