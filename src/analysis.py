from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMessageBox


class AnalysisMenuController:
    def __init__(self, parent):
        self.parent = parent

    def populate_menu(self, analysis_menu):
        export_segment_action = QAction("Export Selected Segment", self.parent)
        export_segment_action.triggered.connect(self.export_selected_segment)
        analysis_menu.addAction(export_segment_action)

    def select_led_roi(self):
        if not self.parent.video_player.has_video():
            QMessageBox.warning(self.parent, "No video", "Please import a video first.")
            return

        self.parent.video_player.start_roi_selection()

    def export_selected_segment(self):
        QMessageBox.information(
            self.parent,
            "Analysis",
            "Export selected segment is not implemented yet.",
        )
