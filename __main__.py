import sys

from PySide6.QtWidgets import QApplication

from src.app import MainWindow
from src.ui.style import APP_STYLE


def main():
    """Run all plotting pipelines and display generated figures."""
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
    



if __name__ == "__main__":
    main()
