import json
import shutil
import tempfile
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from PySide6.QtWidgets import (
    QFileDialog,
    QMessageBox,
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

    def __init__(self, window, app_state):
        self.window = window
        self.app_state = app_state
        self.video_state = self.app_state.video
        self.data_state = self.app_state.data
        self.sync_state = self.app_state.sync
        self.ttl_state = self.app_state.ttl
        self.led_state = self.app_state.led
        self.marker_store = window.marker_store

    def open_project(self):
        """Open a project archive and restore its referenced and bundled data."""
        window = self.window
        if not window.confirm_unsaved_changes("open another project"):
            return
        if not window.stop_led_detection(wait=True):
            QMessageBox.information(
                window,
                "LED detection",
                "LED detection is still stopping. Please try again in a moment.",
            )
            return

        path, _ = QFileDialog.getOpenFileName(
            window,
            "Open Project",
            "",
            "Pig Analysis Project (*.pigproj)",
        )
        if not path:
            return

        project_root = Path(tempfile.mkdtemp(prefix="pigproj_"))
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
                                window,
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
                    source_paths[source_type] = str(destination)
        except (BadZipFile, KeyError, OSError, ValueError, json.JSONDecodeError) as error:
            shutil.rmtree(project_root, ignore_errors=True)
            QMessageBox.warning(window, "Open project failed", str(error))
            return

        try:
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
            window.lfp_panel.apply_project_state()

            video_path = source_paths.get("video")
            if video_path:
                self.sync_state.loading_video = True
                try:
                    if not window.video_player.load_video(video_path):
                        raise ValueError("The bundled video could not be loaded.")
                finally:
                    self.sync_state.loading_video = False
                self.led_state.brightness_cache.clear()
                window.reset_sync_state_for_new_video()
                window.event_table.set_video_timing(
                    self.video_state.metadata.using_fps,
                    self.video_state.metadata.total_frames,
                )

            lfp_path = source_paths.get("lfp")
            if lfp_path:
                info = signal_data.parse_lfp_csv_info(lfp_path)
                self.data_state.lfp_info = info
                window.lfp_panel.set_lfp_info(info)

            axis_path = source_paths.get("axis")
            if axis_path:
                info = signal_data.parse_lfp_csv_info(axis_path)
                self.data_state.axis_info = info
                window.lfp_panel.set_axis_info(info)

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
            roi = led.get("roi")
            if roi is not None:
                restored_roi = tuple(int(value) for value in roi)
                self.led_state.roi = restored_roi
                window.video_player.set_led_roi(restored_roi)
                window.led_analysis_panel.set_led_roi(restored_roi)

            analysis_points = [
                LedBrightnessPoint(**point)
                for point in led.get("analysis_points") or []
            ]
            detected_markers = self.marker_store.by_source(MarkerSource.LED_DETECTION)
            if led.get("analysis_status") is not None:
                window.led_analysis_panel.set_led_analysis(
                    analysis_points,
                    led.get("analysis_threshold", 0.0),
                    detected_markers,
                    stats=led.get("analysis_stats") or {},
                    status=led.get("analysis_status"),
                )
                window.led_analysis_panel.set_led_detection_status(
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
                window.video_player.update_rotation_buttons()
                window.video_player.seek_frame(int(video.get("current_frame", 0)))

            if restored_timeline_xlim is not None:
                window.lfp_panel.set_shared_xlim(
                    *restored_timeline_xlim,
                    source="timeline",
                )
            window.update_waveform_current_time()
        except Exception as error:
            if window.video_player.cap is not None:
                window.video_player.cap.release()
                window.video_player.cap = None
            shutil.rmtree(project_root, ignore_errors=True)
            QMessageBox.warning(window, "Restore project failed", str(error))
            return

        previous_directory = getattr(window, "project_temp_directory", None)
        window.project_temp_directory = project_root
        self.app_state.project.path = str(Path(path).resolve())
        self.app_state.project.dirty = False
        window.update_project_title()
        if previous_directory is not None:
            shutil.rmtree(previous_directory, ignore_errors=True)
        QMessageBox.information(
            window,
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
            self.window, title, "", "CSV Files (*.csv);;All Files (*)"
        )
        return path

    def import_video(self):
        """Provide import video functionality.

        Args:
            None.
        """
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

        self.sync_state.loading_video = True
        try:
            loaded = window.video_player.load_video(path)
        finally:
            self.sync_state.loading_video = False

        if loaded:
            self.led_state.brightness_cache.clear()
            window.reset_sync_state_for_new_video()
            window.event_table.set_video_timing(
                self.video_state.metadata.using_fps,
                self.video_state.metadata.total_frames,
            )
            window.mark_project_dirty()

    def import_signal(self, signal_type):
        """Import an LFP or 3-axis CSV through the shared signal workflow."""
        window = self.window
        path = self.open_csv_file(self.SIGNAL_IMPORT_TITLES[signal_type])
        if not path:
            return

        info = signal_data.parse_lfp_csv_info(path)
        if signal_type == "lfp":
            self.data_state.lfp_info = info
            window.lfp_panel.set_lfp_info(info)
        else:
            self.data_state.axis_info = info
            window.lfp_panel.set_axis_info(info)

        window.update_waveform_current_time()
        window.mark_project_dirty()

    def import_time_marker(self):
        """Provide import time marker functionality.

        Args:
            None.
        """
        window = self.window
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
        window.ttl_panel.set_markers(markers, metadata=metadata)
        window.sync_panel.show_panel("TTL")
        window.mark_project_dirty()
