import json
from datetime import datetime
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
)

from .. import signal_data
from ..led_detection import LedBrightnessPoint, LedEvent
from ..project_format import (
    MAX_MANIFEST_BYTES,
    MAX_STATE_BYTES,
    file_fingerprint,
    validate_manifest,
    validate_state,
    validate_video_bounds,
)
from ..video_player.video_helpers import parse_video_metadata, read_frame


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
        self.led_state = self.app_state.led
        self.event_state = self.app_state.events

    def open_project(self):
        """Validate a path-only project completely before applying it."""
        window = self.window
        if not window.stop_led_detection(wait=True):
            QMessageBox.information(
                window,
                "LED detection",
                "LED detection is still stopping. Please try again in a moment.",
            )
            return
        if not window.confirm_unsaved_changes("open another project"):
            return

        path, _ = QFileDialog.getOpenFileName(
            window,
            "Open Project",
            "",
            "Pig Analysis Project (*.pigproj)",
        )
        if not path:
            return

        window.statusBar().showMessage("Opening project...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            with ZipFile(path, "r") as archive:
                names = set(archive.namelist())
                if (
                    names != {"manifest.json", "state.json"}
                    or len(archive.infolist()) != 2
                ):
                    raise ValueError(
                        "A path-only project must contain only manifest.json and state.json."
                    )
                manifest_info = archive.getinfo("manifest.json")
                state_info = archive.getinfo("state.json")
                if manifest_info.file_size > MAX_MANIFEST_BYTES:
                    raise ValueError("Project manifest is unexpectedly large.")
                if state_info.file_size > MAX_STATE_BYTES:
                    raise ValueError("Project state is too large to load safely.")
                manifest = json.loads(archive.read("manifest.json"))
                state = validate_state(json.loads(archive.read("state.json")))
                sources = validate_manifest(manifest)

                # Resolve and identify every source before changing AppState or widgets.
                source_paths = {}
                for source_type, source in sources.items():
                    source_path = Path(source["external_path"])
                    if not source_path.is_file():
                        title, file_filter = self.PROJECT_SOURCE_DIALOGS[source_type]
                        QApplication.restoreOverrideCursor()
                        window.statusBar().showMessage(
                            f"Locate the project {source_type} source file."
                        )
                        selected_path, _ = QFileDialog.getOpenFileName(
                            window,
                            title,
                            str(source_path.parent),
                            file_filter,
                        )
                        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                        window.statusBar().showMessage("Opening project...")
                        if not selected_path:
                            raise ValueError(
                                f"The project {source_type} source could not be found."
                            )
                        source_path = Path(selected_path)
                    if file_fingerprint(source_path) != source["fingerprint"]:
                        raise ValueError(
                            f"The selected {source_type} file is not the original project source."
                        )
                    source_paths[source_type] = str(source_path.resolve())

            # Prepare every source and persisted value without touching the live UI.
            prepared_video_metadata = None
            video_path = source_paths.get("video")
            if video_path:
                import cv2

                video_capture = cv2.VideoCapture(video_path)
                try:
                    prepared_video_metadata = parse_video_metadata(
                        video_capture, video_path
                    )
                    frame_ok, first_frame = read_frame(video_capture, 0)
                    if not frame_ok or first_frame is None:
                        raise ValueError("The project video first frame cannot be decoded.")
                finally:
                    video_capture.release()
            validate_video_bounds(state, prepared_video_metadata)

            lfp_path = source_paths.get("lfp")
            axis_path = source_paths.get("axis")
            ttl_path = source_paths.get("ttl")
            prepared_lfp_info = (
                signal_data.parse_lfp_csv_info(lfp_path) if lfp_path else None
            )
            prepared_axis_info = (
                signal_data.parse_lfp_csv_info(axis_path) if axis_path else None
            )
            if ttl_path:
                signal_data.parse_time_marker_csv_info(ttl_path)

            data = state.get("data", {})
            timeline_xlim = data.get("timeline_xlim")
            restored_timeline_xlim = (
                tuple(float(value) for value in timeline_xlim)
                if timeline_xlim is not None
                else None
            )
            sync = state.get("sync", {})
            saved_ttl_info = sync.get("time_marker_info")
            prepared_ttl_info = None
            if saved_ttl_info:
                markers = []
                for saved_marker in saved_ttl_info.get("markers", []):
                    marker = dict(saved_marker)
                    local_time = marker.get("local_time")
                    marker["local_time"] = (
                        datetime.fromisoformat(local_time) if local_time else None
                    )
                    markers.append(marker)
                prepared_ttl_info = {
                    "path": ttl_path,
                    "filename": saved_ttl_info.get("filename") or "Project TTL",
                    "time_column_name": saved_ttl_info.get("time_column_name"),
                    "marker_count": len(markers),
                    "markers": markers,
                    "first_marker_sec": (
                        markers[0]["record_time"] / 1_000_000.0
                        if markers
                        else None
                    ),
                }
            led = state.get("led", {})
            roi = led.get("roi")
            restored_roi = tuple(roi) if roi is not None else None
            analysis_points = [
                LedBrightnessPoint(**point)
                for point in led.get("analysis_points") or []
            ]
            analysis_events = [
                LedEvent(**event)
                for event in led.get("analysis_events") or []
            ]
            prepared_cache = []
            for cache in led.get("brightness_cache", []):
                cache_roi = cache.get("roi")
                prepared_cache.append(
                    (
                        (
                            video_path,
                            tuple(cache_roi) if cache_roi is not None else None,
                            int(cache.get("rotation_degrees", 0)),
                            float(cache.get("fps", 0.0)),
                            int(cache.get("start_frame", 0)),
                            int(cache.get("end_frame", 0)),
                            int(cache.get("coarse_step", 1)),
                        ),
                        [
                            LedBrightnessPoint(**point)
                            for point in cache.get("points", [])
                        ],
                    )
                )
        except (BadZipFile, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            QApplication.restoreOverrideCursor()
            window.statusBar().clearMessage()
            QMessageBox.warning(window, "Open project failed", str(error))
            return

        # All file and state validation succeeded. Apply the prepared project now.
        self.app_state.project.loading = True
        try:
            window.statusBar().showMessage("Restoring analysis settings...")
            self.data_state.lfp_step = data.get("lfp_step")
            self.data_state.axis_step = data.get("axis_step")
            self.data_state.line_noise_hz = float(data.get("line_noise_hz", 60.0))
            self.data_state.timeline_xlim = restored_timeline_xlim
            self.data_state.selected_lfp_channel = data.get("selected_lfp_channel")
            self.data_state.lfp_filter_settings = dict(data.get("lfp_filter_settings", {}))
            self.data_state.follow_video_playback = bool(data.get("follow_video_playback", True))
            window.lfp_panel.apply_project_state()

            if video_path:
                window.statusBar().showMessage("Loading video...")
                self.sync_state.loading_video = True
                try:
                    if not window.video_player.load_video(video_path):
                        raise ValueError("The validated project video could not be loaded.")
                finally:
                    self.sync_state.loading_video = False
                self.led_state.brightness_cache.clear()
                window.reset_sync_state_for_new_video()
                window.event_table.set_video_timing(
                    self.video_state.metadata.using_fps,
                    self.video_state.metadata.total_frames,
                )
            if prepared_lfp_info is not None:
                window.statusBar().showMessage("Loading LFP waveform...")
                self.data_state.lfp_info = prepared_lfp_info
                window.lfp_panel.set_lfp_info(prepared_lfp_info)
            if prepared_axis_info is not None:
                window.statusBar().showMessage("Loading 3-axis waveform...")
                self.data_state.axis_info = prepared_axis_info
                window.lfp_panel.set_axis_info(prepared_axis_info)

            self.sync_state.time_offset_sec = sync.get("time_offset_sec")
            self.sync_state.video_time_origin_sec = sync.get("video_time_origin_sec")
            self.sync_state.record_time_origin_sec = sync.get("record_time_origin_sec")
            if prepared_ttl_info is not None:
                window.ttl_panel.set_markers(prepared_ttl_info)
                window.set_ttl_markers(prepared_ttl_info)

            window.event_table.clear_events(emit=False)
            for event in state.get("events", []):
                window.event_table.add_event(
                    event_type=event.get("event_type", ""),
                    video_time_sec=event.get("video_time_sec", 0.0),
                    frame_index=event.get("frame_index", 0),
                    note=event.get("note", ""),
                    source=event.get("source", "manual"),
                )

            if restored_roi is not None:
                self.led_state.roi = restored_roi
                window.video_player.set_led_roi(restored_roi)
                window.sync_panel.set_led_roi(restored_roi)
            if led.get("analysis_status") is not None:
                window.sync_panel.set_led_analysis(
                    analysis_points,
                    led.get("analysis_threshold", 0.0),
                    analysis_events,
                    stats=led.get("analysis_stats") or {},
                    status=led.get("analysis_status"),
                )
                window.sync_panel.set_led_detection_status(
                    "LED detection: restored from project."
                )
            self.led_state.brightness_cache.clear()
            for cache_key, points in prepared_cache:
                self.led_state.brightness_cache[cache_key] = points

            if video_path and self.video_state.metadata is not None:
                rotation = state.get("video", {}).get("rotation_degrees", 0)
                self.video_state.rotation_degrees = rotation
                self.video_state.rotate_180_enabled = rotation == 180
                window.video_player.update_rotation_buttons()
                window.video_player.seek_frame(state.get("video", {}).get("current_frame", 0))

            if restored_timeline_xlim is not None:
                window.lfp_panel.set_shared_xlim(
                    *restored_timeline_xlim,
                    source="timeline",
                )
            window.update_waveform_current_time()
        except Exception as error:
            QApplication.restoreOverrideCursor()
            window.statusBar().clearMessage()
            QMessageBox.warning(window, "Restore project failed", str(error))
            return
        finally:
            self.app_state.project.loading = False

        self.app_state.project.path = str(Path(path).resolve())
        self.app_state.project.dirty = False
        window.update_project_title()
        QApplication.restoreOverrideCursor()
        window.statusBar().clearMessage()
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
        window.set_ttl_markers(info)
        window.ttl_panel.set_markers(info)
        window.sync_panel.show_ttl_panel()
        window.mark_project_dirty()
