from PySide6.QtWidgets import (
    QGridLayout,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..app_state import VideoState


class MarkerPanel(QWidget):
    def __init__(
        self,
        event_table,
        video_player,
        video_state=None,
    ):
        super().__init__()

        self.event_table = event_table
        self.video_player = video_player
        self.video_state = video_state or VideoState()

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
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        select_roi_button.setToolTip("Select LED area and run brightness detection")

        led_on_button.clicked.connect(lambda: self.add_event("LED_on"))
        led_off_button.clicked.connect(lambda: self.add_event("LED_off"))
        select_roi_button.clicked.connect(self.select_led_roi)
        behavior_start_button.clicked.connect(lambda: self.add_event("behavior_start"))
        behavior_end_button.clicked.connect(lambda: self.add_event("behavior_end"))
        seizure_button.clicked.connect(lambda: self.add_event("seizure_like_event"))
        edit_button.clicked.connect(self.event_table.edit_selected_event)
        delete_button.clicked.connect(self.event_table.delete_selected_rows)

        button_layout = QGridLayout()
        button_layout.setContentsMargins(2, 2, 2, 2)
        button_layout.setHorizontalSpacing(2)
        button_layout.setVerticalSpacing(2)
        for column in range(4):
            button_layout.setColumnStretch(column, 1)
        button_layout.addWidget(select_roi_button, 0, 0)
        button_layout.addWidget(led_on_button, 0, 1)
        button_layout.addWidget(led_off_button, 0, 2)
        button_layout.addWidget(edit_button, 0, 3)
        button_layout.addWidget(behavior_start_button, 1, 0)
        button_layout.addWidget(behavior_end_button, 1, 1)
        button_layout.addWidget(seizure_button, 1, 2)
        button_layout.addWidget(delete_button, 1, 3)

        layout = QVBoxLayout()
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        layout.addLayout(button_layout)
        layout.addWidget(self.event_table)

        self.setLayout(layout)

    def add_event(self, event_type):
        """Add a manual event at the current video position."""
        if not self.video_player.has_video():
            QMessageBox.warning(self, "No video", "Please import a video first.")
            return

        self.event_table.add_event(
            event_type=event_type,
            video_time_sec=self.video_player.current_time_sec(),
            frame_index=self.video_state.current_frame,
            note="",
        )

    def select_led_roi(self):
        """Start LED ROI selection for the loaded video."""
        if not self.video_player.has_video():
            QMessageBox.warning(self, "No video", "Please import a video first.")
            return

        self.video_player.start_roi_selection()
