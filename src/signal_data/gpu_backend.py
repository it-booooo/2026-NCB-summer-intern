"""Optional OpenCL backend for bounded-memory LFP computations."""

from __future__ import annotations

import os
from functools import lru_cache

import numpy as np

from ..opencl_runtime import (
    OpenClUnavailable,
    build_opencl_program,
    opencl_runtime,
)


DEFAULT_GPU_MIN_SAMPLES = 100_000
DEFAULT_PEAK_GPU_MIN_SAMPLES = 10_000_000
_last_operation_error = None
_last_peak_operation_error = None


KERNEL_SOURCE = r"""
#if defined(cl_khr_fp64)
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#elif defined(cl_amd_fp64)
#pragma OPENCL EXTENSION cl_amd_fp64 : enable
#endif

__kernel void regression_coefficients_f32(
    __global const float *values,
    __global double *coefficients,
    __global const double *pseudo_inverse,
    __global const int *descriptor_starts,
    __global const int *full_descriptor_indices,
    const int sample_count,
    const int channel_count,
    const int coefficient_count,
    const int window_samples,
    const int full_window_count
) {
    const ulong gid = get_global_id(0);
    const ulong total = (ulong)full_window_count
        * (ulong)channel_count * (ulong)coefficient_count;
    if (gid >= total) {
        return;
    }

    const int coefficient = (int)(gid % (ulong)coefficient_count);
    const ulong window_channel = gid / (ulong)coefficient_count;
    const int channel = (int)(window_channel % (ulong)channel_count);
    const int full_window = (int)(window_channel / (ulong)channel_count);
    const int descriptor = full_descriptor_indices[full_window];
    const int local_start = descriptor_starts[descriptor];
    const ulong value_base = (ulong)channel * (ulong)sample_count
        + (ulong)local_start;
    const ulong inverse_base = (ulong)coefficient * (ulong)window_samples;

    double sum = 0.0;
    for (int sample = 0; sample < window_samples; ++sample) {
        sum += pseudo_inverse[inverse_base + (ulong)sample]
            * (double)values[value_base + (ulong)sample];
    }
    const ulong output_index = (
        ((ulong)descriptor * (ulong)channel_count + (ulong)channel)
        * (ulong)coefficient_count + (ulong)coefficient
    );
    coefficients[output_index] = sum;
}

__kernel void regression_coefficients_f64(
    __global const double *values,
    __global double *coefficients,
    __global const double *pseudo_inverse,
    __global const int *descriptor_starts,
    __global const int *full_descriptor_indices,
    const int sample_count,
    const int channel_count,
    const int coefficient_count,
    const int window_samples,
    const int full_window_count
) {
    const ulong gid = get_global_id(0);
    const ulong total = (ulong)full_window_count
        * (ulong)channel_count * (ulong)coefficient_count;
    if (gid >= total) {
        return;
    }

    const int coefficient = (int)(gid % (ulong)coefficient_count);
    const ulong window_channel = gid / (ulong)coefficient_count;
    const int channel = (int)(window_channel % (ulong)channel_count);
    const int full_window = (int)(window_channel / (ulong)channel_count);
    const int descriptor = full_descriptor_indices[full_window];
    const int local_start = descriptor_starts[descriptor];
    const ulong value_base = (ulong)channel * (ulong)sample_count
        + (ulong)local_start;
    const ulong inverse_base = (ulong)coefficient * (ulong)window_samples;

    double sum = 0.0;
    for (int sample = 0; sample < window_samples; ++sample) {
        sum += pseudo_inverse[inverse_base + (ulong)sample]
            * values[value_base + (ulong)sample];
    }
    const ulong output_index = (
        ((ulong)descriptor * (ulong)channel_count + (ulong)channel)
        * (ulong)coefficient_count + (ulong)coefficient
    );
    coefficients[output_index] = sum;
}

__kernel void reconstruct_clean_f32(
    __global const float *values,
    __global float *cleaned,
    __global const double *coefficients,
    __global const double *sinusoid_design,
    __global const double *window_weights,
    __global const int *descriptor_starts,
    __global const int *descriptor_counts,
    __global const int *descriptor_weight_starts,
    const int sample_count,
    const int channel_count,
    const int descriptor_count,
    const int coefficient_count,
    const int sinusoid_columns,
    const int window_samples,
    const int hop_samples,
    const long sample_offset,
    const long first_window_start
) {
    const ulong gid = get_global_id(0);
    const ulong total = (ulong)sample_count * (ulong)channel_count;
    if (gid >= total) {
        return;
    }

    const int sample = (int)(gid % (ulong)sample_count);
    const int channel = (int)(gid / (ulong)sample_count);
    const long global_sample = sample_offset + (long)sample;
    const long last_descriptor = (global_sample - first_window_start)
        / (long)hop_samples;
    const int candidate_count = (window_samples + hop_samples - 1) / hop_samples;
    double weighted_noise = 0.0;
    double weight_sum = 0.0;

    for (int candidate = 0; candidate < candidate_count; ++candidate) {
        const long descriptor_long = last_descriptor - (long)candidate;
        if (descriptor_long < 0 || descriptor_long >= (long)descriptor_count) {
            continue;
        }
        const int descriptor = (int)descriptor_long;
        const int local_position = sample - descriptor_starts[descriptor];
        if (local_position < 0 || local_position >= descriptor_counts[descriptor]) {
            continue;
        }
        const int weight_position = descriptor_weight_starts[descriptor]
            + local_position;
        const double weight = window_weights[weight_position];
        const ulong coefficient_base = (
            ((ulong)descriptor * (ulong)channel_count + (ulong)channel)
            * (ulong)coefficient_count
        );
        const ulong design_base = (ulong)local_position
            * (ulong)sinusoid_columns;
        double fitted = 0.0;
        for (int column = 0; column < sinusoid_columns; ++column) {
            fitted += sinusoid_design[design_base + (ulong)column]
                * coefficients[coefficient_base + (ulong)column];
        }
        weighted_noise += weight * fitted;
        weight_sum += weight;
    }

    const double noise = weight_sum > 2.2204460492503131e-16
        ? weighted_noise / weight_sum : 0.0;
    cleaned[gid] = values[gid] - (float)noise;
}

__kernel void reconstruct_clean_f64(
    __global const double *values,
    __global double *cleaned,
    __global const double *coefficients,
    __global const double *sinusoid_design,
    __global const double *window_weights,
    __global const int *descriptor_starts,
    __global const int *descriptor_counts,
    __global const int *descriptor_weight_starts,
    const int sample_count,
    const int channel_count,
    const int descriptor_count,
    const int coefficient_count,
    const int sinusoid_columns,
    const int window_samples,
    const int hop_samples,
    const long sample_offset,
    const long first_window_start
) {
    const ulong gid = get_global_id(0);
    const ulong total = (ulong)sample_count * (ulong)channel_count;
    if (gid >= total) {
        return;
    }

    const int sample = (int)(gid % (ulong)sample_count);
    const int channel = (int)(gid / (ulong)sample_count);
    const long global_sample = sample_offset + (long)sample;
    const long last_descriptor = (global_sample - first_window_start)
        / (long)hop_samples;
    const int candidate_count = (window_samples + hop_samples - 1) / hop_samples;
    double weighted_noise = 0.0;
    double weight_sum = 0.0;

    for (int candidate = 0; candidate < candidate_count; ++candidate) {
        const long descriptor_long = last_descriptor - (long)candidate;
        if (descriptor_long < 0 || descriptor_long >= (long)descriptor_count) {
            continue;
        }
        const int descriptor = (int)descriptor_long;
        const int local_position = sample - descriptor_starts[descriptor];
        if (local_position < 0 || local_position >= descriptor_counts[descriptor]) {
            continue;
        }
        const int weight_position = descriptor_weight_starts[descriptor]
            + local_position;
        const double weight = window_weights[weight_position];
        const ulong coefficient_base = (
            ((ulong)descriptor * (ulong)channel_count + (ulong)channel)
            * (ulong)coefficient_count
        );
        const ulong design_base = (ulong)local_position
            * (ulong)sinusoid_columns;
        double fitted = 0.0;
        for (int column = 0; column < sinusoid_columns; ++column) {
            fitted += sinusoid_design[design_base + (ulong)column]
                * coefficients[coefficient_base + (ulong)column];
        }
        weighted_noise += weight * fitted;
        weight_sum += weight;
    }

    const double noise = weight_sum > 2.2204460492503131e-16
        ? weighted_noise / weight_sum : 0.0;
    cleaned[gid] = values[gid] - noise;
}
"""


