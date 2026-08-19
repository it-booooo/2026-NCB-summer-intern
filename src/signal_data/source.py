"""Atomic multi-channel memmap, coarse, and indexed segment caches."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from importlib import import_module
from pathlib import Path

import numpy as np

# pyarrow defaults to the mimalloc allocator, which keeps freed arenas mapped
# instead of returning them to the OS.  After a first-time CSV import that peaks
# at several hundred MB of transient parse buffers, mimalloc leaves that peak
# resident for the life of the process (release_unused() reclaims almost none of
# it), so importing a 20-hour recording left ~2 GB stuck in RAM even though the
# on-disk cache is a fraction of that.  The "system" backend returns freed
# memory promptly with no measurable parse-speed cost, so the working set falls
# back to baseline once conversion finishes.  This must be set before pyarrow is
# first imported (the backend is fixed at pool initialization); pyarrow is only
# ever imported lazily inside this module, so setting it here at import time
# always runs first.  setdefault leaves an explicit override in place.
os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")

CACHE_FORMAT_VERSION = 3
OVERVIEW_ALGORITHM_VERSION = 3
FILTER_COARSE_ALGORITHM_VERSION = 5
DEFAULT_CHUNK_ROWS = 250_000
# Bytes per newline-aligned window handed to pyarrow's multi-threaded CSV
# parser.  Each window is read, concatenated with the previous remainder, and
# parsed, so a few copies of this size are live at once -- the dominant driver
# of peak memory during conversion.  32 MiB keeps every core busy while holding
# the working-set spike of a 20-hour import near ~1 GB instead of ~3 GB; a
# whole-file parse would instead hold the entire recording (~3 GB) in RAM.
PYARROW_CSV_BLOCK_BYTES = 32 * 1024 * 1024
# One filtered coarse batch is sized by its working set instead of by row
# count.  A 20-hour recording resolves to a plot step near 9000, so the old
# ``chunk_rows // step`` rule produced 27-point batches and thousands of tiny
# dispatches, costing 28 ns per sample against 18 ns at a megabyte-scale batch.
# Throughput flattens right about here, so a larger batch would only coarsen
# the incremental repaint and hold more memory for nothing.
COARSE_FILTER_BATCH_SAMPLES = 1024 * 1024
COARSE_FILTER_BATCH_BYTES = 64 * 1024 * 1024
# Channels filtered in one call share the regression design matrix, which is
# where the multi-channel speedup comes from: eight channels of a megabyte each
# reach 12 ns per sample.  Grouping rather than taking every channel at once
# bounds the working set and limits how much a cancelled build throws away.
COARSE_CHANNEL_GROUP = 8
DEFAULT_OVERVIEW_MAX_POINTS = 5_000
DEFAULT_CACHE_MAX_BYTES = 20 * 1024 * 1024 * 1024
DEFAULT_CACHE_MAX_AGE_DAYS = 30
DAY_SECONDS = 24 * 60 * 60
ANALYSIS_FILTER_CACHE_PREFIX = "analysis-filter-"
SIGNAL_CACHE_PREFIXES = (
    "signal-",
    "coarse-",
    ANALYSIS_FILTER_CACHE_PREFIX,
)

_CACHE_CLEANUP_LOCK = threading.RLock()
_CLEANED_CACHE_ROOTS: set[str] = set()
_ACTIVE_CACHE_PATHS: dict[str, int] = {}


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
    cache_prefixes: tuple[str, ...] | None = None,
) -> None:
    """Remove abandoned, expired, and oldest excess signal caches."""
    root = Path(cache_root)
    if not root.is_dir():
        return

    current_time = time.time() if now is None else float(now)
    protected = {str(Path(path).resolve()) for path in protected_paths}
    abandoned_cutoff = current_time - DAY_SECONDS
    age_cutoff = current_time - max(int(max_age_days), 0) * DAY_SECONDS
    accepted_prefixes = (
        SIGNAL_CACHE_PREFIXES
        if cache_prefixes is None
        else tuple(cache_prefixes)
    )

    with _CACHE_CLEANUP_LOCK:
        protected.update(_ACTIVE_CACHE_PATHS)
        try:
            children = list(root.iterdir())
        except OSError:
            return

        caches = []
        for path in children:
            if not path.is_dir():
                continue
            try:
                is_protected = str(path.resolve()) in protected
                if path.name.startswith(".") and path.name.endswith(
                    (".tmp", ".stale")
                ):
                    temporary_name = path.name[1:]
                    matching_temporary = cache_prefixes is None or any(
                        temporary_name.startswith(prefix)
                        for prefix in accepted_prefixes
                    )
                    if (
                        matching_temporary
                        and not is_protected
                        and path.stat().st_mtime <= abandoned_cutoff
                    ):
                        shutil.rmtree(path, ignore_errors=True)
                    continue
                if not path.name.startswith(accepted_prefixes):
                    continue
                complete = path / "COMPLETE"
                if not complete.is_file():
                    if not is_protected and path.stat().st_mtime <= abandoned_cutoff:
                        _remove_cache_directory(path)
                    continue
                access_time = complete.stat().st_mtime
                size = sum(
                    item.stat().st_size
                    for item in path.rglob("*")
                    if item.is_file()
                )
            except OSError:
                continue
            if not is_protected and access_time <= age_cutoff:
                _remove_cache_directory(path)
                continue
            caches.append((access_time, size, path, is_protected))

        total_bytes = sum(size for _access, size, _path, _protected in caches)
        byte_limit = max(int(max_bytes), 0)
        for _access, size, path, is_protected in sorted(caches):
            if total_bytes <= byte_limit:
                break
            if not is_protected and _remove_cache_directory(path):
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
    """Own one shared time memmap and one value memmap per CSV channel."""

    def __init__(
        self,
        path: str,
        metadata: dict,
        *,
        overview_max_points: int = DEFAULT_OVERVIEW_MAX_POINTS,
        chunk_rows: int = DEFAULT_CHUNK_ROWS,
        coarse_batch_bytes: int = COARSE_FILTER_BATCH_BYTES,
        cache_root: str | Path | None = None,
    ):
        self.path = str(Path(path).resolve())
        self.metadata = metadata
        self.overview_max_points = max(int(overview_max_points), 2)
        self.chunk_rows = max(int(chunk_rows), 1)
        self.coarse_batch_bytes = max(int(coarse_batch_bytes), 8)
        self.cache_root = (
            Path(cache_root)
            if cache_root is not None
            else Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
            / "PigBehaviorSync"
            / "signal-cache"
        )
        self._build_lock = threading.RLock()
        self._cache_build_locks_guard = threading.Lock()
        self._cache_build_locks: dict[str, threading.RLock] = {}

    @property
    def channels(self) -> list[int]:
        return [int(item) for item in self.metadata.get("channels", [])]

    def _identity(self) -> dict:
        stat = Path(self.path).stat()
        return {
            "cache_format_version": CACHE_FORMAT_VERSION,
            "overview_algorithm_version": OVERVIEW_ALGORITHM_VERSION,
            "source_path": self.path,
            "source_size": stat.st_size,
            "source_mtime_ns": stat.st_mtime_ns,
            "channels": self.channels,
            "overview_max_points": self.overview_max_points,
        }

    @staticmethod
    def _digest(identity: dict) -> str:
        encoded = json.dumps(identity, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:24]

    def _cache_path(self, identity: dict) -> Path:
        return self.cache_root / f"signal-{self._digest(identity)}"

    @staticmethod
    def _value_name(channel: int) -> str:
        return f"channel_{int(channel)}.bin"

    @staticmethod
    def _overview_name(channel: int) -> str:
        return f"overview_channel_{int(channel)}.bin"

    def _valid_cache(self, path: Path, identity: dict) -> bool:
        try:
            metadata = json.loads((path / "metadata.json").read_text("utf-8"))
            count = int(metadata["sample_count"])
            overview_count = int(metadata["overview_count"])
            if not (
                metadata.get("complete") is True
                and metadata.get("identity") == identity
                and metadata.get("timestamps_monotonic") is True
                and (path / "COMPLETE").is_file()
                and (path / "time_us.bin").stat().st_size == count * 8
                and (path / "overview_time_us.bin").stat().st_size
                == overview_count * 8
            ):
                return False
            return all(
                (path / self._value_name(channel)).stat().st_size == count * 4
                and (path / self._overview_name(channel)).stat().st_size
                == overview_count * 4
                for channel in self.channels
            )
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            return False

    def ensure_cache(
        self,
        channel_id: int | None = None,
        cancel_event: threading.Event | None = None,
        progress_callback=None,
    ) -> Path:
        if channel_id is not None and int(channel_id) not in self.channels:
            raise ValueError(f"CSV does not include channel {channel_id}")
        with self._build_lock:
            identity = self._identity()
            final_path = self._cache_path(identity)
            self.cache_root.mkdir(parents=True, exist_ok=True)
            cleanup_key = str(self.cache_root.resolve())
            with _CACHE_CLEANUP_LOCK:
                if cleanup_key not in _CLEANED_CACHE_ROOTS:
                    cleanup_signal_cache(
                        self.cache_root,
                        protected_paths=(final_path,),
                    )
                    _CLEANED_CACHE_ROOTS.add(cleanup_key)
            if self._valid_cache(final_path, identity):
                self._touch_cache(final_path)
                return final_path
            self._prune_cache({final_path})
            temporary = (
                self.cache_root
                / f".{final_path.name}.{uuid.uuid4().hex}.tmp"
            )
            temporary.mkdir()
            try:
                sample_count = self._convert_csv(
                    temporary,
                    channel_id,
                    cancel_event=cancel_event,
                    progress_callback=progress_callback,
                )
                overview_count = self._build_overview(
                    temporary,
                    sample_count,
                    cancel_event=cancel_event,
                )
                metadata = {
                    "complete": True,
                    "identity": identity,
                    "sample_count": sample_count,
                    "overview_count": overview_count,
                    "timestamps_monotonic": True,
                }
                (temporary / "metadata.json").write_text(
                    json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                (temporary / "COMPLETE").write_text(
                    "complete\n", encoding="ascii"
                )
                self._flush_directory_files(temporary)
                self._atomic_replace_directory(temporary, final_path)
                self._prune_cache({final_path})
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
            return final_path

    def _convert_csv(
        self,
        directory: Path,
        _channel_id: int | None = None,
        *,
        cancel_event: threading.Event | None,
        progress_callback=None,
    ) -> int:
        """Scan the CSV once and write shared time plus every channel."""
        channels = self.channels
        if not channels:
            raise ValueError("CSV does not include channel metadata")
        header_row = self.metadata.get("header_row")
        if header_row is None:
            raise ValueError("CSV missing Time[us] header row")
        usecols = list(range(len(channels) + 1))
        sample_count = 0
        previous_time = None
        source_size = max(Path(self.path).stat().st_size, 1)
        processed_bytes = 0
        with ExitStack() as stack:
            time_file = stack.enter_context((directory / "time_us.bin").open("wb"))
            value_files = {
                channel: stack.enter_context(
                    (directory / self._value_name(channel)).open("wb")
                )
                for channel in channels
            }
            for times, value_columns, chunk_bytes in self._iter_signal_chunks(
                header_row, usecols, cancel_event
            ):
                self._check_cancel(cancel_event)
                if times.size:
                    if not np.isfinite(times).all():
                        raise ValueError("Signal timestamps must be finite.")
                    if previous_time is not None and times[0] < previous_time:
                        raise ValueError("Signal timestamps move backwards.")
                    if np.any(np.diff(times) < 0):
                        raise ValueError("Signal timestamps move backwards.")
                    previous_time = float(times[-1])
                time_file.write(times.tobytes())
                for column_index, channel in enumerate(channels, start=1):
                    value_files[channel].write(
                        value_columns[column_index].tobytes()
                    )
                sample_count += int(times.size)
                if progress_callback is not None:
                    # Neither reader exposes exact consumed input bytes; the
                    # per-chunk buffer size gives a stable monotonic
                    # approximation capped below completion.
                    processed_bytes += int(chunk_bytes)
                    progress_callback(min(0.99, processed_bytes / source_size))
            for stream in [time_file, *value_files.values()]:
                stream.flush()
                os.fsync(stream.fileno())
        if sample_count < 2:
            raise ValueError("Signal CSV must contain at least two samples.")
        if progress_callback is not None:
            progress_callback(1.0)
        return sample_count

    def _iter_signal_chunks(
        self,
        header_row: int,
        usecols: list[int],
        cancel_event: threading.Event | None,
    ):
        """Yield (time, {column_index: values}, chunk_bytes) blocks in file order.

        pyarrow's multi-threaded CSV reader is used when available; the pandas
        reader is an exact-behavior fallback when pyarrow is not installed.
        """
        try:
            import pyarrow as pa  # noqa: F401
            from pyarrow import csv as pyarrow_csv  # noqa: F401
        except ImportError:
            yield from self._iter_signal_chunks_pandas(
                header_row, usecols, cancel_event
            )
            return
        yield from self._iter_signal_chunks_pyarrow(
            header_row, usecols, cancel_event
        )

    def _iter_signal_chunks_pyarrow(
        self,
        header_row: int,
        usecols: list[int],
        cancel_event: threading.Event | None,
    ):
        # Read the data region in newline-aligned byte windows and bulk-parse
        # each window with pyarrow's multi-threaded CSV reader.  This keeps the
        # parse several times faster than pandas while bounding peak memory to
        # roughly one window plus its parsed table -- a whole-file bulk parse
        # would hold the entire ~3 GB table in RAM for a 20-hour recording.
        import pyarrow as pa
        from pyarrow import csv as pyarrow_csv

        # Autogenerated names (f0, f1, ...) avoid depending on the header text;
        # include_columns keeps the leading time column plus one column per
        # channel and drops any trailing columns, matching pandas usecols.
        include_columns = [f"f{index}" for index in usecols]
        column_types = {"f0": pa.float64()}
        for index in usecols[1:]:
            column_types[f"f{index}"] = pa.float32()
        read_options = pyarrow_csv.ReadOptions(
            autogenerate_column_names=True,
            use_threads=True,
        )
        convert_options = pyarrow_csv.ConvertOptions(
            include_columns=include_columns,
            column_types=column_types,
        )

        data_offset = self._signal_data_byte_offset(int(header_row) + 1)
        with open(self.path, "rb") as handle:
            handle.seek(data_offset)
            leftover = b""
            while True:
                self._check_cancel(cancel_event)
                chunk = handle.read(PYARROW_CSV_BLOCK_BYTES)
                if not chunk:
                    buffer = leftover
                    leftover = b""
                else:
                    data = leftover + chunk
                    cut = data.rfind(b"\n")
                    if cut < 0:
                        # No row boundary yet: keep accumulating until one row
                        # fits, so no data line is ever split across windows.
                        leftover = data
                        continue
                    buffer = data[: cut + 1]
                    leftover = data[cut + 1:]
                if buffer.strip():
                    table = pyarrow_csv.read_csv(
                        pa.BufferReader(buffer),
                        read_options=read_options,
                        convert_options=convert_options,
                    )
                    times = table.column(0).to_numpy(
                        zero_copy_only=False
                    ).astype("<f8", copy=False)
                    value_columns = {
                        index: table.column(index)
                        .to_numpy(zero_copy_only=False)
                        .astype("<f4", copy=False)
                        for index in range(1, len(usecols))
                    }
                    yield times, value_columns, len(buffer)
                if not chunk:
                    break

    def _signal_data_byte_offset(self, skip_lines: int) -> int:
        """Return the byte offset of the first data row past the header block."""
        offset = 0
        seen = 0
        with open(self.path, "rb") as handle:
            while seen < skip_lines:
                line = handle.readline()
                if not line:
                    break
                offset += len(line)
                seen += 1
        return offset

    def _iter_signal_chunks_pandas(
        self,
        header_row: int,
        usecols: list[int],
        cancel_event: threading.Event | None,
    ):
        pd = import_module("pandas")
        dtypes = {0: "float64"}
        dtypes.update({index: "float32" for index in usecols[1:]})
        with pd.read_csv(
            self.path,
            skiprows=int(header_row) + 1,
            header=None,
            usecols=usecols,
            dtype=dtypes,
            chunksize=self.chunk_rows,
        ) as reader:
            for chunk in reader:
                self._check_cancel(cancel_event)
                times = chunk.iloc[:, 0].to_numpy(dtype="<f8", copy=False)
                value_columns = {
                    index: chunk.iloc[:, index].to_numpy(dtype="<f4", copy=False)
                    for index in range(1, len(usecols))
                }
                yield times, value_columns, int(
                    chunk.memory_usage(deep=True).sum()
                )

    def _build_overview(
        self,
        directory: Path,
        sample_count: int,
        *,
        cancel_event: threading.Event | None,
    ) -> int:
        step = max(sample_count // self.overview_max_points, 1)
        indices = np.arange(0, sample_count, step, dtype=np.int64)
        times = np.memmap(
            directory / "time_us.bin", dtype="<f8", mode="r", shape=(sample_count,)
        )
        try:
            self._write_array_atomic(
                directory / "overview_time_us.bin",
                np.asarray(times[indices], dtype="<f8"),
            )
        finally:
            del times
        for channel in self.channels:
            self._check_cancel(cancel_event)
            values = np.memmap(
                directory / self._value_name(channel),
                dtype="<f4",
                mode="r",
                shape=(sample_count,),
            )
            try:
                self._write_array_atomic(
                    directory / self._overview_name(channel),
                    np.asarray(values[indices], dtype="<f4"),
                )
            finally:
                del values
        return int(indices.size)

    def _cache_metadata(
        self,
        channel_id: int,
        cancel_event: threading.Event | None = None,
    ) -> tuple[Path, dict]:
        path = self.ensure_cache(channel_id, cancel_event)
        return path, json.loads((path / "metadata.json").read_text("utf-8"))

    def overview(self, channel_id: int) -> SignalOverview:
        path, metadata = self._cache_metadata(channel_id)
        count = int(metadata["overview_count"])
        times = np.memmap(
            path / "overview_time_us.bin", dtype="<f8", mode="r", shape=(count,)
        )
        values = np.memmap(
            path / self._overview_name(channel_id),
            dtype="<f4",
            mode="r",
            shape=(count,),
        )
        try:
            return SignalOverview(
                np.asarray(times).copy(),
                np.asarray(values).copy(),
                int(metadata["sample_count"]),
            )
        finally:
            del times
            del values

    def segment_indices(
        self,
        channel_id: int,
        start_us: float,
        end_us: float,
        cancel_event: threading.Event | None = None,
    ) -> tuple[int, int]:
        self._check_cancel(cancel_event)
        path, metadata = self._cache_metadata(channel_id, cancel_event)
        count = int(metadata["sample_count"])
        times = np.memmap(path / "time_us.bin", dtype="<f8", mode="r", shape=(count,))
        try:
            return (
                int(np.searchsorted(times, start_us, side="left")),
                int(np.searchsorted(times, end_us, side="right")),
            )
        finally:
            del times

    def indexed_segment(
        self,
        channel_id: int,
        left_index: int,
        right_index: int,
        cancel_event: threading.Event | None = None,
    ) -> RawSignalSegment:
        self._check_cancel(cancel_event)
        path, metadata = self._cache_metadata(channel_id, cancel_event)
        count = int(metadata["sample_count"])
        left_index = max(min(int(left_index), count), 0)
        right_index = max(min(int(right_index), count), left_index)
        times = np.memmap(path / "time_us.bin", dtype="<f8", mode="r", shape=(count,))
        values = np.memmap(
            path / self._value_name(channel_id),
            dtype="<f4",
            mode="r",
            shape=(count,),
        )
        try:
            self._check_cancel(cancel_event)
            return RawSignalSegment(
                np.asarray(times[left_index:right_index], dtype="<f8").copy(),
                np.asarray(values[left_index:right_index], dtype="<f4").copy(),
                left_index,
                right_index,
            )
        finally:
            del times
            del values

    def indexed_values(
        self,
        channel_id: int,
        left_index: int,
        right_index: int,
        cancel_event: threading.Event | None = None,
    ) -> np.ndarray:
        """Read only values for numeric analysis, without copying timestamps."""
        self._check_cancel(cancel_event)
        path, metadata = self._cache_metadata(channel_id, cancel_event)
        count = int(metadata["sample_count"])
        left_index = max(min(int(left_index), count), 0)
        right_index = max(min(int(right_index), count), left_index)
        values = np.memmap(
            path / self._value_name(channel_id),
            dtype="<f4",
            mode="r",
            shape=(count,),
        )
        try:
            self._check_cancel(cancel_event)
            return np.asarray(
                values[left_index:right_index],
                dtype="<f4",
            ).copy()
        finally:
            del values

    def indexed_bounds_us(
        self,
        channel_id: int,
        left_index: int,
        right_index: int,
        cancel_event: threading.Event | None = None,
    ) -> tuple[float, float]:
        """Read only the first and last timestamps for an indexed interval."""
        self._check_cancel(cancel_event)
        path, metadata = self._cache_metadata(channel_id, cancel_event)
        count = int(metadata["sample_count"])
        left_index = max(min(int(left_index), count), 0)
        right_index = max(min(int(right_index), count), left_index)
        if right_index <= left_index:
            raise ValueError("Selected time range contains no samples.")
        times = np.memmap(
            path / "time_us.bin",
            dtype="<f8",
            mode="r",
            shape=(count,),
        )
        try:
            self._check_cancel(cancel_event)
            return (
                float(times[left_index]),
                float(times[right_index - 1]),
            )
        finally:
            del times

    def segment(
        self,
        channel_id: int,
        start_us: float,
        end_us: float,
        cancel_event: threading.Event | None = None,
    ) -> RawSignalSegment:
        left, right = self.segment_indices(
            channel_id, start_us, end_us, cancel_event
        )
        return self.indexed_segment(channel_id, left, right, cancel_event)

    def sampled_segment(
        self,
        channel_id: int,
        start_us: float,
        end_us: float,
        step: int,
        cancel_event: threading.Event | None = None,
    ) -> RawSignalSegment:
        step = int(step)
        if step < 1:
            raise ValueError("Sample step must be at least 1.")
        left, right = self.segment_indices(
            channel_id, start_us, end_us, cancel_event
        )
        path, metadata = self._cache_metadata(channel_id, cancel_event)
        count = int(metadata["sample_count"])
        times = np.memmap(path / "time_us.bin", dtype="<f8", mode="r", shape=(count,))
        values = np.memmap(
            path / self._value_name(channel_id),
            dtype="<f4",
            mode="r",
            shape=(count,),
        )
        try:
            return RawSignalSegment(
                np.asarray(times[left:right:step], dtype="<f8").copy(),
                np.asarray(values[left:right:step], dtype="<f4").copy(),
                left,
                right,
            )
        finally:
            del times
            del values

    def coarse(
        self,
        channel_id: int,
        step: int,
        settings=None,
        cancel_event: threading.Event | None = None,
        progress_callback=None,
        range_callback=None,
        priority_sample_index: int | None = None,
        published_callback=None,
        priority_channel_provider=None,
    ) -> SignalOverview:
        """Return an atomically cached full-range coarse for one global step."""
        channel_id = int(channel_id)
        if channel_id not in self.channels:
            raise ValueError(f"CSV does not include channel {channel_id}")
        step = max(int(step), 1)
        identity = self._coarse_identity(step, settings)
        coarse_path = self.cache_root / f"coarse-{self._digest(identity)}"
        if self._valid_coarse_channel(coarse_path, identity, channel_id):
            # Reading an already published channel must never wait behind the
            # build lock: a background build of the remaining channels holds it
            # for minutes, and the GUI reads this path when switching channels.
            self._touch_cache(coarse_path)
        else:
            with self.cache_build_lock(coarse_path):
                self._check_cancel(cancel_event)
                if not self._valid_coarse_channel(coarse_path, identity, channel_id):
                    self._build_coarse_directory(
                        coarse_path,
                        identity,
                        step,
                        settings,
                        cancel_event=cancel_event,
                        progress_callback=progress_callback,
                        range_callback=range_callback,
                        priority_channel=channel_id,
                        priority_sample_index=priority_sample_index,
                        published_callback=published_callback,
                        priority_channel_provider=priority_channel_provider,
                    )
                else:
                    self._touch_cache(coarse_path)
        metadata = json.loads((coarse_path / "metadata.json").read_text("utf-8"))
        count = int(metadata["coarse_count"])
        times = np.memmap(
            coarse_path / "time_us.bin", dtype="<f8", mode="r", shape=(count,)
        )
        values = np.memmap(
            coarse_path / self._value_name(channel_id),
            dtype="<f4",
            mode="r",
            shape=(count,),
        )
        try:
            return SignalOverview(
                np.asarray(times).copy(),
                np.asarray(values).copy(),
                int(metadata["sample_count"]),
            )
        finally:
            del times
            del values

    def coarse_is_ready(self, step: int, settings=None, channel_id=None) -> bool:
        """Check cache validity without starting conversion.

        Args:
            channel_id: Only require this channel; ``None`` requires every one.
        """
        identity = self._coarse_identity(max(int(step), 1), settings)
        path = self.cache_root / f"coarse-{self._digest(identity)}"
        if channel_id is None:
            return self._valid_coarse(path, identity)
        return self._valid_coarse_channel(path, identity, int(channel_id))

    def coarse_ready_channels(self, step: int, settings=None) -> list[int]:
        """List every channel already published for this step and settings.

        The shared header is parsed once, so a caller refreshing a per-channel
        readiness display does not pay for one parse per channel.
        """
        identity = self._coarse_identity(max(int(step), 1), settings)
        path = self.cache_root / f"coarse-{self._digest(identity)}"
        metadata = self._coarse_metadata(path, identity)
        if metadata is None:
            return []
        return [
            channel
            for channel in self.channels
            if self._published_coarse_channel(path, metadata, channel)
        ]

    def _coarse_identity(self, step: int, settings) -> dict:
        filter_settings = asdict(settings) if settings is not None else None
        if filter_settings is not None:
            filter_settings["line_noise_frequencies_hz"] = list(
                filter_settings.get("line_noise_frequencies_hz", ())
            )
        return {
            "source": self._identity(),
            "step": max(int(step), 1),
            "filter_algorithm_version": FILTER_COARSE_ALGORITHM_VERSION,
            "filter_settings": filter_settings,
        }

    @staticmethod
    def _coarse_channel_marker(channel: int) -> str:
        return f"channel_{int(channel)}.complete"

    def _coarse_metadata(self, path: Path, identity: dict) -> dict | None:
        """Return the shared coarse header when its timestamps are usable."""
        try:
            metadata = json.loads((path / "metadata.json").read_text("utf-8"))
            count = int(metadata["coarse_count"])
            if metadata.get("identity") != identity:
                return None
            if (path / "time_us.bin").stat().st_size != count * 8:
                return None
            return metadata
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            return None

    def _published_coarse_channel(
        self, path: Path, metadata: dict, channel: int
    ) -> bool:
        """Check one channel against an already parsed coarse header."""
        try:
            count = int(metadata["coarse_count"])
            if (path / self._value_name(channel)).stat().st_size != count * 4:
                return False
            if (path / self._coarse_channel_marker(channel)).is_file():
                return True
            # Caches written before per-channel publishing only carry the shared
            # marker, and those are complete for every channel.
            return (
                metadata.get("complete") is True
                and (path / "COMPLETE").is_file()
            )
        except (KeyError, OSError, ValueError):
            return False

    def _valid_coarse_channel(
        self, path: Path, identity: dict, channel: int
    ) -> bool:
        """Check one published channel so other channels can still be missing."""
        metadata = self._coarse_metadata(path, identity)
        if metadata is None:
            return False
        return self._published_coarse_channel(path, metadata, channel)

    def _valid_coarse(self, path: Path, identity: dict) -> bool:
        return all(
            self._valid_coarse_channel(path, identity, channel)
            for channel in self.channels
        )

    def _prepare_coarse_directory(
        self,
        final_path: Path,
        identity: dict,
        source_path: Path,
        sample_count: int,
        indices: np.ndarray,
        cancel_event: threading.Event | None,
    ) -> np.ndarray:
        """Publish the shared coarse header once and return its timestamps."""
        metadata = self._coarse_metadata(final_path, identity)
        if metadata is not None:
            count = int(metadata["coarse_count"])
            return np.fromfile(
                final_path / "time_us.bin", dtype="<f8", count=count
            )

        if final_path.exists():
            _remove_cache_directory(final_path)
        final_path.mkdir(parents=True, exist_ok=True)
        source_times = np.memmap(
            source_path / "time_us.bin",
            dtype="<f8",
            mode="r",
            shape=(sample_count,),
        )
        try:
            coarse_times = np.asarray(source_times[indices], dtype="<f8").copy()
        finally:
            del source_times
        self._check_cancel(cancel_event)
        self._publish_cache_file(
            final_path, "time_us.bin", coarse_times.tobytes()
        )
        self._publish_cache_file(
            final_path,
            "metadata.json",
            (
                json.dumps(
                    {
                        "identity": identity,
                        "sample_count": int(sample_count),
                        "coarse_count": int(indices.size),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
        )
        # Publish the shared marker straight away so the cache sweeper treats a
        # partially built directory as live instead of abandoned.
        (final_path / "COMPLETE").write_text("complete\n", encoding="ascii")
        return coarse_times

    def _build_coarse_directory(
        self,
        final_path: Path,
        identity: dict,
        step: int,
        settings,
        *,
        cancel_event: threading.Event | None,
        progress_callback=None,
        range_callback=None,
        priority_channel: int | None = None,
        priority_sample_index: int | None = None,
        published_callback=None,
        priority_channel_provider=None,
    ) -> None:
        source_path, metadata = self._cache_metadata(self.channels[0])
        sample_count = int(metadata["sample_count"])
        indices = np.arange(0, sample_count, step, dtype=np.int64)
        self._check_cancel(cancel_event)
        source_times_for_coarse = self._prepare_coarse_directory(
            final_path, identity, source_path, sample_count, indices, cancel_event
        )
        pending = [
            channel
            for channel in self.channels
            if not self._valid_coarse_channel(final_path, identity, channel)
        ]
        remaining = self._coarse_channel_groups(pending, priority_channel)
        finished = 0
        first_group = True
        while remaining:
            self._check_cancel(cancel_event)
            current_priority = priority_channel
            if priority_channel_provider is not None:
                selected = priority_channel_provider()
                if selected is not None:
                    current_priority = int(selected)
            # The caller can move to another channel while this runs, so the
            # group holding the newly displayed channel is taken next instead
            # of restarting the whole job around it.
            index = next(
                (
                    position
                    for position, group in enumerate(remaining)
                    if current_priority in group
                ),
                0,
            )
            group = remaining.pop(index)
            values = self._filtered_coarse_group(
                source_path,
                sample_count,
                indices,
                step,
                settings,
                group,
                source_times_for_coarse,
                cancel_event=cancel_event,
                range_callback=(
                    range_callback if current_priority in group else None
                ),
                range_channel=current_priority,
                priority_sample_index=(
                    priority_sample_index
                    if first_group and current_priority in group
                    else None
                ),
            )
            first_group = False
            self._check_cancel(cancel_event)
            # Publishing a whole group at once keeps a cancelled build from
            # discarding it.
            for row, channel in enumerate(group):
                self._publish_coarse_channel(final_path, channel, values[row])
            finished += len(group)
            if published_callback is not None:
                published_callback(list(group))
            if progress_callback is not None:
                progress_callback(finished / max(len(pending), 1))
        self._check_cancel(cancel_event)
        # Every channel carries its own marker, so nothing else has to be
        # rewritten here.  Keeping metadata.json immutable means a reader can
        # never collide with a replacement of the file it is parsing.
        self._touch_cache(final_path)
        self._prune_cache({source_path, final_path})

    def _coarse_channel_groups(
        self, pending: list[int], priority_channel: int | None
    ) -> list[list[int]]:
        """Order the work as the visible channel first, then filtered together.

        The visible channel runs alone so its waveform appears after a fraction
        of the job.  Every other channel is filtered in one multi-channel call
        per group, which lets the regression share one design matrix across the
        whole group instead of rebuilding it per channel.  A group is confined
        to one sample rate because padding and every filter coefficient are
        derived from it.
        """
        remaining = list(pending)
        groups: list[list[int]] = []
        if priority_channel in remaining:
            remaining.remove(priority_channel)
            groups.append([priority_channel])
        by_sample_rate: dict[float, list[int]] = {}
        for channel in remaining:
            by_sample_rate.setdefault(self._sample_rate(channel), []).append(
                channel
            )
        for channels in by_sample_rate.values():
            for start in range(0, len(channels), COARSE_CHANNEL_GROUP):
                groups.append(channels[start : start + COARSE_CHANNEL_GROUP])
        return groups

    def _coarse_points_per_batch(self, step: int, group_size: int) -> int:
        """Size one filter call by working-set bytes, not by row count.

        ``chunk_rows // step`` used to decide this, which collapsed to a few
        dozen points on a long recording and turned the build into thousands of
        tiny dispatches.
        """
        budget_samples = self.coarse_batch_bytes // (8 * max(group_size, 1))
        samples_per_batch = min(
            COARSE_FILTER_BATCH_SAMPLES, max(budget_samples, step)
        )
        return max(int(samples_per_batch) // max(int(step), 1), 1)

    def _filtered_coarse_group(
        self,
        source_path: Path,
        sample_count: int,
        indices: np.ndarray,
        step: int,
        settings,
        group: list[int],
        source_times_for_coarse: np.ndarray,
        *,
        cancel_event: threading.Event | None,
        range_callback,
        range_channel: int | None,
        priority_sample_index: int | None,
    ) -> np.ndarray:
        """Return ``(len(group), indices.size)`` coarse values for one group."""
        from .lfp_processing import filter_padding_samples, prepare_lfp_signal

        output = np.empty((len(group), indices.size), dtype="<f4")
        with ExitStack() as stack:
            sources = [
                stack.enter_context(
                    self._channel_memmap(source_path, channel, sample_count)
                )
                for channel in group
            ]
            if settings is None or not settings.show_filtered:
                for row, source_values in enumerate(sources):
                    self._check_cancel(cancel_event)
                    output[row] = np.asarray(source_values[indices], dtype="<f4")
                return output

            sample_rate = self._sample_rate(group[0])
            padding = filter_padding_samples(settings, sample_rate)
            points_per_batch = self._coarse_points_per_batch(step, len(group))
            point_starts = list(range(0, indices.size, points_per_batch))
            if priority_sample_index is not None:
                priority_point = max(
                    min(int(priority_sample_index) // step, indices.size - 1), 0
                )
                point_starts.sort(
                    key=lambda start: abs(
                        start
                        + min(points_per_batch, indices.size - start) / 2
                        - priority_point
                    )
                )
            range_row = (
                group.index(range_channel)
                if range_callback is not None and range_channel in group
                else None
            )
            for point_start in point_starts:
                self._check_cancel(cancel_event)
                point_end = min(point_start + points_per_batch, indices.size)
                requested = indices[point_start:point_end]
                left = int(requested[0])
                right = min(int(requested[-1]) + 1, sample_count)
                loaded_left = max(left - padding, 0)
                loaded_right = min(right + padding, sample_count)
                block = np.stack(
                    [
                        np.asarray(source_values[loaded_left:loaded_right])
                        for source_values in sources
                    ],
                    axis=0,
                )
                filtered = prepare_lfp_signal(
                    block,
                    sample_rate,
                    settings,
                    sample_offset=loaded_left,
                    dispatch_sample_count=sample_count,
                )
                selected = np.atleast_2d(filtered)[:, requested - loaded_left]
                output[:, point_start:point_end] = selected
                if range_row is not None:
                    range_callback(
                        group[range_row],
                        point_start,
                        point_end,
                        np.asarray(
                            source_times_for_coarse[point_start:point_end]
                        ),
                        np.asarray(selected[range_row], dtype="<f4").copy(),
                    )
        return output

    @contextmanager
    def _channel_memmap(self, source_path: Path, channel: int, sample_count: int):
        """Open one channel's full-resolution values and release it on exit."""
        values = np.memmap(
            source_path / self._value_name(channel),
            dtype="<f4",
            mode="r",
            shape=(sample_count,),
        )
        try:
            yield values
        finally:
            del values

    def _publish_coarse_channel(
        self, final_path: Path, channel: int, values: np.ndarray
    ) -> None:
        """Make one finished channel readable before the others are computed."""
        self._publish_cache_file(
            final_path,
            self._value_name(channel),
            np.asarray(values, dtype="<f4").tobytes(),
        )
        (final_path / self._coarse_channel_marker(channel)).write_text(
            "complete\n", encoding="ascii"
        )

    def _sample_rate(self, channel: int) -> float:
        channels = self.channels
        rates = [float(value) for value in self.metadata.get("sample_rates", [])]
        if channel in channels and channels.index(channel) < len(rates):
            return rates[channels.index(channel)]
        raise ValueError(f"Sample rate not found for channel {channel}")

    def sample_count(self, channel_id: int) -> int:
        _, metadata = self._cache_metadata(channel_id)
        return int(metadata["sample_count"])

    def identity_token(self) -> tuple[str, int, int]:
        stat = Path(self.path).stat()
        return self.path, int(stat.st_size), int(stat.st_mtime_ns)

    def cache_identity(self) -> dict:
        """Return the JSON-safe source identity used by derived disk caches."""

        return self._identity()

    def derived_cache_path(self, prefix: str, identity: dict) -> Path:
        """Return a deterministic path for a source-derived cache directory."""

        return self.cache_root / f"{prefix}{self._digest(identity)}"

    def touch_cache_path(self, path: Path) -> None:
        """Mark a complete cache entry as recently used."""

        self._touch_cache(path)

    def bounds(self, channel_id: int) -> tuple[float, float]:
        path, metadata = self._cache_metadata(channel_id)
        count = int(metadata["sample_count"])
        times = np.memmap(path / "time_us.bin", dtype="<f8", mode="r", shape=(count,))
        try:
            return float(times[0]), float(times[-1])
        finally:
            del times

    def clear_cache(self) -> None:
        """Remove only cache directories belonging to this source path."""
        failures = []
        for path in self.cache_root.glob("*"):
            if not path.is_dir():
                continue
            metadata_path = path / "metadata.json"
            try:
                metadata = json.loads(metadata_path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            identity = metadata.get("identity", {})
            source = identity.get("source", identity)
            if source.get("source_path") == self.path:
                try:
                    shutil.rmtree(path)
                except OSError as error:
                    failures.append(f"{path}: {error}")
        if failures:
            raise OSError(
                "Could not remove one or more signal caches:\n"
                + "\n".join(failures)
            )

    @contextmanager
    def hold_cache_path(self, path: str | Path):
        """Keep one cache directory protected while a caller is using it."""

        resolved = str(Path(path).resolve())
        with _CACHE_CLEANUP_LOCK:
            _ACTIVE_CACHE_PATHS[resolved] = _ACTIVE_CACHE_PATHS.get(resolved, 0) + 1
        try:
            yield Path(path)
        finally:
            with _CACHE_CLEANUP_LOCK:
                remaining = _ACTIVE_CACHE_PATHS.get(resolved, 0) - 1
                if remaining > 0:
                    _ACTIVE_CACHE_PATHS[resolved] = remaining
                else:
                    _ACTIVE_CACHE_PATHS.pop(resolved, None)

    @contextmanager
    def cache_build_lock(self, cache_path: str | Path | None = None):
        """Serialize construction per derived cache without blocking other work."""

        if cache_path is None:
            lock = self._build_lock
        else:
            key = str(Path(cache_path).resolve())
            with self._cache_build_locks_guard:
                lock = self._cache_build_locks.setdefault(key, threading.RLock())
        with lock:
            yield

    def commit_cache_directory(self, temporary: Path, final_path: Path) -> None:
        """Flush and atomically publish a fully prepared cache directory."""

        self._flush_directory_files(temporary)
        self._atomic_replace_directory(temporary, final_path)

    def prune_cache(self, protected: set[Path]) -> None:
        """Enforce the shared signal-cache limit while preserving active paths."""

        self._prune_cache(protected)

    def _prune_cache(self, protected: set[Path]) -> None:
        cleanup_signal_cache(
            self.cache_root,
            protected_paths=tuple(protected),
        )

    @staticmethod
    def _touch_cache(path: Path) -> None:
        try:
            (path / "COMPLETE").touch()
        except OSError:
            pass

    @staticmethod
    def _check_cancel(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise CacheBuildCancelled("Signal cache generation was cancelled.")

    @staticmethod
    def _write_array_atomic(path: Path, values: np.ndarray) -> None:
        with path.open("wb") as stream:
            stream.write(np.asarray(values).tobytes())
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _publish_cache_file(directory: Path, name: str, payload: bytes) -> None:
        """Replace one file inside a live cache directory in a single step."""
        temporary = directory / f".{name}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, directory / name)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _flush_directory_files(directory: Path) -> None:
        for path in directory.iterdir():
            if path.is_file():
                with path.open("rb+") as stream:
                    os.fsync(stream.fileno())

    def _atomic_replace_directory(self, temporary: Path, final_path: Path) -> None:
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


_SOURCES: dict[tuple[str, int, int, int], SignalDataSource] = {}


def signal_data_source(
    info: dict,
    *,
    overview_max_points: int = DEFAULT_OVERVIEW_MAX_POINTS,
) -> SignalDataSource:
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
