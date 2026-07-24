import json
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
from zipfile import BadZipFile, ZipFile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
)

from .. import signal_data
from ..led_detection import LedBrightnessPoint
from ..markers import (
    MarkerSource,
    marker_from_dict,
    marker_from_legacy_ttl,
)
from ..project_format import (
    MAX_MANIFEST_BYTES,
    MAX_STATE_BYTES,
    file_fingerprint,
    validate_manifest,
    validate_state,
    validate_video_bounds,
)
from ..video_player.video_helpers import (
    normalize_rotation_degrees,
    parse_video_metadata,
    read_frame,
)


@dataclass
class ImportContext:
    parent: object
    marker_store: object
    video_player: object
    event_table: object
    lfp_panel: object
    ttl_panel: object
    sync_panel: object
    led_analysis_panel: object
    project_controller: object
    sync_controller: object
    led_controller: object


class ImportController:
    """Own all file-selection and import workflows for the main window."""

    SIGNAL_IMPORT_TITLES: ClassVar[dict[str, str]] = {
        "lfp": "Import LFP (.csv)",
        "axis": "Import 3-axis (.csv)",
    }
    PROJECT_SOURCE_DIALOGS: ClassVar[dict[str, tuple[str, str]]] = {
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
        """Open a path-only project after every source has been validated."""
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

        error_title = None
        error_message = None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            staged = self.prepare_project_restore(path)
            self.apply_project_restore(path, staged)
        except (BadZipFile, KeyError, OSError, ValueError, json.JSONDecodeError) as error:
            error_title = "Open project failed"
            error_message = str(error)
        except Exception as error:
            error_title = "Restore project failed"
            error_message = str(error)
        finally:
            QApplication.restoreOverrideCursor()

        if error_message is not None:
            QMessageBox.warning(self.parent, error_title, error_message)
            return

        QMessageBox.information(
            self.parent,
            "Project Opened",
            f"Project restored from:\n{path}",
        )

    def read_project_json(self, archive, name, max_bytes):
        info = archive.getinfo(name)
        if info.file_size > max_bytes:
            raise ValueError(f"Project {name} is too large.")
        return json.loads(archive.read(name))

    def prepare_project_restore(self, path):
        with ZipFile(path, "r") as archive:
            manifest = self.read_project_json(
                archive,
                "manifest.json",
                MAX_MANIFEST_BYTES,
            )
            state = self.read_project_json(archive, "state.json", MAX_STATE_BYTES)

        sources = validate_manifest(manifest)
        state = validate_state(state)
        source_paths = self.resolve_project_sources(sources)

        video_metadata = self.prepare_video_source(source_paths.get("video"))
        if video_metadata is not None:
            validate_video_bounds(state, video_metadata)

        data = state.get("data", {})
        timeline_xlim = data.get("timeline_xlim")
        lfp_path = source_paths.get("lfp")
        axis_path = source_paths.get("axis")
        lfp_info = signal_data.parse_lfp_csv_info(lfp_path) if lfp_path else None
        axis_info = signal_data.parse_lfp_csv_info(axis_path) if axis_path else None
        led = state.get("led", {})
        roi = led.get("roi")

        return {
            "source_paths": source_paths,
            "data": data,
            "analysis": state.get("analysis", {}),
            "timeline_xlim": (
                tuple(float(value) for value in timeline_xlim)
                if timeline_xlim is not None
                else None
            ),
            "lfp_info": lfp_info,
            "axis_info": axis_info,
            "markers": [marker_from_dict(item) for item in state.get("markers", [])],
            "ttl_metadata": dict(state.get("ttl", {}).get("metadata") or {}),
            "led": led,
            "roi": tuple(int(value) for value in roi) if roi is not None else None,
            "analysis_points": [
                LedBrightnessPoint(**point)
                for point in led.get("analysis_points") or []
            ],
            "video": state.get("video", {}),
        }

    def resolve_project_sources(self, sources):
        source_paths = {}
        for source_type, source in sources.items():
            source_path = Path(source["external_path"])
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

            if file_fingerprint(source_path) != source["fingerprint"]:
                raise ValueError(
                    f"The selected {source_type} file is not the original project source."
                )
            source_paths[source_type] = str(source_path.resolve())
        return source_paths

    def prepare_video_source(self, video_path):
        if not video_path:
            return None

        import cv2

        cap = cv2.VideoCapture(video_path)
        try:
            metadata = parse_video_metadata(cap, video_path)
            success, first_frame = read_frame(cap, 0)
            if not success or first_frame is None:
                raise ValueError("The first video frame could not be decoded.")
            return metadata
        finally:
            cap.release()

    def apply_project_restore(self, path, staged):
        context = self.context
        self.app_state.project.loading = True
        try:
            source_paths = staged["source_paths"]
            video_path = source_paths.get("video")
            if video_path:
                self.sync_state.loading_video = True
                try:
                    if not context.video_player.load_video(video_path):
                        raise ValueError("The project video could not be loaded.")
                finally:
                    self.sync_state.loading_video = False
                self.led_state.brightness_cache.clear()
                context.sync_controller.reset_sync_state_for_new_video()
                context.event_table.set_video_timing(
                    self.video_state.metadata.using_fps,
                    self.video_state.metadata.total_frames,
                )

            data = staged["data"]
            self.data_state.lfp_step = data.get("lfp_step")
            self.data_state.axis_step = data.get("axis_step")
            self.data_state.line_noise_hz = float(data.get("line_noise_hz", 60.0))
            self.data_state.timeline_xlim = staged["timeline_xlim"]
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
            analysis = staged["analysis"]
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

            if staged["lfp_info"]:
                self.data_state.lfp_info = staged["lfp_info"]
                context.lfp_panel.set_lfp_info(staged["lfp_info"])

            if staged["axis_info"]:
                self.data_state.axis_info = staged["axis_info"]
                context.lfp_panel.set_axis_info(staged["axis_info"])

            ttl_metadata = dict(staged["ttl_metadata"])
            if source_paths.get("ttl"):
                ttl_metadata["path"] = source_paths["ttl"]
            self.ttl_state.metadata = ttl_metadata or None
            self.marker_store.replace_all(staged["markers"])

            led = staged["led"]
            if staged["roi"] is not None:
                self.led_state.roi = staged["roi"]
                context.video_player.set_led_roi(staged["roi"])
                context.led_analysis_panel.set_led_roi(staged["roi"])

            detected_markers = self.marker_store.by_source(MarkerSource.LED_DETECTION)
            if led.get("analysis_status") is not None:
                context.led_analysis_panel.set_led_analysis(
                    staged["analysis_points"],
                    led.get("analysis_threshold", 0.0),
                    detected_markers,
                    stats=led.get("analysis_stats") or {},
                    status=led.get("analysis_status"),
                )
                context.led_analysis_panel.set_led_detection_status(
                    "LED detection: restored from project."
                )

            if video_path and self.video_state.metadata is not None:
                self.restore_brightness_cache(video_path, led)
                rotation_degrees = staged["video"].get("rotation_degrees")
                if rotation_degrees is None:
                    rotation_degrees = (
                        180 if staged["video"].get("rotate_180_enabled", False) else 0
                    )
                rotation_degrees = normalize_rotation_degrees(rotation_degrees)
                self.video_state.rotation_degrees = rotation_degrees
                self.video_state.rotate_180_enabled = rotation_degrees == 180
                context.video_player.update_rotation_buttons()
                context.video_player.seek_frame(
                    int(staged["video"].get("current_frame", 0))
                )

            if staged["timeline_xlim"] is not None:
                context.lfp_panel.set_shared_xlim(
                    *staged["timeline_xlim"],
                    source="timeline",
                )
            context.sync_controller.update_waveform_current_time()

            self.app_state.project.path = str(Path(path).resolve())
            self.app_state.project.dirty = False
            context.project_controller.update_title()
        finally:
            self.sync_state.loading_video = False
            self.app_state.project.loading = False

    def restore_brightness_cache(self, video_path, led):
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
        context.sync_panel.show_panel("TTL")
        context.project_controller.mark_dirty()