PEAK_KERNEL_SOURCE = r"""
#if defined(cl_khr_fp64)
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#define PIG_PEAK_FP64 1
#endif

__kernel void peak_candidate_mask_f32(
    __global const float *values,
    __global uchar *positive_mask,
    __global uchar *negative_mask,
    const float positive_threshold,
    const float negative_threshold,
    const uchar positive_strict,
    const uchar negative_strict,
    const int sample_count
) {
    const int index = (int)get_global_id(0);
    if (index >= sample_count) {
        return;
    }
    if (index == 0 || index == sample_count - 1) {
        positive_mask[index] = (uchar)0;
        negative_mask[index] = (uchar)0;
        return;
    }

    const float left = values[index - 1];
    const float center = values[index];
    const float right = values[index + 1];
    const int finite_values = isfinite(left) && isfinite(center) && isfinite(right);
    const int positive_height = positive_strict
        ? center > positive_threshold : center >= positive_threshold;
    const int negative_height = negative_strict
        ? center < negative_threshold : center <= negative_threshold;

    positive_mask[index] = (uchar)(
        finite_values && center >= left && center >= right && positive_height
    );
    negative_mask[index] = (uchar)(
        finite_values && center <= left && center <= right && negative_height
    );
}

__kernel void peak_statistics_f32(
    __global const float *values,
    __global ulong *partial_counts,
    __global float *partial_means,
    __global float *partial_m2,
    const int sample_count,
    __local ulong *local_counts,
    __local float *local_means,
    __local float *local_m2
) {
    const int global_id = (int)get_global_id(0);
    const int global_size = (int)get_global_size(0);
    const int local_id = (int)get_local_id(0);
    const int local_size = (int)get_local_size(0);
    ulong count = 0;
    float mean = 0.0f;
    float m2 = 0.0f;

    for (int index = global_id; index < sample_count; index += global_size) {
        const float value = values[index];
        if (!isfinite(value)) {
            continue;
        }
        count += 1;
        const float delta = value - mean;
        mean += delta / (float)count;
        m2 += delta * (value - mean);
    }
    local_counts[local_id] = count;
    local_means[local_id] = mean;
    local_m2[local_id] = m2;
    barrier(CLK_LOCAL_MEM_FENCE);

    for (int offset = local_size / 2; offset > 0; offset /= 2) {
        if (local_id < offset) {
            const ulong right_count = local_counts[local_id + offset];
            if (right_count > 0) {
                const ulong left_count = local_counts[local_id];
                if (left_count == 0) {
                    local_counts[local_id] = right_count;
                    local_means[local_id] = local_means[local_id + offset];
                    local_m2[local_id] = local_m2[local_id + offset];
                } else {
                    const ulong combined = left_count + right_count;
                    const float delta = local_means[local_id + offset]
                        - local_means[local_id];
                    local_m2[local_id] += local_m2[local_id + offset]
                        + delta * delta * (float)left_count * (float)right_count
                        / (float)combined;
                    local_means[local_id] += delta * (float)right_count
                        / (float)combined;
                    local_counts[local_id] = combined;
                }
            }
        }
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (local_id == 0) {
        const int group = (int)get_group_id(0);
        partial_counts[group] = local_counts[0];
        partial_means[group] = local_means[0];
        partial_m2[group] = local_m2[0];
    }
}

#ifdef PIG_PEAK_FP64
__kernel void peak_candidate_mask_f64(
    __global const double *values,
    __global uchar *positive_mask,
    __global uchar *negative_mask,
    const double positive_threshold,
    const double negative_threshold,
    const int sample_count
) {
    const int index = (int)get_global_id(0);
    if (index >= sample_count) {
        return;
    }
    if (index == 0 || index == sample_count - 1) {
        positive_mask[index] = (uchar)0;
        negative_mask[index] = (uchar)0;
        return;
    }

    const double left = values[index - 1];
    const double center = values[index];
    const double right = values[index + 1];
    const int finite_values = isfinite(left) && isfinite(center) && isfinite(right);
    positive_mask[index] = (uchar)(
        finite_values && center >= left && center >= right
        && center >= positive_threshold
    );
    negative_mask[index] = (uchar)(
        finite_values && center <= left && center <= right
        && center <= negative_threshold
    );
}

__kernel void peak_statistics_f64(
    __global const double *values,
    __global ulong *partial_counts,
    __global double *partial_means,
    __global double *partial_m2,
    const int sample_count,
    __local ulong *local_counts,
    __local double *local_means,
    __local double *local_m2
) {
    const int global_id = (int)get_global_id(0);
    const int global_size = (int)get_global_size(0);
    const int local_id = (int)get_local_id(0);
    const int local_size = (int)get_local_size(0);
    ulong count = 0;
    double mean = 0.0;
    double m2 = 0.0;

    for (int index = global_id; index < sample_count; index += global_size) {
        const double value = values[index];
        if (!isfinite(value)) {
            continue;
        }
        count += 1;
        const double delta = value - mean;
        mean += delta / (double)count;
        m2 += delta * (value - mean);
    }
    local_counts[local_id] = count;
    local_means[local_id] = mean;
    local_m2[local_id] = m2;
    barrier(CLK_LOCAL_MEM_FENCE);

    for (int offset = local_size / 2; offset > 0; offset /= 2) {
        if (local_id < offset) {
            const ulong right_count = local_counts[local_id + offset];
            if (right_count > 0) {
                const ulong left_count = local_counts[local_id];
                if (left_count == 0) {
                    local_counts[local_id] = right_count;
                    local_means[local_id] = local_means[local_id + offset];
                    local_m2[local_id] = local_m2[local_id + offset];
                } else {
                    const ulong combined = left_count + right_count;
                    const double delta = local_means[local_id + offset]
                        - local_means[local_id];
                    local_m2[local_id] += local_m2[local_id + offset]
                        + delta * delta * (double)left_count * (double)right_count
                        / (double)combined;
                    local_means[local_id] += delta * (double)right_count
                        / (double)combined;
                    local_counts[local_id] = combined;
                }
            }
        }
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (local_id == 0) {
        const int group = (int)get_group_id(0);
        partial_counts[group] = local_counts[0];
        partial_means[group] = local_means[0];
        partial_m2[group] = local_m2[0];
    }
}
#endif
"""


