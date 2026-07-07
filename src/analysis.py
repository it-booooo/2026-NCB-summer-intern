from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMessageBox

from src.led_detector import compute_led_brightness_curve, score_at_frame


class AnalysisMenuController:
    def __init__(self, parent):
        self.parent = parent
        self.led_curve_points = []
        self.led_curve_roi = None
        self.led_baseline_score = 0.0
        self.led_baseline_frame = 0

    def populate_menu(self, analysis_menu):
        export_segment_action = QAction("Export Selected Segment", self.parent)
        export_segment_action.triggered.connect(self.export_selected_segment)
        analysis_menu.addAction(export_segment_action)

    def select_led_roi(self):
        if not self.parent.video_player.has_video():
            QMessageBox.warning(self.parent, "No video", "Please import a video first.")
            return

        self.parent.video_player.start_roi_selection()

    def load_led_curve(self):
        if not self.parent.video_player.has_video():
            QMessageBox.warning(self.parent, "No video", "Please import a video first.")
            return []

        if self.parent.led_roi is None:
            QMessageBox.warning(
                self.parent,
                "No LED ROI",
                "Please select the LED ROI first.",
            )
            return []

        current_roi = self.parent.led_roi
        current_frame = self.parent.video_player.current_frame

        self.led_curve_points = compute_led_brightness_curve(
            self.parent.video_player.video_path,
            roi=current_roi,
            rotate_180=self.parent.video_player.rotate_180_enabled,
            using_fps=self.parent.video_player.fps,
        )

        self.led_curve_roi = current_roi
        self.led_baseline_frame = current_frame
        self.led_baseline_score = score_at_frame(self.led_curve_points, current_frame)

        return self.led_curve_points

    def export_selected_segment(self):
        QMessageBox.information(
            self.parent,
            "Analysis",
            "Export selected segment is not implemented yet.",
        )
