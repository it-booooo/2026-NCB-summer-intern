import sys

from PySide6.QtWidgets import QApplication

from src.main_window import MainWindow
from src.ui.style import APP_STYLE


def main():
    """Start the desktop synchronization application."""
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
