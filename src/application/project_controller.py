import shutil
from pathlib import Path

from PySide6.QtWidgets import QMessageBox


class ProjectController:
    """Own project dirty state, title, prompts, and temporary files."""

    APPLICATION_TITLE = "Pig Behavior Video-LFP Synchronization Tool"

    def __init__(self, parent, project_state):
        self.parent = parent
        self.project_state = project_state
        self.project_temp_directory = None
        self._save_project = None

    def set_save_callback(self, callback):
        self._save_project = callback

    def connect_dirty_sources(self, *signals):
        for signal in signals:
            signal.connect(self.mark_dirty)

    def mark_dirty(self, *_args):
        if self.project_state.loading:
            return
        self.project_state.dirty = True
        self.update_title()

    def update_title(self):
        path = self.project_state.path
        name = Path(path).name if path else "Untitled"
        dirty = " *" if self.project_state.dirty else ""
        self.parent.setWindowTitle(f"{name}{dirty} - {self.APPLICATION_TITLE}")

    def confirm_unsaved_changes(self, action):
        if not self.project_state.dirty:
            return True
        choice = QMessageBox.warning(
            self.parent,
            "Unsaved Changes",
            f"The current analysis has unsaved changes. Save before you {action}?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Save:
            return bool(self._save_project and self._save_project())
        return choice == QMessageBox.StandardButton.Discard

    def replace_temp_directory(self, directory):
        previous = self.project_temp_directory
        self.project_temp_directory = directory
        if previous is not None and previous != directory:
            shutil.rmtree(previous, ignore_errors=True)

    def cleanup(self):
        if self.project_temp_directory is not None:
            shutil.rmtree(self.project_temp_directory, ignore_errors=True)
            self.project_temp_directory = None
