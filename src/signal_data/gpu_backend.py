"""Optional CuPy backend for bounded-memory LFP computations."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..cupy_bootstrap import configure_cupy_environment


DEFAULT_GPU_MIN_SAMPLES = 100_000
_last_operation_error = None


def _record_operation_error(error) -> None:
    global _last_operation_error
    _last_operation_error = str(error)


def _configured_backend() -> str:
    value = os.environ.get("PIG_LFP_COMPUTE_BACKEND", "auto").strip().lower()
    return value if value in {"auto", "cpu", "cupy"} else "auto"


def _minimum_gpu_samples() -> int:
    try:
        return max(
            int(
                os.environ.get(
                    "PIG_LFP_CUPY_MIN_SAMPLES",
                    DEFAULT_GPU_MIN_SAMPLES,
                )
            ),
            1,
        )
    except (TypeError, ValueError):
        return DEFAULT_GPU_MIN_SAMPLES


@lru_cache(maxsize=1)
def _cupy_runtime():
    try:
        configure_cupy_environment()
        import cupy as cp

        configure_cupy_environment(cp.__file__)
        device_count = int(cp.cuda.runtime.getDeviceCount())
        if device_count <= 0:
            return None, "no CUDA device available"
        cp.cuda.Device().compute_capability
        probe = cp.arange(4, dtype=cp.float32)
        float(cp.sum(probe).item())
        return cp, None
    except UnicodeDecodeError:
        return (
            None,
            "CuPy CUDA kernel compilation failed; verify that the Conda "
            "cuda-version does not exceed the NVIDIA driver's supported CUDA version",
        )
    except Exception as error:
        return None, str(error)


def cupy_status() -> dict:
    """Return availability information without making CuPy mandatory."""

    cp, reason = _cupy_runtime()
    result = {
        "available": cp is not None,
        "backend": "cupy" if cp is not None else "cpu",
        "reason": reason,
        "last_operation_error": _last_operation_error,
        "python": sys.executable,
        "cuda_path": os.environ.get("CUDA_PATH"),
        "temp": os.environ.get("TEMP"),
    }
    if cp is not None:
        result["cupy_path"] = str(Path(cp.__file__).resolve())
        try:
            device = cp.cuda.Device()
            properties = cp.cuda.runtime.getDeviceProperties(device.id)
            name = properties.get("name", "CUDA GPU")
            if isinstance(name, bytes):
                name = name.decode(errors="replace")
            result.update({"device_id": int(device.id), "device_name": str(name)})
        except Exception:
            pass
    return result


def select_backend(sample_count: int, requested: str | None = None) -> str:
    """Select CPU or CuPy while keeping small arrays on the CPU."""

    requested = (requested or _configured_backend()).strip().lower()
    if requested not in {"auto", "cpu", "cupy"}:
        raise ValueError(f"Unsupported LFP compute backend: {requested}")
    if requested == "cpu":
        return "cpu"
    if requested == "auto" and int(sample_count) < _minimum_gpu_samples():
        return "cpu"

    cp, reason = _cupy_runtime()
    if cp is None:
        if requested == "cupy":
            raise RuntimeError(f"CuPy backend is unavailable: {reason}")
        return "cpu"
    return "cupy"


def periodic_noise_regression_cupy(
    values,
    sample_rate_hz: float,
    frequencies,
    window_samples: int,
    hop_samples: int,
    sample_offset: int,
    output_dtype,
    *,
    requested: str | None = None,
):
    """Run batched overlapping sinusoidal regressions on a CUDA GPU.

    Returns ``None`` when automatic backend selection chooses CPU or a CuPy
    operation fails. Explicit ``requested='cupy'`` errors are reported instead
    of silently falling back.
    """

    input_values = np.asarray(values)
    if select_backend(input_values.size, requested) != "cupy":
        return None
    cp, _reason = _cupy_runtime()
    try:
        return _periodic_noise_regression_cupy(
            cp,
            input_values,
            float(sample_rate_hz),
            np.asarray(frequencies, dtype=np.float64),
            int(window_samples),
            int(hop_samples),
            int(sample_offset),
            np.dtype(output_dtype),
        )
    except Exception as error:
        _record_operation_error(error)
        if requested == "cupy" or _configured_backend() == "cupy":
            raise
        return None


def _design_matrix(cp, sample_count, sample_rate_hz, frequencies):
    local_time = cp.arange(sample_count, dtype=cp.float64) / sample_rate_hz
    angular_time = 2.0 * cp.pi * local_time[:, cp.newaxis] * frequencies
    sinusoid_design = cp.empty(
        (sample_count, 2 * int(frequencies.size)),
        dtype=cp.float64,
    )
    sinusoid_design[:, 0::2] = cp.sin(angular_time)
    sinusoid_design[:, 1::2] = cp.cos(angular_time)
    trend = cp.linspace(-1.0, 1.0, sample_count, dtype=cp.float64)
    design = cp.column_stack(
        (sinusoid_design, cp.ones(sample_count, dtype=cp.float64), trend)
    )
    return sinusoid_design, design


def _window_descriptors(
    sample_count,
    window_samples,
    hop_samples,
    sample_offset,
    design_columns,
):
    first_window = max(
        0,
        ((sample_offset - window_samples + 1 + hop_samples - 1) // hop_samples)
        * hop_samples,
    )
    input_end = sample_offset + sample_count
    full_starts = []
    partial = []
    for window_start in range(first_window, input_end, hop_samples):
        local_start = max(window_start - sample_offset, 0)
        local_end = min(window_start + window_samples - sample_offset, sample_count)
        local_count = local_end - local_start
        if local_count < design_columns:
            continue
        weight_start = local_start - (window_start - sample_offset)
        descriptor = (local_start, local_end, weight_start)
        if local_count == window_samples:
            full_starts.append(local_start)
        else:
            partial.append(descriptor)
    return full_starts, partial


def _periodic_noise_regression_cupy(
    cp,
    input_values,
    sample_rate_hz,
    frequency_values,
    window_samples,
    hop_samples,
    sample_offset,
    output_dtype,
):
    channels_first = (
        input_values.reshape(1, -1)
        if input_values.ndim == 1
        else input_values
    )
    sample_count = int(channels_first.shape[-1])
    channel_count = int(channels_first.shape[0])
    design_columns = 2 * int(frequency_values.size) + 2
    full_starts, partial_windows = _window_descriptors(
        sample_count,
        window_samples,
        hop_samples,
        sample_offset,
        design_columns,
    )

    gpu_values = cp.asarray(channels_first)
    gpu_frequencies = cp.asarray(frequency_values, dtype=cp.float64)
    gpu_dtype = cp.dtype(output_dtype)
    accumulated_noise = cp.zeros(channels_first.shape, dtype=gpu_dtype)
    accumulated_weight = cp.zeros(sample_count, dtype=cp.float64)
    full_weight = cp.hanning(window_samples + 2)[1:-1]

    if full_starts:
        sinusoid_design, design = _design_matrix(
            cp,
            window_samples,
            sample_rate_hz,
            gpu_frequencies,
        )
        starts = cp.asarray(full_starts, dtype=cp.int64)
        sample_stride = gpu_values.strides[-1]
        windows = cp.lib.stride_tricks.as_strided(
            gpu_values,
            shape=(
                channel_count,
                sample_count - window_samples + 1,
                window_samples,
            ),
            strides=(gpu_values.strides[0], sample_stride, sample_stride),
        )
        right_hand_sides = windows[:, starts, :].transpose(2, 1, 0).reshape(
            window_samples,
            -1,
        )
        coefficients, *_unused = cp.linalg.lstsq(
            design,
            right_hand_sides,
            rcond=None,
        )
        fitted = sinusoid_design @ coefficients[: sinusoid_design.shape[1]]
        fitted = fitted.reshape(window_samples, len(full_starts), channel_count)
        fitted = fitted.transpose(1, 2, 0)
        weighted = (fitted * full_weight[cp.newaxis, cp.newaxis, :]).astype(
            gpu_dtype,
            copy=False,
        )
        indices = starts[:, cp.newaxis] + cp.arange(
            window_samples,
            dtype=cp.int64,
        )[cp.newaxis, :]
        cp.add.at(
            accumulated_weight,
            indices,
            cp.broadcast_to(full_weight, indices.shape),
        )
        for channel in range(channel_count):
            cp.add.at(
                accumulated_noise[channel],
                indices,
                weighted[:, channel, :],
            )

    for local_start, local_end, weight_start in partial_windows:
        local_count = local_end - local_start
        weights = full_weight[weight_start : weight_start + local_count]
        sinusoid_design, design = _design_matrix(
            cp,
            local_count,
            sample_rate_hz,
            gpu_frequencies,
        )
        coefficients, *_unused = cp.linalg.lstsq(
            design,
            gpu_values[:, local_start:local_end].T,
            rcond=None,
        )
        fitted = sinusoid_design @ coefficients[: sinusoid_design.shape[1]]
        accumulated_noise[:, local_start:local_end] += (
            fitted.T * weights
        ).astype(gpu_dtype, copy=False)
        accumulated_weight[local_start:local_end] += weights

    uncovered = accumulated_weight <= np.finfo(np.float64).eps
    accumulated_noise[:, uncovered] = 0
    accumulated_weight[uncovered] = 1.0
    accumulated_noise /= accumulated_weight[cp.newaxis, :]
    cp.subtract(
        gpu_values,
        accumulated_noise,
        out=accumulated_noise,
        casting="unsafe",
    )
    result = cp.asnumpy(accumulated_noise)
    return result[0] if input_values.ndim == 1 else result
