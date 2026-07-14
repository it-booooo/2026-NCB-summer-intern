import csv

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

import check_function as check
import csv_function as csv_func
import draw_function as draw



def export_events_csv(path, events):
    fields = ["event_type", "video_time_sec", "frame_index", "note"]
    with open(path, "w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()
        for event in events:
            writer.writerow(
                {
                    "event_type": event.get("event_type", ""),
                    "video_time_sec": f"{float(event.get('video_time_sec', 0)):.6f}",
                    "frame_index": int(event.get("frame_index", 0)),
                    "note": event.get("note", ""),
                }
            )


def export_events_excel(path, events):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Markers"
    sheet.append(["event_type", "video_time_sec", "frame_index", "note"])
    for event in events:
        sheet.append(
            [
                event.get("event_type", ""),
                float(event.get("video_time_sec", 0)),
                int(event.get("frame_index", 0)),
                event.get("note", ""),
            ]
        )
    workbook.save(path)


class IoControllerMixin:
    """File import and export actions used by the main window."""

    def open_csv_file(self, title):
        path, _ = QFileDialog.getOpenFileName(
            self, title, "", "CSV Files (*.csv);;All Files (*)"
        )
        return path

    def import_video(self):
        if not self.stop_led_detection(wait=True):
            QMessageBox.information(
                self,
                "LED detection",
                "LED detection is still stopping. Please try again in a moment.",
            )
            return

        if self.video_player.load_video():
            self.led_brightness_cache.clear()
            self.sync_panel.set_video_path(self.video_player.video_path)

    def import_lfp(self):
        path = self.open_csv_file("Import LFP (.csv)")
        if path:
            self.lfp_info = csv_func.parse_lfp_csv_info(path)
            self.lfp_panel.set_lfp_info(self.lfp_info)
            self.sync_panel.set_lfp_status(f"LFP file: {self.lfp_info['filename']}")
            self.update_waveform_current_time(
                self.video_player.current_frame,
                self.video_player.current_time_sec(),
            )

    def import_axis(self):
        path = self.open_csv_file("Import 3-axis (.csv)")
        if path:
            self.axis_info = csv_func.parse_lfp_csv_info(path)
            self.lfp_panel.set_axis_info(self.axis_info)
            self.update_waveform_current_time(
                self.video_player.current_frame,
                self.video_player.current_time_sec(),
            )

    def import_time_marker(self):
        path = self.open_csv_file("Import Time Marker (.csv)")
        if not path:
            return

        self.timeMarker_info = csv_func.parse_time_marker_csv_info(path)
        self.set_ttl_markers(self.timeMarker_info)
        self.ttl_panel.set_markers(self.timeMarker_info)
        self.show_marker_panel()

    def export_markers_csv(self):
        self.export_markers("csv")

    def export_markers_excel(self):
        self.export_markers("xlsx")

    def export_markers(self, file_type):
        events = self.event_table.events()
        if not events:
            QMessageBox.information(
                self, "No markers", "There are no markers to export."
            )
            return

        if file_type == "csv":
            title = "Export Markers as CSV"
            default_name = "video_markers.csv"
            file_filter = "CSV Files (*.csv)"
            export_func = export_events_csv
        else:
            title = "Export Markers as Excel"
            default_name = "video_markers.xlsx"
            file_filter = "Excel Files (*.xlsx)"
            export_func = export_events_excel

        path, _ = QFileDialog.getSaveFileName(self, title, default_name, file_filter)

        if path:
            export_func(path, events)

    def signal_exports(self):
        exports = []
        if self.lfp_info is not None:
            exports.append(("LFP", self.lfp_info))
        if self.axis_info is not None:
            exports.append(("3-axis", self.axis_info))
        return exports

    def choose_signal_export(self, title):
        exports = self.signal_exports()
        if not exports:
            QMessageBox.information(
                self,
                "No signal data",
                "Please import LFP or 3-axis CSV data first.",
            )
            return None

        if len(exports) == 1:
            return exports[0]

        items = [label for label, _ in exports]
        label, accepted = QInputDialog.getItem(
            self,
            title,
            "Data:",
            items,
            0,
            False,
        )
        if not accepted:
            return None

        return exports[items.index(label)]

    def export_check_results(self):
        selected = self.choose_signal_export("Export Check Results")
        if selected is None:
            return

        label, info = selected
        filename = info.get("filename", label).rsplit(".", 1)[0]
        default_name = f"{filename}_check_report.csv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Check Results",
            default_name,
            "CSV Files (*.csv)",
        )
        if not path:
            return

        try:
            output_path = check.check(info=info, output_path=path)
        except Exception as error:
            QMessageBox.warning(self, "Export check results failed", str(error))
            return

        QMessageBox.information(
            self,
            "Check Results Exported",
            f"Check results exported to:\n{output_path}",
        )

    def export_waveform_image(self):
        selected = self.choose_signal_export("Export Waveform Image")
        if selected is None:
            return

        label, info = selected
        channel = None
        if label == "LFP":
            channels = [int(channel) for channel in info.get("channels", [])]
            if not channels:
                QMessageBox.warning(
                    self,
                    "No LFP channels",
                    "The imported LFP CSV does not list available channels.",
                )
                return

            channel_items = [f"Channel {channel}" for channel in channels]
            channel_text, accepted = QInputDialog.getItem(
                self,
                "Export LFP Waveform Image",
                "Channel:",
                channel_items,
                0,
                False,
            )
            if not accepted:
                return

            channel = channels[channel_items.index(channel_text)]
            filename = info.get("filename", "lfp").rsplit(".", 1)[0]
            default_name = f"{filename}_channel_{channel}.png"
        else:
            filename = info.get("filename", "axis").rsplit(".", 1)[0]
            default_name = f"{filename}_waveform.png"

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Waveform Image",
            default_name,
            "PNG Images (*.png);;PDF Files (*.pdf);;SVG Files (*.svg);;All Files (*)",
        )
        if not path:
            return

        try:
            if label == "LFP":
                fig = draw.LFP(
                    info=info,
                    channels=channel,
                    step=self.lfp_panel.lfp_step,
                )
            else:
                fig = draw.accelerator(
                    info=info,
                    compact=False,
                    step=self.lfp_panel.axis_step,
                )
            fig.savefig(path, dpi=300)
        except Exception as error:
            QMessageBox.warning(self, "Export waveform image failed", str(error))
            return

        QMessageBox.information(
            self,
            "Waveform Image Exported",
            f"Waveform image exported to:\n{path}",
        )
