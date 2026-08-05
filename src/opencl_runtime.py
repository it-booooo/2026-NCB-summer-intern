"""Shared OpenCL GPU discovery and runtime configuration.

Both LED analysis and LFP processing use this module so device selection,
PyInstaller DLL handling, and the on-disk OpenCL cache remain consistent.
"""

from __future__ import annotations

import ctypes
import os
import sys
import warnings
from functools import lru_cache
from pathlib import Path


DEFAULT_MEMORY_BYTES = 512 * 1024 * 1024
GPU_VENDOR_ALIASES = {
    "nvidia": ("nvidia",),
    "amd": (
        "amd",
        "advanced micro devices",
        "radeon",
        "ati technologies",
    ),
    "intel": ("intel",),
}
GPU_VENDOR_PRIORITY = ("nvidia", "amd", "intel")
GPU_VENDOR_LABELS = {
    "nvidia": "NVIDIA",
    "amd": "AMD/Radeon",
    "intel": "Intel",
}


class OpenClUnavailable(RuntimeError):
    """Raised when no usable OpenCL GPU runtime is available."""


_DLL_DIRECTORY_HANDLES = []


def _configured_value(name: str, legacy_name: str = "", default: str = "") -> str:
    value = os.environ.get(name)
    if value is None and legacy_name:
        value = os.environ.get(legacy_name)
    return default if value is None else value


def _configure_windows_dll_search() -> None:
    """Make PyInstaller's extraction directory available to native extensions."""

    if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
        return
    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(bundle_root))


def _windows_dll_diagnostics() -> str:
    if sys.platform != "win32":
        return ""
    results = []
    for dll_name in (
        "OpenCL.dll",
        "MSVCP140.dll",
        "VCRUNTIME140.dll",
        "VCRUNTIME140_1.dll",
    ):
        try:
            ctypes.WinDLL(dll_name)
        except OSError as error:
            results.append(f"{dll_name}: FAILED ({error})")
        else:
            results.append(f"{dll_name}: OK")
    return "; ".join(results)


def _configure_opencl_temp() -> str:
    configured_path = _configured_value(
        "PIG_OPENCL_TEMP",
        "PIG_LED_OPENCL_TEMP",
    ).strip()
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


def _power_of_two_at_most(value: int) -> int:
    result = 1
    while result * 2 <= value:
        result *= 2
    return result


def _device_memory(cl, device, info_name, default=0) -> int:
    try:
        return int(device.get_info(info_name) or default)
    except Exception:
        return int(default)


def _device_summary(cl, platform, device) -> dict:
    return {
        "name": str(device.name).strip(),
        "vendor": str(device.vendor).strip(),
        "platform": str(platform.name).strip(),
        "global_mem_mb": _device_memory(
            cl, device, cl.device_info.GLOBAL_MEM_SIZE
        )
        / (1024 * 1024),
        "max_alloc_mb": _device_memory(
            cl, device, cl.device_info.MAX_MEM_ALLOC_SIZE
        )
        / (1024 * 1024),
    }


def _device_search_text(platform, device) -> str:
    return " ".join(
        (
            str(device.name),
            str(device.vendor),
            str(platform.name),
            str(platform.vendor),
        )
    ).lower()


def _request_terms(value: str):
    value = value.strip().lower()
    return GPU_VENDOR_ALIASES.get(value, (value,))


def _matches_device_request(platform, device, requested_text: str) -> bool:
    search_text = _device_search_text(platform, device)
    return any(term and term in search_text for term in _request_terms(requested_text))


def _normalise_vendor(value: str) -> str | None:
    value = value.strip().lower()
    if value in GPU_VENDOR_ALIASES:
        return value
    for vendor, aliases in GPU_VENDOR_ALIASES.items():
        if value in aliases:
            return vendor
    return None


def _largest_memory_device(cl, devices):
    return max(
        devices,
        key=lambda item: _device_memory(
            cl,
            item[1],
            cl.device_info.GLOBAL_MEM_SIZE,
        ),
    )


