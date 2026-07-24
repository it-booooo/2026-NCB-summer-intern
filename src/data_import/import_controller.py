import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
)

from .. import signal_data
from ..led_detection import LedBrightnessPoint
from ..markers import (
    MarkerSource,
    marker_from_dict,
    marker_from_legacy_event,
    marker_from_legacy_ttl,
)
from ..project_format import file_fingerprint, validate_manifest, validate_state
from ..video_player.video_helpers import normalize_rotation_degrees


@dataclass
class ImportContext:
    """Explicit UI and workflow dependencies used by imports."""

    parent: object
    marker_store: object
    video_player: object
    event_table: object
    lfp_panel: object
    ttl_panel: object
    led_analysis_panel: object
    project_controller: object
    sync_controller: object
    led_controller: object


class ImportController:
    """Own all file-selection and import workflows for the main window."""

    SIGNAL_IMPORT_TITLES = {
        "lfp": "Import LFP (.csv)",
        "axis": "Import 3-axis (.csv)",
    }
    PROJECT_SOURCE_DIALOGS = {
        "video": ("Locate Project Video", "Video Files (*.mp4);;All Files (*)"),
        "lfp": ("Locate Project LFP File", "CSV Files (*.csv);;All Files (*)"),
        "axis": ("Locate Project 3-axis File", "CSV Files (*.csv);;All Files (*)"),
        "ttl": ("Locate Project TTL File", "CSV Files (*.csv);;All Files (*)"),
    }

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

    def open_project(self):
        """Open a project archive and restore its referenced and bundled data."""
        context = self.context
        if not context.project_controller.confirm_unsaved_changes(
            "open another project"
        ):
            return
        if not context.led_controller.stop_led_detection(wait=True):
            QMessageBox.information(
                self.parent,
                "LED detection",
                "LED detection is still stopping. Please try again in a moment.",
            )
            return

        path, _ = QFileDialog.getOpenFileName(
            self.parent,
            "Open Project",
            "",
            "Pig Analysis Project (*.pigproj)",
        )
        if not path:
            return

        project_root = Path(tempfile.mkdtemp(prefix="pigproj_"))
        progress = None
        try:
            with ZipFile(path, "r") as archive:
                manifest = json.loads(archive.read("manifest.json"))
                state = json.loads(archive.read("state.json"))
                if manifest.get("format") != "pig-analysis-project":
                    raise ValueError("This is not a Pig Analysis Project file.")
                if manifest.get("version") not in (1, 2, 3):
                    raise ValueError(
                        f"Unsupported project version: {manifest.get('version')}"
                    )
                if manifest.get("version") == 3:
                    validate_manifest(manifest)
                    state = validate_state(state)

                source_paths = {}
                source_items = list(manifest.get("sources", {}).items())
                total_source_bytes = sum(
                    archive.getinfo(source.get("archive_path", "")).file_size
                    for _source_type, source in source_items
                    if source.get("archive_path", "") in archive.namelist()
                )
                completed_source_bytes = 0
                progress = QDialog(self.parent)
                progress.setWindowTitle("Open Project")
                progress.setWindowModality(Qt.WindowModality.WindowModal)
                progress.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
                progress.setFixedSize(480, 140)
                progress_label = QLabel("Reading project...")
                progress_bar = QProgressBar()
                progress_bar.setRange(0, 100)
                progress_bar.setValue(0)
                progress_layout = QVBoxLayout(progress)
                progress_layout.addWidget(progress_label)
                progress_layout.addWidget(progress_bar)
                progress.show()
                progress.repaint()

                for source_type, source in source_items:
                    external_path = source.get("external_path")
                    if external_path:
                        source_path = Path(external_path)
                        if not source_path.is_file():
                            title, file_filter = self.PROJECT_SOURCE_DIALOGS.get(
                                source_type,
                                ("Locate Project Source File", "All Files (*)"),
                            )
                            selected_path, _ = QFileDialog.getOpenFileName(
                                self.parent,
                                title,
                                str(source_path.parent),
                                file_filter,
                            )
                            if not selected_path:
                                raise ValueError(
                                    f"The project {source_type} source could not be found. "
                                    "Select the original file to continue."
                                )
                            source_path = Path(selected_path)
                        expected = source.get("fingerprint")
                        if expected is not None and file_fingerprint(source_path) != expected:
                            raise ValueError(
                                f"The selected {source_type} file is not the original project source."
                            )
                        source_paths[source_type] = str(source_path.resolve())
                        continue
                    archive_path = source.get("archive_path", "")
                    if archive_path not in archive.namelist():
                        raise ValueError(
                            f"Project source is missing: {source_type}"
                        )
                    filename = Path(source.get("filename", "")).name
                    if not filename:
                        raise ValueError(
                            f"Project source filename is invalid: {source_type}"
                        )
                    destination = project_root / source_type / filename
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(archive_path) as source_file:
                        with destination.open("wb") as output_file:
                            while True:
                                chunk = source_file.read(4 * 1024 * 1024)
                                if not chunk:
                                    break
                                output_file.write(chunk)
                                completed_source_bytes += len(chunk)
                                progress_label.setText(
                                    f"Extracting {source_type} data..."
                                )
                                progress_bar.setValue(
                                    min(
                                        int(
                                            completed_source_bytes
                                            * 70
                                            / max(total_source_bytes, 1)
                                        ),
                                        70,
                                    )
                                )
                                progress_label.repaint()
                                progress_bar.repaint()
                    source_paths[source_type] = str(destination)
                progress_bar.setValue(70)
                progress_bar.repaint()
        except (BadZipFile, KeyError, OSError, ValueError, json.JSONDecodeError) as error:
            shutil.rmtree(project_root, ignore_errors=True)
            if progress is not None:
                progress.close()
            QMessageBox.warning(
                self.parent, "Open project failed", str(error)
            )
            return

        try:
            progress_label.setText("Restoring analysis settings...")
            progress_bar.setValue(72)
            progress_label.repaint()
            progress_bar.repaint()
            data = state.get("data", {})
            self.data_state.lfp_step = data.get("lfp_step")
            self.data_state.axis_step = data.get("axis_step")
            self.data_state.line_noise_hz = float(data.get("line_noise_hz", 60.0))
            timeline_xlim = data.get("timeline_xlim")
            restored_timeline_xlim = (
                tuple(float(value) for value in timeline_xlim)
                if timeline_xlim is not None
                else None
            )
            self.data_state.timeline_xlim = restored_timeline_xlim
            selected_channel = data.get("selected_lfp_channel")
            self.data_state.selected_lfp_channel = (
                int(selected_channel) if selected_channel is not None else None
            )
            self.data_state.lfp_filter_settings = dict(
                data.get("lfp_filter_settings", {})
            )
            self.data_state.follow_video_playback = bool(
                data.get("follow_video_playback", True)
            )
            analysis = state.get("analysis", {})
            self.app_state.analysis.lfp_peak_height_sigma = float(
                analysis.get(
                    "lfp_peak_height_sigma",
                    self.app_state.analysis.lfp_peak_height_sigma,
                )
            )
            self.app_state.analysis.lfp_peak_prominence_sigma = float(
                analysis.get(
                    "lfp_peak_prominence_sigma",
                    self.app_state.analysis.lfp_peak_prominence_sigma,
                )
            )
            self.app_state.analysis.lfp_peak_min_distance_sec = float(
                analysis.get(
                    "lfp_peak_min_distance_sec",
                    self.app_state.analysis.lfp_peak_min_distance_sec,
                )
            )
            context.lfp_panel.apply_project_state()

            video_path = source_paths.get("video")
            if video_path:
                progress_label.setText("Loading video...")
                progress_bar.setValue(75)
                progress_label.repaint()
                progress_bar.repaint()
                self.sync_state.loading_video = True
                try:
                    if not context.video_player.load_video(video_path):
                        raise ValueError("The bundled video could not be loaded.")
                finally:
                    self.sync_state.loading_video = False
                self.led_state.brightness_cache.clear()
                context.sync_controller.reset_sync_state_for_new_video()
                context.event_table.set_video_timing(
                    self.video_state.metadata.using_fps,
                    self.video_state.metadata.total_frames,
                )

            lfp_path = source_paths.get("lfp")
            if lfp_path:
                progress_label.setText("Loading LFP waveform...")
                progress_bar.setValue(82)
                progress_label.repaint()
                progress_bar.repaint()
                info = signal_data.parse_lfp_csv_info(lfp_path)
                self.data_state.lfp_info = info
                context.lfp_panel.set_lfp_info(info)

            axis_path = source_paths.get("axis")
            if axis_path:
                progress_label.setText("Loading 3-axis waveform...")
                progress_bar.setValue(87)
                progress_label.repaint()
                progress_bar.repaint()
                info = signal_data.parse_lfp_csv_info(axis_path)
                self.data_state.axis_info = info
                context.lfp_panel.set_axis_info(info)

            progress_label.setText("Restoring TTL and video markers...")
            progress_bar.setValue(90)
            progress_label.repaint()
            progress_bar.repaint()
            if manifest.get("version") == 3:
                restored_markers = [
                    marker_from_dict(item) for item in state.get("markers", [])
                ]
                ttl_metadata = dict(state.get("ttl", {}).get("metadata") or {})
            else:
                legacy_offset = state.get("sync", {}).get("time_offset_sec")
                restored_markers = [
                    marker_from_legacy_event(item, offset_sec=legacy_offset)
                    for item in state.get("events", [])
                ]
                saved_ttl_info = state.get("sync", {}).get("time_marker_info") or {}
                restored_markers.extend(
                    marker_from_legacy_ttl(item)
                    for item in saved_ttl_info.get("markers", [])
                )
                ttl_metadata = {
                    "filename": saved_ttl_info.get("filename") or "Project TTL",
                    "time_column_name": saved_ttl_info.get("time_column_name"),
                }
            if source_paths.get("ttl"):
                ttl_metadata["path"] = source_paths["ttl"]
            self.ttl_state.metadata = ttl_metadata or None
            self.marker_store.replace_all(restored_markers)

            led = state.get("led", {})
            progress_label.setText("Restoring LED ROI and analysis...")
            progress_bar.setValue(94)
            progress_label.repaint()
            progress_bar.repaint()
            roi = led.get("roi")
            if roi is not None:
                restored_roi = tuple(int(value) for value in roi)
                self.led_state.roi = restored_roi
                context.video_player.set_led_roi(restored_roi)
                context.led_analysis_panel.set_led_roi(restored_roi)

            analysis_points = [
                LedBrightnessPoint(**point)
                for point in led.get("analysis_points") or []
            ]
            detected_markers = self.marker_store.by_source(MarkerSource.LED_DETECTION)
            if led.get("analysis_status") is not None:
                context.led_analysis_panel.set_led_analysis(
                    analysis_points,
                    led.get("analysis_threshold", 0.0),
                    detected_markers,
                    stats=led.get("analysis_stats") or {},
                    status=led.get("analysis_status"),
                )
                context.led_analysis_panel.set_led_detection_status(
                    "LED detection: restored from project."
                )

            if video_path and self.video_state.metadata is not None:
                for cache in led.get("brightness_cache", []):
                    cache_roi = cache.get("roi")
                    rotation_degrees = cache.get("rotation_degrees")
                    if rotation_degrees is None:
                        rotation_degrees = 180 if cache.get("rotate_180", False) else 0
                    cache_key = (
                        video_path,
                        tuple(cache_roi) if cache_roi is not None else None,
                        int(rotation_degrees),
                        float(cache.get("fps", 0.0)),
                        int(cache.get("start_frame", 0)),
                        int(cache.get("end_frame", 0)),
                        int(cache.get("coarse_step", 1)),
                    )
                    self.led_state.brightness_cache[cache_key] = [
                        LedBrightnessPoint(**point)
                        for point in cache.get("points", [])
                    ]

                video = state.get("video", {})
                rotation_degrees = video.get("rotation_degrees")
                if rotation_degrees is None:
                    rotation_degrees = 180 if video.get("rotate_180_enabled", False) else 0
                rotation_degrees = normalize_rotation_degrees(rotation_degrees)
                self.video_state.rotation_degrees = rotation_degrees
                self.video_state.rotate_180_enabled = rotation_degrees == 180
                context.video_player.update_rotation_buttons()
                context.video_player.seek_frame(int(video.get("current_frame", 0)))

            if restored_timeline_xlim is not None:
                context.lfp_panel.set_shared_xlim(
                    *restored_timeline_xlim,
                    source="timeline",
                )
            context.sync_controller.update_waveform_current_time()
            progress_label.setText("Project restored.")
            progress_bar.setValue(100)
            progress_label.repaint()
            progress_bar.repaint()
        except Exception as error:
            if context.video_player.cap is not None:
                context.video_player.cap.release()
                context.video_player.cap = None
            shutil.rmtree(project_root, ignore_errors=True)
            progress.close()
            QMessageBox.warning(
                self.parent, "Restore project failed", str(error)
            )
            return

        context.project_controller.replace_temp_directory(project_root)
        self.app_state.project.path = str(Path(path).resolve())
        self.app_state.project.dirty = False
        context.project_controller.update_title()
        progress.close()
        QMessageBox.information(
            self.parent,
            "Project Opened",
            f"Project restored from:\n{path}",
        )

    def actions(self):
        """Create and return the actions exposed by this controller.

        Args:
            None.
        """
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
        """Open csv file.

        Args:
            title: Dialog title displayed to the user.
        """
        path, _ = QFileDialog.getOpenFileName(
            self.parent, title, "", "CSV Files (*.csv);;All Files (*)"
        )
        return path

    def import_video(self):
        """Provide import video functionality.

        Args:
            None.
        """
        context = self.context
        if not context.led_controller.stop_led_detection(wait=True):
            QMessageBox.information(
                self.parent, "LED detection",
                "LED detection is still stopping. Please try again in a moment.",
            )
            return

        path, _ = QFileDialog.getOpenFileName(
            self.parent, "Open MP4", "", "Video Files (*.mp4)"
        )
        if not path:
            return

        self.sync_state.loading_video = True
        try:
            loaded = context.video_player.load_video(path)
        finally:
            self.sync_state.loading_video = False

        if loaded:
            self.led_state.brightness_cache.clear()
            context.sync_controller.reset_sync_state_for_new_video()
            context.event_table.set_video_timing(
                self.video_state.metadata.using_fps,
                self.video_state.metadata.total_frames,
            )
            context.project_controller.mark_dirty()

    def import_signal(self, signal_type):
        """Import an LFP or 3-axis CSV through the shared signal workflow."""
        context = self.context
        path = self.open_csv_file(self.SIGNAL_IMPORT_TITLES[signal_type])
        if not path:
            return

        info = signal_data.parse_lfp_csv_info(path)
        if signal_type == "lfp":
            self.data_state.lfp_info = info
            context.lfp_panel.set_lfp_info(info)
        else:
            self.data_state.axis_info = info
            context.lfp_panel.set_axis_info(info)

        context.sync_controller.update_waveform_current_time()
        context.project_controller.mark_dirty()

    def import_time_marker(self):
        """Provide import time marker functionality.

        Args:
            None.
        """
        context = self.context
        path = self.open_csv_file("Import Time Marker (.csv)")
        if not path:
            return
        info = signal_data.parse_time_marker_csv_info(path)
        markers = [marker_from_legacy_ttl(item) for item in info.get("markers", [])]
        metadata = {
            key: value
            for key, value in info.items()
            if key not in {"markers", "marker_count", "first_marker_sec"}
        }
        context.ttl_panel.set_markers(markers, metadata=metadata)
        context.project_controller.mark_dirty()
