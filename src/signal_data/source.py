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
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from importlib import import_module
from pathlib import Path

import numpy as np

CACHE_FORMAT_VERSION = 3
OVERVIEW_ALGORITHM_VERSION = 3
FILTER_COARSE_ALGORITHM_VERSION = 4
DEFAULT_CHUNK_ROWS = 250_000
DEFAULT_OVERVIEW_MAX_POINTS = 5_000
DEFAULT_CACHE_MAX_BYTES = 20 * 1024 * 1024 * 1024
DEFAULT_CACHE_MAX_AGE_DAYS = 30
DAY_SECONDS = 24 * 60 * 60

_CACHE_CLEANUP_LOCK = threading.RLock()
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
    protected = {str(Path(path).resolve()) for path in protected_paths}
    abandoned_cutoff = current_time - DAY_SECONDS
    age_cutoff = current_time - max(int(max_age_days), 0) * DAY_SECONDS

    with _CACHE_CLEANUP_LOCK:
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
                    if not is_protected and path.stat().st_mtime <= abandoned_cutoff:
                        shutil.rmtree(path, ignore_errors=True)
                    continue
                if not path.name.startswith(("signal-", "coarse-")):
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
        self._build_lock = threading.RLock()

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
        pd = import_module("pandas")
        channels = self.channels
        if not channels:
            raise ValueError("CSV does not include channel metadata")
        header_row = self.metadata.get("header_row")
        if header_row is None:
            raise ValueError("CSV missing Time[us] header row")
        usecols = list(range(len(channels) + 1))
        dtypes = {0: "float64"}
        dtypes.update({index: "float32" for index in usecols[1:]})
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
            reader = stack.enter_context(
                pd.read_csv(
                    self.path,
                    skiprows=int(header_row) + 1,
                    header=None,
                    usecols=usecols,
                    dtype=dtypes,
                    chunksize=self.chunk_rows,
                )
            )
            for chunk in reader:
                self._check_cancel(cancel_event)
                times = chunk.iloc[:, 0].to_numpy(dtype="<f8", copy=False)
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
                    values = chunk.iloc[:, column_index].to_numpy(
                        dtype="<f4", copy=False
                    )
                    value_files[channel].write(values.tobytes())
                sample_count += int(times.size)
                if progress_callback is not None:
                    # Pandas does not expose exact input bytes; row memory gives
                    # a stable monotonic approximation capped below completion.
                    processed_bytes += int(chunk.memory_usage(deep=True).sum())
                    progress_callback(min(0.99, processed_bytes / source_size))
            for stream in [time_file, *value_files.values()]:
                stream.flush()
                os.fsync(stream.fileno())
        if sample_count < 2:
            raise ValueError("Signal CSV must contain at least two samples.")
        if progress_callback is not None:
            progress_callback(1.0)
        return sample_count

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
    ) -> SignalOverview:
        """Return an atomically cached full-range coarse for one global step."""
        channel_id = int(channel_id)
        if channel_id not in self.channels:
            raise ValueError(f"CSV does not include channel {channel_id}")
        step = max(int(step), 1)
        identity = self._coarse_identity(step, settings)
        coarse_path = self.cache_root / f"coarse-{self._digest(identity)}"
        with self._build_lock:
            self._check_cancel(cancel_event)
            if not self._valid_coarse(coarse_path, identity):
                self._build_coarse_directory(
                    coarse_path,
                    identity,
                    step,
                    settings,
                    cancel_event=cancel_event,
                    progress_callback=progress_callback,
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

    def coarse_is_ready(self, step: int, settings=None) -> bool:
        """Check cache validity without starting conversion."""
        identity = self._coarse_identity(max(int(step), 1), settings)
        path = self.cache_root / f"coarse-{self._digest(identity)}"
        return self._valid_coarse(path, identity)

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

    def _valid_coarse(self, path: Path, identity: dict) -> bool:
        try:
            metadata = json.loads((path / "metadata.json").read_text("utf-8"))
            count = int(metadata["coarse_count"])
            return (
                metadata.get("identity") == identity
                and metadata.get("complete") is True
                and (path / "COMPLETE").is_file()
                and (path / "time_us.bin").stat().st_size == count * 8
                and all(
                    (path / self._value_name(channel)).stat().st_size == count * 4
                    for channel in self.channels
                )
            )
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            return False

    def _build_coarse_directory(
        self,
        final_path: Path,
        identity: dict,
        step: int,
        settings,
        *,
        cancel_event: threading.Event | None,
        progress_callback=None,
    ) -> None:
        from .lfp_processing import filter_padding_samples, prepare_lfp_signal

        source_path, metadata = self._cache_metadata(self.channels[0])
        sample_count = int(metadata["sample_count"])
        indices = np.arange(0, sample_count, step, dtype=np.int64)
        temporary = self.cache_root / f".{final_path.name}.{uuid.uuid4().hex}.tmp"
        temporary.mkdir(parents=True)
        try:
            self._check_cancel(cancel_event)
            source_times = np.memmap(
                source_path / "time_us.bin",
                dtype="<f8",
                mode="r",
                shape=(sample_count,),
            )
            try:
                self._write_array_atomic(
                    temporary / "time_us.bin",
                    np.asarray(source_times[indices], dtype="<f8"),
                )
            finally:
                del source_times
            channel_count = max(len(self.channels), 1)
            for channel_index, channel in enumerate(self.channels):
                self._check_cancel(cancel_event)
                source_values = np.memmap(
                    source_path / self._value_name(channel),
                    dtype="<f4",
                    mode="r",
                    shape=(sample_count,),
                )
                try:
                    if settings is None or not settings.show_filtered:
                        coarse_values = np.asarray(
                            source_values[indices], dtype="<f4"
                        )
                    else:
                        sample_rate = self._sample_rate(channel)
                        padding = filter_padding_samples(settings, sample_rate)
                        output = np.empty(indices.size, dtype="<f4")
                        output_offset = 0
                        points_per_batch = max(self.chunk_rows // step, 1)
                        for point_start in range(0, indices.size, points_per_batch):
                            self._check_cancel(cancel_event)
                            point_end = min(
                                point_start + points_per_batch, indices.size
                            )
                            requested = indices[point_start:point_end]
                            left = int(requested[0])
                            right = min(int(requested[-1]) + 1, sample_count)
                            loaded_left = max(left - padding, 0)
                            loaded_right = min(right + padding, sample_count)
                            filtered = prepare_lfp_signal(
                                np.asarray(
                                    source_values[loaded_left:loaded_right]
                                ),
                                sample_rate,
                                settings,
                                sample_offset=loaded_left,
                            )
                            relative = requested - loaded_left
                            selected = filtered[relative]
                            output[output_offset : output_offset + selected.size] = (
                                selected
                            )
                            output_offset += selected.size
                        coarse_values = output
                    self._write_array_atomic(
                        temporary / self._value_name(channel), coarse_values
                    )
                    if progress_callback is not None:
                        progress_callback((channel_index + 1) / channel_count)
                finally:
                    del source_values
            self._check_cancel(cancel_event)
            coarse_metadata = {
                "complete": True,
                "identity": identity,
                "sample_count": sample_count,
                "coarse_count": int(indices.size),
            }
            (temporary / "metadata.json").write_text(
                json.dumps(coarse_metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (temporary / "COMPLETE").write_text("complete\n", encoding="ascii")
            self._flush_directory_files(temporary)
            self._atomic_replace_directory(temporary, final_path)
            self._prune_cache({source_path, final_path})
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

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
