import sys

from PySide6.QtWidgets import QApplication

from src.app import MainWindow
from src.style import APP_STYLE


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()