def _record_operation_error(error) -> None:
    global _last_operation_error
    _last_operation_error = str(error)


def _record_peak_operation_error(error) -> None:
    global _last_peak_operation_error
    _last_peak_operation_error = str(error)


def _configured_backend() -> str:
    value = os.environ.get("PIG_LFP_COMPUTE_BACKEND", "auto").strip().lower()
    if value not in {"auto", "cpu", "opencl"}:
        raise ValueError(f"Unsupported LFP compute backend: {value}")
    return value


def configured_backend(requested: str | None = None) -> str:
    """Return and validate an explicit or environment-selected LFP backend."""

    value = _configured_backend() if requested is None else str(requested).strip().lower()
    if value not in {"auto", "cpu", "opencl"}:
        raise ValueError(f"Unsupported LFP compute backend: {value}")
    return value


def _minimum_gpu_samples() -> int:
    try:
        return max(
            int(
                os.environ.get(
                    "PIG_LFP_OPENCL_MIN_SAMPLES",
                    DEFAULT_GPU_MIN_SAMPLES,
                )
            ),
            1,
        )
    except (TypeError, ValueError):
        return DEFAULT_GPU_MIN_SAMPLES


def regression_opencl_minimum_samples() -> int:
    """Return the workload threshold used by automatic regression dispatch."""

    return _minimum_gpu_samples()


