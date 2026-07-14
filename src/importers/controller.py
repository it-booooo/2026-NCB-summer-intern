from PySide6.QtWidgets import QFileDialog, QMessageBox

from .. import data_io


class ImportController:
    """Own all file-selection and import workflows for the main window."""

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
                self.import_lfp,
                "Load LFP data from a CSV file, parse its channels and sampling information, and display the waveform.",
            ),
            (
                "Import 3-axis (.csv)",
                self.import_axis,
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
        # 更換影片前先停止背景 LED 分析，避免舊影片的工作執行緒繼續寫入狀態。
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
            window.sync_panel.set_video_path(window.video_player.video_path)

    def import_lfp(self):
        # LFP 解析、畫面狀態更新與波形刷新都集中在此匯入流程。
        window = self.window
        path = self.open_csv_file("Import LFP (.csv)")
        if path:
            window.lfp_info = data_io.parse_lfp_csv_info(path)
            window.lfp_panel.set_lfp_info(window.lfp_info)
            window.sync_panel.set_lfp_status(
                f"LFP file: {window.lfp_info['filename']}"
            )
            window.update_waveform_current_time(
                window.video_player.current_frame,
                window.video_player.current_time_sec(),
            )

    def import_axis(self):
        # 三軸資料沿用相同的 CSV metadata 格式，再交由波形面板繪製。
        window = self.window
        path = self.open_csv_file("Import 3-axis (.csv)")
        if path:
            window.axis_info = data_io.parse_lfp_csv_info(path)
            window.lfp_panel.set_axis_info(window.axis_info)
            window.update_waveform_current_time(
                window.video_player.current_frame,
                window.video_player.current_time_sec(),
            )

    def import_time_marker(self):
        # TTL marker 載入後立即更新同步計算及側邊 marker 面板。
        window = self.window
        path = self.open_csv_file("Import Time Marker (.csv)")
        if not path:
            return
        window.timeMarker_info = data_io.parse_time_marker_csv_info(path)
        window.set_ttl_markers(window.timeMarker_info)
        window.ttl_panel.set_markers(window.timeMarker_info)
        window.show_marker_panel()
