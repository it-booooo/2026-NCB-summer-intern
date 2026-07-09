from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
import check_function as check
import csv_function as csv_func
import draw_function as draw
from .analysis import AnalysisMenuController
from .event_table import EventTable
from .export import export_events_csv, export_events_excel
from .lfp_panel import LfpPanel
from .led_worker import LedDetectionWorker
from .marker_panel import MarkerPanel
from .sync_panel import SyncPanel
from src.ttl_panel import TtlPanel
from .video_player import VideoPlayer


class MainWindow(QMainWindow):
    MARKER_PANEL_WIDTH = 300
    WAVEFORM_AREA_HEIGHT = 420

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pig Behavior Video-LFP Synchronization Tool")
        self.resize(1280, 720)
        self.setMinimumSize(1100, 640)

        self.video_player = VideoPlayer()
        self.event_table = EventTable()
        self.lfp_panel = LfpPanel()
        self.sync_panel = SyncPanel()
        self.ttl_panel = TtlPanel()
        self.marker_panel = MarkerPanel(
            self.event_table,
            self.add_event,
            self.select_led_roi,
        )
        self.analysis_controller = AnalysisMenuController(self)
        self.lfp_info = None
        self.axis_info = None
        self.timeMarker_info = None
        self.led_roi = None
        self.led_worker = None
        self.led_brightness_cache = {}
        self.time_offset_sec = None
        self.video_player.roi_selected.connect(self.set_led_roi)
        self.video_player.frame_changed.connect(self.update_waveform_current_time)
        self.ttl_panel.markers_changed.connect(self.set_ttl_markers)
        self.event_table.events_changed.connect(self.update_time_offset)

        self.create_menu()
        self.create_layout()

    def add_action(self, menu, text, callback):
        action = QAction(text, self)
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    def open_csv_file(self, title):
        path, _ = QFileDialog.getOpenFileName(
            self, title, "", "CSV Files (*.csv);;All Files (*)"
        )
        return path

    def create_group(self, title, widget, margins=(6, 6, 6, 6)):
        group = QGroupBox(title)
        layout = QVBoxLayout()
        layout.setContentsMargins(*margins)
        layout.addWidget(widget)
        group.setLayout(layout)
        return group

    def create_menu(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")
        settings_menu = menu_bar.addMenu("Settings")
        analysis_menu = menu_bar.addMenu("Analysis")
        import_menu = file_menu.addMenu("Import")
        export_menu = file_menu.addMenu("Export")

        import_actions = [
            ("Import Video (.mp4)", self.import_video),
            ("Import LFP (.csv)", self.import_lfp),
            ("Import 3-axis (.csv)", self.import_axis),
            ("Import Time Marker (.csv)", self.import_time_marker),
        ]
        export_actions = [
            ("Export Markers as CSV", self.export_markers_csv),
            ("Export Markers as Excel", self.export_markers_excel),
            ("Export Check Results", self.export_check_results),
            ("Export Waveform Image", self.export_waveform_image),
        ]

        self.add_action(import_menu, *import_actions[0])
        import_menu.addSeparator()
        for text, callback in import_actions[1:]:
            self.add_action(import_menu, text, callback)

        for text, callback in export_actions:
            self.add_action(export_menu, text, callback)

        self.add_action(settings_menu, "Set LFP step", self.set_lfp_step)
        self.add_action(settings_menu, "Set 3-axis step", self.set_axis_step)

        self.analysis_controller.populate_menu(analysis_menu)

    def ask_step(self, title, current_step):
        step, accepted = QInputDialog.getInt(
            self,
            title,
            "Step (-1 auto, 0 all):",
            -1 if current_step is None else int(current_step),
            -1,
            1_000_000,
            1,
        )
        if not accepted:
            return False, None
        return True, None if step == -1 else step

    def set_lfp_step(self):
        accepted, step = self.ask_step("Set LFP step", self.lfp_panel.lfp_step)
        if accepted:
            self.lfp_panel.set_lfp_step(step)

    def set_axis_step(self):
        accepted, step = self.ask_step("Set 3-axis step", self.lfp_panel.axis_step)
        if accepted:
            self.lfp_panel.set_axis_step(step)

    def create_layout(self):
        lfp_group = self.create_group("Waveform Area", self.lfp_panel)
        lfp_group.setFixedHeight(self.WAVEFORM_AREA_HEIGHT)
        sync_group = self.create_group("Synchronization Area", self.sync_panel)
        ttl_group = self.create_group("TTL", self.ttl_panel, margins=(6, 10, 6, 6))
        marker_group = self.create_group("Video Marker", self.marker_panel)

        video_group = QGroupBox("Behavior Video")
        video_layout = QVBoxLayout()
        video_layout.setContentsMargins(4, 4, 4, 4)
        video_layout.setSpacing(2)
        video_layout.addWidget(self.video_player, stretch=1)
        video_group.setLayout(video_layout)

        self.open_marker_button = QPushButton("Open Video Marker")
        self.open_marker_button.setFixedSize(150, 26)
        self.open_marker_button.clicked.connect(self.show_marker_panel)
        self.sync_panel.add_top_left_widget(self.open_marker_button)

        lower_splitter = QSplitter(Qt.Orientation.Horizontal)
        lower_splitter.addWidget(sync_group)
        lower_splitter.addWidget(video_group)
        lower_splitter.setChildrenCollapsible(False)
        lower_splitter.setStretchFactor(0, 1)
        lower_splitter.setStretchFactor(1, 1)
        lower_splitter.setSizes([640, 640])

        main_content = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(4)
        main_layout.addWidget(lfp_group)
        main_layout.addWidget(lower_splitter, stretch=1)
        main_content.setLayout(main_layout)

        self.side_panel = QWidget()
        self.side_panel.setFixedWidth(self.MARKER_PANEL_WIDTH)

        close_button = QPushButton("X")
        close_button.setObjectName("sidebarCloseButton")
        close_button.setFlat(True)
        close_button.setFixedSize(16, 16)
        close_button.clicked.connect(self.hide_marker_panel)

        close_layout = QHBoxLayout()
        close_layout.setContentsMargins(0, 0, 2, 0)
        close_layout.setSpacing(0)
        close_layout.addStretch()
        close_layout.addWidget(close_button)

        side_layout = QVBoxLayout()
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(0)
        side_layout.addLayout(close_layout)
        side_layout.addWidget(ttl_group, stretch=2)
        side_layout.addSpacing(6)
        side_layout.addWidget(marker_group, stretch=3)
        self.side_panel.setLayout(side_layout)
        self.side_panel.hide()

        root_layout = QHBoxLayout()
        root_layout.setContentsMargins(4, 4, 4, 4)
        root_layout.setSpacing(4)
        root_layout.addWidget(self.side_panel)
        root_layout.addWidget(main_content, stretch=1)

        container = QWidget()
        container.setLayout(root_layout)
        self.setCentralWidget(container)

    def show_marker_panel(self):
        self.side_panel.show()

    def hide_marker_panel(self):
        self.side_panel.hide()

    def select_led_roi(self):
        self.analysis_controller.select_led_roi()

    def set_led_roi(self, roi):
        self.led_roi = roi
        self.sync_panel.set_led_roi(roi)
        self.start_led_detection()

    def start_led_detection(self):
        if not self.video_player.has_video() or self.led_roi is None:
            return

        try:
            scan_start_sec, scan_end_sec = self.sync_panel.led_scan_range_sec()
        except ValueError as error:
            self.sync_panel.mark_scan_range_valid(False)
            QMessageBox.warning(self, "Invalid LED scan range", str(error))
            return

        scan_start_frame = (
            self.video_player.time_sec_to_frame(scan_start_sec)
            if scan_start_sec is not None
            else 0
        )
        scan_end_frame = (
            self.video_player.time_sec_to_frame(scan_end_sec)
            if scan_end_sec is not None
            else max(self.video_player.total_frames - 1, 0)
        )
        if scan_start_frame >= scan_end_frame:
            self.sync_panel.mark_scan_range_valid(False)
            QMessageBox.warning(
                self,
                "Invalid LED scan range",
                "LED scan range is too short after converting to frames.",
            )
            return

        if self.led_worker is not None and self.led_worker.isRunning():
            if not self.stop_led_detection(wait=True):
                QMessageBox.information(
                    self,
                    "LED detection",
                    "LED detection is still stopping. Please try again in a moment.",
                )
                return

        cache_key = self.led_cache_key(scan_start_frame, scan_end_frame)
        cached_points = self.led_brightness_cache.get(cache_key)

        self.sync_panel.set_led_detection_status(
            "LED detection: using cached ROI brightness data."
            if cached_points is not None
            else "LED detection: analyzing ROI frame changes. You can wait here; video playback is not required."
        )
        self.sync_panel.begin_led_detection_progress()
        self.led_worker = LedDetectionWorker(
            video_path=self.video_player.video_path,
            roi=self.led_roi,
            rotate_180=self.video_player.rotate_180_enabled,
            fps=self.video_player.fps,
            scan_start_frame=scan_start_frame,
            scan_end_frame=scan_end_frame,
            detect_multiple=self.sync_panel.detect_multiple_led_events(),
            cached_points=cached_points,
        )
        worker = self.led_worker
        worker.result_ready.connect(
            lambda points, threshold, events, stats, worker=worker: (
                self.finish_led_detection(
                    worker,
                    points,
                    threshold,
                    events,
                    stats,
                    cache_key,
                )
            )
        )
        worker.progress_changed.connect(
            lambda current_frame, total_frames, worker=worker: (
                self.update_led_detection_progress(worker, current_frame, total_frames)
            )
        )
        worker.stage_changed.connect(
            lambda text, worker=worker: self.update_led_detection_stage(worker, text)
        )
        worker.failed.connect(
            lambda message, worker=worker: self.fail_led_detection(worker, message)
        )
        self.led_worker.finished.connect(self.cleanup_led_worker)
        self.led_worker.start()

    def led_cache_key(self, scan_start_frame, scan_end_frame):
        return (
            self.video_player.video_path,
            tuple(self.led_roi) if self.led_roi is not None else None,
            bool(self.video_player.rotate_180_enabled),
            float(self.video_player.fps or 0.0),
            int(scan_start_frame),
            int(scan_end_frame),
            20,
        )

    def stop_led_detection(self, wait=False):
        if self.led_worker is None:
            return True

        if self.led_worker.isRunning():
            self.led_worker.requestInterruption()
            if wait:
                self.led_worker.wait(3000)

        return not self.led_worker.isRunning()

    def finish_led_detection(
        self,
        worker,
        points,
        threshold,
        events,
        stats,
        cache_key,
    ):
        if self.led_worker is not None and worker is not self.led_worker:
            return

        cache_hit = worker.cached_points is not None
        if points and cache_key is not None and not cache_hit:
            self.led_brightness_cache[cache_key] = points

        self.sync_panel.finish_led_detection_progress()
        self.sync_panel.set_led_analysis(
            points,
            threshold,
            events,
            stats=stats,
        )
        interval_count = stats.get("event_count", len(events) // 2)
        mode_label = stats.get("mode_label", "Frame delta (ROI mean brightness)")
        self.add_led_events(events)
        event_status = (
            f"event pairs={interval_count}" if events else "no LED event selected"
        )
        status = (
            f"LED detection: {mode_label} | {interval_count} intervals | "
            f"scan frames={stats.get('scan_start_frame', 0)}-{stats.get('scan_end_frame', 0)} | "
            f"coarse step={stats.get('coarse_step', 20)} frames | "
            f"refine window={stats.get('refine_window_sec', 1.0):.1f}s | "
            f"points={stats.get('points_count', len(points or []))} | "
            f"{'multiple' if stats.get('detect_multiple') else 'single'} | "
            f"threshold={stats.get('threshold', threshold):.6f} | "
            f"duration={stats.get('min_duration_sec', 0.6):.1f}-{stats.get('max_duration_sec', 1.5):.1f}s "
            f"target={stats.get('expected_duration_sec', 1.0):.1f}s | "
            f"{event_status}"
        )
        status += (
            f" | scan={stats.get('scan_elapsed_sec', 0.0):.1f}s"
            f" detect={stats.get('detect_elapsed_sec', 0.0):.1f}s"
        )
        if cache_hit:
            status += " | cached scan"
        self.sync_panel.set_led_detection_status(status)

    def update_led_detection_progress(self, worker, current_frame, total_frames):
        if self.led_worker is not None and worker is not self.led_worker:
            return

        self.sync_panel.update_led_detection_progress(current_frame, total_frames)

    def update_led_detection_stage(self, worker, text):
        if self.led_worker is not None and worker is not self.led_worker:
            return

        self.sync_panel.set_led_detection_stage(text)

    def fail_led_detection(self, worker, message):
        if self.led_worker is not None and worker is not self.led_worker:
            return

        self.sync_panel.fail_led_detection_progress()
        self.sync_panel.set_led_detection_status("LED detection: failed")
        QMessageBox.warning(self, "LED detection failed", message)

    def cleanup_led_worker(self):
        worker = self.sender()
        if worker is not None:
            worker.deleteLater()

        if worker is self.led_worker:
            self.led_worker = None

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

    def closeEvent(self, event):
        if self.stop_led_detection(wait=True):
            event.accept()
            return

        QMessageBox.information(
            self,
            "LED detection",
            "LED detection is still stopping. Please close the window again in a moment.",
        )
        event.ignore()

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

    def set_ttl_markers(self, info):
        self.timeMarker_info = info
        first_marker_sec = self.timeMarker_info.get("first_marker_sec")
        if first_marker_sec is not None:
            self.sync_panel.set_ttl_marker(first_marker_sec)
        else:
            self.sync_panel.ttl_label.setText("TTL marker: Not loaded")
        self.update_time_offset()

    def add_event(self, event_type):
        if not self.video_player.has_video():
            QMessageBox.warning(self, "No video", "Please import a video first.")
            return

        self.event_table.add_event(
            event_type=event_type,
            video_time_sec=self.video_player.current_time_sec(),
            frame_index=self.video_player.current_frame,
            note="",
        )

    def add_led_events(self, led_events):
        for event in led_events:
            self.event_table.add_event(
                event_type=event.event_type,
                video_time_sec=event.video_time_sec,
                frame_index=event.frame_index,
                note=f"brightness={event.brightness:.4f}",
            )

        if led_events:
            self.show_marker_panel()

    def first_video_led_time_sec(self):
        led_events = [
            event for event in self.event_table.events()
            if event["event_type"] == "LED_on"
        ]
        if not led_events:
            return None

        first_led_event = min(led_events, key=lambda event: event["frame_index"])
        if self.video_player.has_video() and self.video_player.fps:
            return self.video_player.frame_to_time_sec(first_led_event["frame_index"])

        return first_led_event["video_time_sec"]

    def update_time_offset(self):
        video_led_sec = self.first_video_led_time_sec()
        if video_led_sec is None:
            self.sync_panel.video_led_label.setText("Video LED marker: Not selected")
            self.sync_panel.offset_label.setText(
                "Time offset (video - TTL): Not calculated"
            )
            self.time_offset_sec = None
            self.lfp_panel.clear_current_time_marker()
            return

        self.sync_panel.set_video_led_marker(video_led_sec)

        if self.timeMarker_info is None:
            self.sync_panel.offset_label.setText(
                "Time offset (video - TTL): Not calculated"
            )
            self.time_offset_sec = None
            self.lfp_panel.clear_current_time_marker()
            return

        ttl_marker_sec = self.timeMarker_info.get("first_marker_sec")
        if ttl_marker_sec is None:
            self.sync_panel.offset_label.setText(
                "Time offset (video - TTL): Not calculated"
            )
            self.time_offset_sec = None
            self.lfp_panel.clear_current_time_marker()
            return

        self.time_offset_sec = video_led_sec - ttl_marker_sec
        self.sync_panel.set_offset(self.time_offset_sec)
        self.update_waveform_current_time(
            self.video_player.current_frame,
            self.video_player.current_time_sec(),
        )

    def update_waveform_current_time(self, frame_index, video_time_sec):
        if self.time_offset_sec is None:
            return

        record_time_sec = video_time_sec - self.time_offset_sec
        self.lfp_panel.set_current_time_marker(record_time_sec)

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
