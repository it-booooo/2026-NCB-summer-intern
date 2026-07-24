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
        led = self.components.led_controller
        video_player = self.components.video_player

        if not project.confirm_unsaved_changes("close the application"):
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
        project.cleanup()
        event.accept()