def _minimum_peak_gpu_samples() -> int:
    try:
        return max(
            int(
                os.environ.get(
                    "PIG_LFP_OPENCL_PEAK_MIN_SAMPLES",
                    DEFAULT_PEAK_GPU_MIN_SAMPLES,
                )
            ),
            1,
        )
    except (TypeError, ValueError):
        return DEFAULT_PEAK_GPU_MIN_SAMPLES


def peak_opencl_minimum_samples() -> int:
    """Return the configured threshold used by automatic peak dispatch."""

    return _minimum_peak_gpu_samples()


@lru_cache(maxsize=1)
def _opencl_runtime():
    try:
        shared = opencl_runtime()
        if not shared["supports_fp64"]:
            raise OpenClUnavailable(
                "the selected OpenCL GPU lacks double-precision (cl_khr_fp64) support"
            )
        program = build_opencl_program(shared, KERNEL_SOURCE)
        return {**shared, "program": program}, None
    except Exception as error:
        return None, str(error)


@lru_cache(maxsize=1)
def _opencl_peak_runtime():
    """Build peak kernels independently from FP64 periodic regression kernels."""

    try:
        shared = opencl_runtime()
        extensions = set(str(shared["device"].extensions).lower().split())
        program = build_opencl_program(shared, PEAK_KERNEL_SOURCE)
        return {
            **shared,
            "peak_program": program,
            "peak_supports_fp64": "cl_khr_fp64" in extensions,
        }, None
    except Exception as error:
        return None, str(error)


def opencl_status() -> dict:
    """Return LFP OpenCL availability information without making it mandatory."""

    runtime, reason = _opencl_runtime()
    result = {
        "available": runtime is not None,
        "backend": "opencl" if runtime is not None else "cpu",
        "reason": reason,
        "last_operation_error": _last_operation_error,
        "minimum_samples": _minimum_gpu_samples(),
    }
    if runtime is not None:
        result.update(
            {
                "device_name": runtime["device_name"],
                "device_vendor": runtime["device_vendor"],
                "platform": runtime["platform_name"],
                "selected_reason": runtime["selected_reason"],
                "supports_fp64": runtime["supports_fp64"],
            }
        )
    peak_status = opencl_peak_status()
    result.update(
        {
            "device_available": peak_status["device_available"],
            "periodic_regression": runtime is not None,
            "peak_statistics_f32": peak_status["peak_statistics_f32"],
            "peak_statistics_f64": peak_status["peak_statistics_f64"],
            "peak_candidates_f32": peak_status["peak_candidates_f32"],
            "peak_candidates_f64": peak_status["peak_candidates_f64"],
        }
    )
    return result


def opencl_peak_status() -> dict:
    """Return serializable peak capabilities without exposing PyOpenCL objects."""

    runtime, reason = _opencl_peak_runtime()
    available = runtime is not None
    supports_fp64 = bool(available and runtime["peak_supports_fp64"])
    result = {
        "device_available": available,
        "supports_fp64": supports_fp64,
        "periodic_regression": bool(available and runtime["supports_fp64"]),
        "peak_statistics_f32": available,
        "peak_statistics_f64": supports_fp64,
        "peak_candidates_f32": available,
        "peak_candidates_f64": supports_fp64,
        "minimum_samples": _minimum_peak_gpu_samples(),
        "reason": reason,
        "last_operation_error": _last_peak_operation_error,
    }
    if available:
        result.update(
            {
                "device_name": runtime["device_name"],
                "device_vendor": runtime["device_vendor"],
                "platform": runtime["platform_name"],
                "selected_reason": runtime["selected_reason"],
            }
        )
    return result


def last_peak_operation_error():
    """Return the most recent peak OpenCL failure, if any."""

    return _last_peak_operation_error


def select_backend(sample_count: int, requested: str | None = None) -> str:
    """Select CPU or OpenCL while keeping small arrays on the CPU."""

    requested = configured_backend(requested)
    if requested == "cpu":
        return "cpu"
    if requested == "auto" and int(sample_count) < _minimum_gpu_samples():
        return "cpu"

    runtime, reason = _opencl_runtime()
    if runtime is None:
        if requested == "opencl":
            raise RuntimeError(f"OpenCL backend is unavailable: {reason}")
        return "cpu"
    return "opencl"


