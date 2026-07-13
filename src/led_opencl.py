import os
import warnings
from functools import lru_cache
from pathlib import Path


DEFAULT_BATCH_FRAMES = 20_000
DEFAULT_COARSE_BATCH_FRAMES = 100
DEFAULT_AUTO_COARSE_BATCHES = 500
DEFAULT_AUTO_COARSE_BYTES = 64 * 1024 * 1024
DEFAULT_BATCH_BYTES = 512 * 1024 * 1024
KERNEL_SOURCE = r"""
__kernel void roi_mean_brightness(
    __global const uchar *frames,
    __global float *means,
    const uint frame_pixels
) {
    const uint frame_id = get_group_id(0);
    const uint local_id = get_local_id(0);
    const uint local_size = get_local_size(0);
    __local float partial[256];

    float sum = 0.0f;
    const ulong frame_offset = (ulong)frame_id * (ulong)frame_pixels * 3UL;
    for (uint pixel = local_id; pixel < frame_pixels; pixel += local_size) {
        const ulong offset = frame_offset + (ulong)pixel * 3UL;
        const float b = (float)frames[offset + 0];
        const float g = (float)frames[offset + 1];
        const float r = (float)frames[offset + 2];
        sum += 0.114f * b + 0.587f * g + 0.299f * r;
    }

    partial[local_id] = sum;
    barrier(CLK_LOCAL_MEM_FENCE);

    for (uint stride = local_size >> 1; stride > 0; stride >>= 1) {
        if (local_id < stride) {
            partial[local_id] += partial[local_id + stride];
        }
        barrier(CLK_LOCAL_MEM_FENCE);
    }

    if (local_id == 0) {
        means[frame_id] = partial[0] / (255.0f * (float)frame_pixels);
    }
}
"""


class OpenClUnavailable(RuntimeError):
    pass


def _env_int(name, default):
    try:
        return max(int(os.environ.get(name, default)), 1)
    except (TypeError, ValueError):
        return default


def _env_text(name, default):
    return os.environ.get(name, default).strip().lower()


def _opencl_disabled():
    value = os.environ.get("PIG_LED_OPENCL", "1").strip().lower()
    return value in {"0", "false", "no", "off"}


def _configure_opencl_temp():
    configured_path = os.environ.get("PIG_LED_OPENCL_TEMP", "").strip()
    temp_path = Path(configured_path) if configured_path else Path.cwd() / ".opencl_temp"
    try:
        temp_path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return ""

    path_text = str(temp_path)
    os.environ.setdefault("PYOPENCL_CACHE_DIR", path_text)
    os.environ.setdefault("TMP", path_text)
    os.environ.setdefault("TEMP", path_text)
    return path_text


def _power_of_two_at_most(value):
    result = 1
    while result * 2 <= value:
        result *= 2
    return result


def _device_memory(cl, device, info_name, default=0):
    try:
        return int(device.get_info(info_name) or default)
    except Exception:
        return default


def _device_summary(cl, platform, device):
    return {
        "name": str(device.name).strip(),
        "vendor": str(device.vendor).strip(),
        "platform": str(platform.name).strip(),
        "global_mem_mb": _device_memory(
            cl,
            device,
            cl.device_info.GLOBAL_MEM_SIZE,
        )
        / (1024 * 1024),
        "max_alloc_mb": _device_memory(
            cl,
            device,
            cl.device_info.MAX_MEM_ALLOC_SIZE,
        )
        / (1024 * 1024),
    }


def _device_search_text(platform, device):
    return " ".join(
        [
            str(device.name),
            str(device.vendor),
            str(platform.name),
            str(platform.vendor),
        ]
    ).lower()


def _choose_gpu_device(cl, gpu_devices):
    requested_device = os.environ.get("PIG_LED_OPENCL_DEVICE", "").strip().lower()
    if requested_device:
        matches = [
            item
            for item in gpu_devices
            if requested_device in _device_search_text(item[0], item[1])
        ]
        if not matches:
            raise OpenClUnavailable(
                f"requested OpenCL GPU not found: {requested_device}"
            )
        platform, device = max(
            matches,
            key=lambda item: _device_memory(
                cl,
                item[1],
                cl.device_info.GLOBAL_MEM_SIZE,
            ),
        )
        return platform, device, f"PIG_LED_OPENCL_DEVICE={requested_device}"

    nvidia_devices = [
        item for item in gpu_devices if "nvidia" in _device_search_text(item[0], item[1])
    ]
    if nvidia_devices:
        platform, device = max(
            nvidia_devices,
            key=lambda item: _device_memory(
                cl,
                item[1],
                cl.device_info.GLOBAL_MEM_SIZE,
            ),
        )
        return platform, device, "preferred NVIDIA OpenCL GPU"

    platform, device = max(
        gpu_devices,
        key=lambda item: _device_memory(
            cl,
            item[1],
            cl.device_info.GLOBAL_MEM_SIZE,
        ),
    )
    return platform, device, "largest available OpenCL GPU"


