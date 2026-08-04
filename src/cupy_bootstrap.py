"""Prepare the optional Conda CUDA runtime before Qt changes DLL lookup state."""

from __future__ import annotations

import os
import sys
from pathlib import Path


_DLL_DIRECTORY_HANDLES = []


def _bind_cuda_root(environment_root) -> bool:
    environment_root = Path(environment_root).resolve()
    library_root = environment_root / "Library"
    library_bin = library_root / "bin"
    if not library_bin.is_dir():
        return False

    library_bin_text = str(library_bin)
    current_path = os.environ.get("PATH", "")
    entries = current_path.split(os.pathsep) if current_path else []
    if library_bin_text.lower() not in {entry.lower() for entry in entries}:
        os.environ["PATH"] = library_bin_text + os.pathsep + current_path
    os.environ["CUDA_PATH"] = str(library_root)
    if hasattr(os, "add_dll_directory"):
        try:
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(library_bin_text))
        except OSError:
            pass
    return True


def configure_cupy_environment(cupy_file=None) -> None:
    """Use ASCII runtime paths and the CUDA installation paired with CuPy."""

    workspace = Path.cwd()
    cache_path = workspace / ".cupy_cache"
    temp_path = workspace / ".cupy_temp"
    cache_path.mkdir(parents=True, exist_ok=True)
    temp_path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("CUPY_CACHE_DIR", str(cache_path))
    os.environ["TEMP"] = str(temp_path)
    os.environ["TMP"] = str(temp_path)
    os.environ["TMPDIR"] = str(temp_path)

    candidates = []
    if cupy_file is not None:
        candidates.extend(Path(cupy_file).resolve().parents)
    candidates.extend(
        candidate
        for candidate in (
            os.environ.get("CONDA_PREFIX"),
            sys.prefix,
            Path(sys.executable).resolve().parent,
        )
        if candidate
    )
    for candidate in candidates:
        if _bind_cuda_root(candidate):
            break


def preload_cupy() -> str | None:
    """Load the CUDA/NVRTC DLL set before PySide6/Qt is imported."""

    try:
        configure_cupy_environment()
        import cupy as cp

        configure_cupy_environment(cp.__file__)
        probe = cp.arange(4, dtype=cp.float32)
        float(cp.sum(probe).item())
        return None
    except Exception as error:
        return str(error)
