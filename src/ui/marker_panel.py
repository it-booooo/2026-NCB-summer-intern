from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from ..app_state import SyncState, VideoState
from ..markers import Marker, MarkerKind, MarkerSource, RecordPosition, VideoPosition
from .marker_view_panel import MarkerViewPanel


SYNC_VIDEO_LABELS = {
    MarkerKind.LED_ON: "LED On",
    MarkerKind.BEHAVIOR_START: "Action Start",
}


def numbered_sync_markers(markers):
    ttl_markers = sorted(
        [
            marker for marker in markers
            if marker.kind == MarkerKind.TTL
            and isinstance(marker.position, RecordPosition)
        ],
        key=lambda marker: marker.position.time_sec,
    )
    all_video_markers = [
        marker for marker in markers if isinstance(marker.position, VideoPosition)
    ]
    video_markers = [
        (number, marker)
        for number, marker in enumerate(all_video_markers, start=1)
        if marker.kind in SYNC_VIDEO_LABELS
    ]
    return ttl_markers, video_markers


class SyncEventDialog(QDialog):
    def __init__(self, markers, sync_state, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Sync Events")
        ttl_markers, video_markers = numbered_sync_markers(markers)

        self.mode_input = QComboBox()
        self.mode_input.addItem("Automatic: earliest TTL + earliest LED On", "auto")
        self.mode_input.addItem("Manual selection", "manual")
        self.ttl_input = QComboBox()
        self.video_input = QComboBox()
        for number, marker in enumerate(ttl_markers, start=1):
            self.ttl_input.addItem(
                f"#{number} | {marker.position.time_sec:.6f} s",
                marker.marker_id,
            )
        for number, marker in video_markers:
            self.video_input.addItem(
                f"#{number} | {SYNC_VIDEO_LABELS[marker.kind]} | "
                f"{marker.position.time_sec:.6f} s",
                marker.marker_id,
            )

        if sync_state.reference_mode == "manual":
            self.mode_input.setCurrentIndex(1)
            ttl_id = sync_state.ttl_reference_marker_id
            video_id = sync_state.video_reference_marker_id
        else:
            ttl_id = ttl_markers[0].marker_id if ttl_markers else None
            led_markers = [
                marker
                for _number, marker in video_markers
                if marker.kind == MarkerKind.LED_ON
            ]
            video_id = (
                min(led_markers, key=lambda marker: marker.position.time_sec).marker_id
                if led_markers
                else None
            )
        self._select_marker(self.ttl_input, ttl_id)
        self._select_marker(self.video_input, video_id)

        self.mode_input.currentIndexChanged.connect(self.update_mode)
        form = QFormLayout()
        form.addRow("Mode", self.mode_input)
        form.addRow("TTL event", self.ttl_input)
        form.addRow("Video event", self.video_input)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.update_mode()

    @staticmethod
    def _select_marker(combo, marker_id):
        combo.setCurrentIndex(combo.findData(marker_id) if marker_id else -1)

    def update_mode(self):
        manual = self.mode_input.currentData() == "manual"
        self.ttl_input.setEnabled(manual)
        self.video_input.setEnabled(manual)

    def accept(self):
        if self.mode_input.currentData() == "manual" and (
            self.ttl_input.currentIndex() < 0 or self.video_input.currentIndex() < 0
        ):
            QMessageBox.warning(
                self,
                "Select Sync Events",
                "Select one TTL event and one LED On or Action Start event.",
            )
            return
        super().accept()

    def selection(self):
        mode = self.mode_input.currentData()
        if mode == "auto":
            return mode, None, None
        return mode, self.ttl_input.currentData(), self.video_input.currentData()


def behavior_interval_warning(markers):
    pending_start = None
    pending_led_on = None
    video_number = 0
    for marker in markers:
        if not isinstance(marker.position, VideoPosition):
            continue
        video_number += 1
        if marker.kind == MarkerKind.LED_ON:
            pending_led_on = (video_number, marker)
        elif marker.kind == MarkerKind.LED_OFF:
            if pending_led_on is None:
                return (
                    f"Event #{video_number} LED Off has no preceding LED On; "
                    "add or move an LED On before it."
                )
            led_on_number, led_on_marker = pending_led_on
            if marker.position.time_sec <= led_on_marker.position.time_sec:
                return (
                    f"Event #{video_number} LED Off time must be later than "
                    f"Event #{led_on_number} LED On time."
                )
            pending_led_on = None
        elif marker.kind == MarkerKind.BEHAVIOR_START:
            pending_start = (video_number, marker)
        elif marker.kind == MarkerKind.BEHAVIOR_END:
            if pending_start is None:
                return f"Event #{video_number} Action End has no preceding Action Start."
            start_number, start_marker = pending_start
            if marker.position.time_sec <= start_marker.position.time_sec:
                return (
                    f"Event #{video_number} Action End time must be later than "
                    f"Event #{start_number} Action Start time."
                )
            pending_start = None
    return ""


class MarkerPanel(MarkerViewPanel):
    """Create and edit manual markers on the video timeline."""

    sync_selection_changed = Signal(str, object, object)

    def __init__(
        self,
        marker_store,
        event_table,
        video_player,
        video_state=None,
        sync_state=None,
    ):
        super().__init__(marker_store)
        self.event_table = event_table
        self.video_player = video_player
        self.video_state = video_state or VideoState()
        self.sync_state = sync_state or SyncState()

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
        sync_button = QPushButton("Select Sync Events...")
        edit_button.clicked.connect(self.event_table.edit_selected_event)
        delete_button.clicked.connect(self.event_table.delete_selected_rows)
        sync_button.clicked.connect(self.open_sync_event_dialog)

        self.sync_selection_label = QLabel()
        self.sync_selection_label.setWordWrap(True)

        self.interval_warning_label = QLabel()
        self.interval_warning_label.setStyleSheet("color: #b54708;")
        self.interval_warning_label.setWordWrap(True)
        self.marker_store.changed.connect(self.update_interval_warning)

        all_buttons = [*marker_buttons, edit_button, delete_button, sync_button]
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
        layout.addWidget(self.sync_selection_label)
        layout.addWidget(self.interval_warning_label)
        layout.addWidget(self.event_table)
        self.update_sync_selection_status()
        self.update_interval_warning()

    def accepts_marker(self, marker):
        return isinstance(marker.position, VideoPosition)

    def update_interval_warning(self):
        warning = behavior_interval_warning(self.marker_store.all())
        self.interval_warning_label.setText(warning)
        self.interval_warning_label.setVisible(bool(warning))

    def open_sync_event_dialog(self):
        dialog = SyncEventDialog(
            self.marker_store.all(),
            self.sync_state,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.sync_selection_changed.emit(*dialog.selection())

    def update_sync_selection_status(self):
        markers = self.marker_store.all()
        ttl_markers, video_markers = numbered_sync_markers(markers)
        ttl_numbers = {
            marker.marker_id: number
            for number, marker in enumerate(ttl_markers, start=1)
        }
        video_numbers = {
            marker.marker_id: (number, marker)
            for number, marker in video_markers
        }
        if self.sync_state.reference_mode == "manual":
            ttl_id = self.sync_state.ttl_reference_marker_id
            video_id = self.sync_state.video_reference_marker_id
            if ttl_id not in ttl_numbers or video_id not in video_numbers:
                self.sync_selection_label.setText(
                    "Manual sync selection is no longer available. Select sync events again."
                )
                self.sync_selection_label.setStyleSheet("color: #b54708;")
                return
            video_number, video_marker = video_numbers[video_id]
            text = (
                f"Sync: Manual (TTL #{ttl_numbers[ttl_id]} <-> Video "
                f"#{video_number} {SYNC_VIDEO_LABELS[video_marker.kind]})"
            )
        else:
            led_markers = [
                (number, marker)
                for number, marker in video_markers
                if marker.kind == MarkerKind.LED_ON
            ]
            if not ttl_markers or not led_markers:
                text = "Sync: Automatic selection needs a TTL and an LED On."
            else:
                video_number, _marker = min(
                    led_markers,
                    key=lambda item: item[1].position.time_sec,
                )
                text = f"Sync: Automatic (TTL #1 <-> Video #{video_number} LED_on)"
        self.sync_selection_label.setText(text)
        self.sync_selection_label.setStyleSheet("color: #555;")

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
