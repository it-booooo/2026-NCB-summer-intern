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
from src.csv_loader import parse_lfp_csv_info, parse_time_marker_csv_info
from src.event_table import EventTable
from src.export import export_events_csv, export_events_excel
from src.lfp_panel import LfpPanel
from src.marker_panel import MarkerPanel
from src.sync_panel import SyncPanel
from src.video_player import VideoPlayer


class MainWindow(QMainWindow):
    MARKER_PANEL_WIDTH = 300

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Pig Behavior Video-LFP Synchronization Tool")
        self.resize(1280, 720)
        self.setMinimumSize(1100, 640)

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
        import_axis_action = QAction("Import 3-axis (.csv)", self)
        import_time_marker_action = QAction("Import Time Marker (.csv)", self)

        export_csv_action = QAction("Export Markers as CSV", self)
        export_excel_action = QAction("Export Markers as Excel", self)

        import_video_action.triggered.connect(self.import_video)
        import_lfp_action.triggered.connect(self.import_lfp)
        import_axis_action.triggered.connect(self.import_axis)
        import_time_marker_action.triggered.connect(self.import_time_marker)

        export_csv_action.triggered.connect(self.export_markers_csv)
        export_excel_action.triggered.connect(self.export_markers_excel)

        import_menu.addAction(import_video_action)
        import_menu.addSeparator()
        import_menu.addAction(import_lfp_action)
        import_menu.addAction(import_axis_action)
        import_menu.addAction(import_time_marker_action)

        export_menu.addAction(export_csv_action)
        export_menu.addAction(export_excel_action)

        self.analysis_controller.populate_menu(analysis_menu)

    def create_layout(self):
        lfp_group = QGroupBox("Waveform Area")
        lfp_layout = QVBoxLayout()
        lfp_layout.setContentsMargins(6, 6, 6, 6)
        lfp_layout.addWidget(self.lfp_panel)
        lfp_group.setLayout(lfp_layout)

        sync_group = QGroupBox("Synchronization Area")
        sync_layout = QVBoxLayout()
        sync_layout.setContentsMargins(6, 6, 6, 6)
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

        self.marker_panel.setFixedWidth(self.MARKER_PANEL_WIDTH)
        self.marker_panel.hide()

        container = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addWidget(self.marker_panel)
        layout.addWidget(main_content, stretch=1)

        container.setLayout(layout)
        self.setCentralWidget(container)

    def show_marker_panel(self):
        self.marker_panel.show()

    def hide_marker_panel(self):
        self.marker_panel.hide()

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

        info = parse_lfp_csv_info(path)
        self.lfp_panel.set_lfp_info(info)
        self.sync_panel.set_lfp_status(f"LFP file: {info['filename']}")

    def import_axis(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import 3-axis (.csv)",
            "",
            "CSV Files (*.csv);;All Files (*)",
        )

        if not path:
            return

        info = parse_lfp_csv_info(path)
        self.lfp_panel.set_axis_info(info)

    def import_time_marker(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Time Marker (.csv)",
            "",
            "CSV Files (*.csv);;All Files (*)",
        )

        if not path:
            return

        info = parse_time_marker_csv_info(path)
        self.lfp_panel.set_time_marker_info(info)

        first_marker_sec = info.get("first_marker_sec")

        if first_marker_sec is not None:
            self.sync_panel.set_ttl_marker(first_marker_sec)

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
                color: #111111;
            }

            QWidget {
                color: #111111;
                font-size: 13px;
            }

            QMenuBar {
                background-color: #e8e8e8;
                color: #111111;
                border-bottom: 1px solid #c4c4c4;
            }

            QMenuBar::item {
                padding: 5px 12px;
                background-color: transparent;
                color: #111111;
            }

            QMenuBar::item:selected {
                background-color: #d6d6d6;
                color: #111111;
            }

            QMenu {
                background-color: #ffffff;
                color: #111111;
                border: 1px solid #b8b8b8;
            }

            QMenu::item {
                padding: 5px 24px;
                color: #111111;
            }

            QMenu::item:selected {
                background-color: #dcecff;
                color: #111111;
            }

            QGroupBox {
                font-weight: bold;
                color: #111111;
                border: 1px solid #b8b8b8;
                margin-top: 8px;
                background-color: #ffffff;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
                color: #111111;
                background-color: #ffffff;
            }

            QLabel {
                color: #111111;
                font-size: 13px;
            }

            QPushButton {
                background-color: #f7f7f7;
                color: #111111;
                border: 1px solid #b8b8b8;
                border-radius: 3px;
                padding: 4px 8px;
            }

            QPushButton:hover {
                background-color: #eeeeee;
            }

            QPushButton:pressed {
                background-color: #dddddd;
            }

            QPushButton:disabled {
                background-color: #eeeeee;
                color: #888888;
            }

            QComboBox {
                background-color: #ffffff;
                color: #111111;
                border: 1px solid #b8b8b8;
                padding: 3px 6px;
            }

            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #111111;
                selection-background-color: #dcecff;
                selection-color: #111111;
            }

            QTableWidget {
                background-color: #ffffff;
                color: #111111;
                gridline-color: #d0d0d0;
                selection-background-color: transparent;
                selection-color: #111111;
            }

            QTableWidget::item {
                color: #111111;
                background-color: #ffffff;
            }

            QTableWidget::item:selected {
                background-color: transparent;
                color: #111111;
            }

            QHeaderView::section {
                background-color: #eeeeee;
                color: #111111;
                border: 1px solid #c8c8c8;
                padding: 3px;
            }

            QLineEdit,
            QPlainTextEdit,
            QTextEdit {
                background-color: #ffffff;
                color: #111111;
                border: 1px solid #c8c8c8;
                selection-background-color: #bcdcff;
                selection-color: #111111;
            }

            QSlider::groove:horizontal {
                height: 6px;
                background: #c8c8c8;
                border-radius: 3px;
            }

            QSlider::handle:horizontal {
                background: #2f80ed;
                width: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }

            QScrollBar:horizontal,
            QScrollBar:vertical {
                background: #f0f0f0;
            }

            QScrollBar::handle:horizontal,
            QScrollBar::handle:vertical {
                background: #b8b8b8;
                border-radius: 3px;
            }

            QScrollBar::handle:horizontal:hover,
            QScrollBar::handle:vertical:hover {
                background: #9f9f9f;
            }
            """
        )