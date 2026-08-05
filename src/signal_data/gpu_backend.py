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
_last_operation_error = None


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


def _record_operation_error(error) -> None:
    global _last_operation_error
    _last_operation_error = str(error)


def _configured_backend() -> str:
    value = os.environ.get("PIG_LFP_COMPUTE_BACKEND", "auto").strip().lower()
    return value if value in {"auto", "cpu", "opencl"} else "auto"


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
    return result


def select_backend(sample_count: int, requested: str | None = None) -> str:
    """Select CPU or OpenCL while keeping small arrays on the CPU."""

    requested = (requested or _configured_backend()).strip().lower()
    if requested not in {"auto", "cpu", "opencl"}:
        raise ValueError(f"Unsupported LFP compute backend: {requested}")
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
    if select_backend(input_values.size, requested) != "opencl":
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