def _choose_gpu_device(cl, gpu_devices):
    requested_device = _configured_value(
        "PIG_OPENCL_DEVICE",
        "PIG_LED_OPENCL_DEVICE",
    ).strip().lower()
    if requested_device:
        matches = [
            item
            for item in gpu_devices
            if _matches_device_request(item[0], item[1], requested_device)
        ]
        if not matches:
            raise OpenClUnavailable(
                f"requested OpenCL GPU not found: {requested_device}"
            )
        platform, device = _largest_memory_device(cl, matches)
        return platform, device, f"PIG_OPENCL_DEVICE={requested_device}"

    requested_vendor = _configured_value(
        "PIG_OPENCL_VENDOR",
        "PIG_LED_OPENCL_VENDOR",
    ).strip().lower()
    if requested_vendor:
        normalised_vendor = _normalise_vendor(requested_vendor)
        if normalised_vendor is None:
            supported = ", ".join(GPU_VENDOR_ALIASES)
            raise OpenClUnavailable(
                f"unsupported OpenCL GPU vendor '{requested_vendor}'. "
                f"Supported vendors: {supported}"
            )
        vendor_devices = [
            item
            for item in gpu_devices
            if _matches_device_request(item[0], item[1], normalised_vendor)
        ]
        if not vendor_devices:
            raise OpenClUnavailable(
                f"requested OpenCL GPU vendor not found: {requested_vendor}"
            )
        platform, device = _largest_memory_device(cl, vendor_devices)
        vendor_label = GPU_VENDOR_LABELS[normalised_vendor]
        return platform, device, f"PIG_OPENCL_VENDOR={vendor_label}"

    for vendor in GPU_VENDOR_PRIORITY:
        vendor_devices = [
            item
            for item in gpu_devices
            if _matches_device_request(item[0], item[1], vendor)
        ]
        if vendor_devices:
            platform, device = _largest_memory_device(cl, vendor_devices)
            return (
                platform,
                device,
                f"preferred {GPU_VENDOR_LABELS[vendor]} OpenCL GPU",
            )

    platform, device = _largest_memory_device(cl, gpu_devices)
    return platform, device, "largest available OpenCL GPU"


@lru_cache(maxsize=1)
def opencl_runtime() -> dict:
    """Return the shared GPU context and device metadata."""

    disabled = _configured_value(
        "PIG_OPENCL",
        "PIG_LED_OPENCL",
        "1",
    ).strip().lower()
    if disabled in {"0", "false", "no", "off"}:
        raise OpenClUnavailable("OpenCL disabled by PIG_OPENCL")

    _configure_opencl_temp()
    _configure_windows_dll_search()
    try:
        import pyopencl as cl
    except ModuleNotFoundError as error:
        raise OpenClUnavailable(
            f"pyopencl is not bundled in this application ({error})"
        ) from error
    except Exception as error:
        raise OpenClUnavailable(
            "pyopencl could not load; an OpenCL driver or runtime DLL may be missing "
            f"({type(error).__name__}: {error}). DLL check: "
            f"{_windows_dll_diagnostics()}"
        ) from error

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
    max_work_group_size = int(
        device.get_info(cl.device_info.MAX_WORK_GROUP_SIZE) or 1
    )
    local_size = max(_power_of_two_at_most(min(max_work_group_size, 256)), 1)
    extensions = set(str(device.extensions).lower().split())
    supports_fp64 = bool({"cl_khr_fp64", "cl_amd_fp64"} & extensions)

    return {
        "cl": cl,
        "context": context,
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
            DEFAULT_MEMORY_BYTES,
        ),
        "global_mem_size": _device_memory(
            cl,
            device,
            cl.device_info.GLOBAL_MEM_SIZE,
            DEFAULT_MEMORY_BYTES,
        ),
        "supports_fp64": supports_fp64,
    }


def build_opencl_program(runtime: dict, source: str):
    """Compile a program in the shared context while suppressing benign warnings."""

    cl = runtime["cl"]
    warning_category = getattr(cl, "CompilerWarning", Warning)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=warning_category)
        return cl.Program(runtime["context"], source).build()
