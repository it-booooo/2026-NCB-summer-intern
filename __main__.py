import sys
import matplotlib.pyplot as plt

import draw_function as draw
from PySide6.QtWidgets import QApplication

from src.app import MainWindow
from src.style import APP_STYLE


def main():
    """Run all plotting pipelines and display generated figures."""
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)

    window = MainWindow()
    window.show()
    draw.accelerator()
    draw.LFP()
    plt.show()
    sys.exit(app.exec())
    



if __name__ == "__main__":
    main()
