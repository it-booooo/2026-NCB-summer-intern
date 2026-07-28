"""Generate a fixture and record comparable CSV performance metrics."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from benchmarks.signal_csv_fixture import SignalFixtureConfig, generate_signal_csv
from src.signal_data.csv_loader import parse_lfp_csv_info
from src.signal_data.lfp_dataset import LfpDataset
from src.signal_data.source import CacheBuildCancelled, SignalDataSource


def _elapsed(operation):
    started = time.perf_counter()
    result = operation()
    return result, time.perf_counter() - started


def _peak_memory_bytes() -> int:
    if os.name == "nt":
        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        get_process = ctypes.windll.kernel32.GetCurrentProcess
        get_process.restype = ctypes.c_void_p
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(Counters),
            ctypes.c_ulong,
        ]
        get_memory.restype = ctypes.c_int
        succeeded = get_memory(
            get_process(),
            ctypes.byref(counters),
            counters.cb,
        )
        if not succeeded:
            raise ctypes.WinError()
        return int(counters.PeakWorkingSetSize)
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak * (1 if os.uname().sysname == "Darwin" else 1024))


def run(path: Path, config: SignalFixtureConfig) -> dict:
    generated_rows = generate_signal_csv(path, config)
    info, metadata_s = _elapsed(lambda: parse_lfp_csv_info(path))
    with tempfile.TemporaryDirectory(prefix="pig-signal-cache-") as cache_directory:
        info["_signal_cache_root"] = cache_directory
        dataset = LfpDataset.from_csv(info)
        step = max(config.sample_count // 5_000, 1)
        (first_times, first_values), first_display_s = _elapsed(
            lambda: dataset.coarse_values(config.channels[0], step)
        )
        _, channel_switch_s = _elapsed(
            lambda: dataset.coarse_values(config.channels[1], step)
        )
        start_s, end_s = dataset.record_bounds_s(config.channels[0])
        segment_end_s = min(start_s + 10.0, end_s)
        segment, segment_s = _elapsed(
            lambda: dataset.segment(
                config.channels[0],
                start_s,
                segment_end_s,
                None,
            )
        )
        dataset.close(wait=True)

    cancel = threading.Event()
    cancel_observed = threading.Event()
    cancel_errors = []
    with tempfile.TemporaryDirectory(
        prefix="pig-signal-cancel-"
    ) as cancel_cache:
        cancel_source = SignalDataSource(
            str(path),
            info["metadata"],
            chunk_rows=1,
            cache_root=cancel_cache,
        )

        def build_cancelable_cache():
            try:
                cancel_source.ensure_cache(config.channels[0], cancel)
            except CacheBuildCancelled:
                cancel_observed.set()
            except Exception as error:
                cancel_errors.append(error)

        worker = threading.Thread(
            target=build_cancelable_cache,
            name="benchmark-cache-cancel",
            daemon=True,
        )
        worker.start()
        time.sleep(0.02)
        cancel_started = time.perf_counter()
        cancel.set()
        worker.join(timeout=10)
        cancellation_s = time.perf_counter() - cancel_started
        if worker.is_alive():
            raise RuntimeError("Cache conversion did not stop within 10 seconds")
        if cancel_errors:
            raise cancel_errors[0]

    return {
        "fixture": {
            "path": str(path),
            "bytes": path.stat().st_size,
            "rows": generated_rows,
            "sample_rate_hz": config.sample_rate_hz,
            "duration_s": config.duration_s,
            "channels": list(config.channels),
        },
        "metrics": {
            "metadata_parse_s": metadata_s,
            "first_display_s": first_display_s,
            "channel_switch_s": channel_switch_s,
            "segment_10s_s": segment_s,
            "peak_memory_bytes": _peak_memory_bytes(),
            "background_cancel_s": cancellation_s,
        },
        "observations": {
            "first_display_rows": len(first_values),
            "first_display_first_time_us": (
                None if len(first_times) == 0 else float(first_times[0])
            ),
            "segment_10s_rows": segment.sample_count,
            "background_cancel_observed": cancel_observed.is_set(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-rate", type=int, default=1_000)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--with-anomalies", action="store_true")
    args = parser.parse_args()
    anomalies = {
        "missing_sample_indices": (7,),
        "duplicate_timestamp_indices": (11,),
        "discontinuity_after_indices": (17,),
    } if args.with_anomalies else {}
    config = SignalFixtureConfig(
        sample_rate_hz=args.sample_rate, duration_s=args.duration, **anomalies
    )

    if args.output:
        result = run(args.output, config)
    else:
        with tempfile.TemporaryDirectory(prefix="pig-sync-benchmark-") as directory:
            result = run(Path(directory) / "signal.csv", config)
            result["fixture"]["path"] = "<temporary>"
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.result:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
