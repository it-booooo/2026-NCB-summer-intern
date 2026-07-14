from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .exporters import ExportController
from .importers import ImportController
from .led_controller import LedControllerMixin
from .sync_controller import SyncControllerMixin
from .ui import EventTable, LfpPanel, MarkerPanel, SyncPanel, TtlPanel
from .video import VideoPlayer


class MainWindow(LedControllerMixin, SyncControllerMixin, QMainWindow):
    """Compose the application widgets and connect feature controllers."""

    MARKER_PANEL_WIDTH = 300
    WAVEFORM_AREA_HEIGHT = 320

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pig Behavior Video-LFP Synchronization Tool")
        self.resize(1280, 720)
        self.setMinimumSize(1100, 640)

        self.video_player = VideoPlayer()
        self.event_table = EventTable()
        self.lfp_panel = LfpPanel()
        self.sync_panel = SyncPanel()
        self.ttl_panel = TtlPanel()
        self.marker_panel = MarkerPanel(
            self.event_table,
            self.add_event,
            self.select_led_roi,
        )
        self.import_controller = ImportController(self)
        self.export_controller = ExportController(self)
        self.lfp_info = None
        self.axis_info = None
        self.timeMarker_info = None
        self.led_roi = None
        self.led_worker = None
        self.led_brightness_cache = {}
        self.time_offset_sec = None
        self.loading_video = False

        self.video_player.roi_selected.connect(self.set_led_roi)
        self.video_player.frame_changed.connect(self.update_waveform_current_time)
        self.lfp_panel.time_selected.connect(self.seek_video_record_time)
        self.ttl_panel.markers_changed.connect(self.set_ttl_markers)
        self.event_table.events_changed.connect(self.update_time_offset)
        self.event_table.video_time_selected.connect(self.seek_video_marker_time)

        self.create_menu()
        self.create_layout()

    def add_action(self, menu, text, callback, description=""):
        action = QAction(text, self)
        action.triggered.connect(callback)
        if description:
            action.setToolTip(description)
            action.setStatusTip(description)
        menu.addAction(action)
        return action

    def create_group(self, title, widget, margins=(6, 6, 6, 6)):
        group = QGroupBox(title)
        layout = QVBoxLayout()
        layout.setContentsMargins(*margins)
        layout.addWidget(widget)
        group.setLayout(layout)
        return group

    def create_menu(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")
        settings_menu = menu_bar.addMenu("Settings")
        import_menu = file_menu.addMenu("Import")
        export_menu = file_menu.addMenu("Export")
        import_menu.setToolTipsVisible(True)
        export_menu.setToolTipsVisible(True)

        import_actions = self.import_controller.actions()
        export_actions = self.export_controller.actions()

        self.add_action(import_menu, *import_actions[0])
        import_menu.addSeparator()
        for text, callback, description in import_actions[1:]:
            self.add_action(import_menu, text, callback, description)

        for text, callback, description in export_actions:
            self.add_action(export_menu, text, callback, description)

        self.add_action(settings_menu, "Set LFP step", self.set_lfp_step)
        self.add_action(settings_menu, "Set 3-axis step", self.set_axis_step)
        self.add_action(
            settings_menu,
            "Set power noise frequency",
            self.set_power_noise_frequency,
        )
        self.add_action(
            settings_menu,
            "Check OpenCL GPU",
            self.show_opencl_status,
        )

    def ask_step(self, title, current_step):
        step, accepted = QInputDialog.getInt(
            self,
            title,
            "Step (-1 auto, 0 all):",
            -1 if current_step is None else int(current_step),
            -1,
            1_000_000,
            1,
        )
        if not accepted:
            return False, None
        return True, None if step == -1 else step

    def set_lfp_step(self):
        accepted, step = self.ask_step("Set LFP step", self.lfp_panel.lfp_step)
        if accepted:
            self.lfp_panel.set_lfp_step(step)

    def set_axis_step(self):
        accepted, step = self.ask_step("Set 3-axis step", self.lfp_panel.axis_step)
        if accepted:
            self.lfp_panel.set_axis_step(step)

    def set_power_noise_frequency(self):
        items = ["60 Hz", "50 Hz"]
        values = [60.0, 50.0]
        current_index = 1 if self.lfp_panel.line_noise_hz == 50.0 else 0
        text, accepted = QInputDialog.getItem(
            self,
            "Set power noise frequency",
            "Power noise filter:",
            items,
            current_index,
            False,
        )
        if accepted:
            self.lfp_panel.set_line_noise_hz(values[items.index(text)])

    def create_layout(self):
        lfp_group = self.create_group(
            "Waveform Area",
            self.lfp_panel,
            margins=(6, 6, 6, 4),
        )
        lfp_group.setMinimumHeight(self.WAVEFORM_AREA_HEIGHT)
        lfp_group.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )
        sync_group = self.create_group("Synchronization Area", self.sync_panel)
        ttl_group = self.create_group("TTL", self.ttl_panel, margins=(6, 10, 6, 6))
        marker_group = self.create_group("Video Marker", self.marker_panel)

        video_group = QGroupBox("Behavior Video")
        video_layout = QVBoxLayout()
        video_layout.setContentsMargins(4, 4, 4, 4)
        video_layout.setSpacing(2)
        video_layout.addWidget(self.video_player, stretch=1)
        video_group.setLayout(video_layout)

        self.open_marker_button = QPushButton("Open Video Marker")
        self.open_marker_button.setFixedSize(150, 26)
        self.open_marker_button.clicked.connect(self.show_marker_panel)
        self.sync_panel.add_top_left_widget(self.open_marker_button)

        lower_splitter = QSplitter(Qt.Orientation.Horizontal)
        lower_splitter.addWidget(sync_group)
        lower_splitter.addWidget(video_group)
        lower_splitter.setChildrenCollapsible(False)
        lower_splitter.setStretchFactor(0, 1)
        lower_splitter.setStretchFactor(1, 1)
        lower_splitter.setSizes([640, 640])

        main_content = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(4)
        main_layout.addWidget(lfp_group)
        main_layout.addWidget(lower_splitter, stretch=1)
        main_content.setLayout(main_layout)

        self.side_panel = QWidget()
        self.side_panel.setFixedWidth(self.MARKER_PANEL_WIDTH)

        close_button = QPushButton("X")
        close_button.setObjectName("sidebarCloseButton")
        close_button.setFlat(True)
        close_button.setFixedSize(16, 16)
        close_button.clicked.connect(self.hide_marker_panel)

        close_layout = QHBoxLayout()
        close_layout.setContentsMargins(0, 0, 2, 0)
        close_layout.setSpacing(0)
        close_layout.addStretch()
        close_layout.addWidget(close_button)

        side_layout = QVBoxLayout()
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(0)
        side_layout.addLayout(close_layout)
        side_layout.addWidget(ttl_group, stretch=2)
        side_layout.addSpacing(6)
        side_layout.addWidget(marker_group, stretch=3)
        self.side_panel.setLayout(side_layout)
        self.side_panel.hide()

        root_layout = QHBoxLayout()
        root_layout.setContentsMargins(4, 4, 4, 4)
        root_layout.setSpacing(4)
        root_layout.addWidget(self.side_panel)
        root_layout.addWidget(main_content, stretch=1)

        container = QWidget()
        container.setLayout(root_layout)
        self.setCentralWidget(container)

    def show_marker_panel(self):
        self.side_panel.show()

    def hide_marker_panel(self):
        self.side_panel.hide()

    def closeEvent(self, event):
        if self.stop_led_detection(wait=True):
            event.accept()
            return

        QMessageBox.information(
            self,
            "LED detection",
            "LED detection is still stopping. Please close the window again in a moment.",
        )
        event.ignore()
