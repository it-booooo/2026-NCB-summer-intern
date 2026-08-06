import multiprocessing
import sys
from pathlib import Path

from src.cupy_bootstrap import preload_cupy

# Load the optional CUDA/NVRTC DLL set before Qt registers its own DLL paths.
_CUPY_PRELOAD_ERROR = preload_cupy()

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.main_window import MainWindow
from src.ui.style import APP_STYLE


def main():
    """Start the desktop synchronization application."""
    from src.cupy_bootstrap import preload_cupy

    # Load optional CUDA/NVRTC DLLs before Qt registers its own DLL paths.
    preload_cupy()

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

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
