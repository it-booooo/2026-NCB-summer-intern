from PySide6.QtWidgets import (
    QGridLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class MarkerPanel(QWidget):
    def __init__(
        self,
        event_table,
        add_event_callback,
        select_led_roi_callback,
    ):
        super().__init__()

        self.event_table = event_table
        self.add_event_callback = add_event_callback

        led_on_button = QPushButton("LED On")
        led_off_button = QPushButton("LED Off")
        select_roi_button = QPushButton("Select LED")
        behavior_start_button = QPushButton("Action Start")
        behavior_end_button = QPushButton("Action End")
        seizure_button = QPushButton("Seizure-like")
        edit_button = QPushButton("Edit Selected")
        delete_button = QPushButton("Delete Selected")

        for button in (
            led_on_button,
            led_off_button,
            select_roi_button,
            behavior_start_button,
            behavior_end_button,
            seizure_button,
            edit_button,
            delete_button,
        ):
            button.setFixedHeight(22)

        select_roi_button.setToolTip("Select LED area and run brightness detection")

        led_on_button.clicked.connect(lambda: self.add_event_callback("LED_on"))
        led_off_button.clicked.connect(lambda: self.add_event_callback("LED_off"))
        select_roi_button.clicked.connect(select_led_roi_callback)
        behavior_start_button.clicked.connect(lambda: self.add_event_callback("behavior_start"))
        behavior_end_button.clicked.connect(lambda: self.add_event_callback("behavior_end"))
        seizure_button.clicked.connect(lambda: self.add_event_callback("seizure_like_event"))
        edit_button.clicked.connect(self.event_table.edit_selected_event)
        delete_button.clicked.connect(self.event_table.delete_selected_rows)

        button_layout = QGridLayout()
        button_layout.setContentsMargins(2, 2, 2, 2)
        button_layout.setHorizontalSpacing(2)
        button_layout.setVerticalSpacing(2)
        for column in range(6):
            button_layout.setColumnStretch(column, 1)
        button_layout.addWidget(select_roi_button, 0, 0, 1, 2)
        button_layout.addWidget(led_on_button, 0, 2, 1, 2)
        button_layout.addWidget(led_off_button, 0, 4, 1, 2)
        button_layout.addWidget(behavior_start_button, 1, 0, 1, 2)
        button_layout.addWidget(behavior_end_button, 1, 2, 1, 2)
        button_layout.addWidget(seizure_button, 1, 4, 1, 2)
        button_layout.addWidget(delete_button, 2, 0, 1, 3)
        button_layout.addWidget(edit_button, 2, 3, 1, 3)

        layout = QVBoxLayout()
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        layout.addLayout(button_layout)
        layout.addWidget(self.event_table)

        self.setLayout(layout)
