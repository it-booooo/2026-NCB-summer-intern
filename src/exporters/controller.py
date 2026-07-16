from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox

from .. import plotting, signal_processing, validation
from .lfp_image_dialog import LfpImageExportDialog
from .writers import export_events_csv, export_events_excel


class ExportController:
    """Own all save dialogs, export validation, and output generation."""

    def __init__(self, window, data_state=None, event_state=None):
        self.window = window
        self.data_state = data_state or window.data_state
        self.event_state = event_state or window.event_state
        self.last_lfp_export_directory = None

    def actions(self):
        # 第三個欄位是顯示給使用者的英文滑鼠懸停說明。
        """Describe actions.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
        """
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
                "Export LFP Images...",
                self.export_lfp_images,
                "Configure and batch-export the LFP waveform, power spectrum, and spectrogram.",
            ),
        ]

    def export_markers(self, file_type):
        # UI 流程只負責選擇格式與路徑；實際寫檔由 writers 模組處理。
        """Describe export_markers.

        Args:
            file_type: Input accepted by this function.

        Returns:
            The value produced by this function, if any.
        """
        events = [dict(event) for event in self.event_state.events]
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


    def export_check_results(self):
        """Describe export_check_results.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
        """
        exports = []

        if self.data_state.lfp_info is not None:
            exports.append(("LFP", self.data_state.lfp_info))

        if self.data_state.axis_info is not None:
            exports.append(("3-axis", self.data_state.axis_info))

        if not exports:
            QMessageBox.information(
                self.window,
                "No signal data",
                "Please import LFP or 3-axis CSV data first.",
            )
            return

        if len(exports) == 1:
            label, info = exports[0]
        else:
            items = [label for label, _ in exports]

            label, accepted = QInputDialog.getItem(
                self.window,
                "Export Check Results",
                "Data:",
                items,
                0,
                False,
            )

            if not accepted:
                return

            info = exports[items.index(label)][1]

        filename = info.get("filename", label).rsplit(".", 1)[0]

        path, _ = QFileDialog.getSaveFileName(
            self.window,
            "Export Check Results",
            f"{filename}_check_report.csv",
            "CSV Files (*.csv)",
        )

        if not path:
            return

        try:
            output_path = validation.check(
                info=info,
                output_path=path,
            )
        except Exception as error:
            QMessageBox.warning(
                self.window,
                "Export check results failed",
                str(error),
            )
            return

        QMessageBox.information(
            self.window,
            "Check Results Exported",
            f"Check results exported to:\n{output_path}",
        )

    def export_waveform_image(self):
        """Describe export_waveform_image.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
        """
        window = self.window
        if self.data_state.axis_info is None:
            QMessageBox.information(
                window, "No 3-axis data", "Please import 3-axis CSV data first."
            )
            return
        stem = self.data_state.axis_info.get("filename", "axis").rsplit(".", 1)[0]
        path, _ = QFileDialog.getSaveFileName(
            window,
            "Export 3-axis Waveform Image",
            f"{stem}_waveform.png",
            "PNG Images (*.png);;PDF Files (*.pdf);;SVG Files (*.svg);;All Files (*)",
        )
        if not path:
            return
        try:
            figure = plotting.accelerator(
                info=self.data_state.axis_info,
                compact=False,
                step=window.lfp_panel.axis_step,
            )
            figure.savefig(path, dpi=300)
        except Exception as error:
            QMessageBox.warning(
                window, "Export 3-axis waveform image failed", str(error)
            )
            return
        QMessageBox.information(
            window,
            "3-axis Waveform Image Exported",
            f"3-axis waveform image exported to:\n{path}",
        )

    def export_lfp_images(self):
        """Describe export_lfp_images.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
        """
        panel = self.window.lfp_panel
        if not panel.lfp_path:
            QMessageBox.information(
                self.window, "No LFP data", "Please import LFP CSV data first."
            )
            return

        default_directory = self.last_lfp_export_directory
        if default_directory is None or not Path(default_directory).is_dir():
            default_directory = Path(panel.lfp_path).parent

        try:
            dialog = LfpImageExportDialog(
                panel,
                default_directory,
                parent=self.window,
            )
        except (OSError, ValueError) as error:
            QMessageBox.warning(self.window, "Cannot export LFP images", str(error))
            return

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        options = dialog.options()
        self.last_lfp_export_directory = options.directory

        paths = {
            image_type: options.directory
            / self._lfp_filename(
                options.channel,
                options.settings,
                image_type,
            )
            for image_type in options.image_types
        }
        existing_paths = [path for path in paths.values() if path.exists()]
        if existing_paths:
            filenames = "\n".join(f"- {path.name}" for path in existing_paths)
            answer = QMessageBox.question(
                self.window,
                "Replace existing images?",
                f"The following files already exist:\n{filenames}\n\nReplace them?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        figures = {}
        saved_paths = []
        try:
            segment = panel.load_lfp_segment(
                options.channel,
                options.left,
                options.right,
                options.settings,
            )
            time_mode = (
                "Sync time" if panel.sync_time_origin_sec is not None else "Time"
            )

            if "waveform" in options.image_types:
                figures["waveform"] = panel.create_lfp_waveform_figure(
                    options.channel,
                    segment,
                    options.settings,
                    time_mode,
                    self.data_state.lfp_info,
                )

            if "power_spectrum" in options.image_types:
                frequencies, power = signal_processing.compute_power_spectrum(
                    segment.values,
                    segment.sample_rate_hz,
                )
                figures["power_spectrum"] = panel.create_power_spectrum_figure(
                    options.channel,
                    frequencies,
                    power,
                )

            if "spectrogram" in options.image_types:
                frequencies, times, power = signal_processing.compute_time_frequency(
                    segment.values,
                    segment.sample_rate_hz,
                )
                figures["spectrogram"] = panel.create_spectrogram_figure(
                    options.channel,
                    segment,
                    frequencies,
                    times,
                    power,
                    time_mode,
                )

            for figure in figures.values():
                panel.annotate_lfp_figure(
                    figure,
                    options.channel,
                    segment,
                    options.settings,
                )

            for image_type in options.image_types:
                path = paths[image_type]
                figures[image_type].savefig(str(path), dpi=options.dpi)
                saved_paths.append(path)
        except Exception as error:
            saved_message = ""
            if saved_paths:
                names = "\n".join(f"- {path.name}" for path in saved_paths)
                saved_message = f"\n\nAlready exported:\n{names}"
            QMessageBox.warning(
                self.window,
                "Export LFP images failed",
                f"{error}{saved_message}",
            )
            return
        finally:
            for figure in figures.values():
                figure.clear()

        filenames = "\n".join(f"- {path.name}" for path in saved_paths)
        QMessageBox.information(
            self.window,
            "LFP Images Exported",
            f"Exported {len(saved_paths)} image(s) to:\n"
            f"{options.directory}\n\n{filenames}",
        )

    def _lfp_filename(self, channel, settings, suffix):
        # 將通道、處理模式與同步後的時間範圍編入預設檔名，方便辨識輸出內容。
        panel = self.window.lfp_panel
        filename = panel.lfp_info.get("filename", "lfp") if panel.lfp_info else "lfp"
        stem = filename.rsplit(".", 1)[0]
        mode = "processed" if settings.show_filtered else "raw"
        middle = f"_{suffix}" if suffix else ""
        return f"{stem}_channel_{channel}_{mode}{middle}.png"
