from PySide6.QtWidgets import QComboBox, QStackedWidget, QVBoxLayout, QWidget


class SyncPanel(QWidget):
    """Container that switches between the independent marker panels."""

    def __init__(self):
        super().__init__()
        self.marker_selector = QComboBox()
        self.marker_selector.addItems(["TTL", "Video", "Find Peak", "LED Analysis"])
        self.marker_selector.setFixedHeight(24)
        self.marker_stack = QStackedWidget()
        self.marker_selector.currentIndexChanged.connect(
            self.marker_stack.setCurrentIndex
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.marker_selector)
        layout.addWidget(self.marker_stack, stretch=1)

    def set_marker_panels(
        self,
        ttl_panel,
        video_marker_panel,
        find_peak_panel,
        led_analysis_panel,
    ):
        while self.marker_stack.count():
            widget = self.marker_stack.widget(0)
            self.marker_stack.removeWidget(widget)
            widget.setParent(None)
        for panel in (
            ttl_panel,
            video_marker_panel,
            find_peak_panel,
            led_analysis_panel,
        ):
            self.marker_stack.addWidget(panel)
        self.marker_selector.setCurrentIndex(1)
