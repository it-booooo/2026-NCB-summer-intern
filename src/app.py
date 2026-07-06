from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.analysis import AnalysisMenuController
from src.event_table import EventTable
from src.export import export_events_csv, export_events_excel
from src.lfp_panel import LfpPanel
from src.marker_panel import MarkerPanel
from src.sync_panel import SyncPanel
from src.video_player import VideoPlayer


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Pig Behavior Video-LFP Synchronization Tool")
        self.resize(1280, 720)

        self.video_player = VideoPlayer()
        self.event_table = EventTable()
        self.lfp_panel = LfpPanel()
        self.sync_panel = SyncPanel()
        self.marker_panel = MarkerPanel(self.event_table, self.add_event)
        self.analysis_controller = AnalysisMenuController(self)

        self.marker_panel.close_requested.connect(self.hide_marker_panel)

        self.create_menu()
        self.create_layout()
        self.apply_style()

    def create_menu(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("File")
        analysis_menu = menu_bar.addMenu("Analysis")

        import_menu = file_menu.addMenu("Import")
        export_menu = file_menu.addMenu("Export")

        import_video_action = QAction("Import Video (.mp4)", self)
        import_lfp_action = QAction("Import LFP (.csv)", self)

        export_csv_action = QAction("Export Markers as CSV", self)
        export_excel_action = QAction("Export Markers as Excel", self)

        import_video_action.triggered.connect(self.import_video)
        import_lfp_action.triggered.connect(self.import_lfp)

        export_csv_action.triggered.connect(self.export_markers_csv)
        export_excel_action.triggered.connect(self.export_markers_excel)

        import_menu.addAction(import_video_action)
        import_menu.addAction(import_lfp_action)

        export_menu.addAction(export_csv_action)
        export_menu.addAction(export_excel_action)

        self.analysis_controller.populate_menu(analysis_menu)

    def create_layout(self):
        lfp_group = QGroupBox("LFP Waveform Area")
        lfp_layout = QVBoxLayout()
        lfp_layout.addWidget(self.lfp_panel)
        lfp_group.setLayout(lfp_layout)

        sync_group = QGroupBox("Synchronization Area")
        sync_layout = QVBoxLayout()
        sync_layout.addWidget(self.sync_panel)
        sync_group.setLayout(sync_layout)

        video_group = QGroupBox("Behavior Video")
        video_layout = QVBoxLayout()
        video_layout.setContentsMargins(4, 4, 4, 4)
        video_layout.setSpacing(2)
        video_layout.addWidget(self.video_player, stretch=1)

        self.open_marker_button = QPushButton("Open Event Marker")
        self.open_marker_button.setFixedSize(150, 26)
        self.open_marker_button.clicked.connect(self.show_marker_panel)

        marker_button_layout = QHBoxLayout()
        marker_button_layout.setContentsMargins(0, 0, 0, 0)
        marker_button_layout.setSpacing(0)
        marker_button_layout.addStretch()
        marker_button_layout.addWidget(self.open_marker_button)

        video_layout.addLayout(marker_button_layout)
        video_group.setLayout(video_layout)

        lower_splitter = QSplitter(Qt.Horizontal)
        lower_splitter.addWidget(sync_group)
        lower_splitter.addWidget(video_group)
        lower_splitter.setSizes([820, 420])

        main_content = QSplitter(Qt.Vertical)
        main_content.addWidget(lfp_group)
        main_content.addWidget(lower_splitter)
        main_content.setSizes([260, 400])

        self.marker_panel.setMinimumWidth(360)
        self.marker_panel.setMaximumWidth(460)
        self.marker_panel.hide()

        root_splitter = QSplitter(Qt.Horizontal)
        root_splitter.addWidget(main_content)
        root_splitter.addWidget(self.marker_panel)
        root_splitter.setSizes([1120, 0])

        container = QWidget()
        layout = QHBoxLayout()
        layout.addWidget(root_splitter)
        container.setLayout(layout)

        self.setCentralWidget(container)

    def import_video(self):
        loaded = self.video_player.load_video()

        if loaded:
            self.sync_panel.set_video_path(self.video_player.video_path)

    def import_lfp(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import LFP (.csv)",
            "",
            "CSV Files (*.csv);;All Files (*)",
        )

        if not path:
            return

        self.lfp_panel.set_lfp_path(path)
        self.sync_panel.set_lfp_status(f"LFP file: {path}")

    def show_marker_panel(self):
        self.marker_panel.show()

    def hide_marker_panel(self):
        self.marker_panel.hide()

    def add_event(self, event_type):
        if not self.video_player.has_video():
            QMessageBox.warning(self, "No video", "Please import a video first.")
            return

        self.event_table.add_event(
            event_type=event_type,
            video_time_sec=self.video_player.current_time_sec(),
            frame_index=self.video_player.current_frame,
            note="",
        )

    def export_markers_csv(self):
        events = self.event_table.events()

        if not events:
            QMessageBox.information(self, "No markers", "There are no markers to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Markers as CSV",
            "video_markers.csv",
            "CSV Files (*.csv)",
        )

        if path:
            export_events_csv(path, events)

    def export_markers_excel(self):
        events = self.event_table.events()

        if not events:
            QMessageBox.information(self, "No markers", "There are no markers to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Markers as Excel",
            "video_markers.xlsx",
            "Excel Files (*.xlsx)",
        )

        if path:
            export_events_excel(path, events)

    def apply_style(self):
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #f0f0f0;
            }

            QMenuBar {
                background-color: #e8e8e8;
                border-bottom: 1px solid #c4c4c4;
            }

            QMenuBar::item {
                padding: 5px 12px;
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