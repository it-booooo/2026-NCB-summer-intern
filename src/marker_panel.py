from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class MarkerPanel(QWidget):
    close_requested = Signal()

    def __init__(self, event_table, add_event_callback):
        super().__init__()

        self.event_table = event_table
        self.add_event_callback = add_event_callback

        title = QLabel("Event Marker")
        title.setStyleSheet("font-weight: bold;")

        close_button = QPushButton("X")
        close_button.setFixedWidth(36)
        close_button.clicked.connect(self.close_requested.emit)

        header_layout = QHBoxLayout()
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(close_button)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)

        led_on_button = QPushButton("LED On")
        led_off_button = QPushButton("LED Off")
        behavior_start_button = QPushButton("Behavior Start")
        behavior_end_button = QPushButton("Behavior End")
        seizure_button = QPushButton("Seizure-like Event")
        delete_button = QPushButton("Delete Selected")

        led_on_button.clicked.connect(lambda: self.add_event_callback("LED_on"))
        led_off_button.clicked.connect(lambda: self.add_event_callback("LED_off"))
        behavior_start_button.clicked.connect(lambda: self.add_event_callback("behavior_start"))
        behavior_end_button.clicked.connect(lambda: self.add_event_callback("behavior_end"))
        seizure_button.clicked.connect(lambda: self.add_event_callback("seizure_like_event"))
        delete_button.clicked.connect(self.event_table.delete_selected_rows)

        button_layout = QVBoxLayout()
        button_layout.addWidget(led_on_button)
        button_layout.addWidget(led_off_button)
        button_layout.addWidget(behavior_start_button)
        button_layout.addWidget(behavior_end_button)
        button_layout.addWidget(seizure_button)
        button_layout.addWidget(delete_button)

        layout = QVBoxLayout()
        layout.addLayout(header_layout)
        layout.addWidget(divider)
        layout.addLayout(button_layout)
        layout.addWidget(self.event_table)

        self.setLayout(layout)