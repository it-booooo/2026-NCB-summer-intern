from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class MarkerPanel(QWidget):
    def __init__(self, event_table, add_event_callback):
        super().__init__()

        self.event_table = event_table
        self.add_event_callback = add_event_callback

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

        button_layout = QGridLayout()
        button_layout.setHorizontalSpacing(4)
        button_layout.setVerticalSpacing(4)
        button_layout.addWidget(led_on_button, 0, 0)
        button_layout.addWidget(led_off_button, 0, 1)
        button_layout.addWidget(behavior_start_button, 1, 0)
        button_layout.addWidget(behavior_end_button, 1, 1)
        button_layout.addWidget(seizure_button, 2, 0)
        button_layout.addWidget(delete_button, 2, 1)

        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addLayout(button_layout)
        layout.addWidget(divider)
        layout.addWidget(self.event_table)

        self.setLayout(layout)
