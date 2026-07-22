from PySide6.QtWidgets import QWidget


class MarkerViewPanel(QWidget):
    """Shared base for panels that present a filtered MarkerStore view."""

    def __init__(self, marker_store, parent=None):
        super().__init__(parent)
        self.marker_store = marker_store
        self.marker_store.changed.connect(self.refresh_markers)

    def accepts_marker(self, marker):
        return True

    def markers(self):
        return tuple(
            marker for marker in self.marker_store.all() if self.accepts_marker(marker)
        )

    def delete_marker(self, marker_id):
        self.marker_store.delete(marker_id)

    def refresh_markers(self):
        """Refresh the panel after a shared marker change."""

