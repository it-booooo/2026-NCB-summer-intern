from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
import csv_function as csv_func
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
        self.video_player.roi_selected.connect(self.set_led_roi)

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
        ]

        self.add_action(import_menu, *import_actions[0])
        import_menu.addSeparator()
        for text, callback in import_actions[1:]:
            self.add_action(import_menu, text, callback)

        for text, callback in export_actions:
            self.add_action(export_menu, text, callback)

        self.analysis_controller.populate_menu(analysis_menu)

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

        if self.led_worker is not None and self.led_worker.isRunning():
            if not self.stop_led_detection(wait=True):
                QMessageBox.information(
                    self,
                    "LED detection",
                    "LED detection is still stopping. Please try again in a moment.",
                )
                return

        self.sync_panel.set_led_detection_status(
            "LED detection: analyzing ROI frame changes. You can wait here; video playback is not required."
        )
        self.sync_panel.begin_led_detection_progress()
        self.led_worker = LedDetectionWorker(
            video_path=self.video_player.video_path,
            roi=self.led_roi,
            rotate_180=self.video_player.rotate_180_enabled,
            fps=self.video_player.fps,
            baseline_frame=self.video_player.current_frame,
        )
        self.led_worker.result_ready.connect(self.finish_led_detection)
        self.led_worker.progress_changed.connect(self.update_led_detection_progress)
        self.led_worker.failed.connect(self.fail_led_detection)
        self.led_worker.finished.connect(self.cleanup_led_worker)
        self.led_worker.start()

    def stop_led_detection(self, wait=False):
        if self.led_worker is None:
            return True

        if self.led_worker.isRunning():
            self.led_worker.requestInterruption()
            if wait:
                self.led_worker.wait(3000)

        return not self.led_worker.isRunning()

    def finish_led_detection(self, points, threshold, events, baseline, stats):
        if self.sender() is not self.led_worker:
            return

        self.sync_panel.finish_led_detection_progress()
        self.sync_panel.set_led_analysis(
            points,
            threshold,
            events,
            baseline=baseline,
            stats=stats,
        )
        self.add_led_events(events)
        event_status = (
            f"on delta={stats.get('selected_on_delta', 0.0):.4f} "
            f"at {stats.get('selected_on_time_sec', 0.0):.3f}s | "
            f"off delta={stats.get('selected_off_delta', 0.0):.4f} "
            f"at {stats.get('selected_off_time_sec', 0.0):.3f}s"
            if events
            else "no LED event selected"
        )
        self.sync_panel.set_led_detection_status(
            f"LED detection: ROI mean brightness delta | {len(events) // 2} intervals | "
            f"coarse step={stats.get('coarse_step', 1)} frames | "
            f"{'refined' if stats.get('refined') else 'coarse only'} | "
            f"{event_status}"
        )

    def update_led_detection_progress(self, current_frame, total_frames):
        if self.sender() is not self.led_worker:
            return

        self.sync_panel.update_led_detection_progress(current_frame, total_frames)

    def fail_led_detection(self, message):
        if self.sender() is not self.led_worker:
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

    def import_axis(self):
        path = self.open_csv_file("Import 3-axis (.csv)")
        if path:
            self.axis_info = csv_func.parse_lfp_csv_info(path)
            self.lfp_panel.set_axis_info(self.axis_info)

    def import_time_marker(self):
        path = self.open_csv_file("Import Time Marker (.csv)")
        if not path:
            return

        self.timeMarker_info = csv_func.parse_time_marker_csv_info(path)
        self.ttl_panel.set_markers(self.timeMarker_info.get("markers", []))
        self.show_marker_panel()

        first_marker_sec = self.timeMarker_info.get("first_marker_sec")
        if first_marker_sec is not None:
            self.sync_panel.set_ttl_marker(first_marker_sec)

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
