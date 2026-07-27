import json
from zipfile import BadZipFile

from PySide6.QtCore import QThread, Signal

from ..led_detection import LedBrightnessPoint
from ..markers import Marker, marker_from_dict
from ..project_archive import load_project_archive


def prepare_project_objects(archive_data):
    """Convert persisted marker and LED dictionaries into runtime objects."""
    if archive_data.get("objects_prepared"):
        return archive_data

    state = archive_data["state"]
    state["markers"] = [
        item if isinstance(item, Marker) else marker_from_dict(item)
        for item in state.get("markers", [])
    ]

    led = state.get("led", {})
    led["analysis_points"] = [
        point
        if isinstance(point, LedBrightnessPoint)
        else LedBrightnessPoint(**point)
        for point in led.get("analysis_points") or []
    ]
    for cache in led.get("brightness_cache") or []:
        cache["points"] = [
            point
            if isinstance(point, LedBrightnessPoint)
            else LedBrightnessPoint(**point)
            for point in cache.get("points", [])
        ]

    archive_data["objects_prepared"] = True
    return archive_data


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
            prepare_project_objects(archive_data)
        except (BadZipFile, KeyError, OSError, ValueError, json.JSONDecodeError) as error:
            self.failed.emit("Open project failed", str(error))
            return
        except Exception as error:
            self.failed.emit("Restore project failed", str(error))
            return

        self.loaded.emit(archive_data)
