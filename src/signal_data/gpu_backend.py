"""Optional CuPy helpers for large, bounded-memory signal operations."""

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
    if value not in {"auto", "cpu", "cupy"}:
        return "auto"
    return value


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
        if not os.environ.get("CUPY_CACHE_DIR"):
            cache_path = Path.cwd() / ".cupy_cache"
            cache_path.mkdir(parents=True, exist_ok=True)
            os.environ["CUPY_CACHE_DIR"] = str(cache_path)
        # NVRTC and CuPy JIT are unreliable with non-ASCII Windows temp paths,
        # and different launchers can provide conflicting TEMP/TMP values.
        temp_path = Path.cwd() / ".cupy_temp"
        temp_path.mkdir(parents=True, exist_ok=True)
        os.environ["TEMP"] = str(temp_path)
        os.environ["TMP"] = str(temp_path)
        os.environ["TMPDIR"] = str(temp_path)
        import cupy as cp
        configure_cupy_environment(cp.__file__)

        device_count = int(cp.cuda.runtime.getDeviceCount())
        if device_count <= 0:
            return None, "no CUDA device available"
        # Force runtime initialization now so later operations do not fail
        # after the backend has already been selected.
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
    if requested == "auto" and int(sample_count) < _minimum_gpu_samples():
        return "cpu"
    return "cupy"


def chunk_mean_m2(values, requested: str | None = None):
    """Return finite count, mean and M2 using the selected array backend."""

    values = np.asarray(values)
    backend = select_backend(values.size, requested)
    if backend == "cpu":
        finite = values[np.isfinite(values)]
        count = int(finite.size)
        if count == 0:
            return 0, 0.0, 0.0, backend
        mean = float(np.mean(finite, dtype=np.float64))
        centered = finite.astype(np.float64) - mean
        m2 = float(np.sum(centered * centered, dtype=np.float64))
        return count, mean, m2, backend

    cp, _ = _cupy_runtime()
    try:
        gpu_values = cp.asarray(values)
        finite = gpu_values[cp.isfinite(gpu_values)].astype(cp.float64, copy=False)
        count = int(finite.size)
        if count == 0:
            return 0, 0.0, 0.0, backend
        mean_gpu = cp.mean(finite, dtype=cp.float64)
        centered = finite - mean_gpu
        m2_gpu = cp.sum(centered * centered, dtype=cp.float64)
        return count, float(mean_gpu.item()), float(m2_gpu.item()), backend
    except Exception:
        if requested == "cupy" or _configured_backend() == "cupy":
            raise
        return chunk_mean_m2(values, requested="cpu")


def local_peak_candidate_mask(
    values,
    minimum_height: float,
    *,
    negative: bool = False,
    requested: str | None = None,
):
    """Return a superset mask of local peaks, including complete plateaus."""

    values = np.asarray(values)
    if values.size < 3:
        return np.zeros(values.size, dtype=bool), "cpu"
    backend = select_backend(values.size, requested)
    if backend == "cpu":
        working = -values if negative else values
        center = working[1:-1]
        mask = np.zeros(values.size, dtype=bool)
        mask[1:-1] = (
            np.isfinite(center)
            & (center >= working[:-2])
            & (center >= working[2:])
            & (center >= float(minimum_height))
        )
        return mask, backend

    cp, _ = _cupy_runtime()
    try:
        gpu_values = cp.asarray(values)
        working = -gpu_values if negative else gpu_values
        center = working[1:-1]
        inner = (
            cp.isfinite(center)
            & (center >= working[:-2])
            & (center >= working[2:])
            & (center >= float(minimum_height))
        )
        mask = cp.zeros(gpu_values.size, dtype=cp.bool_)
        mask[1:-1] = inner
        return cp.asnumpy(mask), backend
    except Exception as error:
        _record_operation_error(error)
        if requested == "cupy" or _configured_backend() == "cupy":
            raise
        return local_peak_candidate_mask(
            values,
            minimum_height,
            negative=negative,
            requested="cpu",
        )


def _finite_gpu_signal(cp, values):
    signal_values = cp.asarray(values)
    if signal_values.dtype.kind != "f":
        signal_values = signal_values.astype(cp.float64)
    if signal_values.ndim != 1:
        signal_values = signal_values.reshape(-1)
    if signal_values.size == 0:
        return signal_values.copy()

    finite = cp.isfinite(signal_values)
    finite_count = int(cp.count_nonzero(finite).item())
    if finite_count == signal_values.size:
        return signal_values.copy()
    if finite_count == 0:
        return cp.zeros_like(signal_values)
    indices = cp.arange(signal_values.size)
    return cp.interp(indices, indices[finite], signal_values[finite]).astype(
        signal_values.dtype,
        copy=False,
    )


