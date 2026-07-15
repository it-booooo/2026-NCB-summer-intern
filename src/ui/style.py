APP_STYLE = """
QMainWindow {
    background-color: #f0f0f0;
    color: #111111;
}

QWidget {
    background-color: #f0f0f0;
    color: #111111;
    font-size: 10pt;
}

QMenuBar {
    background-color: #e8e8e8;
    color: #111111;
    border-bottom: 1px solid #c4c4c4;
}

QMenuBar::item {
    padding: 5px 12px;
    background-color: transparent;
    color: #111111;
}

QMenuBar::item:selected {
    background-color: #d6d6d6;
    color: #111111;
}

QMenu {
    background-color: #ffffff;
    color: #111111;
    border: 1px solid #b8b8b8;
}

QMenu::item {
    padding: 5px 24px;
    color: #111111;
}

QMenu::item:selected {
    background-color: #dcecff;
    color: #111111;
}

QGroupBox {
    font-weight: bold;
    color: #111111;
    border: 1px solid #111111;
    margin-top: 12px;
    background-color: #ffffff;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 1px 6px;
    border: 1px solid #111111;
    color: #111111;
    background-color: #ffffff;
}

QLabel {
    color: #111111;
    background-color: transparent;
    font-size: 10pt;
}

QPushButton {
    background-color: #f7f7f7;
    color: #111111;
    border: 1px solid #b8b8b8;
    border-radius: 3px;
    padding: 4px 8px;
}

QPushButton:hover {
    background-color: #eeeeee;
}

QPushButton:pressed {
    background-color: #dddddd;
}

QPushButton:disabled {
    background-color: #eeeeee;
    color: #888888;
}

QComboBox {
    background-color: #ffffff;
    color: #111111;
    border: 1px solid #b8b8b8;
    padding: 3px 6px;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #111111;
    selection-background-color: #dcecff;
    selection-color: #111111;
}

QTableWidget {
    background-color: #ffffff;
    color: #111111;
    gridline-color: #d0d0d0;
    selection-background-color: transparent;
    selection-color: #111111;
}

QTableWidget::item {
    color: #111111;
    background-color: #ffffff;
}

QTableWidget::item:selected {
    background-color: transparent;
    color: #111111;
}

QHeaderView::section {
    background-color: #eeeeee;
    color: #111111;
    border: 1px solid #c8c8c8;
    padding: 3px;
}

QLineEdit,
QPlainTextEdit,
QTextEdit {
    background-color: #ffffff;
    color: #111111;
    border: 1px solid #c8c8c8;
    selection-background-color: #bcdcff;
    selection-color: #111111;
}

QSlider::groove:horizontal {
    height: 6px;
    background: #c8c8c8;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #2f80ed;
    width: 12px;
    margin: -4px 0;
    border-radius: 6px;
}

QScrollBar:horizontal,
QScrollBar:vertical {
    background: #f0f0f0;
}

QScrollBar::handle:horizontal,
QScrollBar::handle:vertical {
    background: #b8b8b8;
    border-radius: 3px;
}

QScrollBar::handle:horizontal:hover,
QScrollBar::handle:vertical:hover {
    background: #9f9f9f;
}

QMessageBox {
    background-color: #ffffff;
    color: #111111;
}

QMessageBox QLabel {
    background-color: #ffffff;
    color: #111111;
}

QMessageBox QPushButton {
    background-color: #f7f7f7;
    color: #111111;
    border: 1px solid #b8b8b8;
    border-radius: 3px;
    padding: 5px 14px;
    min-width: 72px;
}
"""
