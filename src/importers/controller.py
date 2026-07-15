from PySide6.QtWidgets import QFileDialog, QMessageBox

from .. import data_io


class ImportController:
    """Own all file-selection and import workflows for the main window."""

    SIGNAL_IMPORT_TITLES = {
        "lfp": "Import LFP (.csv)",
        "axis": "Import 3-axis (.csv)",
    }

    def __init__(self, window):
        self.window = window

    def actions(self):
        return [
            (
                "Import Video (.mp4)",
                self.import_video,
                "Load an MP4 behavior video and reset the current synchronization and LED analysis state.",
            ),
            (
                "Import LFP (.csv)",
                lambda: self.import_signal("lfp"),
                "Load LFP data from a CSV file, parse its channels and sampling information, and display the waveform.",
            ),
            (
                "Import 3-axis (.csv)",
                lambda: self.import_signal("axis"),
                "Load three-axis sensor data from a CSV file and display its waveforms.",
            ),
            (
                "Import Time Marker (.csv)",
                self.import_time_marker,
                "Load TTL time markers from a CSV file for video and signal synchronization.",
            ),
        ]

    def open_csv_file(self, title):
        path, _ = QFileDialog.getOpenFileName(
            self.window, title, "", "CSV Files (*.csv);;All Files (*)"
        )
        return path

    def import_video(self):
        window = self.window
        if not window.stop_led_detection(wait=True):
            QMessageBox.information(
                window, "LED detection",
                "LED detection is still stopping. Please try again in a moment.",
            )
            return

        path, _ = QFileDialog.getOpenFileName(
            window, "Open MP4", "", "Video Files (*.mp4)"
        )
        if not path:
            return

        window.loading_video = True
        try:
            loaded = window.video_player.load_video(path)
        finally:
            window.loading_video = False

        if loaded:
            window.led_brightness_cache.clear()
            window.reset_sync_state_for_new_video()
            window.event_table.set_video_timing(
                window.video_player.fps,
                window.video_player.total_frames,
            )
            window.sync_panel.set_video_path(window.video_player.video_path)

    def import_signal(self, signal_type):
        """Import an LFP or 3-axis CSV through the shared signal workflow."""
        window = self.window
        path = self.open_csv_file(self.SIGNAL_IMPORT_TITLES[signal_type])
        if not path:
            return

        info = data_io.parse_lfp_csv_info(path)
        if signal_type == "lfp":
            window.lfp_info = info
            window.lfp_panel.set_lfp_info(info)
            window.sync_panel.set_lfp_status(f"LFP file: {info['filename']}")
        else:
            window.axis_info = info
            window.lfp_panel.set_axis_info(info)

        window.update_waveform_current_time()

    def import_time_marker(self):
        window = self.window
        path = self.open_csv_file("Import Time Marker (.csv)")
        if not path:
            return
        window.timeMarker_info = data_io.parse_time_marker_csv_info(path)
        window.set_ttl_markers(window.timeMarker_info)
        window.ttl_panel.set_markers(window.timeMarker_info)
        window.show_marker_panel()
