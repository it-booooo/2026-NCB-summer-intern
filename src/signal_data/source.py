"""Versioned overview and memory-mapped segment access for signal CSV files."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

CACHE_FORMAT_VERSION = 2
OVERVIEW_ALGORITHM_VERSION = 2
DEFAULT_CHUNK_ROWS = 250_000
DEFAULT_OVERVIEW_MAX_POINTS = 5_000
DEFAULT_CACHE_MAX_BYTES = 20 * 1024**3
DEFAULT_CACHE_MAX_AGE_DAYS = 30
DAY_SECONDS = 24 * 60 * 60

_CACHE_CLEANUP_LOCK = threading.Lock()
_CLEANED_CACHE_ROOTS: set[str] = set()


def _remove_cache_directory(path: Path) -> bool:
    claimed = path.with_name(f".{path.name}.{uuid.uuid4().hex}.stale")
    try:
        path.rename(claimed)
    except OSError:
        return False
    shutil.rmtree(claimed, ignore_errors=True)
    return not claimed.exists()


def cleanup_signal_cache(
    cache_root: str | Path,
    *,
    max_bytes: int = DEFAULT_CACHE_MAX_BYTES,
    max_age_days: int = DEFAULT_CACHE_MAX_AGE_DAYS,
    protected_paths: tuple[Path, ...] = (),
    now: float | None = None,
) -> None:
    """Remove abandoned, expired, and oldest excess signal caches."""
    root = Path(cache_root)
    if not root.is_dir():
        return

    current_time = time.time() if now is None else float(now)
    protected = {str(path.resolve()) for path in protected_paths}
    age_cutoff = current_time - max(int(max_age_days), 0) * DAY_SECONDS

    try:
        children = list(root.iterdir())
    except OSError:
        return

    caches = []
    for path in children:
        if not path.is_dir():
            continue
        try:
            if path.name.startswith(".") and path.name.endswith((".tmp", ".stale")):
                if path.stat().st_mtime <= current_time - DAY_SECONDS:
                    shutil.rmtree(path, ignore_errors=True)
                continue
            if not path.name.startswith("signal-"):
                continue

            is_protected = str(path.resolve()) in protected
            access_time = (path / "COMPLETE").stat().st_mtime
            size = sum(
                item.stat().st_size for item in path.iterdir() if item.is_file()
            )
        except OSError:
            continue
        if not is_protected and access_time <= age_cutoff:
            _remove_cache_directory(path)
            continue
        caches.append((access_time, size, path, is_protected))

    total_bytes = sum(size for _access_time, size, _path, _protected in caches)
    byte_limit = max(int(max_bytes), 0)
    removable = [item for item in caches if not item[3]]
    for _access_time, size, path, _protected in sorted(removable):
        if total_bytes <= byte_limit:
            break
        if _remove_cache_directory(path):
            total_bytes -= size


class CacheBuildCancelled(RuntimeError):
    """Raised when cache generation is cancelled by the caller."""


@dataclass(frozen=True)
class SignalOverview:
    time_us: np.ndarray
    values: np.ndarray
    sample_count: int


@dataclass(frozen=True)
class RawSignalSegment:
    time_us: np.ndarray
    values: np.ndarray
    left_index: int
    right_index: int


class SignalDataSource:
    """Build a disk cache lazily and expose overview or indexed raw segments."""

    def __init__(
        self,
        path: str,
        metadata: dict,
        *,
        overview_max_points: int = DEFAULT_OVERVIEW_MAX_POINTS,
        chunk_rows: int = DEFAULT_CHUNK_ROWS,
        cache_root: str | Path | None = None,
    ):
        self.path = str(Path(path).resolve())
        self.metadata = metadata
        self.overview_max_points = max(int(overview_max_points), 2)
        self.chunk_rows = max(int(chunk_rows), 1)
        self.cache_root = (
            Path(cache_root)
            if cache_root is not None
            else Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
            / "PigBehaviorSync"
            / "signal-cache"
        )
        self._cache_locks: dict[int, threading.RLock] = {}
        self._cache_locks_guard = threading.Lock()

    def _identity(self, channel_id: int) -> dict:
        stat = Path(self.path).stat()
        return {
            "cache_format_version": CACHE_FORMAT_VERSION,
            "overview_algorithm_version": OVERVIEW_ALGORITHM_VERSION,
            "source_path": self.path,
            "source_size": stat.st_size,
            "source_mtime_ns": stat.st_mtime_ns,
            "channel_id": int(channel_id),
            "overview_max_points": self.overview_max_points,
        }

    def _cache_path(self, identity: dict) -> Path:
        encoded = json.dumps(identity, sort_keys=True).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()[:24]
        return self.cache_root / f"signal-{digest}"

    def _valid_cache(self, path: Path, identity: dict) -> bool:
        try:
            metadata = json.loads((path / "metadata.json").read_text("utf-8"))
            count = int(metadata["sample_count"])
            overview_count = int(metadata["overview_count"])
            return (
                metadata.get("complete") is True
                and metadata.get("identity") == identity
                and metadata.get("timestamps_monotonic") is True
                and (path / "COMPLETE").is_file()
                and (path / "time_us.bin").stat().st_size == count * 8
                and (path / "values.bin").stat().st_size == count * 4
                and (path / "overview_time_us.bin").stat().st_size
                == overview_count * 8
                and (path / "overview_values.bin").stat().st_size
                == overview_count * 4
            )
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            return False

    def ensure_cache(
        self,
        channel_id: int,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        channel_id = int(channel_id)
        with self._cache_locks_guard:
            channel_lock = self._cache_locks.setdefault(channel_id, threading.RLock())
        with channel_lock:
            return self._ensure_cache(channel_id, cancel_event)

    def _ensure_cache(
        self,
        channel_id: int,
        cancel_event: threading.Event | None,
    ) -> Path:
        identity = self._identity(channel_id)
        final_path = self._cache_path(identity)
        cleanup_key = str(self.cache_root.resolve())
        with _CACHE_CLEANUP_LOCK:
            if cleanup_key not in _CLEANED_CACHE_ROOTS:
                cleanup_signal_cache(
                    self.cache_root,
                    protected_paths=(final_path,),
                )
                _CLEANED_CACHE_ROOTS.add(cleanup_key)
        if self._valid_cache(final_path, identity):
            try:
                (final_path / "COMPLETE").touch()
            except OSError:
                pass
            return final_path

        self.cache_root.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_root / f".{final_path.name}.{uuid.uuid4().hex}.tmp"
        temporary.mkdir()
        try:
            sample_count = self._convert_csv(
                temporary, channel_id, cancel_event=cancel_event
            )
            overview_count = self._build_overview(
                temporary, sample_count, cancel_event=cancel_event
            )
            metadata = {
                "complete": True,
                "identity": identity,
                "sample_count": sample_count,
                "overview_count": overview_count,
                "timestamps_monotonic": True,
            }
            metadata_path = temporary / "metadata.json"
            metadata_path.write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (temporary / "COMPLETE").write_text("complete\n", encoding="ascii")
            self._flush_directory_files(temporary)

            stale = None
            if final_path.exists():
                stale = self.cache_root / f".{final_path.name}.{uuid.uuid4().hex}.stale"
                final_path.rename(stale)
            try:
                temporary.rename(final_path)
            except Exception:
                if stale is not None and stale.exists() and not final_path.exists():
                    stale.rename(final_path)
                raise
            if stale is not None:
                shutil.rmtree(stale, ignore_errors=True)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

        return final_path

    def _convert_csv(
        self,
        directory: Path,
        channel_id: int,
        *,
        cancel_event: threading.Event | None,
    ) -> int:
        channels = [int(item) for item in self.metadata.get("channels", [])]
        if channel_id not in channels:
            raise ValueError(f"CSV does not include channel {channel_id}")
        header_row = self.metadata.get("header_row")
        if header_row is None:
            raise ValueError("CSV missing Time[us] header row")
        channel_column = channels.index(channel_id) + 1
        sample_count = 0
        previous_time = None
        with (
            (directory / "time_us.bin").open("wb") as time_file,
            (directory / "values.bin").open("wb") as value_file,
        ):
            with pd.read_csv(
                self.path,
                skiprows=int(header_row) + 1,
                header=None,
                usecols=[0, channel_column],
                dtype={0: "float64", channel_column: "float32"},
                chunksize=self.chunk_rows,
            ) as chunks:
                for chunk in chunks:
                    self._check_cancel(cancel_event)
                    times = chunk.iloc[:, 0].to_numpy(dtype="<f8", copy=False)
                    values = chunk.iloc[:, 1].to_numpy(dtype="<f4", copy=False)
                    if times.size:
                        if not np.isfinite(times).all():
                            raise ValueError("Signal timestamps must be finite.")
                        if previous_time is not None and times[0] < previous_time:
                            raise ValueError("Signal timestamps move backwards.")
                        if np.any(np.diff(times) < 0):
                            raise ValueError("Signal timestamps move backwards.")
                        previous_time = float(times[-1])
                    time_file.write(times.tobytes())
                    value_file.write(values.tobytes())
                    sample_count += int(times.size)
            time_file.flush()
            value_file.flush()
            os.fsync(time_file.fileno())
            os.fsync(value_file.fileno())
        if sample_count < 2:
            raise ValueError("Signal CSV must contain at least two samples.")
        return sample_count

    def _build_overview(
        self,
        directory: Path,
        sample_count: int,
        *,
        cancel_event: threading.Event | None,
    ) -> int:
        times = np.memmap(
            directory / "time_us.bin", dtype="<f8", mode="r", shape=(sample_count,)
        )
        values = np.memmap(
            directory / "values.bin", dtype="<f4", mode="r", shape=(sample_count,)
        )
        # Match the original chart behavior: take every nth raw sample rather
        # than connecting each bucket's minimum and maximum as a dense zigzag.
        plot_step = max(sample_count // self.overview_max_points, 1)
        overview_count = 0
        try:
            with (
                (directory / "overview_time_us.bin").open("wb") as time_file,
                (directory / "overview_values.bin").open("wb") as value_file,
            ):
                write_batch = max(self.chunk_rows, 1)
                for batch_start in range(0, sample_count, plot_step * write_batch):
                    self._check_cancel(cancel_event)
                    batch_end = min(
                        batch_start + plot_step * write_batch,
                        sample_count,
                    )
                    indices = np.arange(
                        batch_start,
                        batch_end,
                        plot_step,
                        dtype=int,
                    )
                    selected_times = np.asarray(times[indices], dtype="<f8")
                    selected_values = np.asarray(values[indices], dtype="<f4")
                    time_file.write(selected_times.tobytes())
                    value_file.write(selected_values.tobytes())
                    overview_count += int(indices.size)
                time_file.flush()
                value_file.flush()
                os.fsync(time_file.fileno())
                os.fsync(value_file.fileno())
        finally:
            del times
            del values
        return overview_count

    @staticmethod
    def _check_cancel(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise CacheBuildCancelled("Signal cache generation was cancelled.")

    @staticmethod
    def _flush_directory_files(directory: Path) -> None:
        for path in directory.iterdir():
            if path.is_file():
                with path.open("rb+") as stream:
                    os.fsync(stream.fileno())

    def _cache_metadata(
        self,
        channel_id: int,
        cancel_event: threading.Event | None = None,
    ) -> tuple[Path, dict]:
        path = self.ensure_cache(channel_id, cancel_event)
        metadata = json.loads((path / "metadata.json").read_text("utf-8"))
        return path, metadata

    def overview(self, channel_id: int) -> SignalOverview:
        path, metadata = self._cache_metadata(channel_id)
        count = int(metadata["overview_count"])
        mapped_times = np.memmap(
            path / "overview_time_us.bin", dtype="<f8", mode="r", shape=(count,)
        )
        mapped_values = np.memmap(
            path / "overview_values.bin", dtype="<f4", mode="r", shape=(count,)
        )
        try:
            return SignalOverview(
                time_us=np.asarray(mapped_times).copy(),
                values=np.asarray(mapped_values).copy(),
                sample_count=int(metadata["sample_count"]),
            )
        finally:
            del mapped_times
            del mapped_values

    def segment(
        self,
        channel_id: int,
        start_us: float,
        end_us: float,
        cancel_event: threading.Event | None = None,
    ) -> RawSignalSegment:
        self._check_cancel(cancel_event)
        path, metadata = self._cache_metadata(channel_id, cancel_event)
        count = int(metadata["sample_count"])
        times = np.memmap(path / "time_us.bin", dtype="<f8", mode="r", shape=(count,))
        values = np.memmap(path / "values.bin", dtype="<f4", mode="r", shape=(count,))
        left_index = int(np.searchsorted(times, start_us, side="left"))
        right_index = int(np.searchsorted(times, end_us, side="right"))
        self._check_cancel(cancel_event)
        try:
            return RawSignalSegment(
                time_us=np.asarray(times[left_index:right_index]).copy(),
                values=np.asarray(values[left_index:right_index]).copy(),
                left_index=left_index,
                right_index=right_index,
            )
        finally:
            del times
            del values

    def bounds(self, channel_id: int) -> tuple[float, float]:
        path, metadata = self._cache_metadata(channel_id)
        count = int(metadata["sample_count"])
        times = np.memmap(path / "time_us.bin", dtype="<f8", mode="r", shape=(count,))
        try:
            return float(times[0]), float(times[-1])
        finally:
            del times


_SOURCES: dict[tuple[str, int, int, int], SignalDataSource] = {}


def signal_data_source(
    info: dict,
    *,
    overview_max_points: int = DEFAULT_OVERVIEW_MAX_POINTS,
) -> SignalDataSource:
    """Return a shared source keyed by absolute path and source file version."""
    path = Path(info["path"]).resolve()
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size, int(overview_max_points))
    source = _SOURCES.get(key)
    if source is None:
        metadata = info.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("Signal metadata not found in info dictionary.")
        source = SignalDataSource(
            str(path),
            metadata,
            overview_max_points=overview_max_points,
            cache_root=info.get("_signal_cache_root"),
        )
        for old_key in [item for item in _SOURCES if item[0] == str(path)]:
            del _SOURCES[old_key]
        _SOURCES[key] = source
    return source
