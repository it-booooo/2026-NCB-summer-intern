from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.event_table import EventTable
from src.export import export_events_csv
from src.video_player import VideoPlayer


class SignalPlaceholder(QWidget):
    def __init__(self):
        super().__init__()

        title = QLabel("Signal Viewer")
        title.setStyleSheet("font-weight: bold;")

        hint = QLabel(
            "LFP / TTL signal area\n"
            "This area can be connected to your teammate's CSV/LFP module later."
        )
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color: #666;")

        channel_grid = QGridLayout()

        for row in range(6):
            channel_name = QLabel(f"Ch {row + 1}")
            channel_name.setFixedWidth(48)

            trace = QFrame()
            trace.setMinimumHeight(48)
            trace.setStyleSheet(
                """
                QFrame {
                    background-color: #fbfbfb;
                    border: 1px solid #d0d0d0;
                }
                """
            )

            channel_grid.addWidget(channel_name, row, 0)
            channel_grid.addWidget(trace, row, 1)

        layout = QVBoxLayout()
        layout.addWidget(title)
        layout.addLayout(channel_grid)
        layout.addWidget(hint)

        self.setLayout(layout)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Pig Behavior Video-LFP Synchronization Tool")
        self.resize(1400, 850)

        self.video_player = VideoPlayer()
        self.event_table = EventTable()
        self.signal_placeholder = SignalPlaceholder()

        self.create_toolbar()
        self.create_main_layout()
        self.apply_style()

    def create_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)

        self.load_video_button = QPushButton("Load MP4")
        self.mark_led_button = QPushButton("Mark LED")
        self.mark_behavior_button = QPushButton("Mark Behavior")
        self.delete_event_button = QPushButton("Delete Event")
        self.export_button = QPushButton("Export CSV")

        self.load_video_button.clicked.connect(self.video_player.load_video)
        self.mark_led_button.clicked.connect(lambda: self.add_event("LED_on"))
        self.mark_behavior_button.clicked.connect(lambda: self.add_event("behavior"))
        self.delete_event_button.clicked.connect(self.event_table.delete_selected_rows)
        self.export_button.clicked.connect(self.export_events)

        toolbar.addWidget(self.load_video_button)
        toolbar.addSeparator()
        toolbar.addWidget(self.mark_led_button)
        toolbar.addWidget(self.mark_behavior_button)
        toolbar.addWidget(self.delete_event_button)
        toolbar.addSeparator()
        toolbar.addWidget(self.export_button)

        self.addToolBar(Qt.TopToolBarArea, toolbar)

    def create_main_layout(self):
        signal_group = QGroupBox("LFP / TTL Preview")
        signal_layout = QVBoxLayout()
        signal_layout.addWidget(self.signal_placeholder)
        signal_group.setLayout(signal_layout)

        video_group = QGroupBox("Behavior Video")
        video_layout = QVBoxLayout()
        video_layout.addWidget(self.video_player)
        video_group.setLayout(video_layout)

        top_splitter = QSplitter(Qt.Horizontal)
        top_splitter.addWidget(signal_group)
        top_splitter.addWidget(video_group)
        top_splitter.setSizes([900, 500])

        event_group = QGroupBox("Event Marker Table")
        event_layout = QVBoxLayout()

        quick_mark_layout = QHBoxLayout()

        led_on_button = QPushButton("LED On")
        led_off_button = QPushButton("LED Off")
        behavior_start_button = QPushButton("Behavior Start")
        behavior_end_button = QPushButton("Behavior End")
        seizure_button = QPushButton("Seizure-like Event")

        led_on_button.clicked.connect(lambda: self.add_event("LED_on"))
        led_off_button.clicked.connect(lambda: self.add_event("LED_off"))
        behavior_start_button.clicked.connect(lambda: self.add_event("behavior_start"))
        behavior_end_button.clicked.connect(lambda: self.add_event("behavior_end"))
        seizure_button.clicked.connect(lambda: self.add_event("seizure_like_event"))

        quick_mark_layout.addWidget(led_on_button)
        quick_mark_layout.addWidget(led_off_button)
        quick_mark_layout.addWidget(behavior_start_button)
        quick_mark_layout.addWidget(behavior_end_button)
        quick_mark_layout.addWidget(seizure_button)
        quick_mark_layout.addStretch()

        event_layout.addLayout(quick_mark_layout)
        event_layout.addWidget(self.event_table)
        event_group.setLayout(event_layout)

        main_splitter = QSplitter(Qt.Vertical)
        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(event_group)
        main_splitter.setSizes([610, 240])

        container = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(main_splitter)
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

    def apply_style(self):
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #f0f0f0;
            }

            QToolBar {
                background-color: #e6e6e6;
                border-bottom: 1px solid #bdbdbd;
                spacing: 6px;
                padding: 4px;
            }

            QGroupBox {
                font-weight: bold;
                border: 1px solid #b8b8b8;
                margin-top: 8px;
                background-color: #ffffff;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }

            QPushButton {
                padding: 6px 10px;
            }

            QLabel {
                font-size: 13px;
            }

            QTableWidget {
                background-color: #ffffff;
                gridline-color: #d0d0d0;
            }
            """
        )