def _select_peak_backend(
    sample_count: int,
    dtype,
    requested: str | None,
    capability_name: str,
) -> str:
    selected = configured_backend(requested)
    if selected == "cpu":
        return "cpu"
    if selected == "auto" and int(sample_count) < _minimum_peak_gpu_samples():
        return "cpu"

    dtype = np.dtype(dtype)
    if dtype not in {np.dtype(np.float32), np.dtype(np.float64)}:
        if selected == "opencl":
            raise TypeError(
                f"OpenCL {capability_name} supports float32 and float64, not {dtype}."
            )
        return "cpu"

    runtime, reason = _opencl_peak_runtime()
    if runtime is None:
        _record_peak_operation_error(reason)
        if selected == "opencl":
            raise RuntimeError(
                f"OpenCL {capability_name} is unavailable: {reason}"
            )
        return "cpu"
    if dtype == np.dtype(np.float64) and not runtime["peak_supports_fp64"]:
        reason = (
            f"OpenCL {capability_name} for float64 requires the standard "
            "cl_khr_fp64 extension"
        )
        _record_peak_operation_error(reason)
        if selected == "opencl":
            raise RuntimeError(
                f"OpenCL {capability_name} is unavailable: operation={capability_name}; "
                f"dtype={dtype}; device={runtime.get('device_name', 'unknown')}; "
                f"vendor={runtime.get('device_vendor', 'unknown')}; "
                f"platform={runtime.get('platform_name', 'unknown')}; reason={reason}"
            )
        return "cpu"
    return "opencl"


def select_peak_candidate_backend(
    sample_count: int,
    dtype=np.float32,
    requested: str | None = None,
) -> str:
    """Select the candidate scan independently from other OpenCL features."""

    return _select_peak_backend(sample_count, dtype, requested, "peak candidates")


def select_peak_statistics_backend(
    sample_count: int,
    dtype=np.float32,
    requested: str | None = None,
) -> str:
    """Select chunk statistics independently from the candidate scan."""

    return _select_peak_backend(sample_count, dtype, requested, "peak statistics")


def _peak_error_message(operation, dtype, sample_count, runtime, error) -> str:
    def metadata(name, default="unknown"):
        try:
            return str(runtime.get(name, default))
        except Exception:
            return default

    return (
        f"OpenCL peak operation failed: operation={operation}; dtype={np.dtype(dtype)}; "
        f"sample_count={int(sample_count)}; device={metadata('device_name')}; "
        f"vendor={metadata('device_vendor')}; platform={metadata('platform_name')}; "
        f"reason={type(error).__name__}: {error}"
    )


def peak_candidate_masks_cpu(
    values,
    positive_threshold: float,
    negative_threshold: float,
):
    """Return the exact CPU reference masks used to validate OpenCL kernels."""

    input_values = np.asarray(values)
    if input_values.ndim != 1:
        raise ValueError("Peak candidates require a one-dimensional signal.")
    if not np.isfinite(positive_threshold) or not np.isfinite(negative_threshold):
        raise ValueError("Peak candidate thresholds must be finite.")
    positive = np.zeros(input_values.size, dtype=np.uint8)
    negative = np.zeros(input_values.size, dtype=np.uint8)
    if input_values.size < 3:
        return positive, negative
    left = input_values[:-2]
    center = input_values[1:-1]
    right = input_values[2:]
    threshold_values = center.astype(np.float64, copy=False)
    finite = np.isfinite(left) & np.isfinite(center) & np.isfinite(right)
    positive[1:-1] = (
        finite
        & (center >= left)
        & (center >= right)
        & (threshold_values >= float(positive_threshold))
    )
    negative[1:-1] = (
        finite
        & (center <= left)
        & (center <= right)
        & (threshold_values <= float(negative_threshold))
    )
    return positive, negative


def peak_candidate_masks_opencl(
    values,
    positive_threshold: float,
    negative_threshold: float,
    *,
    requested: str | None = None,
):
    """Return positive/negative uint8 masks, or ``None`` for automatic CPU use."""

    input_values = np.asarray(values)
    if input_values.ndim != 1:
        raise ValueError("OpenCL peak candidates require a one-dimensional signal.")
    if not np.isfinite(positive_threshold) or not np.isfinite(negative_threshold):
        raise ValueError("Peak candidate thresholds must be finite.")
    sample_count = int(input_values.size)
    if sample_count < 3:
        empty = np.zeros(sample_count, dtype=np.uint8)
        return empty, empty.copy()
    if (
        select_peak_candidate_backend(sample_count, input_values.dtype, requested)
        != "opencl"
    ):
        return None

    runtime, reason = _opencl_peak_runtime()
    if runtime is None:
        error = RuntimeError(reason or "OpenCL peak runtime is unavailable")
        _record_peak_operation_error(error)
        if configured_backend(requested) == "opencl":
            raise error
        return None
    try:
        return _peak_candidate_masks_opencl(
            runtime,
            input_values,
            float(positive_threshold),
            float(negative_threshold),
        )
    except Exception as error:
        detail = _peak_error_message(
            "candidate-mask",
            input_values.dtype,
            sample_count,
            runtime,
            error,
        )
        _record_peak_operation_error(detail)
        if configured_backend(requested) == "opencl":
            raise RuntimeError(detail) from error
        return None


