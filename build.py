# build.py
import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_ROOT = Path(sys.prefix)
LOCAL_DEPS = ROOT / ".build_deps"


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
        *conda_runtime_binaries(),
        "__main__.py",
    ]
    subprocess.run(cmd, cwd=ROOT, check=True, env=env)


if __name__ == "__main__":
    main()
