import json
from zipfile import BadZipFile

from PySide6.QtCore import QThread, Signal

from ..project_archive import load_project_archive


class ProjectLoadWorker(QThread):
    """Read and validate a project archive away from the GUI thread."""

    loaded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        try:
            archive_data = load_project_archive(self.path)
        except (BadZipFile, KeyError, OSError, ValueError, json.JSONDecodeError) as error:
            self.failed.emit("Open project failed", str(error))
            return
        except Exception as error:
            self.failed.emit("Restore project failed", str(error))
            return

        self.loaded.emit(archive_data)
