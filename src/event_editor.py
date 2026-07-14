from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)


DEFAULT_EVENT_TYPES = [
    "LED_on",
    "LED_off",
    "behavior_start",
    "behavior_end",
    "seizure_like_event",
]


class EventEditDialog(QDialog):
    """Edit all user-facing fields of one event marker."""

    def __init__(self, event, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Event")

        self.event_type_input = QComboBox()
        self.event_type_input.setEditable(True)
        self.event_type_input.addItems(DEFAULT_EVENT_TYPES)
        self.event_type_input.setCurrentText(str(event.get("event_type", "")))

        self.video_time_input = QDoubleSpinBox()
        self.video_time_input.setDecimals(6)
        self.video_time_input.setRange(0.0, 1_000_000_000.0)
        self.video_time_input.setSuffix(" s")
        self.video_time_input.setValue(float(event.get("video_time_sec", 0.0)))

        self.frame_input = QSpinBox()
        self.frame_input.setRange(0, 2_147_483_647)
        self.frame_input.setValue(int(event.get("frame_index", 0)))

        self.note_input = QLineEdit(str(event.get("note", "")))
        self.note_input.setPlaceholderText("Add note...")

        form = QFormLayout()
        form.addRow("Event type", self.event_type_input)
        form.addRow("Video time", self.video_time_input)
        form.addRow("Frame index", self.frame_input)
        form.addRow("Note", self.note_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def accept(self):
        if not self.event_type_input.currentText().strip():
            QMessageBox.warning(
                self,
                "Invalid event type",
                "Event type cannot be empty.",
            )
            return
        super().accept()

    def values(self):
        return {
            "event_type": self.event_type_input.currentText().strip(),
            "video_time_sec": float(self.video_time_input.value()),
            "frame_index": int(self.frame_input.value()),
            "note": self.note_input.text(),
        }
