# build.py
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

subprocess.run(
    [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        "PigBehaviorSync",
        "--windowed",
        "--onefile",
        "__main__.py",
    ],
    cwd=ROOT,
    check=True,
)
