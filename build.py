# build.py
import subprocess
import sys
import os
import importlib.util
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


def conda_runtime_binaries():
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

    import pyopencl

    try:
        import pyopencl._cl
    except Exception as error:
        raise SystemExit(
            "Build environment has pyopencl, but its native _cl module cannot load: "
            f"{type(error).__name__}: {error}"
        ) from error

    print(f"Bundling pyopencl {pyopencl.VERSION_TEXT} from {pyopencl.__file__}")

    ensure_output_is_replaceable()

    env = os.environ.copy()
    if LOCAL_DEPS.exists():
        pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            f"{LOCAL_DEPS}{os.pathsep}{pythonpath}" if pythonpath else str(LOCAL_DEPS)
        )

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
        "--add-data=input_data/icon.png;input_data",
        "--icon=input_data/icon.png",
        *conda_runtime_binaries(),
        "__main__.py",
    ]
    subprocess.run(cmd, cwd=ROOT, check=True, env=env)


if __name__ == "__main__":
    main()
