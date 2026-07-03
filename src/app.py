from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.event_table import EventTable
from src.export import export_events_csv
from src.video_player import VideoPlayer


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Pig Behavior Video Annotation Tool")
        self.resize(1200, 760)

        self.video_player = VideoPlayer()
        self.event_table = EventTable()

        self.mark_led_button = QPushButton("Mark LED")
        self.mark_behavior_button = QPushButton("Mark Behavior")
        self.delete_event_button = QPushButton("Delete Event")
        self.export_button = QPushButton("Export CSV")

        self.mark_led_button.clicked.connect(lambda: self.add_event("LED_on"))
        self.mark_behavior_button.clicked.connect(lambda: self.add_event("behavior"))
        self.delete_event_button.clicked.connect(self.event_table.delete_selected_rows)
        self.export_button.clicked.connect(self.export_events)

        event_controls = QHBoxLayout()
        event_controls.addWidget(self.mark_led_button)
        event_controls.addWidget(self.mark_behavior_button)
        event_controls.addWidget(self.delete_event_button)
        event_controls.addWidget(self.export_button)

        side_panel = QWidget()
        side_layout = QVBoxLayout()
        side_layout.addWidget(QLabel("Events"))
        side_layout.addLayout(event_controls)
        side_layout.addWidget(self.event_table)
        side_panel.setLayout(side_layout)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.video_player)
        splitter.addWidget(side_panel)
        splitter.setSizes([820, 380])

        container = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(splitter)
        container.setLayout(layout)

        self.setCentralWidget(container)

    def add_event(self, event_type):
        if not self.video_player.has_video():
            QMessageBox.warning(self, "No video", "Please load an MP4 first.")
            return

        self.event_table.add_event(
            event_type=event_type,
            video_time_sec=self.video_player.current_time_sec(),
            frame_index=self.video_player.current_frame,
            note="",
        )

    def export_events(self):
        events = self.event_table.events()

        if not events:
            QMessageBox.information(self, "No events", "There are no events to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export events",
            "video_events.csv",
            "CSV Files (*.csv)",
        )

        if not path:
            return

        export_events_csv(path, events)

        QMessageBox.information(
            self,
            "Export complete",
            f"Saved events to:\n{path}",
        )