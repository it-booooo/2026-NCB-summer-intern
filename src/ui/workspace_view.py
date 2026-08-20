from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


class WorkspaceView(QWidget):
    """Lay out the application's already-constructed feature panels."""

    WAVEFORM_DEFAULT_HEIGHT = 320
    WAVEFORM_MIN_HEIGHT = 270

    def __init__(self, wave_panel, sync_panel, video_player, parent=None):
        super().__init__(parent)
        lfp_group = self._create_group(
            "Waveform Area",
            wave_panel,
            margins=(6, 6, 6, 4),
        )
        lfp_group.setMinimumHeight(self.WAVEFORM_MIN_HEIGHT)
        lfp_group.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        sync_group = self._create_group("Sync Area", sync_panel)

        video_group = QGroupBox("Behavior Video")
        video_layout = QVBoxLayout(video_group)
        video_layout.setContentsMargins(4, 4, 4, 4)
        video_layout.setSpacing(2)
        video_layout.addWidget(video_player, stretch=1)

        lower_splitter = QSplitter(Qt.Orientation.Horizontal)
        lower_splitter.addWidget(sync_group)
        lower_splitter.addWidget(video_group)
        lower_splitter.setChildrenCollapsible(False)
        lower_splitter.setStretchFactor(0, 1)
        lower_splitter.setStretchFactor(1, 1)
        lower_splitter.setSizes([640, 640])

        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.addWidget(lfp_group)
        main_splitter.addWidget(lower_splitter)
        main_splitter.setChildrenCollapsible(False)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([self.WAVEFORM_DEFAULT_HEIGHT, 640])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(main_splitter, stretch=1)

    @staticmethod
    def _create_group(title, widget, margins=(6, 6, 6, 6)):
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(*margins)
        layout.addWidget(widget)
        return group
