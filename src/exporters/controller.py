from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from .. import plotting, signal_processing, validation
from .writers import export_events_csv, export_events_excel, write_lfp_segment_csv


class ExportController:
    """Own all save dialogs, export validation, and output generation."""

    def __init__(self, window):
        self.window = window

    def actions(self):
        # 第三個欄位是顯示給使用者的英文滑鼠懸停說明。
        return [
            (
                "Export Markers as CSV",
                lambda: self.export_markers("csv"),
                "Export the current video event markers as a UTF-8 CSV file.",
            ),
            (
                "Export Markers as Excel",
                lambda: self.export_markers("xlsx"),
                "Export the current video event markers as an Excel workbook.",
            ),
            (
                "Export Check Results",
                self.export_check_results,
                "Validate the loaded LFP or three-axis data and export a CSV check report.",
            ),
            (
                "Export 3-axis Waveform Image",
                self.export_waveform_image,
                "Export the complete three-axis waveform as a PNG, PDF, or SVG image.",
            ),
            (
                "Export LFP Waveform Image",
                self.export_lfp_segment,
                "Export LFP signal data for the selected channel and time range as CSV.",
            ),
            (
                "Export Power Spectrum Image",
                self.export_power_spectrum_image,
                "Calculate the power spectrum of the selected LFP segment and export it as an image.",
            ),
            (
                "Export Spectrogram Image",
                self.export_spectrogram_image,
                "Calculate the spectrogram of the selected LFP segment and export it as an image.",
            ),
        ]

    def export_selected_segment(self):
        QMessageBox.information(
            self.window, "Analysis", "Export selected segment is not implemented yet."
        )

    def export_markers(self, file_type):
        # UI 流程只負責選擇格式與路徑；實際寫檔由 writers 模組處理。
        events = self.window.event_table.events()
        if not events:
            QMessageBox.information(
                self.window, "No markers", "There are no markers to export."
            )
            return
        is_csv = file_type == "csv"
        path, _ = QFileDialog.getSaveFileName(
            self.window,
            "Export Markers as CSV" if is_csv else "Export Markers as Excel",
            "video_markers.csv" if is_csv else "video_markers.xlsx",
            "CSV Files (*.csv)" if is_csv else "Excel Files (*.xlsx)",
        )
        if path:
            (export_events_csv if is_csv else export_events_excel)(path, events)

    def signal_exports(self):
        result = []
        if self.window.lfp_info is not None:
            result.append(("LFP", self.window.lfp_info))
        if self.window.axis_info is not None:
            result.append(("3-axis", self.window.axis_info))
        return result

    def choose_signal_export(self, title):
        exports = self.signal_exports()
        if not exports:
            QMessageBox.information(
                self.window, "No signal data",
                "Please import LFP or 3-axis CSV data first.",
            )
            return None
        if len(exports) == 1:
            return exports[0]
        items = [label for label, _ in exports]
        label, accepted = QInputDialog.getItem(
            self.window, title, "Data:", items, 0, False
        )
        return exports[items.index(label)] if accepted else None

    def export_check_results(self):
        selected = self.choose_signal_export("Export Check Results")
        if selected is None:
            return
        label, info = selected
        filename = info.get("filename", label).rsplit(".", 1)[0]
        path, _ = QFileDialog.getSaveFileName(
            self.window, "Export Check Results", f"{filename}_check_report.csv",
            "CSV Files (*.csv)",
        )
        if not path:
            return
        try:
            output_path = validation.check(info=info, output_path=path)
        except Exception as error:
            QMessageBox.warning(self.window, "Export check results failed", str(error))
            return
        QMessageBox.information(
            self.window, "Check Results Exported",
            f"Check results exported to:\n{output_path}",
        )

    def export_waveform_image(self):
        window = self.window
        if window.axis_info is None:
            QMessageBox.information(
                window, "No 3-axis data", "Please import 3-axis CSV data first."
            )
            return
        stem = window.axis_info.get("filename", "axis").rsplit(".", 1)[0]
        path, _ = QFileDialog.getSaveFileName(
            window, "Export 3-axis Waveform Image", f"{stem}_waveform.png",
            "PNG Images (*.png);;PDF Files (*.pdf);;SVG Files (*.svg);;All Files (*)",
        )
        if not path:
            return
        try:
            figure = plotting.accelerator(
                info=window.axis_info, compact=False, step=window.lfp_panel.axis_step
            )
            figure.savefig(path, dpi=300)
        except Exception as error:
            QMessageBox.warning(window, "Export 3-axis waveform image failed", str(error))
            return
        QMessageBox.information(
            window, "3-axis Waveform Image Exported",
            f"3-axis waveform image exported to:\n{path}",
        )

    def _lfp_parameters(self, title):
        # 所有 LFP 輸出共用相同的資料存在檢查及參數選擇流程。
        panel = self.window.lfp_panel
        if not panel.lfp_path:
            QMessageBox.information(
                self.window, "No LFP data", "Please import LFP CSV data first."
            )
            return None
        return panel.ask_lfp_output_parameters(title)

    def _lfp_filename(self, channel, left, right, settings, suffix, extension):
        # 將通道、處理模式與同步後的時間範圍編入預設檔名，方便辨識輸出內容。
        panel = self.window.lfp_panel
        filename = panel.lfp_info.get("filename", "lfp") if panel.lfp_info else "lfp"
        stem = filename.rsplit(".", 1)[0]
        mode = "processed" if settings.show_filtered else "raw"
        start = f"{panel.display_time(left):.3f}".replace("-", "neg")
        end = f"{panel.display_time(right):.3f}".replace("-", "neg")
        middle = f"_{suffix}" if suffix else ""
        return f"{stem}_channel_{channel}_{mode}{middle}_{start}-{end}s.{extension}"

    def export_lfp_segment(self):
        parameters = self._lfp_parameters("Export LFP Data")
        if parameters is None:
            return
        channel, left, right, settings = parameters
        filename = self._lfp_filename(channel, left, right, settings, "", "csv")
        path, _ = QFileDialog.getSaveFileName(
            self.window, "Export LFP Data", filename,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        try:
            segment = self.window.lfp_panel.load_lfp_segment(channel, left, right, settings)
            write_lfp_segment_csv(
                path, channel, segment, self.window.lfp_panel.sync_time_origin_sec
            )
        except Exception as error:
            QMessageBox.warning(self.window, "Export LFP segment failed", str(error))
            return
        QMessageBox.information(
            self.window, "LFP Data Exported", f"LFP data exported to:\n{path}"
        )

    def export_power_spectrum_image(self):
        parameters = self._lfp_parameters("Export Power Spectrum Image")
        if parameters is None:
            return
        channel, left, right, settings = parameters
        filename = self._lfp_filename(
            channel, left, right, settings, "power_spectrum", "png"
        )
        path, _ = QFileDialog.getSaveFileName(
            self.window, "Export Power Spectrum Image", filename,
            "PNG Images (*.png);;PDF Files (*.pdf);;SVG Files (*.svg);;All Files (*)",
        )
        if not path:
            return
        try:
            panel = self.window.lfp_panel
            segment = panel.load_lfp_segment(channel, left, right, settings)
            frequencies, power = signal_processing.compute_power_spectrum(
                segment.values, segment.sample_rate_hz
            )
            panel.create_power_spectrum_figure(channel, frequencies, power).savefig(
                path, dpi=300
            )
        except Exception as error:
            QMessageBox.warning(self.window, "Export power spectrum failed", str(error))
            return
        QMessageBox.information(
            self.window, "Power Spectrum Exported",
            f"Power spectrum image exported to:\n{path}",
        )

    def export_spectrogram_image(self):
        parameters = self._lfp_parameters("Export Spectrogram Image")
        if parameters is None:
            return
        channel, left, right, settings = parameters
        filename = self._lfp_filename(
            channel, left, right, settings, "spectrogram", "png"
        )
        path, _ = QFileDialog.getSaveFileName(
            self.window, "Export Spectrogram Image", filename,
            "PNG Images (*.png);;PDF Files (*.pdf);;SVG Files (*.svg);;All Files (*)",
        )
        if not path:
            return
        try:
            panel = self.window.lfp_panel
            segment = panel.load_lfp_segment(channel, left, right, settings)
            frequencies, times, power = signal_processing.compute_time_frequency(
                segment.values, segment.sample_rate_hz
            )
            time_mode = "sync time" if panel.sync_time_origin_sec is not None else "time"
            panel.create_spectrogram_figure(
                channel, segment, frequencies, times, power, time_mode
            ).savefig(path, dpi=300)
        except Exception as error:
            QMessageBox.warning(self.window, "Export spectrogram failed", str(error))
            return
        QMessageBox.information(
            self.window, "Spectrogram Exported",
            f"Spectrogram image exported to:\n{path}",
        )