def _peak_candidate_masks_opencl(
    runtime,
    input_values,
    positive_threshold,
    negative_threshold,
):
    host_values = np.ascontiguousarray(input_values)
    sample_count = int(host_values.size)
    max_alloc_size = int(runtime.get("max_alloc_size", host_values.nbytes))
    if host_values.nbytes > max_alloc_size or sample_count > max_alloc_size:
        raise MemoryError("one peak candidate buffer exceeds the device allocation limit")

    cl = runtime["cl"]
    context = runtime["context"]
    queue = cl.CommandQueue(context)
    values_buffer = _read_only_buffer(cl, context, host_values)
    positive_mask = np.empty(sample_count, dtype=np.uint8)
    negative_mask = np.empty(sample_count, dtype=np.uint8)
    positive_buffer = cl.Buffer(
        context, cl.mem_flags.WRITE_ONLY, positive_mask.nbytes
    )
    negative_buffer = cl.Buffer(
        context, cl.mem_flags.WRITE_ONLY, negative_mask.nbytes
    )

    if host_values.dtype == np.dtype(np.float32):
        with np.errstate(over="ignore", invalid="ignore"):
            positive_bound = np.float32(positive_threshold)
            negative_bound = np.float32(negative_threshold)
        # A strict flag preserves comparison with a Python float threshold even
        # when that threshold lies between adjacent representable float32 values.
        positive_strict = np.uint8(float(positive_bound) < positive_threshold)
        negative_strict = np.uint8(float(negative_bound) > negative_threshold)
        kernel = cl.Kernel(runtime["peak_program"], "peak_candidate_mask_f32")
        kernel(
            queue,
            (sample_count,),
            None,
            values_buffer,
            positive_buffer,
            negative_buffer,
            positive_bound,
            negative_bound,
            positive_strict,
            negative_strict,
            np.int32(sample_count),
        )
    else:
        kernel = cl.Kernel(runtime["peak_program"], "peak_candidate_mask_f64")
        kernel(
            queue,
            (sample_count,),
            None,
            values_buffer,
            positive_buffer,
            negative_buffer,
            np.float64(positive_threshold),
            np.float64(negative_threshold),
            np.int32(sample_count),
        )
    cl.enqueue_copy(queue, positive_mask, positive_buffer, is_blocking=False)
    cl.enqueue_copy(queue, negative_mask, negative_buffer, is_blocking=True)
    queue.finish()
    return positive_mask, negative_mask


def chunk_statistics_opencl(values, *, requested: str | None = None):
    """Return finite ``(count, mean, M2)`` or ``None`` for automatic CPU use."""

    input_values = np.asarray(values)
    if input_values.ndim != 1:
        raise ValueError("OpenCL peak statistics require a one-dimensional signal.")
    sample_count = int(input_values.size)
    if sample_count == 0:
        return 0, float("nan"), 0.0
    if (
        select_peak_statistics_backend(sample_count, input_values.dtype, requested)
        != "opencl"
    ):
        return None

    runtime, reason = _opencl_peak_runtime()
    if runtime is None:
        error = RuntimeError(reason or "OpenCL peak runtime is unavailable")
        _record_peak_operation_error(error)
        if configured_backend(requested) == "opencl":
            raise error
        return None
    try:
        return _chunk_statistics_opencl(runtime, input_values)
    except Exception as error:
        detail = _peak_error_message(
            "chunk-statistics",
            input_values.dtype,
            sample_count,
            runtime,
            error,
        )
        _record_peak_operation_error(detail)
        if configured_backend(requested) == "opencl":
            raise RuntimeError(detail) from error
        return None


