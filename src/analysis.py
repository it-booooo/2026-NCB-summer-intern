from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMessageBox


class AnalysisMenuController:
    def __init__(self, parent):
        self.parent = parent

    def populate_menu(self, analysis_menu):
        auto_detect_led_action = QAction("Auto Detect LED", self.parent)
        led_brightness_action = QAction("Show LED Brightness Curve", self.parent)
        export_segment_action = QAction("Export Selected Segment", self.parent)

        auto_detect_led_action.triggered.connect(self.auto_detect_led)
        led_brightness_action.triggered.connect(self.show_led_brightness_curve)
        export_segment_action.triggered.connect(self.export_selected_segment)

        analysis_menu.addAction(auto_detect_led_action)
        analysis_menu.addAction(led_brightness_action)
        analysis_menu.addSeparator()
        analysis_menu.addAction(export_segment_action)

    def auto_detect_led(self):
        QMessageBox.information(
            self.parent,
            "Analysis",
            "Auto Detect LED is not implemented yet.",
        )

    def show_led_brightness_curve(self):
        QMessageBox.information(
            self.parent,
            "Analysis",
            "LED brightness curve is not implemented yet.",
        )

    def export_selected_segment(self):
        QMessageBox.information(
            self.parent,
            "Analysis",
            "Export selected segment is not implemented yet.",
        )