def _filter_gpu_signal(cp, values, sample_rate_hz, settings):
    """Apply the existing LFP filter definition without leaving the GPU."""

    from scipy import signal as scipy_signal
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"cupyx\.jit\.rawkernel is experimental\..*",
            category=FutureWarning,
        )
        from cupyx.scipy import signal as cupy_signal

    filtered = _finite_gpu_signal(cp, values)
    if settings is None or not settings.show_filtered:
        return filtered

    if settings.bandpass_enabled:
        sos = scipy_signal.butter(
            4,
            [float(settings.bandpass_low_hz), float(settings.bandpass_high_hz)],
            btype="bandpass",
            fs=float(sample_rate_hz),
            output="sos",
        )
        gpu_sos = cp.asarray(sos)
        padlen = 3 * (2 * sos.shape[0] + 1)
        if filtered.size <= padlen:
            filtered = cupy_signal.sosfilt(gpu_sos, filtered)
        else:
            filtered = cupy_signal.sosfiltfilt(gpu_sos, filtered)

    if settings.line_noise_hz is not None:
        b, a = scipy_signal.iirnotch(
            float(settings.line_noise_hz),
            float(settings.notch_quality),
            fs=float(sample_rate_hz),
        )
        gpu_b = cp.asarray(b)
        gpu_a = cp.asarray(a)
        padlen = 3 * max(len(a), len(b))
        if filtered.size <= padlen:
            filtered = cupy_signal.lfilter(gpu_b, gpu_a, filtered)
        else:
            filtered = cupy_signal.filtfilt(gpu_b, gpu_a, filtered)
    return filtered