@lru_cache(maxsize=1)
def _opencl_runtime():
    if _opencl_disabled():
        raise OpenClUnavailable("OpenCL disabled by PIG_LED_OPENCL")

    try:
        _configure_opencl_temp()
        import pyopencl as cl
    except Exception as error:
        raise OpenClUnavailable("pyopencl is not installed") from error

    gpu_devices = []
    try:
        platforms = cl.get_platforms()
    except Exception as error:
        raise OpenClUnavailable("no OpenCL platform available") from error

    for platform in platforms:
        try:
            gpu_devices.extend(
                (platform, device)
                for device in platform.get_devices(device_type=cl.device_type.GPU)
            )
        except Exception:
            continue

    if not gpu_devices:
        raise OpenClUnavailable("no OpenCL GPU device available")

    platform, device, selected_reason = _choose_gpu_device(cl, gpu_devices)
    context = cl.Context([device])
    queue = cl.CommandQueue(context)
    warning_category = getattr(cl, "CompilerWarning", Warning)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=warning_category)
        program = cl.Program(context, KERNEL_SOURCE).build()
    kernel = cl.Kernel(program, "roi_mean_brightness")

    max_work_group_size = int(
        device.get_info(cl.device_info.MAX_WORK_GROUP_SIZE) or 1
    )
    local_size = _power_of_two_at_most(min(max_work_group_size, 256))
    if local_size < 1:
        local_size = 1

    return {
        "cl": cl,
        "context": context,
        "queue": queue,
        "program": program,
        "kernel": kernel,
        "device": device,
        "device_name": str(device.name).strip(),
        "device_vendor": str(device.vendor).strip(),
        "platform_name": str(platform.name).strip(),
        "selected_reason": selected_reason,
        "devices": [
            _device_summary(cl, candidate_platform, candidate_device)
            for candidate_platform, candidate_device in gpu_devices
        ],
        "local_size": local_size,
        "max_alloc_size": _device_memory(
            cl,
            device,
            cl.device_info.MAX_MEM_ALLOC_SIZE,
            DEFAULT_BATCH_BYTES,
        ),
        "global_mem_size": _device_memory(
            cl,
            device,
            cl.device_info.GLOBAL_MEM_SIZE,
            DEFAULT_BATCH_BYTES,
        ),
    }


def _normalise_roi(roi, frame_width, frame_height, rotate_180):
    if roi is None:
        return 0, 0, int(frame_width), int(frame_height)

    x, y, width, height = (int(value) for value in roi)
    if rotate_180:
        x = int(frame_width) - x - width
        y = int(frame_height) - y - height

    x0 = max(x, 0)
    y0 = max(y, 0)
    x1 = min(x + width, int(frame_width))
    y1 = min(y + height, int(frame_height))
    return x0, y0, max(x1 - x0, 0), max(y1 - y0, 0)


