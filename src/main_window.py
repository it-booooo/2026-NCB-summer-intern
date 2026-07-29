from PySide6.QtWidgets import QMainWindow, QMessageBox

from .app_state import AppState
from .application import ApplicationComposer


class MainWindow(QMainWindow):
    """Application shell.

    Feature construction, signal wiring, menus, settings, and workflows live in
    dedicated collaborators assembled by ``ApplicationComposer``.
    """

    def __init__(self, app_state=None):
        super().__init__()
        self.app_state = app_state or AppState()
        self.resize(1280, 720)
        self.setMinimumSize(1100, 640)

        self.components = ApplicationComposer(
            self,
            self.app_state,
        ).compose()
        self.setCentralWidget(self.components.workspace)
        self.components.project_controller.update_title()

    def closeEvent(self, event):
        project = self.components.project_controller
        importer = self.components.import_controller
        led = self.components.led_controller
        video_player = self.components.video_player

        if not project.confirm_unsaved_changes("close the application"):
            event.ignore()
            return

        if not importer.stop_project_load(wait=True):
            QMessageBox.information(
                self,
                "Project loading",
                "The project is still loading. Please close the window again in a moment.",
            )
            event.ignore()
            return

        if not importer.stop_signal_import(wait=True):
            QMessageBox.information(
                self,
                "Signal import",
                "The signal cache is still closing file handles. Please close the window again in a moment.",
            )
            event.ignore()
            return

        background_stopped = (
            self.components.wave_panel.stop_background_work(wait=True)
            and self.components.find_peak_panel.cancel_peak_detection(wait=True)
            and self.components.export_controller.stop_background_work(wait=True)
        )
        if not background_stopped:
            QMessageBox.information(
                self,
                "Background work",
                "Signal analysis is still closing. Please close the window again in a moment.",
            )
            event.ignore()
            return

        if not led.stop_led_detection(wait=True):
            QMessageBox.information(
                self,
                "LED detection",
                "LED detection is still stopping. Please close the window again in a moment.",
            )
            event.ignore()
            return

        video_player.pause()
        if video_player.cap is not None:
            video_player.cap.release()
            video_player.cap = None
        if self.app_state.data.lfp_dataset is not None:
            self.app_state.data.lfp_dataset.close(wait=True)
        event.accept()
