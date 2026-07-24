import json
import tempfile
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
)

from .. import charts, signal_data, data_validation
from ..project_format import PROJECT_FORMAT, PROJECT_VERSION, file_fingerprint
from ..markers import (
    MarkerKind,
    VideoPosition,
    marker_to_dict,
    marker_video_time,
)
from .lfp_image_dialog import LfpImageExportDialog
from .file_writers import (
    export_events_csv,
    export_events_excel,
    export_ttl_markers_csv,
    export_ttl_markers_excel,
)


@dataclass
class ExportContext:
    """Explicit UI and workflow dependencies used by exports."""

    parent: object
    marker_store: object
    lfp_panel: object
    led_controller: object
    project_controller: object


class ExportController:
    """Own all save dialogs, export validation, and output generation."""

    def __init__(self, context, app_state):
        self.context = context
        self.parent = context.parent
        self.app_state = app_state
        self.video_state = self.app_state.video
        self.data_state = self.app_state.data
        self.sync_state = self.app_state.sync
        self.ttl_state = self.app_state.ttl
        self.led_state = self.app_state.led
        self.marker_store = context.marker_store
        self.last_lfp_export_directory = None

    def save_project(self):
        """Save project state while referencing every source file by path."""
        worker = self.context.led_controller.led_worker
        if worker is not None and worker.isRunning():
            QMessageBox.information(
                self.parent,
                "LED detection is running",
                "Wait for LED detection to finish before saving the project.",
            )
            return False

        path, _ = QFileDialog.getSaveFileName(
            self.parent,
            "Save Project",
            "analysis.pigproj",
            "Pig Analysis Project (*.pigproj)",
        )
        if not path:
            return False
        output_path = Path(path)
        if output_path.suffix.lower() != ".pigproj":
            output_path = output_path.with_suffix(".pigproj")

        sources = {}
        source_candidates = {
            "video": (
                self.video_state.metadata.path
                if self.video_state.metadata is not None
                else None
            ),
            "lfp": (
                self.data_state.lfp_info.get("path")
                if self.data_state.lfp_info
                else None
            ),
            "axis": (
                self.data_state.axis_info.get("path")
                if self.data_state.axis_info
                else None
            ),
            "ttl": (
                self.ttl_state.metadata.get("path")
                if self.ttl_state.metadata
                else None
            ),
        }
        for source_type, source_path in source_candidates.items():
            if not source_path:
                continue
            file_path = Path(source_path)
            if not file_path.is_file():
                QMessageBox.warning(
                    self.parent,
                    "Cannot save project",
                    f"Source file not found:\n{file_path}",
                )
                return False
            sources[source_type] = {
                "external_path": str(file_path.resolve()),
                "filename": file_path.name,
                "fingerprint": file_fingerprint(file_path),
            }

        def record(value):
            if is_dataclass(value):
                return asdict(value)
            if isinstance(value, datetime):
                return value.isoformat()
            if hasattr(value, "item"):
                return value.item()
            if hasattr(value, "tolist"):
                return value.tolist()
            raise TypeError(f"Unsupported project value: {type(value).__name__}")

        brightness_cache = []
        for cache_key, points in self.led_state.brightness_cache.items():
            (
                _video_path,
                roi,
                rotation_degrees,
                fps,
                start_frame,
                end_frame,
                coarse_step,
            ) = cache_key
            if isinstance(rotation_degrees, bool):
                rotation_degrees = 180 if rotation_degrees else 0
            brightness_cache.append(
                {
                    "roi": roi,
                    "rotation_degrees": rotation_degrees,
                    "rotate_180": int(rotation_degrees) == 180,
                    "fps": fps,
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                    "coarse_step": coarse_step,
                    "points": points,
                }
            )

        state = {
            "video": {
                "current_frame": self.video_state.current_frame,
                "rotation_degrees": self.video_state.rotation_degrees,
                "rotate_180_enabled": self.video_state.rotate_180_enabled,
            },
            "data": {
                "lfp_step": self.data_state.lfp_step,
                "axis_step": self.data_state.axis_step,
                "line_noise_hz": self.data_state.line_noise_hz,
                "timeline_xlim": self.data_state.timeline_xlim,
                "selected_lfp_channel": self.data_state.selected_lfp_channel,
                "lfp_filter_settings": self.data_state.lfp_filter_settings,
                "follow_video_playback": self.data_state.follow_video_playback,
            },
            "analysis": {
                "lfp_peak_height_sigma": (
                    self.app_state.analysis.lfp_peak_height_sigma
                ),
                "lfp_peak_prominence_sigma": (
                    self.app_state.analysis.lfp_peak_prominence_sigma
                ),
                "lfp_peak_min_distance_sec": (
                    self.app_state.analysis.lfp_peak_min_distance_sec
                ),
            },
            "sync": {
                "time_offset_sec": self.sync_state.time_offset_sec,
                "video_time_origin_sec": self.sync_state.video_time_origin_sec,
                "record_time_origin_sec": self.sync_state.record_time_origin_sec,
            },
            "ttl": {"metadata": dict(self.ttl_state.metadata or {})},
            "led": {
                "roi": self.led_state.roi,
                "analysis_points": self.led_state.analysis_points,
                "analysis_threshold": self.led_state.analysis_threshold,
                "analysis_stats": self.led_state.analysis_stats,
                "analysis_status": self.led_state.analysis_status,
                "brightness_cache": brightness_cache,
            },
            "markers": [marker_to_dict(marker) for marker in self.marker_store.all()],
        }
        manifest = {
            "format": PROJECT_FORMAT,
            "version": PROJECT_VERSION,
            "sources": sources,
        }

        progress = QDialog(self.parent)
        progress.setWindowTitle("Save Project")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        progress.setFixedSize(480, 140)
        progress_label = QLabel("Preparing project...")
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(0)
        progress_layout = QVBoxLayout(progress)
        progress_layout.addWidget(progress_label)
        progress_layout.addWidget(progress_bar)
        progress.show()
        progress.repaint()

        temporary_path = None
        try:
            manifest_bytes = json.dumps(
                manifest,
                indent=2,
                ensure_ascii=False,
            ).encode("utf-8")
            state_bytes = json.dumps(
                state,
                indent=2,
                ensure_ascii=False,
                default=record,
            ).encode("utf-8")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                prefix=f"{output_path.name}.",
                suffix=".tmp",
                dir=output_path.parent,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)

            with ZipFile(temporary_path, "w", allowZip64=True) as archive:
                archive.writestr(
                    "manifest.json",
                    manifest_bytes,
                    compress_type=ZIP_DEFLATED,
                )
                progress_label.setText("Writing project information...")
                progress_bar.setValue(45)
                progress_label.repaint()
                progress_bar.repaint()
                archive.writestr(
                    "state.json",
                    state_bytes,
                    compress_type=ZIP_DEFLATED,
                )
                progress_label.setText("Writing analysis state...")
                progress_bar.setValue(95)
                progress_label.repaint()
                progress_bar.repaint()
            temporary_path.replace(output_path)
            temporary_path = None
            progress_bar.setValue(100)
            progress_bar.repaint()
        except Exception as error:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            progress.close()
            QMessageBox.warning(
                self.parent,
                "Save project failed",
                str(error),
            )
            return False
        finally:
            progress.close()

        QMessageBox.information(
            self.parent,
            "Project Saved",
            f"Project saved to:\n{output_path}",
        )
        self.app_state.project.path = str(output_path.resolve())
        self.app_state.project.dirty = False
        self.context.project_controller.update_title()
        return True

    def actions(self):
        # 第三個欄位是顯示給使用者的英文滑鼠懸停說明。
        """Create and return the actions exposed by this controller.

        Args:
            None.
        """
        return [
            (
                "Export Markers...",
                self.export_markers,
                "Choose TTL or video markers and export them as CSV or Excel.",
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

    def export_markers(self):
        # UI 流程只負責選擇格式與路徑；實際寫檔由 writers 模組處理。
        """Choose a marker source and file type, then export it."""
        dialog = QDialog(self.parent)
        dialog.setWindowTitle("Export Markers")
        dialog.setMinimumWidth(340)

        marker_selector = QComboBox()
        marker_selector.addItem("Video markers", "video")
        marker_selector.addItem("TTL markers", "ttl")

        file_type_selector = QComboBox()
        file_type_selector.addItem("CSV (.csv)", "csv")
        file_type_selector.addItem("Excel (.xlsx)", "xlsx")

        form = QFormLayout()
        form.addRow("Markers", marker_selector)
        form.addRow("File type", file_type_selector)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Export")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        dialog.setLayout(layout)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        marker_type = marker_selector.currentData()
        file_type = file_type_selector.currentData()
        if marker_type == "video":
            markers = []
            for marker in self.marker_store.all():
                if marker.kind == MarkerKind.TTL:
                    continue
                video_time = marker_video_time(marker, self.sync_state.time_offset_sec)
                if video_time is None:
                    continue
                frame_index = (
                    marker.position.frame_index
                    if isinstance(marker.position, VideoPosition)
                    else int(
                        marker.payload.get(
                            "frame_index",
                            round(
                                video_time
                                * float(self.video_state.metadata.using_fps or 0.0)
                            ),
                        )
                    )
                )
                markers.append(
                    {
                        "event_type": marker.kind.value,
                        "video_time_sec": video_time,
                        "frame_index": frame_index,
                        "note": marker.note,
                    }
                )
            filename_stem = "video_markers"
            writer = (
                export_events_csv
                if file_type == "csv"
                else export_events_excel
            )
        else:
            markers = []
            for marker in self.marker_store.by_kind(MarkerKind.TTL):
                record_time = int(
                    marker.payload.get(
                        "record_time_us", round(marker.position.time_sec * 1_000_000)
                    )
                )
                markers.append({"record_time": record_time, **marker.payload})
            filename_stem = "ttl_markers"
            writer = (
                export_ttl_markers_csv
                if file_type == "csv"
                else export_ttl_markers_excel
            )

        if not markers:
            QMessageBox.information(
                self.parent, "No markers", "There are no markers to export."
            )
            return

        is_csv = file_type == "csv"
        suffix = "csv" if is_csv else "xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self.parent,
            "Export Markers as CSV" if is_csv else "Export Markers as Excel",
            f"{filename_stem}.{suffix}",
            "CSV Files (*.csv)" if is_csv else "Excel Files (*.xlsx)",
        )
        if path:
            writer(path, markers)


    def export_check_results(self):
        """Export check results.

        Args:
            None.
        """
        exports = []

        if self.data_state.lfp_info is not None:
            exports.append(("LFP", self.data_state.lfp_info))

        if self.data_state.axis_info is not None:
            exports.append(("3-axis", self.data_state.axis_info))

        if not exports:
            QMessageBox.information(
                self.parent,
                "No signal data",
                "Please import LFP or 3-axis CSV data first.",
            )
            return

        if len(exports) == 1:
            label, info = exports[0]
        else:
            items = [label for label, _ in exports]

            label, accepted = QInputDialog.getItem(
                self.parent,
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
            self.parent,
            "Export Check Results",
            f"{filename}_check_report.csv",
            "CSV Files (*.csv)",
        )

        if not path:
            return

        try:
            output_path = data_validation.check(
                info=info,
                output_path=path,
            )
        except Exception as error:
            QMessageBox.warning(
                self.parent,
                "Export check results failed",
                str(error),
            )
            return

        QMessageBox.information(
            self.parent,
            "Check Results Exported",
            f"Check results exported to:\n{output_path}",
        )

    def export_waveform_image(self):
        """Export waveform image.

        Args:
            None.
        """
        window = self.parent
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
            figure = charts.accelerator(
                info=self.data_state.axis_info,
                compact=False,
                step=self.data_state.axis_step,
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
        """Export lfp images.

        Args:
            None.
        """
        panel = self.context.lfp_panel
        lfp_path = self.data_state.lfp_info.get("path") if self.data_state.lfp_info else None
        if not lfp_path:
            QMessageBox.information(
                self.parent, "No LFP data", "Please import LFP CSV data first."
            )
            return

        default_directory = self.last_lfp_export_directory
        if default_directory is None or not Path(default_directory).is_dir():
            default_directory = Path(lfp_path).parent

        try:
            dialog = LfpImageExportDialog(
                panel,
                default_directory,
                parent=self.parent,
            )
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self.parent, "Cannot export LFP images", str(error)
            )
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
                self.parent,
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
                "Sync time" if panel.sync_state.record_time_origin_sec is not None else "Time"
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
                frequencies, power = signal_data.compute_power_spectrum(
                    segment.values,
                    segment.sample_rate_hz,
                )
                figures["power_spectrum"] = panel.create_power_spectrum_figure(
                    options.channel,
                    frequencies,
                    power,
                )

            if "spectrogram" in options.image_types:
                frequencies, times, power = signal_data.compute_time_frequency(
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
                self.parent,
                "Export LFP images failed",
                f"{error}{saved_message}",
            )
            return
        finally:
            for figure in figures.values():
                figure.clear()

        filenames = "\n".join(f"- {path.name}" for path in saved_paths)
        QMessageBox.information(
            self.parent,
            "LFP Images Exported",
            f"Exported {len(saved_paths)} image(s) to:\n"
            f"{options.directory}\n\n{filenames}",
        )

    def _lfp_filename(self, channel, settings, suffix):
        # 將通道、處理模式與同步後的時間範圍編入預設檔名，方便辨識輸出內容。
        panel = self.context.lfp_panel
        info = self.data_state.lfp_info
        filename = info.get("filename", "lfp") if info else "lfp"
        stem = filename.rsplit(".", 1)[0]
        mode = "processed" if settings.show_filtered else "raw"
        middle = f"_{suffix}" if suffix else ""
        return f"{stem}_channel_{channel}_{mode}{middle}.png"
