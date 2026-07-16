from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QGroupBox,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .exporters import ExportController
from .importers import ImportController
from .led_controller import LedControllerMixin
from .state import AppState
from .sync_controller import SyncControllerMixin
from .ui import EventTable, LfpPanel, MarkerPanel, SyncPanel, TtlPanel
from .video import VideoPlayer


class MainWindow(LedControllerMixin, SyncControllerMixin, QMainWindow):
    """Compose the application widgets and connect feature controllers."""

    WAVEFORM_AREA_HEIGHT = 320

    def __init__(self, app_state=None):
        super().__init__()
        self.app_state = app_state or AppState()
        self.video_state = self.app_state.video
        self.data_state = self.app_state.data
        self.sync_state = self.app_state.sync
        self.led_state = self.app_state.led
        self.event_state = self.app_state.events

        self.setWindowTitle("Pig Behavior Video-LFP Synchronization Tool")
        self.resize(1280, 720)
        self.setMinimumSize(1100, 640)
        self.setWindowIcon(QIcon("input_data/icon.png"))

        self.video_player = VideoPlayer(
            self.video_state,
            self.sync_state,
            self.led_state,
        )
        self.event_table = EventTable(
            self.event_state,
            self.video_state,
            self.sync_state,
        )
        self.lfp_panel = LfpPanel(self.data_state, self.sync_state)
        self.sync_panel = SyncPanel(self.led_state)
        self.ttl_panel = TtlPanel(
            self.video_player,
            self.sync_state,
        )
        self.marker_panel = MarkerPanel(
            self.event_table,
            self.video_player,
        )
        self.import_controller = ImportController(
            self,
            self.data_state,
            self.sync_state,
            self.led_state,
        )
        self.export_controller = ExportController(
            self,
            self.data_state,
            self.event_state,
        )
        self.led_worker = None

        self.video_player.roi_selected.connect(self.set_led_roi)
        self.video_player.frame_changed.connect(self.update_waveform_current_time)
        self.lfp_panel.time_selected.connect(self.seek_video_record_time)
        self.ttl_panel.markers_changed.connect(self.set_ttl_markers)
        self.event_table.events_changed.connect(self.update_time_offset)
        self.event_table.video_time_selected.connect(self.seek_video_marker_time)

        self.create_menu()
        self.create_layout()

    def add_action(self, menu, text, callback, description=""):
        """Perform ``add_action``.

        Args:
            menu: Input accepted by this function.
            text: Input accepted by this function.
            callback: Input accepted by this function.
            description: Input accepted by this function.

        Returns:
            The value produced by this function, if any.
        """
        action = QAction(text, self)
        action.triggered.connect(callback)
        if description:
            action.setToolTip(description)
            action.setStatusTip(description)
        menu.addAction(action)
        return action

    def create_group(self, title, widget, margins=(6, 6, 6, 6)):
        """Perform ``create_group``.

        Args:
            title: Input accepted by this function.
            widget: Input accepted by this function.
            margins: Input accepted by this function.

        Returns:
            The value produced by this function, if any.
        """
        group = QGroupBox(title)
        layout = QVBoxLayout()
        layout.setContentsMargins(*margins)
        layout.addWidget(widget)
        group.setLayout(layout)
        return group

    def create_menu(self):
        """Perform ``create_menu``.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
        """
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")
        settings_menu = menu_bar.addMenu("Settings")
        import_menu = file_menu.addMenu("Import")
        export_menu = file_menu.addMenu("Export")
        import_menu.setToolTipsVisible(True)
        export_menu.setToolTipsVisible(True)

        import_actions = self.import_controller.actions()
        export_actions = self.export_controller.actions()

        for text, callback, description in import_actions:
            self.add_action(import_menu, text, callback, description)

        for text, callback, description in export_actions:
            self.add_action(export_menu, text, callback, description)

        self.add_action(
            settings_menu,
            "Set LFP step",
            lambda: self.set_plot_step("lfp"),
        )
        self.add_action(
            settings_menu,
            "Set 3-axis step",
            lambda: self.set_plot_step("axis"),
        )
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
        """Perform ``ask_step``.

        Args:
            title: Input accepted by this function.
            current_step: Input accepted by this function.

        Returns:
            The value produced by this function, if any.
        """
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

    def set_plot_step(self, plot_name):
        """Perform ``set_plot_step``.

        Args:
            plot_name: Input accepted by this function.

        Returns:
            The value produced by this function, if any.
        """
        title, step_attribute = {
            "lfp": ("Set LFP step", "lfp_step"),
            "axis": ("Set 3-axis step", "axis_step"),
        }[plot_name]
        accepted, step = self.ask_step(
            title, getattr(self.lfp_panel, step_attribute)
        )
        if accepted:
            self.lfp_panel.set_plot_step(plot_name, step)

    def set_power_noise_frequency(self):
        """Perform ``set_power_noise_frequency``.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
        """
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
        """Perform ``create_layout``.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
        """
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
        sync_group = self.create_group("Sync Area", self.sync_panel)
        ttl_group = self.create_group("TTL", self.ttl_panel, margins=(6, 10, 6, 6))
        marker_group = self.create_group("Video Marker", self.marker_panel)

        video_group = QGroupBox("Behavior Video")
        video_layout = QVBoxLayout()
        video_layout.setContentsMargins(4, 4, 4, 4)
        video_layout.setSpacing(2)
        video_layout.addWidget(self.video_player, stretch=1)
        video_group.setLayout(video_layout)

        self.sync_panel.set_embedded_panels(ttl_group, marker_group)

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

        self.setCentralWidget(main_content)

    def closeEvent(self, event):
        """Perform ``closeEvent``.

        Args:
            event: Input accepted by this function.

        Returns:
            The value produced by this function, if any.
        """
        if self.stop_led_detection(wait=True):
            event.accept()
            return

        QMessageBox.information(
            self,
            "LED detection",
            "LED detection is still stopping. Please close the window again in a moment.",
        )
        event.ignore()
