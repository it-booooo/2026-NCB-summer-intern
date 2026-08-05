"""Reproducible end-to-end benchmark for hybrid LFP peak detection."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

from src.signal_data.background_workers import (
    _cpu_chunk_statistics,
    _finalize_peak_mask,
    _merge_statistics,
)
from src.signal_data.gpu_backend import (
    chunk_statistics_opencl,
    last_peak_operation_error,
    opencl_peak_status,
    peak_candidate_masks_opencl,
)


SEED = 20260805


def synthetic_signal(sample_count: int, sample_rate_hz: float) -> np.ndarray:
    """Build noise, periodic background, signed peaks, plateaus, and boundaries."""

    rng = np.random.default_rng(SEED)
    time_values = np.arange(sample_count, dtype=np.float64) / sample_rate_hz
    values = (
        0.35 * np.sin(2.0 * np.pi * 8.0 * time_values)
        + 0.18 * np.sin(2.0 * np.pi * 60.0 * time_values + 0.3)
        + rng.normal(0.0, 0.22, sample_count)
    ).astype(np.float32)
    spacing = max(int(round(2.5 * sample_rate_hz)), 20)
    for number, index in enumerate(range(spacing, sample_count - spacing, spacing)):
        amplitude = 3.0 + 0.4 * (number % 4)
        values[index] += amplitude if number % 2 == 0 else -amplitude

    special = [
        (sample_count // 5, 4.5),
        (sample_count // 5 + max(int(0.01 * sample_rate_hz), 2), 3.0),
        (sample_count // 2, -4.6),
    ]
    for index, amplitude in special:
        if 2 <= index < sample_count - 2:
            values[index] = amplitude
    plateau = sample_count // 3
    if 2 <= plateau < sample_count - 5:
        values[plateau : plateau + 4] = 4.2
    return values


def _append_owned(output, peaks, prominences, values, loaded_left, core_left, core_right, negative):
    for local_index, prominence in zip(peaks, prominences):
        global_index = loaded_left + int(local_index)
        if core_left <= global_index < core_right:
            output.append(
                {
                    "index": global_index,
                    "value": float(values[local_index]),
                    "negative": bool(negative),
                    "prominence": float(prominence),
                }
            )


def _deduplicate(candidates, distance):
    accepted = []
    buckets = {}
    for candidate in sorted(
        candidates,
        key=lambda item: (-item["prominence"], -abs(item["value"]), item["index"]),
    ):
        index = candidate["index"]
        bucket = index // distance
        if any(
            abs(index - other["index"]) < distance
            for nearby in (bucket - 1, bucket, bucket + 1)
            for other in buckets.get(nearby, ())
        ):
            continue
        buckets.setdefault(bucket, []).append(candidate)
        accepted.append(candidate)
    return sorted(accepted, key=lambda item: item["index"])


def run_pipeline(values, sample_rate_hz, chunk_samples, statistics_backend, candidate_backend):
    started = time.perf_counter()
    count = 0
    mean = 0.0
    m2 = 0.0
    gpu_statistics_chunks = 0
    cpu_statistics_chunks = 0
    statistics_started = time.perf_counter()
    for core_left in range(0, values.size, chunk_samples):
        core = values[core_left : core_left + chunk_samples]
        if statistics_backend == "opencl":
            chunk = chunk_statistics_opencl(core, requested="opencl")
            gpu_statistics_chunks += 1
        else:
            chunk = _cpu_chunk_statistics(core)
            cpu_statistics_chunks += 1
        count, mean, m2 = _merge_statistics(count, mean, m2, *chunk)
    statistics_sec = time.perf_counter() - statistics_started
    sigma = float(np.sqrt(m2 / count))
    height_delta = 2.0 * sigma
    prominence_threshold = 1.0 * sigma
    positive_threshold = mean + height_delta
    negative_threshold = mean - height_delta
    distance = max(1, round(0.05 * sample_rate_hz))
    context = max(distance, round(2.0 * sample_rate_hz))
    prominence_wlen = 2 * context + 1

    candidates = []
    gpu_candidate_chunks = 0
    cpu_candidate_chunks = 0
    candidate_scan_sec = 0.0
    finalization_sec = 0.0
    for core_left in range(0, values.size, chunk_samples):
        core_right = min(core_left + chunk_samples, values.size)
        loaded_left = max(core_left - context, 0)
        loaded_right = min(core_right + context, values.size)
        loaded = values[loaded_left:loaded_right]
        scan_started = time.perf_counter()
        if candidate_backend == "opencl":
            masks = peak_candidate_masks_opencl(
                loaded,
                positive_threshold,
                negative_threshold,
                requested="opencl",
            )
            candidate_scan_sec += time.perf_counter() - scan_started
            final_started = time.perf_counter()
            positive, positive_prominence = _finalize_peak_mask(
                loaded,
                masks[0],
                height=positive_threshold,
                prominence=prominence_threshold,
                distance=distance,
                wlen=prominence_wlen,
            )
            negative, negative_prominence = _finalize_peak_mask(
                -loaded,
                masks[1],
                height=-negative_threshold,
                prominence=prominence_threshold,
                distance=distance,
                wlen=prominence_wlen,
            )
            finalization_sec += time.perf_counter() - final_started
            gpu_candidate_chunks += 1
        else:
            positive, positive_properties = find_peaks(
                loaded,
                height=positive_threshold,
                prominence=prominence_threshold,
                distance=distance,
                wlen=prominence_wlen,
            )
            negative, negative_properties = find_peaks(
                -loaded,
                height=-negative_threshold,
                prominence=prominence_threshold,
                distance=distance,
                wlen=prominence_wlen,
            )
            candidate_scan_sec += time.perf_counter() - scan_started
            positive_prominence = positive_properties["prominences"]
            negative_prominence = negative_properties["prominences"]
            cpu_candidate_chunks += 1
        _append_owned(
            candidates,
            positive,
            positive_prominence,
            loaded,
            loaded_left,
            core_left,
            core_right,
            False,
        )
        _append_owned(
            candidates,
            negative,
            negative_prominence,
            loaded,
            loaded_left,
            core_left,
            core_right,
            True,
        )
    dedup_started = time.perf_counter()
    accepted = _deduplicate(candidates, distance)
    finalization_sec += time.perf_counter() - dedup_started
    elapsed_sec = time.perf_counter() - started
    negative_types = np.asarray([item["negative"] for item in accepted], dtype=bool)
    return {
        "available": True,
        "elapsed_sec": elapsed_sec,
        "statistics_sec": statistics_sec,
        "candidate_scan_sec": candidate_scan_sec,
        "cpu_finalization_sec": finalization_sec,
        "statistics_backend": statistics_backend,
        "candidate_backend": candidate_backend,
        "gpu_statistics_chunks": gpu_statistics_chunks,
        "gpu_candidate_chunks": gpu_candidate_chunks,
        "cpu_statistics_chunks": cpu_statistics_chunks,
        "cpu_candidate_chunks": cpu_candidate_chunks,
        "peak_count": len(accepted),
        "positive_peak_count": int(np.count_nonzero(~negative_types)),
        "negative_peak_count": int(np.count_nonzero(negative_types)),
        "indices": np.asarray([item["index"] for item in accepted], dtype=np.int64),
        "negative": negative_types,
        "values": np.asarray([item["value"] for item in accepted], dtype=np.float64),
    }


def _summarize_runs(runs):
    result = dict(runs[-1])
    for name in ("elapsed_sec", "statistics_sec", "candidate_scan_sec", "cpu_finalization_sec"):
        result[name] = statistics.median(run[name] for run in runs)
    return result


def _public_metrics(result):
    return {
        key: value
        for key, value in result.items()
        if key not in {"indices", "negative", "values"}
    }


def benchmark(args):
    sample_count = int(args.samples or round(args.duration * args.sample_rate))
    values = synthetic_signal(sample_count, args.sample_rate)
    chunk_count = (sample_count + args.chunk_samples - 1) // args.chunk_samples
    status_started = time.perf_counter()
    status = opencl_peak_status()
    cold_start_sec = time.perf_counter() - status_started

    cpu_runs = [
        run_pipeline(values, args.sample_rate, args.chunk_samples, "cpu", "cpu")
        for _ in range(args.repeats)
    ]
    cpu = _summarize_runs(cpu_runs)
    modes = {"cpu_full_pipeline": _public_metrics(cpu)}

    opencl_modes = (
        ("cpu_statistics_opencl_candidates", "cpu", "opencl"),
        ("opencl_statistics_opencl_candidates", "opencl", "opencl"),
    )
    if args.backend != "cpu" and status["peak_candidates_f32"]:
        for _ in range(args.warmup):
            run_pipeline(values, args.sample_rate, args.chunk_samples, "cpu", "opencl")
        for label, statistics_backend, candidate_backend in opencl_modes:
            if statistics_backend == "opencl" and not status["peak_statistics_f32"]:
                modes[label] = {
                    "available": False,
                    "fallback_reason": status.get("reason") or "OpenCL statistics unavailable",
                }
                continue
            try:
                runs = [
                    run_pipeline(
                        values,
                        args.sample_rate,
                        args.chunk_samples,
                        statistics_backend,
                        candidate_backend,
                    )
                    for _ in range(args.repeats)
                ]
                measured = _summarize_runs(runs)
                measured["peak_index_equality"] = bool(
                    np.array_equal(measured["indices"], cpu["indices"])
                )
                measured["peak_type_equality"] = bool(
                    np.array_equal(measured["negative"], cpu["negative"])
                )
                measured["maximum_peak_value_difference"] = (
                    float(np.max(np.abs(measured["values"] - cpu["values"])))
                    if measured["values"].shape == cpu["values"].shape
                    and measured["values"].size
                    else None
                )
                measured["speedup_vs_cpu"] = cpu["elapsed_sec"] / measured["elapsed_sec"]
                modes[label] = _public_metrics(measured)
            except Exception as error:
                modes[label] = {
                    "available": False,
                    "fallback_reason": str(error),
                }
    else:
        reason = status.get("reason") or "OpenCL peak candidates unavailable"
        for label, _statistics_backend, _candidate_backend in opencl_modes:
            modes[label] = {"available": False, "fallback_reason": reason}

    return {
        "seed": SEED,
        "sample_rate_hz": args.sample_rate,
        "sample_count": sample_count,
        "duration_sec": sample_count / args.sample_rate,
        "chunk_samples": args.chunk_samples,
        "chunk_count": chunk_count,
        "repeats": args.repeats,
        "warmup": args.warmup,
        "opencl_cold_start_sec": cold_start_sec,
        "cpu_peak_count": int(cpu["indices"].size),
        "positive_peak_count": int(np.count_nonzero(~cpu["negative"])),
        "negative_peak_count": int(np.count_nonzero(cpu["negative"])),
        "opencl_device": status.get("device_name"),
        "opencl_vendor": status.get("device_vendor"),
        "opencl_platform": status.get("platform"),
        "supports_fp64": status.get("supports_fp64", False),
        "fallback_reason": status.get("reason") or last_peak_operation_error(),
        "opencl_elapsed_scope": (
            "End-to-end: CPU-to-GPU copy, kernels, GPU-to-CPU copy, CPU plateau, "
            "distance, prominence, chunk orchestration, and global deduplication."
        ),
        "modes": modes,
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-rate", type=float, default=1000.0)
    parser.add_argument("--duration", type=float, default=300.0)
    parser.add_argument("--samples", type=int)
    parser.add_argument("--chunk-samples", type=int, default=250_000)
    parser.add_argument("--backend", choices=("all", "cpu", "opencl"), default="all")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    if args.sample_rate <= 0 or args.duration <= 0:
        parser.error("sample rate and duration must be positive")
    if args.samples is not None and args.samples < 3:
        parser.error("samples must be at least 3")
    if args.chunk_samples < 3 or args.repeats < 1 or args.warmup < 0:
        parser.error("chunk-samples/repeats must be positive and warmup non-negative")
    return args


def main():
    args = parse_args()
    result = benchmark(args)
    encoded = json.dumps(result, indent=2, sort_keys=True)
    print(encoded)
    if args.result is not None:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(encoded + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