def processed_chunk_statistics_cupy(
    values,
    sample_rate_hz,
    settings,
    *,
    crop_left=0,
    crop_right=None,
    requested: str | None = None,
):
    """Filter and reduce one chunk on the GPU, returning only scalars."""

    values = np.asarray(values)
    if select_backend(values.size, requested) != "cupy":
        return None
    cp, _ = _cupy_runtime()
    try:
        filtered = _filter_gpu_signal(cp, values, sample_rate_hz, settings)
        crop_right = filtered.size if crop_right is None else int(crop_right)
        filtered = filtered[int(crop_left) : crop_right]
        finite = filtered[cp.isfinite(filtered)].astype(cp.float64, copy=False)
        count = int(finite.size)
        if count == 0:
            return 0, 0.0, 0.0
        mean = cp.mean(finite, dtype=cp.float64)
        centered = finite - mean
        m2 = cp.sum(centered * centered, dtype=cp.float64)
        return count, float(mean.item()), float(m2.item())
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
def _plateau_midpoints_from_candidates(
    candidate_indices,
    left_values,
    center_values,
    right_values,
):
    """Collapse a small CPU-side candidate superset to SciPy peak midpoints."""

    if candidate_indices.size == 0:
        return candidate_indices
    peaks = []
    group_start = 0
    for offset in range(1, candidate_indices.size + 1):
        ended = (
            offset == candidate_indices.size
            or candidate_indices[offset] != candidate_indices[offset - 1] + 1
        )
        if not ended:
            continue
        group_indices = candidate_indices[group_start:offset]
        group_values = center_values[group_start:offset]
        if (
            np.all(group_values == group_values[0])
            and left_values[group_start] < group_values[0]
            and right_values[offset - 1] < group_values[0]
        ):
            peaks.append((int(group_indices[0]) + int(group_indices[-1])) // 2)
        group_start = offset
    return np.asarray(peaks, dtype=np.intp)


def _distance_keep(indices, priorities, distance):
    if indices.size < 2 or distance <= 1:
        return np.ones(indices.size, dtype=bool)
    keep = np.ones(indices.size, dtype=bool)
    for position in reversed(np.argsort(priorities, kind="stable")):
        if not keep[position]:
            continue
        left = position - 1
        while left >= 0 and indices[position] - indices[left] < distance:
            keep[left] = False
            left -= 1
        right = position + 1
        while right < indices.size and indices[right] - indices[position] < distance:
            keep[right] = False
            right += 1
    return keep


def _find_peaks_in_gpu_signal(
    cp,
    filtered,
    *,
    crop_left,
    crop_right,
    minimum_height,
    minimum_prominence,
    prominence_wlen,
    distance,
    negative=False,
):
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"cupyx\.jit\.rawkernel is experimental\..*",
            category=FutureWarning,
        )
        from cupyx.scipy.signal import peak_prominences

    working = -filtered if negative else filtered
    center = working[1:-1]
    inner = (
        cp.isfinite(center)
        & (center >= working[:-2])
        & (center >= working[2:])
        & (center >= float(minimum_height))
    )
    candidate_gpu = cp.nonzero(inner)[0] + 1
    if candidate_gpu.size == 0:
        empty_i = np.asarray([], dtype=np.intp)
        empty_f = np.asarray([], dtype=float)
        return empty_i, empty_f, empty_f

    gather = cp.stack(
        (
            working[candidate_gpu - 1],
            working[candidate_gpu],
            working[candidate_gpu + 1],
        ),
        axis=1,
    )
    candidate_indices = cp.asnumpy(candidate_gpu)
    gathered = cp.asnumpy(gather)
    indices = _plateau_midpoints_from_candidates(
        candidate_indices,
        gathered[:, 0],
        gathered[:, 1],
        gathered[:, 2],
    )
    if indices.size == 0:
        empty_f = np.asarray([], dtype=float)
        return indices, empty_f, empty_f

    indices_gpu = cp.asarray(indices)
    priorities = cp.asnumpy(working[indices_gpu])
    keep = _distance_keep(indices, priorities, int(distance))
    indices = indices[keep]
    if indices.size == 0:
        empty_f = np.asarray([], dtype=float)
        return indices, empty_f, empty_f

    indices_gpu = cp.asarray(indices)
    prominences_gpu = peak_prominences(
        working,
        indices_gpu,
        # CuPy 13 with NumPy 2 rejects a plain Python int in can_cast().
        wlen=np.int64(prominence_wlen),
    )[0]
    keep_gpu = prominences_gpu >= float(minimum_prominence)
    indices_gpu = indices_gpu[keep_gpu]
    prominences_gpu = prominences_gpu[keep_gpu]
    if indices_gpu.size == 0:
        empty_i = np.asarray([], dtype=np.intp)
        empty_f = np.asarray([], dtype=float)
        return empty_i, empty_f, empty_f

    owned_gpu = (indices_gpu >= int(crop_left)) & (
        indices_gpu < int(crop_right)
    )
    indices_gpu = indices_gpu[owned_gpu]
    prominences_gpu = prominences_gpu[owned_gpu]
    peak_values_gpu = filtered[indices_gpu]
    return (
        cp.asnumpy(indices_gpu - int(crop_left)),
        cp.asnumpy(prominences_gpu),
        cp.asnumpy(peak_values_gpu),
    )


def find_peak_pairs_cupy(
    values,
    sample_rate_hz,
    settings,
    *,
    crop_left,
    crop_right,
    positive_height,
    negative_height,
    minimum_prominence,
    prominence_wlen,
    distance,
    requested: str | None = None,
):
    """Filter once and find positive and negative peaks on the same GPU array."""

    values = np.asarray(values)
    if select_backend(values.size, requested) != "cupy":
        return None
    cp, _ = _cupy_runtime()
    try:
        filtered = _filter_gpu_signal(cp, values, sample_rate_hz, settings)
        filtered = filtered[int(crop_left) : int(crop_right)]
        owned_left = 0
        owned_right = int(filtered.size)
        positive = _find_peaks_in_gpu_signal(
            cp,
            filtered,
            crop_left=owned_left,
            crop_right=owned_right,
            minimum_height=positive_height,
            minimum_prominence=minimum_prominence,
            prominence_wlen=prominence_wlen,
            distance=distance,
            negative=False,
        )
        negative = _find_peaks_in_gpu_signal(
            cp,
            filtered,
            crop_left=owned_left,
            crop_right=owned_right,
            minimum_height=negative_height,
            minimum_prominence=minimum_prominence,
            prominence_wlen=prominence_wlen,
            distance=distance,
            negative=True,
        )
        return (*positive, *negative)
    except Exception as error:
        _record_operation_error(error)
        if requested == "cupy" or _configured_backend() == "cupy":
            raise
        return None
