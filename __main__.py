import multiprocessing
import os
import sys
from pathlib import Path

# Force pyarrow onto the OS-returning "system" allocator before anything can
# import pyarrow.  Its default mimalloc backend, fixed at pyarrow import time,
# keeps the multi-hundred-MB CSV-parse peak resident for the whole session.
# Also set inside src/signal_data/source.py for test/benchmark entry points.
os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")


def main():
    """Start the desktop synchronization application."""
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from src.main_window import MainWindow
    from src.ui.style import APP_STYLE

    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "NCB.PigBehaviorSync"
        )

    app = QApplication(sys.argv)
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    app.setWindowIcon(QIcon(str(bundle_root / "input_data" / "icon.png")))
    app.setStyleSheet(APP_STYLE)

    from src.gui_watchdog import install_gui_stall_watchdog

    install_gui_stall_watchdog(
        app,
        log_path=Path.home() / "ncb_gui_stall.log",
    )

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
