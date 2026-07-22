from PySide6.QtWidgets import (
    QGridLayout,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from ..app_state import VideoState
from ..markers import Marker, MarkerKind, MarkerSource, VideoPosition
from .marker_view_panel import MarkerViewPanel


class MarkerPanel(MarkerViewPanel):
    """Create and edit manual markers on the video timeline."""

    def __init__(self, marker_store, event_table, video_player, video_state=None):
        super().__init__(marker_store)
        self.event_table = event_table
        self.video_player = video_player
        self.video_state = video_state or VideoState()

        button_specs = [
            ("LED On", MarkerKind.LED_ON),
            ("LED Off", MarkerKind.LED_OFF),
            ("Action Start", MarkerKind.BEHAVIOR_START),
            ("Action End", MarkerKind.BEHAVIOR_END),
            ("Seizure-like", MarkerKind.SEIZURE_LIKE),
        ]
        marker_buttons = []
        for text, kind in button_specs:
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, value=kind: self.add_marker(value))
            marker_buttons.append(button)

        edit_button = QPushButton("Edit Selected")
        delete_button = QPushButton("Delete Selected")
        edit_button.clicked.connect(self.event_table.edit_selected_event)
        delete_button.clicked.connect(self.event_table.delete_selected_rows)

        all_buttons = [*marker_buttons, edit_button, delete_button]
        for button in all_buttons:
            button.setFixedHeight(22)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        button_layout = QGridLayout()
        button_layout.setContentsMargins(2, 2, 2, 2)
        button_layout.setHorizontalSpacing(2)
        button_layout.setVerticalSpacing(2)
        for column in range(4):
            button_layout.setColumnStretch(column, 1)
        for index, button in enumerate(all_buttons):
            button_layout.addWidget(button, index // 4, index % 4)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        layout.addLayout(button_layout)
        layout.addWidget(self.event_table)

    def accepts_marker(self, marker):
        return isinstance(marker.position, VideoPosition)

    def add_marker(self, kind):
        if not self.video_player.has_video():
            QMessageBox.warning(self, "No video", "Please import a video first.")
            return
        self.marker_store.add(
            Marker(
                kind=kind,
                source=MarkerSource.MANUAL,
                position=VideoPosition(
                    self.video_player.current_time_sec(),
                    self.video_state.current_frame,
                ),
            )
        )
