"""Diagnose where time goes when first loading a large signal CSV.

Run against your real file to see whether pyarrow is active, how fast each
reader parses it, and how long each conversion phase takes on your machine:

    python -m benchmarks.diagnose_signal_load "D:\\path\\to\\your.csv"

Nothing is written next to your CSV; a throwaway cache is built in a temp
directory and removed afterwards.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

# Keep printing working on legacy Windows consoles (cp950/cp1252) even when a
# file path or value contains characters the console cannot encode.
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass

# Allow running both as "python -m benchmarks.diagnose_signal_load" and
# "python benchmarks/diagnose_signal_load.py".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.signal_data.csv_loader import parse_signal_csv_info  # noqa: E402
from src.signal_data.source import SignalDataSource  # noqa: E402


def _human_mb(num_bytes: int) -> float:
    return num_bytes / (1024 * 1024)


def _drain(generator) -> int:
    rows = 0
    for times, _value_columns, _chunk_bytes in generator:
        rows += int(times.size)
    return rows


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"File not found: {path}")
        return 2

    size_mb = _human_mb(path.stat().st_size)
    print(f"file            : {path}")
    print(f"size            : {size_mb:,.0f} MB")
    print(f"cpu cores       : {os.cpu_count()}")

    try:
        import pyarrow

        print(f"pyarrow         : available ({pyarrow.__version__})  <- fast path")
    except ImportError:
        print("pyarrow         : NOT INSTALLED  <- falling back to slow pandas path")

    info = parse_signal_csv_info(path)
    metadata = info["metadata"]
    channels = metadata.get("channels") or []
    sample_rates = metadata.get("sample_rates") or []
    header_row = metadata.get("header_row")
    print(f"channels        : {len(channels)}  {channels}")
    print(f"sample_rates    : {sample_rates}")
    print(f"header_row      : {header_row}")
    if header_row is None or not channels:
        print("Cannot diagnose: missing header row or channel metadata.")
        return 1

    usecols = list(range(len(channels) + 1))

    with tempfile.TemporaryDirectory(prefix="signal-diag-") as tmp:
        source = SignalDataSource(str(path), metadata, cache_root=tmp)

        # Warm up pyarrow's import and worker thread pool so the timed run is
        # representative rather than paying one-off startup cost.
        try:
            import pyarrow as _pa
            from pyarrow import csv as _pacsv

            _pacsv.read_csv(
                _pa.BufferReader(b"0,0\n1,1\n"),
                read_options=_pacsv.ReadOptions(autogenerate_column_names=True),
            )
        except Exception:
            pass

        # 1) Parse-only throughput for each reader (no disk writes).
        print("\n--- parse-only throughput (no writing) ---")
        try:
            start = time.perf_counter()
            rows = _drain(
                source._iter_signal_chunks_pyarrow(header_row, usecols, None)
            )
            dt = time.perf_counter() - start
            print(
                f"pyarrow reader  : {dt:7.2f}s  "
                f"{size_mb / dt:8.1f} MB/s  ({rows:,} rows)"
            )
        except ImportError:
            print("pyarrow reader  : skipped (pyarrow not installed)")

        start = time.perf_counter()
        rows = _drain(source._iter_signal_chunks_pandas(header_row, usecols, None))
        dt = time.perf_counter() - start
        print(
            f"pandas reader   : {dt:7.2f}s  "
            f"{size_mb / dt:8.1f} MB/s  ({rows:,} rows)"
        )

        # 2) Full first-time conversion, phase by phase (as the app does it).
        print("\n--- full first-time conversion phases ---")
        out = Path(tmp) / "phases"
        out.mkdir()
        sample_count = 0
        write_seconds = 0.0
        start = time.perf_counter()
        with ExitStack() as stack:
            time_file = stack.enter_context((out / "time_us.bin").open("wb"))
            value_files = {
                channel: stack.enter_context(
                    (out / f"channel_{channel}.bin").open("wb")
                )
                for channel in channels
            }
            for times, value_columns, _bytes in source._iter_signal_chunks(
                header_row, usecols, None
            ):
                sample_count += int(times.size)
                write_start = time.perf_counter()
                time_file.write(times.tobytes())
                for column_index, channel in enumerate(channels, start=1):
                    value_files[channel].write(
                        value_columns[column_index].tobytes()
                    )
                write_seconds += time.perf_counter() - write_start
            fsync_start = time.perf_counter()
            for stream in [time_file, *value_files.values()]:
                stream.flush()
                os.fsync(stream.fileno())
            fsync_seconds = time.perf_counter() - fsync_start
        parse_write_seconds = time.perf_counter() - start

        overview_start = time.perf_counter()
        source._build_overview(out, sample_count, cancel_event=None)
        overview_seconds = time.perf_counter() - overview_start

        parse_seconds = parse_write_seconds - write_seconds
        print(f"samples         : {sample_count:,}")
        print(f"parse           : {parse_seconds:7.2f}s")
        print(f"binary write    : {write_seconds:7.2f}s")
        print(f"fsync           : {fsync_seconds:7.2f}s")
        print(f"build_overview  : {overview_seconds:7.2f}s")
        print(
            f"TOTAL convert   : "
            f"{parse_write_seconds + fsync_seconds + overview_seconds:7.2f}s"
        )

    print(
        "\nInterpretation:\n"
        "  * If 'pyarrow reader' is much faster than 'pandas reader' but your\n"
        "    app is still slow, the app is not using pyarrow (e.g. the packaged\n"
        "    exe did not bundle it).\n"
        "  * If parse dominates and pyarrow is already active, you are limited\n"
        "    by CPU cores / disk read speed for the CSV text itself.\n"
        "  * If the app is slow only with the filter ON, the cost is elsewhere\n"
        "    (full-range filtered coarse build), not in this CSV conversion."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
