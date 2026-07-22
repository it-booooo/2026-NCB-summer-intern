from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .data_export import ExportController
from .data_import import ImportController
from .led_detection.led_controller import LedControllerMixin
from .app_state import AppState
from .synchronization.sync_controller import SyncControllerMixin
from .ui import (
    EventTable,
    FindPeakPanel,
    LfpPanel,
    MarkerPanel,
    SyncPanel,
    TtlPanel,
)
from .video_player import VideoPlayer


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
        self.lfp_panel = LfpPanel(
            self.data_state,
            self.sync_state,
            self.event_state,
        )
        self.sync_panel = SyncPanel(self.led_state)
        self.ttl_panel = TtlPanel(
            self.video_player,
            self.sync_state,
            self.video_state,
        )
        self.marker_panel = MarkerPanel(
            self.event_table,
            self.video_player,
            self.video_state,
            self.lfp_panel,
            self.sync_state,
        )
        self.find_peak_panel = FindPeakPanel(
            self.app_state,
            self.event_table,
            self.video_player,
            self.lfp_panel,
        )
        self.import_controller = ImportController(
            self,
            self.app_state,
        )
        self.export_controller = ExportController(
            self,
            self.app_state,
        )
        self.led_worker = None

        self.video_player.roi_selected.connect(self.set_led_roi)
        self.video_player.roi_selected.connect(self.mark_project_dirty)
        self.video_player.project_changed.connect(self.mark_project_dirty)
        self.video_player.frame_changed.connect(self.update_waveform_current_time)
        self.lfp_panel.time_selected.connect(self.seek_video_record_time)
        self.ttl_panel.markers_changed.connect(self.set_ttl_markers)
        self.ttl_panel.markers_changed.connect(self.mark_project_dirty)
        self.event_table.events_changed.connect(self.update_time_offset)
        self.event_table.events_changed.connect(self.lfp_panel.update_lfp_peak_artist)
        self.event_table.events_changed.connect(self.mark_project_dirty)
        self.lfp_panel.project_changed.connect(self.mark_project_dirty)
        self.sync_panel.project_changed.connect(self.mark_project_dirty)
        self.event_table.video_time_selected.connect(self.seek_video_marker_time)

        self.create_menu()
        self.create_layout()
        self.update_project_title()

    def mark_project_dirty(self, *_args):
        """Record a user-visible project change unless a project is loading."""
        if self.app_state.project.loading:
            return
        self.app_state.project.dirty = True
        self.update_project_title()

    def update_project_title(self):
        """Show the current project name and unsaved marker in the title bar."""
        project_path = self.app_state.project.path
        project_name = Path(project_path).name if project_path else "Untitled"
        dirty_marker = " *" if self.app_state.project.dirty else ""
        self.setWindowTitle(
            f"{project_name}{dirty_marker} - Pig Behavior Video-LFP Synchronization Tool"
        )

    def confirm_unsaved_changes(self, action):
        """Offer Save, Discard, or Cancel before replacing unsaved work."""
        if not self.app_state.project.dirty:
            return True
        choice = QMessageBox.warning(
            self,
            "Unsaved Changes",
            f"The current analysis has unsaved changes. Save before you {action}?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Save:
            return bool(self.export_controller.save_project())
        return choice == QMessageBox.StandardButton.Discard

    def add_action(self, menu, text, callback, description=""):
        """Add action.

        Args:
            menu: Input used by this operation.
            text: Text displayed to the user.
            callback: Function invoked when the operation completes or changes.
            description: Input used by this operation.
        """
        action = QAction(text, self)
        action.triggered.connect(callback)
        if description:
            action.setToolTip(description)
            action.setStatusTip(description)
        menu.addAction(action)
        return action

    def create_group(self, title, widget, margins=(6, 6, 6, 6)):
        """Create group.

        Args:
            title: Dialog title displayed to the user.
            widget: Input used by this operation.
            margins: Input used by this operation.
        """
        group = QGroupBox(title)
        layout = QVBoxLayout()
        layout.setContentsMargins(*margins)
        layout.addWidget(widget)
        group.setLayout(layout)
        return group

    def create_menu(self):
        """Create menu.

        Args:
            None.
        """
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")
        settings_menu = menu_bar.addMenu("Settings")
        self.add_action(
            file_menu,
            "Open Project...",
            self.import_controller.open_project,
            "Restore a complete analysis session from a .pigproj file.",
        )
        self.add_action(
            file_menu,
            "Save Project...",
            self.export_controller.save_project,
            "Save analysis state in one .pigproj file while referencing all imported files by path.",
        )
        file_menu.addSeparator()
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
            "set LFP peak thresholds",
            self.set_lfp_peak_thresholds,
        )
        self.add_action(
            settings_menu,
            "Check OpenCL GPU",
            self.show_opencl_status,
        )

    def ask_step(self, title, current_step):
        """Show a dialog for choosing a plot step and return the confirmed value.

        Args:
            title: Dialog title displayed to the user.
            current_step: Currently selected plot step.
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
        """Set plot step.

        Args:
            plot_name: Input used by this operation.
        """
        title, step_attribute = {
            "lfp": ("Set LFP step", "lfp_step"),
            "axis": ("Set 3-axis step", "axis_step"),
        }[plot_name]
        accepted, step = self.ask_step(
            title, getattr(self.app_state.data, step_attribute)
        )
        if accepted:
            self.lfp_panel.set_plot_step(plot_name, step)

    def set_power_noise_frequency(self):
        """Set power noise frequency.

        Args:
            None.
        """
        items = ["60 Hz", "50 Hz"]
        values = [60.0, 50.0]
        current_index = 1 if self.app_state.data.line_noise_hz == 50.0 else 0
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

    def set_lfp_peak_thresholds(self):
        """Set both sigma thresholds used by LFP peak detection."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Set LFP peak thresholds")

        height_input = QDoubleSpinBox(dialog)
        prominence_input = QDoubleSpinBox(dialog)
        for spinbox in (height_input, prominence_input):
            spinbox.setDecimals(2)
            spinbox.setRange(0.0, 100.0)
            spinbox.setSingleStep(0.1)
            spinbox.setSuffix(" σ")

        height_input.setValue(float(self.find_peak_panel.LFP_PEAK_HEIGHT_SIGMA))
        prominence_input.setValue(
            float(self.find_peak_panel.LFP_PEAK_PROMINENCE_SIGMA)
        )

        form = QFormLayout()
        form.addRow("Peak height threshold:", height_input)
        form.addRow("Peak prominence threshold:", prominence_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        layout = QVBoxLayout(dialog)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self.find_peak_panel.LFP_PEAK_HEIGHT_SIGMA = height_input.value()
        self.find_peak_panel.LFP_PEAK_PROMINENCE_SIGMA = prominence_input.value()
        self.find_peak_panel.add_lfp_peaks()

    def create_layout(self):
        """Create layout.

        Args:
            None.
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
        video_group = QGroupBox("Behavior Video")
        video_layout = QVBoxLayout()
        video_layout.setContentsMargins(4, 4, 4, 4)
        video_layout.setSpacing(2)
        video_layout.addWidget(self.video_player, stretch=1)
        video_group.setLayout(video_layout)

        self.sync_panel.set_marker_panels(
            self.ttl_panel,
            self.marker_panel,
            self.find_peak_panel,
        )

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
        """Close event.

        Args:
            event: Event record to process.
        """
        if not self.confirm_unsaved_changes("close the application"):
            event.ignore()
            return

        if self.stop_led_detection(wait=True):
            self.video_player.pause()
            if self.video_player.cap is not None:
                self.video_player.cap.release()
                self.video_player.cap = None

            event.accept()
            return

        QMessageBox.information(
            self,
            "LED detection",
            "LED detection is still stopping. Please close the window again in a moment.",
        )
        event.ignore()