def _ceil_div(value, divisor):
    return max((int(value) + int(divisor) - 1) // int(divisor), 1)


def _manual_env_int(name):
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip().lower()
    if not value or value == "auto":
        return None
    try:
        return max(int(value), 1)
    except ValueError:
        return None


def _auto_coarse_batch_frames(frame_bytes, sample_count):
    target_batches = _env_int(
        "PIG_LED_OPENCL_AUTO_COARSE_BATCHES",
        DEFAULT_AUTO_COARSE_BATCHES,
    )
    target_frames = max(
        DEFAULT_COARSE_BATCH_FRAMES,
        _ceil_div(sample_count, target_batches),
    )

    max_batch_bytes = _env_int(
        "PIG_LED_OPENCL_AUTO_COARSE_BYTES",
        DEFAULT_AUTO_COARSE_BYTES,
    )
    byte_limited_frames = max(max_batch_bytes // max(int(frame_bytes), 1), 1)
    return max(min(target_frames, byte_limited_frames), 1)


def _target_batch_frames(frame_step, frame_bytes, sample_count):
    target_frames = _env_int("PIG_LED_OPENCL_BATCH_FRAMES", DEFAULT_BATCH_FRAMES)
    if int(frame_step) <= 1:
        return target_frames

    coarse_frames = _manual_env_int("PIG_LED_OPENCL_COARSE_BATCH_FRAMES")
    if coarse_frames is None:
        coarse_frames = _auto_coarse_batch_frames(frame_bytes, sample_count)

    return min(target_frames, coarse_frames)


def _batch_capacity(runtime, frame_bytes, frame_step, sample_count):
    target_frames = _target_batch_frames(frame_step, frame_bytes, sample_count)
    configured_bytes = _env_int("PIG_LED_OPENCL_BATCH_BYTES", DEFAULT_BATCH_BYTES)
    device_alloc_bytes = max(int(runtime["max_alloc_size"] * 0.75), 1)
    device_working_bytes = max(int(runtime["global_mem_size"] * 0.25), 1)
    usable_bytes = min(configured_bytes, device_alloc_bytes, device_working_bytes)
    return max(min(target_frames, usable_bytes // max(int(frame_bytes), 1)), 1)


def opencl_status():
    try:
        runtime = _opencl_runtime()
    except OpenClUnavailable as error:
        return {
            "available": False,
            "reason": str(error),
        }
    except Exception as error:
        return {
            "available": False,
            "reason": str(error),
        }

    return {
        "available": True,
        "device": runtime["device_name"],
        "device_vendor": runtime["device_vendor"],
        "platform": runtime["platform_name"],
        "selected_reason": runtime["selected_reason"],
        "devices": runtime["devices"],
        "local_size": runtime["local_size"],
        "max_alloc_mb": runtime["max_alloc_size"] / (1024 * 1024),
        "global_mem_mb": runtime["global_mem_size"] / (1024 * 1024),
        "target_batch_frames": _env_int(
            "PIG_LED_OPENCL_BATCH_FRAMES",
            DEFAULT_BATCH_FRAMES,
        ),
        "target_coarse_batch_frames": _env_int(
            "PIG_LED_OPENCL_COARSE_BATCH_FRAMES",
            DEFAULT_COARSE_BATCH_FRAMES,
        ),
        "target_coarse_batch_mode": _env_text(
            "PIG_LED_OPENCL_COARSE_BATCH_FRAMES",
            "auto",
        ),
        "target_auto_coarse_batches": _env_int(
            "PIG_LED_OPENCL_AUTO_COARSE_BATCHES",
            DEFAULT_AUTO_COARSE_BATCHES,
        ),
        "target_batch_mb": _env_int(
            "PIG_LED_OPENCL_BATCH_BYTES",
            DEFAULT_BATCH_BYTES,
        )
        / (1024 * 1024),
    }


def _run_opencl_batch(runtime, frames, frame_pixels):
    import numpy as np

    cl = runtime["cl"]
    context = runtime["context"]
    queue = runtime["queue"]
    kernel = runtime["kernel"]
    batch_count = int(frames.shape[0])
    local_size = int(runtime["local_size"])

    frames = np.ascontiguousarray(frames, dtype=np.uint8)
    means = np.empty(batch_count, dtype=np.float32)

    frames_buffer = cl.Buffer(
        context,
        cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,
        hostbuf=frames,
    )
    means_buffer = cl.Buffer(context, cl.mem_flags.WRITE_ONLY, means.nbytes)

    kernel(
        queue,
        (batch_count * local_size,),
        (local_size,),
        frames_buffer,
        means_buffer,
        np.uint32(frame_pixels),
    )
    cl.enqueue_copy(queue, means, means_buffer).wait()
    return means


def compute_led_brightness_curve_opencl(
    video_path,
    roi=None,
    rotate_180=False,
    using_fps=30.0,
    frame_step=1,
    start_frame=0,
    end_frame=None,
    should_stop=None,
    progress_callback=None,
    acceleration_info=None,
):
    import cv2
    import numpy as np
    from src.video_capture import open_video_capture

    runtime = _opencl_runtime()
    cap, decode_backend, decode_fallback_reason = open_video_capture(cv2, video_path)

    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    try:
        fps = float(using_fps or cap.get(cv2.CAP_PROP_FPS) or 30.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if frame_width <= 0 or frame_height <= 0:
            raise OpenClUnavailable("video frame size is unknown")

        frame_step = max(int(frame_step), 1)
        start_frame = max(int(start_frame), 0)
        if end_frame is None:
            end_frame = max(total_frames - 1, 0)
        end_frame = min(max(int(end_frame), start_frame), max(total_frames - 1, 0))

        x, y, roi_width, roi_height = _normalise_roi(
            roi,
            frame_width,
            frame_height,
            rotate_180,
        )
        if roi_width <= 0 or roi_height <= 0:
            raise OpenClUnavailable("LED ROI is empty")

        frame_pixels = int(roi_width * roi_height)
        frame_bytes = int(frame_pixels * 3)
        sample_count = _ceil_div(end_frame - start_frame + 1, frame_step)
        batch_capacity = _batch_capacity(
            runtime,
            frame_bytes,
            frame_step,
            sample_count,
        )
        batch = np.empty(
            (batch_capacity, roi_height, roi_width, 3),
            dtype=np.uint8,
        )
        batch_frame_indices = []
        batch_count = 0
        batches_processed = 0
        frames_processed = 0
        max_batch_used = 0
        points = []

        scan_total_frames = max(end_frame - start_frame + 1, 1)

        if acceleration_info is not None:
            acceleration_info.update(
                {
                    "brightness_backend": "opencl",
                    "opencl_device": runtime["device_name"],
                    "opencl_device_vendor": runtime["device_vendor"],
                    "opencl_platform": runtime["platform_name"],
                    "opencl_selected_reason": runtime["selected_reason"],
                    "opencl_batch_capacity": batch_capacity,
                    "opencl_batch_mode": _env_text(
                        "PIG_LED_OPENCL_COARSE_BATCH_FRAMES",
                        "auto",
                    )
                    if frame_step > 1
                    else "fixed",
                    "opencl_batch_target": _env_int(
                        "PIG_LED_OPENCL_BATCH_FRAMES",
                        DEFAULT_BATCH_FRAMES,
                    ),
                    "opencl_coarse_batch_target": _manual_env_int(
                        "PIG_LED_OPENCL_COARSE_BATCH_FRAMES",
                    )
                    or DEFAULT_COARSE_BATCH_FRAMES,
                    "opencl_auto_coarse_batches": _env_int(
                        "PIG_LED_OPENCL_AUTO_COARSE_BATCHES",
                        DEFAULT_AUTO_COARSE_BATCHES,
                    ),
                    "opencl_batch_source_frames": batch_capacity * frame_step,
                    "opencl_sample_count": sample_count,
                    "opencl_roi_width": roi_width,
                    "opencl_roi_height": roi_height,
                    "opencl_frame_bytes": frame_bytes,
                    "video_decode_backend": decode_backend,
                    "video_decode_fallback_reason": decode_fallback_reason,
                }
            )

        def emit_progress(frame_index):
            if progress_callback is None:
                return

            completed_frames = min(
                max(frame_index - start_frame, 0),
                scan_total_frames,
            )
            progress_callback(completed_frames, scan_total_frames)

        def flush_batch():
            nonlocal batch_count, batches_processed, frames_processed, max_batch_used
            if batch_count <= 0:
                return

            means = _run_opencl_batch(
                runtime,
                batch[:batch_count],
                frame_pixels,
            )
            for frame_index, brightness in zip(batch_frame_indices, means):
                points.append(
                    (
                        int(frame_index),
                        int(frame_index) / fps,
                        float(brightness),
                    )
                )

            batches_processed += 1
            frames_processed += batch_count
            max_batch_used = max(max_batch_used, batch_count)
            batch_frame_indices.clear()
            batch_count = 0

        if progress_callback is not None:
            progress_callback(0, scan_total_frames)

        if start_frame > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        frame_index = start_frame
        while frame_index <= end_frame:
            if should_stop is not None and should_stop():
                break

            success, frame = cap.read()
            if not success:
                break

            if frame.shape[1] != frame_width or frame.shape[0] != frame_height:
                raise OpenClUnavailable("variable-size video frames are not supported")

            batch[batch_count] = frame[y : y + roi_height, x : x + roi_width]
            batch_frame_indices.append(frame_index)
            batch_count += 1

            if batch_count >= batch_capacity:
                flush_batch()

            frame_index += 1

            skipped = 0
            while skipped < frame_step - 1 and frame_index <= end_frame:
                if should_stop is not None and should_stop():
                    break
                if not cap.grab():
                    frame_index = end_frame + 1
                    break
                frame_index += 1
                skipped += 1

            emit_progress(frame_index)

        if should_stop is None or not should_stop():
            flush_batch()

        emit_progress(frame_index)

        if acceleration_info is not None:
            acceleration_info.update(
                {
                    "opencl_batches": batches_processed,
                    "opencl_frames": frames_processed,
                    "opencl_max_batch_frames": max_batch_used,
                }
            )

        return points
    finally:
        cap.release()
