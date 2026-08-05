from typing import ClassVar
import uuid

import numpy as np
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QProgressDialog,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..background_requests import widget_is_valid
from ..markers import (
    MarkerKind,
    MarkerSource,
    marker_video_time,
    peak_records_to_markers,
)
from ..signal_data import PeakDetectionWorker
from ..synchronization import relative_time
from .marker_table import NoteEditor
from .marker_view_panel import MarkerViewPanel


class LfpPeakPanel(MarkerViewPanel):
    DISPLAY_HEADERS: ClassVar[list[str]] = ["marker type", "video time", "note"]
    video_time_selected = Signal(float)
    VIDEO_TIME_ROLE = Qt.UserRole + 1
    MARKER_ID_ROLE = Qt.UserRole + 2

    def __init__(
        self,
        marker_store,
        lfp_service,
        sync_state,
        video_state,
        video_player,
        analysis_settings,
    ):
        super().__init__(marker_store)
        self.lfp_service = lfp_service
        self.sync_state = sync_state
        self.video_state = video_state
        self.video_player = video_player
        self.analysis_settings = analysis_settings
        self._refreshing = False
        self._analysis_dialogs = set()
        self._peak_workers = {}
        self._peak_request_id = None
        self._peak_progress = None
        self._peak_message_boxes = set()

        self.channel_selector = QComboBox()
        self.channel_selector.setMinimumContentsLength(12)
        self.channel_selector.currentIndexChanged.connect(self.refresh_table)
        self.detect_lfp_peaks_button = QPushButton("Detect LFP Peaks")
        self.delete_selected_button = QPushButton("Delete Selected")
        self.analysis_button = QPushButton("Analyze Peaks")
        for button in (
            self.detect_lfp_peaks_button,
            self.delete_selected_button,
            self.analysis_button,
        ):
            button.setFixedHeight(26)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.detect_lfp_peaks_button.clicked.connect(self.detect_lfp_peaks)
        self.delete_selected_button.clicked.connect(self.delete_selected_peak)
        self.analysis_button.clicked.connect(self.analyze_peaks)
        self.delete_selected_button.setEnabled(False)
        self.table = QTableWidget(0, len(self.DISPLAY_HEADERS))
        self.table.setHorizontalHeaderLabels(self.DISPLAY_HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 92)
        self.table.cellClicked.connect(self.handle_cell_clicked)
        self.table.itemSelectionChanged.connect(self.update_selection_state)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        channel_layout = QHBoxLayout()
        channel_layout.addWidget(QLabel("Channel"))
        channel_layout.addWidget(self.channel_selector, stretch=1)
        layout.addLayout(channel_layout)
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.detect_lfp_peaks_button, stretch=1)
        button_layout.addWidget(self.delete_selected_button, stretch=1)
        button_layout.addWidget(self.analysis_button, stretch=1)
        layout.addLayout(button_layout)
        layout.addWidget(self.table)
        self.refresh_table()

    def accepts_marker(self, marker):
        return marker.kind == MarkerKind.LFP_PEAK

    def refresh_markers(self):
        self.refresh_table()

    def peak_markers(self):
        channel = self.selected_channel()
        return tuple(
            marker
            for marker in self.markers()
            if channel is None or marker.payload.get("channel") == channel
        )

    def selected_channel(self):
        channel = self.channel_selector.currentData()
        return None if channel is None else int(channel)

    def refresh_channels(self):
        channels = self.lfp_service.available_channels()
        selected = self.selected_channel()
        preferred = (
            selected if selected in channels else self.lfp_service.selected_channel()
        )
        self.channel_selector.blockSignals(True)
        self.channel_selector.clear()
        for channel in channels:
            self.channel_selector.addItem(f"Channel {channel}", channel)
        if preferred in channels:
            self.channel_selector.setCurrentIndex(channels.index(preferred))
        self.channel_selector.setEnabled(bool(channels))
        self.channel_selector.blockSignals(False)

    def refresh_table(self):
        self.refresh_channels()
        current_id = self.selected_marker_id()
        self._refreshing = True
        self.table.setRowCount(0)
        try:
            offset = self.sync_state.time_offset_sec
            is_synchronized = self.sync_state.video_time_origin_sec is not None
            self.table.setHorizontalHeaderItem(
                1,
                QTableWidgetItem("sync time" if is_synchronized else "video time"),
            )
            for row, marker in enumerate(self.peak_markers()):
                self.table.insertRow(row)
                video_time = marker_video_time(marker, offset)
                display_time = (
                    relative_time(video_time, self.sync_state.video_time_origin_sec)
                    if video_time is not None
                    else None
                )

                type_item = QTableWidgetItem(marker.kind.value)
                type_item.setData(self.MARKER_ID_ROLE, marker.marker_id)
                type_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                type_item.setTextAlignment(Qt.AlignCenter)

                time_item = QTableWidgetItem(
                    f"{display_time:.3f}" if display_time is not None else "--"
                )
                time_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                time_item.setTextAlignment(Qt.AlignCenter)
                if video_time is not None:
                    time_item.setData(self.VIDEO_TIME_ROLE, video_time)

                self.table.setItem(row, 0, type_item)
                self.table.setItem(row, 1, time_item)

                note_editor = NoteEditor(marker.note)
                note_editor.selection_requested.connect(
                    lambda editor=note_editor: self.select_note_editor_row(editor)
                )
                note_editor.editingFinished.connect(
                    lambda editor=note_editor, marker_id=marker.marker_id: (
                        self.update_note(marker_id, editor.text())
                    )
                )
                self.table.setCellWidget(row, 2, note_editor)
                if marker.marker_id == current_id:
                    self.table.selectRow(row)
        finally:
            self._refreshing = False
        self.update_selection_state()

    def handle_cell_clicked(self, row, column):
        """Seek to a peak when any cell in its row is clicked."""
        item = self.table.item(row, 1)
        video_time = item.data(self.VIDEO_TIME_ROLE) if item is not None else None
        if video_time is not None:
            self.video_time_selected.emit(float(video_time))

    def selected_marker_id(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.data(self.MARKER_ID_ROLE) if item is not None else None

    def select_note_editor_row(self, editor):
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 2) is editor:
                self.table.selectRow(row)
                item = self.table.item(row, 1)
                video_time = (
                    item.data(self.VIDEO_TIME_ROLE) if item is not None else None
                )
                if video_time is not None:
                    self.video_time_selected.emit(float(video_time))
                return

    def update_note(self, marker_id, note):
        if not self._refreshing:
            self.marker_store.update(marker_id, note=str(note))

    def update_selection_state(self):
        selected_rows = {
            index.row() for index in self.table.selectionModel().selectedRows()
        }
        self.delete_selected_button.setEnabled(bool(selected_rows))
        for row in range(self.table.rowCount()):
            editor = self.table.cellWidget(row, 2)
            if editor is not None:
                editor.set_row_selected(row in selected_rows)

    def create_peak_analysis_figure(self, channel=None):
        """Create the peak analysis figure without attaching it to a Qt canvas."""
        channel = self.selected_channel() if channel is None else int(channel)
        peaks = (
            marker
            for marker in self.marker_store.by_kind(MarkerKind.LFP_PEAK)
            if channel is None or marker.payload.get("channel") == channel
        )
        peak_per_minute = {}
        for marker in peaks:
            video_time = marker_video_time(marker, self.sync_state.time_offset_sec)
            if video_time is not None:
                display_time = relative_time(
                    video_time, self.sync_state.video_time_origin_sec
                )
                minute = int(np.floor(display_time / 60))
                peak_per_minute[minute] = peak_per_minute.get(minute, 0) + 1

        if not peak_per_minute:
            return None

        minutes = sorted(peak_per_minute)
        duration_minutes = max(1, minutes[-1] - minutes[0] + 1)
        canvas_width = min(16_000, max(900, round(duration_minutes * 2.5)))
        canvas_height = 500

        figure = Figure(
            figsize=(canvas_width / 100, canvas_height / 100),
            dpi=100,
            constrained_layout=True,
        )

        time_label = (
            "Sync time (min)"
            if self.sync_state.video_time_origin_sec is not None
            else "Video time (min)"
        )

        minutes = sorted(peak_per_minute)
        counts = np.array([peak_per_minute[minute] for minute in minutes])

        ax = figure.add_subplot(111)
        ax.bar(
            minutes,
            counts,
            width=0.85,
            color="#1f77b4",
            edgecolor="none",
        )
        title = "LFP peak count over time"
        if channel is not None:
            title += f" - Channel {channel}"
        ax.set_title(title)
        ax.set_xlabel(time_label)
        ax.set_ylabel("Peaks per minute")
        ax.set_xlim(minutes[0] - 0.5, minutes[-1] + 0.5)
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", alpha=0.25)

        from matplotlib.ticker import MaxNLocator

        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        return figure, canvas_width, canvas_height

    def analyze_peaks(self):
        """Analyze the detected peaks."""
        figure_data = self.create_peak_analysis_figure()
        if figure_data is None:
            QMessageBox.information(
                self, "LFP Peak Analysis", "No synchronized LFP peaks to analyze."
            )
            return

        figure, canvas_width, canvas_height = figure_data

        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

        dialog = QDialog(self)
        dialog.setWindowTitle("LFP Peak Analysis")
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        canvas = FigureCanvas(figure)
        canvas.setMinimumSize(canvas_width, canvas_height)
        canvas.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.close)

        layout = QVBoxLayout(dialog)
        scroll_area = QScrollArea()
        scroll_area.setWidget(canvas)
        scroll_area.setWidgetResizable(False)
        scroll_area.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(scroll_area, stretch=1)
        layout.addWidget(buttons)

        available = dialog.screen().availableGeometry()
        dialog.resize(
            min(canvas_width + 40, round(available.width() * 0.9)),
            min(canvas_height + 80, round(available.height() * 0.9)),
        )
        canvas.draw()
        self._analysis_dialogs.add(dialog)
        dialog.finished.connect(
            lambda _result, item=dialog: self._analysis_dialogs.discard(item)
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def delete_selected_peak(self):
        """Delete the selected peak through the canonical marker store."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return
        markers = self.peak_markers()
        row = selected_rows[0].row()
        if 0 <= row < len(markers):
            self.marker_store.delete(markers[row].marker_id)
            if self.table.rowCount() > 0:
                self.table.selectRow(min(row, self.table.rowCount() - 1))

    def detect_lfp_peaks(self):
        if not self.video_player.has_video():
            QMessageBox.warning(self, "No video", "Please import a video first.")
            return
        if self.sync_state.time_offset_sec is None:
            QMessageBox.warning(
                self,
                "LFP is not synchronized",
                "Please synchronize the video and LFP before finding peaks.",
            )
            return
        channel = self.selected_channel()
        if channel is None:
            QMessageBox.warning(self, "No LFP channel", "Please select a channel.")
            return

        metadata = self.video_state.metadata
        duration = float(metadata.duration_sec)
        offset = float(self.sync_state.time_offset_sec)
        dataset = self.lfp_service.dataset()
        request_id = uuid.uuid4().hex
        self.cancel_peak_detection()
        self._peak_request_id = request_id
        worker = PeakDetectionWorker(
            request_id,
            dataset,
            channel,
            -offset,
            duration - offset,
            self.lfp_service.filter_settings(),
            height_sigma=self.analysis_settings.lfp_peak_height_sigma,
            prominence_sigma=self.analysis_settings.lfp_peak_prominence_sigma,
            min_distance_sec=self.analysis_settings.lfp_peak_min_distance_sec,
        )
        self._peak_workers[request_id] = worker
        progress = QProgressDialog(
            "Detecting LFP peaks…",
            "Cancel",
            0,
            100,
            self,
        )
        progress.setWindowTitle("LFP peak detection")
        progress.setWindowModality(Qt.WindowModality.NonModal)
        progress.setAutoClose(False)
        self._peak_progress = progress
        worker.progress.connect(self._update_peak_progress)
        worker.completed.connect(self._finish_peak_detection)
        worker.failed.connect(self._fail_peak_detection)
        worker.canceled.connect(
            lambda result_id, _identity: self._complete_peak_request(result_id)
        )
        progress.canceled.connect(worker.cancel)
        worker.finished.connect(
            lambda result_id=request_id: self._discard_peak_worker(result_id)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()
        progress.show()

    def _peak_result_is_current(self, request_id, identity):
        if request_id != self._peak_request_id or not widget_is_valid(self):
            return False
        try:
            return self.lfp_service.dataset().source.identity_token() == identity
        except (OSError, RuntimeError, ValueError):
            return False

    def _update_peak_progress(self, request_id, value):
        if request_id != self._peak_request_id:
            return
        if self._peak_progress is not None and widget_is_valid(self._peak_progress):
            self._peak_progress.setValue(value)

    def _finish_peak_detection(self, request_id, identity, result):
        if not self._peak_result_is_current(request_id, identity):
            return
        channel = int(result["channel"])
        markers = peak_records_to_markers(channel, result["records"])
        retained = [
            marker
            for marker in self.marker_store.all()
            if not (
                marker.source == MarkerSource.LFP_DETECTION
                and marker.payload.get("channel") == channel
            )
        ]
        self._complete_peak_request(request_id)
        self.marker_store.replace_all([*retained, *markers])
        acceleration = result.get("acceleration", {})
        details = ""
        if acceleration:
            details = (
                f"\n\nBackend: {acceleration.get('backend', 'cpu')}"
                f"\nStatistics: {acceleration.get('statistics_backend', 'cpu')}"
                f"\nCandidates: {acceleration.get('candidate_backend', 'cpu')}"
                f"\nElapsed: {acceleration.get('elapsed_sec', 0.0):.3f} s"
                f"\nOpenCL statistics chunks: "
                f"{acceleration.get('gpu_statistics_chunks', 0)}"
                f"\nOpenCL candidate chunks: "
                f"{acceleration.get('gpu_candidate_chunks', 0)}"
            )
            if acceleration.get("fallback_reason"):
                fallback = str(acceleration["fallback_reason"])
                fallback = fallback.split("reason=", 1)[-1]
                if len(fallback) > 240:
                    fallback = fallback[:237] + "..."
                details += f"\nFallback: {fallback}"
        message = f"Added {len(markers)} peak markers from channel {channel}.{details}"
        QTimer.singleShot(
            0,
            lambda title="LFP peaks", text=message: self._show_peak_message(
                title,
                text,
            ),
        )

    def _show_peak_message(self, title, message):
        """Show completion without starting a nested event loop during canvas redraw."""

        if not widget_is_valid(self):
            return
        box = QMessageBox(QMessageBox.Icon.Information, title, message, parent=self)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._peak_message_boxes.add(box)
        box.finished.connect(
            lambda _result, item=box: self._peak_message_boxes.discard(item)
        )
        box.open()

    def _fail_peak_detection(self, request_id, identity, message):
        if not self._peak_result_is_current(request_id, identity):
            return
        self._complete_peak_request(request_id)
        QMessageBox.warning(self, "Peak detection failed", message)

    def _complete_peak_request(self, request_id):
        if request_id != self._peak_request_id:
            return
        if self._peak_progress is not None and widget_is_valid(self._peak_progress):
            self._peak_progress.close()
        self._peak_progress = None

    def _discard_peak_worker(self, request_id):
        self._peak_workers.pop(request_id, None)

    def cancel_peak_detection(self, wait=False):
        workers = list(self._peak_workers.values())
        for worker in workers:
            worker.cancel()
        if wait:
            for worker in workers:
                worker.wait(10_000)
        return not any(worker.isRunning() for worker in workers)