def _chunk_statistics_opencl(runtime, input_values):
    host_values = np.ascontiguousarray(input_values)
    sample_count = int(host_values.size)
    max_alloc_size = int(runtime.get("max_alloc_size", host_values.nbytes))
    if host_values.nbytes > max_alloc_size:
        raise MemoryError("the peak statistics input exceeds the device allocation limit")

    cl = runtime["cl"]
    context = runtime["context"]
    queue = cl.CommandQueue(context)
    local_size = max(int(runtime.get("local_size", 1)), 1)
    group_count = max(1, min((sample_count + local_size - 1) // local_size, 256))
    global_size = group_count * local_size
    partial_dtype = host_values.dtype
    partial_counts = np.empty(group_count, dtype=np.uint64)
    partial_means = np.empty(group_count, dtype=partial_dtype)
    partial_m2 = np.empty(group_count, dtype=partial_dtype)

    values_buffer = _read_only_buffer(cl, context, host_values)
    counts_buffer = cl.Buffer(context, cl.mem_flags.WRITE_ONLY, partial_counts.nbytes)
    means_buffer = cl.Buffer(context, cl.mem_flags.WRITE_ONLY, partial_means.nbytes)
    m2_buffer = cl.Buffer(context, cl.mem_flags.WRITE_ONLY, partial_m2.nbytes)
    suffix = "f32" if partial_dtype == np.dtype(np.float32) else "f64"
    kernel = cl.Kernel(runtime["peak_program"], f"peak_statistics_{suffix}")
    scalar_bytes = int(partial_dtype.itemsize)
    kernel(
        queue,
        (global_size,),
        (local_size,),
        values_buffer,
        counts_buffer,
        means_buffer,
        m2_buffer,
        np.int32(sample_count),
        cl.LocalMemory(local_size * np.dtype(np.uint64).itemsize),
        cl.LocalMemory(local_size * scalar_bytes),
        cl.LocalMemory(local_size * scalar_bytes),
    )
    cl.enqueue_copy(queue, partial_counts, counts_buffer, is_blocking=False)
    cl.enqueue_copy(queue, partial_means, means_buffer, is_blocking=False)
    cl.enqueue_copy(queue, partial_m2, m2_buffer, is_blocking=True)
    queue.finish()

    count = 0
    mean = 0.0
    m2 = 0.0
    for partial_count, partial_mean, partial_value_m2 in zip(
        partial_counts, partial_means, partial_m2
    ):
        right_count = int(partial_count)
        if right_count == 0:
            continue
        right_mean = float(partial_mean)
        combined = count + right_count
        delta = right_mean - mean
        m2 += (
            float(partial_value_m2)
            + delta * delta * count * right_count / combined
        )
        mean += delta * right_count / combined
        count = combined
    if count == 0:
        return 0, float("nan"), 0.0
    return count, mean, m2


def periodic_noise_regression_opencl(
    values,
    sample_rate_hz: float,
    frequencies,
    window_samples: int,
    hop_samples: int,
    sample_offset: int,
    output_dtype,
    *,
    requested: str | None = None,
    dispatch_sample_count: int | None = None,
):
    """Run overlapping sinusoidal regressions on an OpenCL GPU.

    The small, signal-independent pseudo-inverse is cached on the CPU. Window
    coefficient multiplication, overlap-add reconstruction, and subtraction are
    performed by OpenCL kernels. Automatic mode returns ``None`` when CPU is
    selected or a GPU operation fails; an explicit OpenCL request reports errors.
    """

    input_values = np.asarray(values)
    output_dtype = np.dtype(output_dtype)
    if output_dtype not in {np.dtype(np.float32), np.dtype(np.float64)}:
        requested_backend = (requested or _configured_backend()).strip().lower()
        if requested_backend == "opencl":
            raise TypeError(
                "OpenCL sinusoidal regression supports float32 and float64 output."
            )
        return None
    selection_count = (
        input_values.size
        if dispatch_sample_count is None
        else max(int(dispatch_sample_count), 0)
    )
    if select_backend(selection_count, requested) != "opencl":
        return None
    runtime, _reason = _opencl_runtime()
    try:
        return _periodic_noise_regression_opencl(
            runtime,
            input_values,
            float(sample_rate_hz),
            np.asarray(frequencies, dtype=np.float64),
            int(window_samples),
            int(hop_samples),
            int(sample_offset),
            output_dtype,
        )
    except Exception as error:
        _record_operation_error(error)
        if requested == "opencl" or _configured_backend() == "opencl":
            raise
        return None


def _design_matrix(sample_count, sample_rate_hz, frequencies):
    local_time = np.arange(sample_count, dtype=np.float64) / sample_rate_hz
    angular_time = 2.0 * np.pi * local_time[:, np.newaxis] * frequencies
    sinusoid_design = np.empty(
        (sample_count, 2 * int(frequencies.size)),
        dtype=np.float64,
    )
    sinusoid_design[:, 0::2] = np.sin(angular_time)
    sinusoid_design[:, 1::2] = np.cos(angular_time)
    trend = np.linspace(-1.0, 1.0, sample_count, dtype=np.float64)
    design = np.column_stack(
        (sinusoid_design, np.ones(sample_count, dtype=np.float64), trend)
    )
    return sinusoid_design, design


@lru_cache(maxsize=32)
def _cached_design(sample_count, sample_rate_hz, frequencies):
    frequency_values = np.asarray(frequencies, dtype=np.float64)
    sinusoid_design, design = _design_matrix(
        int(sample_count),
        float(sample_rate_hz),
        frequency_values,
    )
    pseudo_inverse = np.linalg.pinv(design)
    return (
        np.ascontiguousarray(sinusoid_design),
        np.ascontiguousarray(pseudo_inverse),
    )


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
    descriptors = []
    full_descriptor_indices = []
    for window_start in range(first_window, input_end, hop_samples):
        local_start = max(window_start - sample_offset, 0)
        local_end = min(window_start + window_samples - sample_offset, sample_count)
        local_count = local_end - local_start
        if local_count < design_columns:
            continue
        weight_start = local_start - (window_start - sample_offset)
        descriptor_index = len(descriptors)
        descriptors.append(
            (window_start, local_start, local_count, weight_start)
        )
        if local_count == window_samples:
            full_descriptor_indices.append(descriptor_index)

    if not descriptors:
        raise ValueError("No regression window contains enough signal samples.")
    expected_starts = range(
        descriptors[0][0],
        descriptors[0][0] + len(descriptors) * hop_samples,
        hop_samples,
    )
    if any(
        descriptor[0] != expected
        for descriptor, expected in zip(descriptors, expected_starts)
    ):
        raise RuntimeError("Regression windows are not contiguous.")
    return descriptors, full_descriptor_indices


def _read_only_buffer(cl, context, values):
    contiguous = np.ascontiguousarray(values)
    return cl.Buffer(
        context,
        cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,
        hostbuf=contiguous,
    )


def _periodic_noise_regression_opencl(
    runtime,
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
    host_values = np.ascontiguousarray(channels_first, dtype=output_dtype)
    sample_count = int(host_values.shape[-1])
    channel_count = int(host_values.shape[0])
    sinusoid_columns = 2 * int(frequency_values.size)
    design_columns = sinusoid_columns + 2
    descriptors, full_descriptor_indices = _window_descriptors(
        sample_count,
        window_samples,
        hop_samples,
        sample_offset,
        design_columns,
    )
    descriptor_count = len(descriptors)
    first_window_start = descriptors[0][0]
    descriptor_starts = np.ascontiguousarray(
        [descriptor[1] for descriptor in descriptors], dtype=np.int32
    )
    descriptor_counts = np.ascontiguousarray(
        [descriptor[2] for descriptor in descriptors], dtype=np.int32
    )
    descriptor_weight_starts = np.ascontiguousarray(
        [descriptor[3] for descriptor in descriptors], dtype=np.int32
    )
    full_descriptor_indices = np.ascontiguousarray(
        full_descriptor_indices, dtype=np.int32
    )

    frequencies_key = tuple(float(value) for value in frequency_values)
    sinusoid_design, pseudo_inverse = _cached_design(
        window_samples,
        sample_rate_hz,
        frequencies_key,
    )
    coefficients = np.zeros(
        (descriptor_count, channel_count, design_columns),
        dtype=np.float64,
    )
    full_descriptor_set = set(int(value) for value in full_descriptor_indices)
    for descriptor_index, descriptor in enumerate(descriptors):
        if descriptor_index in full_descriptor_set:
            continue
        _window_start, local_start, local_count, _weight_start = descriptor
        _partial_sinusoids, partial_inverse = _cached_design(
            local_count,
            sample_rate_hz,
            frequencies_key,
        )
        coefficients[descriptor_index] = (
            partial_inverse
            @ host_values[:, local_start : local_start + local_count].T
        ).T

    full_weight = np.ascontiguousarray(
        np.hanning(window_samples + 2)[1:-1], dtype=np.float64
    )
    coefficients = np.ascontiguousarray(coefficients)
    cl = runtime["cl"]
    context = runtime["context"]
    queue = cl.CommandQueue(context)
    program = runtime["program"]

    values_buffer = _read_only_buffer(cl, context, host_values)
    coefficients_buffer = cl.Buffer(
        context,
        cl.mem_flags.READ_WRITE | cl.mem_flags.COPY_HOST_PTR,
        hostbuf=coefficients,
    )
    inverse_buffer = _read_only_buffer(cl, context, pseudo_inverse)
    design_buffer = _read_only_buffer(cl, context, sinusoid_design)
    weights_buffer = _read_only_buffer(cl, context, full_weight)
    starts_buffer = _read_only_buffer(cl, context, descriptor_starts)
    counts_buffer = _read_only_buffer(cl, context, descriptor_counts)
    weight_starts_buffer = _read_only_buffer(
        cl, context, descriptor_weight_starts
    )

    if full_descriptor_indices.size:
        full_indices_buffer = _read_only_buffer(
            cl, context, full_descriptor_indices
        )
        coefficient_kernel = (
            cl.Kernel(program, "regression_coefficients_f32")
            if output_dtype == np.dtype(np.float32)
            else cl.Kernel(program, "regression_coefficients_f64")
        )
        coefficient_kernel(
            queue,
            (
                int(full_descriptor_indices.size)
                * channel_count
                * design_columns,
            ),
            None,
            values_buffer,
            coefficients_buffer,
            inverse_buffer,
            starts_buffer,
            full_indices_buffer,
            np.int32(sample_count),
            np.int32(channel_count),
            np.int32(design_columns),
            np.int32(window_samples),
            np.int32(full_descriptor_indices.size),
        )

    result = np.empty_like(host_values)
    result_buffer = cl.Buffer(context, cl.mem_flags.WRITE_ONLY, result.nbytes)
    reconstruction_kernel = (
        cl.Kernel(program, "reconstruct_clean_f32")
        if output_dtype == np.dtype(np.float32)
        else cl.Kernel(program, "reconstruct_clean_f64")
    )
    reconstruction_kernel(
        queue,
        (sample_count * channel_count,),
        None,
        values_buffer,
        result_buffer,
        coefficients_buffer,
        design_buffer,
        weights_buffer,
        starts_buffer,
        counts_buffer,
        weight_starts_buffer,
        np.int32(sample_count),
        np.int32(channel_count),
        np.int32(descriptor_count),
        np.int32(design_columns),
        np.int32(sinusoid_columns),
        np.int32(window_samples),
        np.int32(hop_samples),
        np.int64(sample_offset),
        np.int64(first_window_start),
    )
    cl.enqueue_copy(queue, result, result_buffer, is_blocking=True)
    queue.finish()
    return result[0] if input_values.ndim == 1 else result
