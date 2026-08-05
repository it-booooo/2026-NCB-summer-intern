# build.py
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_ROOT = Path(sys.prefix)
LOCAL_DEPS = ROOT / ".build_deps"
OUTPUT_EXE = ROOT / "dist" / "PigBehaviorSync.exe"


def ensure_output_is_replaceable():
    """Fail early when a running app or another process locks the old executable."""
    if not OUTPUT_EXE.exists():
        return

    probe = OUTPUT_EXE.with_suffix(".exe.build-lock-check")
    try:
        OUTPUT_EXE.rename(probe)
        probe.rename(OUTPUT_EXE)
    except PermissionError as error:
        raise SystemExit(
            f"Cannot replace {OUTPUT_EXE}. Close PigBehaviorSync.exe (including "
            "Task Manager background processes) and run build.py again."
        ) from error
    finally:
        if probe.exists() and not OUTPUT_EXE.exists():
            probe.rename(OUTPUT_EXE)


def conda_runtime_binaries(*, include_cuda=False):
    """Collect conda DLLs required by stdlib extension modules at runtime."""
    search_dirs = [
        ENV_ROOT / "Library" / "bin",
        ENV_ROOT / "DLLs",
    ]
    patterns = (
        "ffi*.dll",
        "libffi*.dll",
        "expat*.dll",
        "libexpat*.dll",
        "sqlite3.dll",
        "libsqlite3*.dll",
    )
    if include_cuda:
        patterns += (
            "cublas*.dll",
            "cudart*.dll",
            "curand*.dll",
            "cusolver*.dll",
            "cusparse*.dll",
            "nvJitLink*.dll",
            "nvrtc*.dll",
        )

    binaries = []
    seen = set()
    separator = ";" if sys.platform == "win32" else ":"
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for pattern in patterns:
            for dll in sorted(search_dir.glob(pattern)):
                if dll in seen:
                    continue
                seen.add(dll)
                binaries.extend(["--add-binary", f"{dll}{separator}."])
    return binaries


def optional_cupy_bundle_args():
    """Bundle CuPy and Conda CUDA DLLs when the build environment has them."""

    if importlib.util.find_spec("cupy") is None:
        print("CuPy is not installed; the executable will use the CPU fallback.")
        return []
    import cupy

    print(f"Bundling CuPy {cupy.__version__} from {cupy.__file__}")
    return ["--collect-all=cupy"]


def main():
    missing = [
        package
        for package in ("PyInstaller", "pyopencl")
        if importlib.util.find_spec(package) is None
    ]
    if missing:
        raise SystemExit(
            "Build environment is missing: "
            + ", ".join(missing)
            + ". Install requirements before building so they can be bundled."
        )

    try:
        import numpy
    except Exception as error:
        raise SystemExit(
            "Build environment has an incompatible NumPy installation. "
            f"Run `{sys.executable} -m pip install --force-reinstall -r "
            f"{ROOT / 'requirements.txt'}` and try again.\n"
            f"{type(error).__name__}: {error}"
        ) from error

    import pyopencl

    try:
        import pyopencl._cl
    except Exception as error:
        raise SystemExit(
            "Build environment has pyopencl, but its native _cl module cannot load: "
            f"{type(error).__name__}: {error}"
        ) from error

    print(f"Bundling pyopencl {pyopencl.VERSION_TEXT} from {pyopencl.__file__}")
    print(f"Bundling NumPy {numpy.__version__} from {numpy.__file__}")

    ensure_output_is_replaceable()
    cupy_args = optional_cupy_bundle_args()

    env = os.environ.copy()
    pythonpath_entries = env.get("PYTHONPATH", "").split(os.pathsep)
    clean_pythonpath = [
        entry
        for entry in pythonpath_entries
        if entry and Path(entry).resolve() != LOCAL_DEPS.resolve()
    ]
    if clean_pythonpath:
        env["PYTHONPATH"] = os.pathsep.join(clean_pythonpath)
    else:
        env.pop("PYTHONPATH", None)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--name",
        "PigBehaviorSync",
        "--windowed",
        "--onefile",
        "--collect-all=pyopencl",
        *cupy_args,
        "--add-data=input_data/icon.png;input_data",
        "--icon=input_data/icon.png",
        *conda_runtime_binaries(include_cuda=bool(cupy_args)),
        "__main__.py",
    ]
    subprocess.run(cmd, cwd=ROOT, check=True, env=env)


if __name__ == "__main__":
    main()
