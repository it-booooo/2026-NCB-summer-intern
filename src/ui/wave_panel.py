import numpy as np
import uuid
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QProgressDialog,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import charts as draw
from .. import signal_data as signal_func
from ..app_state import DataState, SyncState
from ..charts.chart_helpers import (
    clamp_xlim,
    format_time_tick,
    resolve_plot_step,
)
from ..background_requests import widget_is_valid
from ..markers import MarkerKind, marker_record_time
from .lfp_analysis import LfpAnalysisMixin
from .lfp_controls import PlaybackAwareComboBox, SharedTimelineSlider


class WavePanel(LfpAnalysisMixin, QWidget):
    time_selected = Signal(float)
    project_changed = Signal()

    DEFAULT_PLAYBACK_WINDOW_SEC = 30.0
    PLAYBACK_CURSOR_FRACTION = 0.35
    PLAYBACK_EDGE_MARGIN_FRACTION = 0.18

    def __init__(self, data_state=None, sync_state=None, marker_store=None):
        super().__init__()
        self.data_state = data_state or DataState()
        self.sync_state = sync_state or SyncState()
        self.marker_store = marker_store
        self.setMinimumHeight(270)

        self.lfp_canvas = None
        self.axis_canvas = None
        self.timeline_canvas = None
        self.timeline_fig = None
        self.timeline_slider = None
        self.timeline_full_xlim = None
        self.lfp_fig = None
        self.axis_fig = None
        self.updating_timeline = False
        self.lfp_callback_connected = False
        self.axis_callback_connected = False
        self.current_time_lines = {}
        self.current_time_backgrounds = {}
        self.event_interval_artists = []
        self.click_seek_state = None
        self.spectrum_dialogs = []
        self._lfp_coarse_workers = {}
        self._lfp_coarse_request_id = None
        self._lfp_coarse_progress = None
        self._lfp_coarse_key = None

        self.lfp_file_label = QLabel("LFP CSV: Not imported")
        self.axis_file_label = QLabel("3-axis CSV: Not imported")

        self.lfp_channel_selector = PlaybackAwareComboBox()
        self.lfp_channel_selector.addItem("No LFP channel")
        self.lfp_channel_selector.setEnabled(False)
        self.lfp_channel_selector.setMinimumContentsLength(12)
        self.lfp_channel_selector.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        self.lfp_channel_selector.setMaxVisibleItems(20)
        self.lfp_channel_selector.currentIndexChanged.connect(self.plot_lfp)

        self.signal_view_selector = PlaybackAwareComboBox()
        self.signal_view_selector.addItem("Raw", False)
        self.signal_view_selector.addItem("Filtered", True)
        self.signal_view_selector.setToolTip("Switch between raw and filtered LFP.")
        self.signal_view_selector.currentIndexChanged.connect(
            self.refresh_lfp_processing
        )

        self.bandpass_checkbox = QCheckBox("Bandpass")
        self.bandpass_checkbox.setToolTip("Apply a basic LFP bandpass filter.")
        self.bandpass_checkbox.stateChanged.connect(self.refresh_lfp_processing)

        self.bandpass_low_spin = self.create_frequency_spinbox(1.0)
        self.bandpass_low_spin.setToolTip("Bandpass low cutoff frequency.")
        self.bandpass_low_spin.valueChanged.connect(self.refresh_lfp_processing)

        self.bandpass_high_spin = self.create_frequency_spinbox(100.0)
        self.bandpass_high_spin.setToolTip("Bandpass high cutoff frequency.")
        self.bandpass_high_spin.valueChanged.connect(self.refresh_lfp_processing)

        self.notch_checkbox = QCheckBox()
        self.notch_checkbox.setChecked(True)
        self.notch_checkbox.stateChanged.connect(self.refresh_lfp_processing)
        self.update_notch_control_text()

        self.apply_filter_button = QPushButton("confirm")
        self.apply_filter_button.setToolTip(
            "Apply the current filter settings and redraw the LFP waveform."
        )
        self.apply_filter_button.clicked.connect(self.apply_lfp_filter_settings)

        self.spectrum_button = QPushButton("Power spectrum")
        self.spectrum_button.setEnabled(False)
        self.spectrum_button.setToolTip(
            "Calculate the power spectrum of the selected LFP time range."
        )
        self.spectrum_button.clicked.connect(
            lambda _checked=False: self.show_lfp_analysis("power_spectrum")
        )

        self.spectrogram_button = QPushButton("Spectrogram")
        self.spectrogram_button.setEnabled(False)
        self.spectrogram_button.setToolTip(
            "Calculate the time-frequency map of the selected LFP time range."
        )
        self.spectrogram_button.clicked.connect(
            lambda _checked=False: self.show_lfp_analysis("spectrogram")
        )

        self.follow_video_checkbox = QCheckBox("Follow video playback")
        self.follow_video_checkbox.setChecked(self.data_state.follow_video_playback)
        self.follow_video_checkbox.toggled.connect(
            self.set_follow_video_playback
        )
        self.follow_video_checkbox.setToolTip(
            "Auto-pan the waveform time window while the video is playing."
        )

        waveform_grid = QGridLayout()
        waveform_grid.setVerticalSpacing(8)
        waveform_grid.setColumnStretch(1, 1)
        waveform_grid.setRowStretch(0, 3)
        waveform_grid.setRowStretch(1, 2)

        self.lfp_waveform_area = self.create_waveform_area(
            "Import LFP CSV to show waveform"
        )
        self.lfp_waveform_area.setFixedHeight(100)
        self.axis_waveform_area = self.create_waveform_area(
            "Import 3-axis CSV to show waveform"
        )
        self.axis_waveform_area.setFixedHeight(80)

        waveform_grid.addWidget(QLabel("LFP"), 0, 0)
        waveform_grid.addWidget(self.lfp_waveform_area, 0, 1)

        waveform_grid.addWidget(QLabel("3-axis"), 1, 0)
        waveform_grid.addWidget(self.axis_waveform_area, 1, 1)

        self.timeline_area = self.create_waveform_area("Shared time range")
        self.timeline_area.setFixedHeight(44)
        self.timeline_area.layout().setContentsMargins(1, 0, 1, 2)

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 4, 8, 3)
        layout.setSpacing(4)

        layout.addWidget(self.lfp_file_label)

        channel_layout = QHBoxLayout()
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.setSpacing(8)
        channel_layout.addWidget(QLabel("Channel"))
        channel_layout.addWidget(self.lfp_channel_selector)
        channel_layout.addWidget(QLabel("Signal"))
        channel_layout.addWidget(self.signal_view_selector)
        channel_layout.addStretch()
        channel_layout.addWidget(self.follow_video_checkbox)
        layout.addLayout(channel_layout)

        filter_layout = QHBoxLayout()
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(6)
        filter_layout.addWidget(self.bandpass_checkbox)
        filter_layout.addWidget(QLabel("Low"))
        filter_layout.addWidget(self.bandpass_low_spin)
        filter_layout.addWidget(QLabel("High"))
        filter_layout.addWidget(self.bandpass_high_spin)
        filter_layout.addWidget(self.notch_checkbox)
        filter_layout.addWidget(self.apply_filter_button)
        filter_layout.addStretch()
        filter_layout.addWidget(self.spectrum_button)
        filter_layout.addWidget(self.spectrogram_button)
        layout.addLayout(filter_layout)

        layout.addWidget(self.axis_file_label)
        layout.addLayout(waveform_grid, stretch=1)
        layout.addWidget(self.timeline_area)

        self.setLayout(layout)

        self.apply_project_state()
        for signal in (
            self.bandpass_checkbox.stateChanged,
            self.bandpass_low_spin.valueChanged,
            self.bandpass_high_spin.valueChanged,
            self.notch_checkbox.stateChanged,
        ):
            try:
                signal.disconnect(self.refresh_lfp_processing)
            except (RuntimeError, TypeError):
                pass
            signal.connect(self.mark_lfp_filter_settings_pending)
        self.signal_view_selector.currentIndexChanged.disconnect(
            self.refresh_lfp_processing
        )
        self.signal_view_selector.currentIndexChanged.connect(
            self.switch_lfp_signal_view
        )
        self.apply_filter_button.setEnabled(False)

    def apply_project_state(self):
        """Apply the shared project state to the waveform controls."""
        settings = self.data_state.lfp_filter_settings
        show_filtered = bool(settings.get("show_filtered", False))
        self.signal_view_selector.setCurrentIndex(1 if show_filtered else 0)
        self.bandpass_checkbox.setChecked(
            bool(settings.get("bandpass_enabled", False))
        )
        self.bandpass_low_spin.setValue(
            float(settings.get("bandpass_low_hz", 1.0))
        )
        self.bandpass_high_spin.setValue(
            float(settings.get("bandpass_high_hz", 100.0))
        )
        self.notch_checkbox.setChecked(settings.get("line_noise_hz") is not None)
        self.follow_video_checkbox.setChecked(self.data_state.follow_video_playback)
        self._applied_lfp_filter_settings = self.pending_lfp_filter_settings()
        self.update_notch_control_text()
        self.apply_filter_button.setEnabled(False)

    def store_lfp_filter_settings(self, settings):
        """Keep the applied filter configuration in the project state."""
        self.data_state.lfp_filter_settings = {
            "show_filtered": bool(settings.show_filtered),
            "bandpass_enabled": bool(settings.bandpass_enabled),
            "bandpass_low_hz": float(settings.bandpass_low_hz),
            "bandpass_high_hz": float(settings.bandpass_high_hz),
            "line_noise_hz": (
                None
                if settings.line_noise_hz is None
                else float(settings.line_noise_hz)
            ),
            "notch_quality": float(settings.notch_quality),
        }
        self.project_changed.emit()

    def set_follow_video_playback(self, enabled):
        """Keep the playback-follow preference in the project state."""
        self.data_state.follow_video_playback = bool(enabled)
        self.project_changed.emit()


    def create_frequency_spinbox(self, value):
        """Create frequency spinbox.

        Args:
            value: New value to store or apply.
        """
        spinbox = QDoubleSpinBox()
        spinbox.setDecimals(2)
        spinbox.setRange(0.01, 10000.0)
        spinbox.setSingleStep(1.0)
        spinbox.setValue(float(value))
        spinbox.setSuffix(" Hz")
        spinbox.setMaximumWidth(95)
        return spinbox

    def format_line_noise_label(self):
        """Format line noise label.

        Args:
            None.
        """
        return f"{self.data_state.line_noise_hz:g} Hz" if self.data_state.line_noise_hz else "not set"

    def update_notch_control_text(self):
        """Update notch control text.

        Args:
            None.
        """
        label = self.format_line_noise_label()
        self.notch_checkbox.setText(f"Notch {label}")
        self.notch_checkbox.setToolTip(
            f"Apply {label} power-line noise notch filter when Filtered is selected."
        )

    def create_waveform_area(self, text):
        """Create waveform area.

        Args:
            text: Text displayed to the user.
        """
        frame = QFrame()
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        frame.setStyleSheet(
            """
            QFrame {
                background-color: #fbfbfb;
                border: 1px solid #d0d0d0;
            }
            """
        )

        frame.setToolTip(text)
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        placeholder = QLabel(text)
        placeholder.setAlignment(Qt.AlignCenter)  # type: ignore
        placeholder.setStyleSheet("color: #777; border: none;")
        layout.addWidget(placeholder)
        frame.setLayout(layout)
        return frame

    def set_figure(self, frame, canvas_attr, fig):
        """Set figure."""
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

        old_canvas = getattr(self, canvas_attr)
        if old_canvas is not None:
            old_canvas.setParent(None)
            old_canvas.deleteLater()

        layout = frame.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        canvas = FigureCanvas(fig)
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.connect_canvas_events(canvas)
        layout.addWidget(canvas)
        setattr(self, canvas_attr, canvas)
        self.invalidate_current_time_backgrounds()
        self.apply_sync_time_axis_formatters()
        canvas.draw_idle()

    def timeline_limits(self):
        """Convert time to line limits.

        Args:
            None.
        """
        limits = []

        if self.lfp_fig is not None:
            limits.append(self.lfp_fig.lfp_full_xlim)

        if self.axis_fig is not None:
            limits.append(self.axis_fig.axis_full_xlim)

        if not limits:
            return None

        return min(limit[0] for limit in limits), max(limit[1] for limit in limits)

    def set_shared_xlim(self, left, right, source=None):
        """Set shared xlim."""
        if self.updating_timeline:
            return

        left, right = float(left), float(right)
        self.data_state.timeline_xlim = (left, right)
        self.updating_timeline = True

        if self.lfp_fig is not None and source != "lfp":
            self.lfp_fig.set_lfp_xlim(left, right, emit=False)

        if self.axis_fig is not None and source != "axis":
            self.axis_fig.set_axis_xlim(left, right, emit=False)

        if self.timeline_slider is not None and source != "timeline":
            self.timeline_slider.set_val((left, right), emit=False)

        self.invalidate_current_time_backgrounds()
        self.updating_timeline = False
        dataset = self.data_state.lfp_dataset
        if dataset is not None:
            dataset.update_visible_range(
                left,
                right,
                self.current_lfp_filter_settings(),
            )

    def on_plot_xlim_changed(self, value, source):
        if self.updating_timeline:
            return

        left, right = value
        self.set_shared_xlim(float(left), float(right), source=source)

    def should_follow_video_playback(self):
        return self.follow_video_checkbox.isChecked()

    def set_sync_time_origin(self, origin_sec):
        """Set sync time origin."""
        next_origin = None if origin_sec is None else float(origin_sec)
        if self.sync_state.record_time_origin_sec == next_origin:
            return

        self.sync_state.record_time_origin_sec = next_origin
        self.apply_sync_time_axis_formatters()

    def apply_sync_time_axis_formatters(self):
        """Apply sync time axis formatters.

        Args:
            None.
        """
        formatter = FuncFormatter(
            lambda value, pos: format_time_tick(value, self.sync_state.record_time_origin_sec)
        )

        for _key, fig, canvas in self.figure_items():
            if fig is None or canvas is None or not fig.axes:
                continue

            fig.axes[0].xaxis.set_major_formatter(formatter)
            canvas.draw_idle()

        if self.timeline_slider is not None:
            self.timeline_slider.set_time_origin(self.sync_state.record_time_origin_sec)

        self.invalidate_current_time_backgrounds()

    def connect_canvas_events(self, canvas):
        """Connect canvas events.

        Args:
            canvas: Matplotlib canvas to configure.
        """
        canvas.mpl_connect("draw_event", self.on_canvas_draw)
        canvas.mpl_connect("button_press_event", self.on_canvas_press)
        canvas.mpl_connect("button_release_event", self.on_canvas_release)

    def is_seekable_axis(self, ax):
        """Determine whether seekable axis.

        Args:
            ax: Matplotlib axes to draw on.
        """
        return any(
            fig is not None and fig.axes and ax is fig.axes[0]
            for _key, fig, _canvas in self.figure_items()
        )

    def on_canvas_press(self, event):
        if (
            event.button != 1
            or event.inaxes is None
            or event.xdata is None
            or getattr(event, "dblclick", False)
            or not self.is_seekable_axis(event.inaxes)
        ):
            self.click_seek_state = None
            return

        self.click_seek_state = {
            "canvas": event.canvas,
            "ax": event.inaxes,
            "x": event.x,
            "y": event.y,
            "xdata": float(event.xdata),
        }

    def on_canvas_release(self, event):
        state = self.click_seek_state
        self.click_seek_state = None
        if state is None:
            return

        if (
            event.button != 1
            or event.canvas is not state["canvas"]
            or event.inaxes is not state["ax"]
        ):
            return

        dx = abs(float(event.x or 0) - float(state["x"] or 0))
        dy = abs(float(event.y or 0) - float(state["y"] or 0))
        if dx > 5 or dy > 5:
            return

        record_time_sec = (
            float(event.xdata) if event.xdata is not None else state["xdata"]
        )
        self.time_selected.emit(record_time_sec)

    def follow_current_time_marker(self, force=False):
        if (
            self.sync_state.current_record_time_sec is None
            or (not force and not self.should_follow_video_playback())
        ):
            return

        full_xlim = self.timeline_full_xlim or self.timeline_limits()
        if full_xlim is None:
            return

        full_left, full_right = full_xlim
        full_width = full_right - full_left
        if full_width <= 0:
            return

        current_xlim = self.data_state.timeline_xlim or full_xlim
        left, right = current_xlim
        current_width = max(right - left, 1e-6)
        default_width = min(self.DEFAULT_PLAYBACK_WINDOW_SEC, full_width)

        if current_width >= full_width * 0.98:
            target_width = default_width
            force_recenter = force or target_width < current_width
        else:
            target_width = min(current_width, full_width)
            force_recenter = force

        if target_width >= full_width:
            next_left, next_right = full_left, full_right
        else:
            cursor_time = min(
                max(float(self.sync_state.current_record_time_sec), full_left),
                full_right,
            )
            margin = target_width * self.PLAYBACK_EDGE_MARGIN_FRACTION
            needs_follow = (
                force_recenter
                or cursor_time < left + margin
                or cursor_time > right - margin
            )
            if not needs_follow:
                return

            next_left = cursor_time - target_width * self.PLAYBACK_CURSOR_FRACTION
            next_right = next_left + target_width
            next_left, next_right = clamp_xlim(
                next_left,
                next_right,
                full_xlim,
            )

        if abs(next_left - left) < 1e-9 and abs(next_right - right) < 1e-9:
            return

        self.set_shared_xlim(next_left, next_right, source="playback")

    def figure_items(self):
        return [
            ("lfp", self.lfp_fig, self.lfp_canvas),
            ("axis", self.axis_fig, self.axis_canvas),
            ("timeline", self.timeline_fig, self.timeline_canvas),
        ]

    def invalidate_current_time_backgrounds(self, key=None):
        """Invalidate current time backgrounds."""
        if key is None:
            self.current_time_backgrounds = {}
            return

        self.current_time_backgrounds.pop(key, None)

    def background_signature(self, canvas, ax):
        return (
            canvas.get_width_height(),
            tuple(round(value, 6) for value in ax.bbox.bounds),
            tuple(round(value, 9) for value in ax.get_xlim()),
            tuple(round(value, 9) for value in ax.get_ylim()),
        )

    def supports_marker_blit(self, canvas):
        return all(
            hasattr(canvas, name)
            for name in ("copy_from_bbox", "restore_region", "blit")
        )

    def on_canvas_draw(self, event):
        for key, fig, canvas in self.figure_items():
            if canvas is not event.canvas:
                continue

            line = self.current_time_lines.get(key)
            if fig is None or canvas is None or line is None or not fig.axes:
                return

            ax = fig.axes[0]
            if line.axes is not ax or not self.supports_marker_blit(canvas):
                return

            try:
                self.current_time_backgrounds[key] = (
                    self.background_signature(canvas, ax),
                    canvas.copy_from_bbox(ax.bbox),
                )
                ax.draw_artist(line)
                canvas.blit(ax.bbox)
            except Exception:
                self.invalidate_current_time_backgrounds(key)
            return

    def draw_marker_line(self, key, canvas, ax, line):
        """Draw marker line.

        Args:
            canvas: Matplotlib canvas to configure.
            ax: Matplotlib axes to draw on.
        """
        if not self.supports_marker_blit(canvas):
            canvas.draw_idle()
            return

        signature = self.background_signature(canvas, ax)
        cached = self.current_time_backgrounds.get(key)
        if cached is None or cached[0] != signature:
            canvas.draw_idle()
            return

        try:
            canvas.restore_region(cached[1])
            ax.draw_artist(line)
            canvas.blit(ax.bbox)
        except Exception:
            self.invalidate_current_time_backgrounds(key)
            canvas.draw_idle()

    def create_or_update_timeline(self):
        """Create or update timeline.

        Args:
            None.
        """
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

        full_xlim = self.timeline_limits()
        if full_xlim is None:
            return

        if self.timeline_full_xlim == full_xlim and self.timeline_slider is not None:
            current_xlim = self.data_state.timeline_xlim
            if current_xlim is not None:
                self.set_shared_xlim(*current_xlim, source="timeline")
            return

        old_canvas = self.timeline_canvas
        if old_canvas is not None:
            old_canvas.setParent(None)
            old_canvas.deleteLater()

        layout = self.timeline_area.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        fig = Figure(figsize=(8, 0.50), constrained_layout=False)
        slider_ax = fig.add_axes((0.12, 0.34, 0.76, 0.34))
        slider = SharedTimelineSlider(
            slider_ax,
            full_xlim,
            full_xlim,
        )
        slider.set_time_origin(self.sync_state.record_time_origin_sec)
        slider.on_changed(lambda value: self.on_plot_xlim_changed(value, "timeline"))

        canvas = FigureCanvas(fig)
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        canvas.setFixedHeight(40)
        self.connect_canvas_events(canvas)
        layout.addWidget(canvas)

        self.timeline_fig = fig
        self.timeline_slider = slider
        self.timeline_canvas = canvas
        self.timeline_full_xlim = full_xlim
        self.invalidate_current_time_backgrounds()
        canvas.draw_idle()

        self.set_shared_xlim(*full_xlim, source="timeline")
        self.update_event_interval_artists()
        self.update_current_time_marker()

    def set_current_time_marker(
        self,
        record_time_sec,
        follow_playback=False,
        force_follow=False,
    ):
        """Set current time marker.

        Args:
            force_follow: Recenter the visible waveform around this time.
        """
        self.sync_state.current_record_time_sec = record_time_sec

        if follow_playback or force_follow:
            self.follow_current_time_marker(force=force_follow)

        self.update_current_time_marker()

    def clear_current_time_marker(self):
        """Clear current time marker.

        Args:
            None.
        """
        self.sync_state.current_record_time_sec = None
        for line in self.current_time_lines.values():
            line.remove()
        self.current_time_lines = {}
        self.invalidate_current_time_backgrounds()

        for canvas in [self.lfp_canvas, self.axis_canvas, self.timeline_canvas]:
            if canvas is not None:
                canvas.draw_idle()

    def set_event_intervals(self, intervals):
        """Set event intervals."""
        self.sync_state.event_intervals = [dict(interval) for interval in intervals]
        self.update_event_interval_artists()

    def clear_event_interval_artists(self):
        """Clear event interval artists.

        Args:
            None.
        """
        for artist in self.event_interval_artists:
            try:
                artist.remove()
            except (RuntimeError, ValueError):
                pass
        self.event_interval_artists = []

    def update_event_interval_artists(self):
        """Update event interval artists.

        Args:
            None.
        """
        self.clear_event_interval_artists()

        for key, fig, canvas in self.figure_items():
            if fig is None or canvas is None or not fig.axes:
                continue

            ax = fig.axes[0]
            for interval in self.sync_state.event_intervals:
                event_type = interval.get("event_type", "action")
                if event_type == "ttl":
                    self.event_interval_artists.append(
                        ax.axvline(
                            float(interval["record_time_sec"]),
                            color="#2eaf62",
                            linestyle="-",
                            linewidth=1.2,
                            zorder=4,
                        )
                    )
                    continue

                if event_type == "seizure_like_event":
                    self.event_interval_artists.append(
                        ax.axvline(
                            float(interval["record_time_sec"]),
                            color="#d62728",
                            linestyle="-",
                            linewidth=1.2,
                            zorder=3,
                        )
                    )
                    continue

                start_sec = float(interval["record_start_sec"])
                end_sec = float(interval["record_end_sec"])
                if end_sec <= start_sec:
                    continue

                color = "#2eaf62" if event_type == "led" else "#f39c12"
                alpha = 0.30 if event_type == "led" else 0.25
                self.event_interval_artists.append(
                    ax.axvspan(
                        start_sec,
                        end_sec,
                        color=color,
                        alpha=alpha,
                        linewidth=0,
                        zorder=1,
                    )
                )

            self.invalidate_current_time_backgrounds(key)
            canvas.draw_idle()

    def update_current_time_marker(self):
        """Update current time marker.

        Args:
            None.
        """
        if self.sync_state.current_record_time_sec is None:
            return

        dataset = self.data_state.lfp_dataset
        if dataset is not None:
            visible = self.data_state.timeline_xlim
            visible_preloaded = (
                visible is not None
                and dataset.update_visible_range(
                    visible[0],
                    visible[1],
                    self.current_lfp_filter_settings(),
                )
            )
            if not visible_preloaded:
                dataset.update_playback_window(
                    self.sync_state.current_record_time_sec,
                    self.current_lfp_filter_settings(),
                )

        for key, fig, canvas in self.figure_items():
            if fig is None or canvas is None or not fig.axes:
                continue

            ax = fig.axes[0]
            line = self.current_time_lines.get(key)
            if line is None or line.axes is not ax:
                line = ax.axvline(
                    self.sync_state.current_record_time_sec,
                    color="#d62728",
                    linestyle="--",
                    linewidth=1.0,
                    zorder=10,
                    animated=True,
                )
                self.current_time_lines[key] = line
                self.invalidate_current_time_backgrounds(key)
            else:
                line.set_xdata(
                    [
                        self.sync_state.current_record_time_sec,
                        self.sync_state.current_record_time_sec,
                    ]
                )

            self.draw_marker_line(key, canvas, ax, line)

    def selected_channel(self, selector):
        """Select ed channel."""
        channel = selector.currentData()
        if channel is None:
            return None

        try:
            return int(channel)
        except (TypeError, ValueError):
            return None

    def current_lfp_filter_settings(self):
        return self._applied_lfp_filter_settings

    def pending_lfp_filter_settings(self):
        return self.settings_from_processing_controls(
            self.signal_view_selector,
            self.bandpass_checkbox,
            self.bandpass_low_spin,
            self.bandpass_high_spin,
            self.notch_checkbox,
        )

    def mark_lfp_filter_settings_pending(self, *_args):
        """Mark lfp filter settings pending."""
        self.apply_filter_button.setEnabled(
            self.pending_lfp_filter_settings() != self._applied_lfp_filter_settings
        )

    def apply_lfp_filter_settings(self):
        """Apply lfp filter settings.

        Args:
            None.
        """
        settings = self.pending_lfp_filter_settings()
        if (
            settings.bandpass_enabled
            and settings.bandpass_low_hz >= settings.bandpass_high_hz
        ):
            QMessageBox.warning(
                self,
                "Invalid bandpass range",
                "Bandpass low cutoff must be lower than the high cutoff.",
            )
            return

        if settings == self._applied_lfp_filter_settings:
            self.apply_filter_button.setEnabled(False)
            return

        self._applied_lfp_filter_settings = settings
        self.store_lfp_filter_settings(settings)
        self.apply_filter_button.setEnabled(False)
        self.refresh_lfp_processing()

    def switch_lfp_signal_view(self, *_args):
        """Switch lfp signal view."""
        current = self._applied_lfp_filter_settings
        show_filtered = bool(self.signal_view_selector.currentData())
        self._applied_lfp_filter_settings = signal_func.LfpFilterSettings(
            show_filtered=show_filtered,
            bandpass_enabled=current.bandpass_enabled,
            bandpass_low_hz=current.bandpass_low_hz,
            bandpass_high_hz=current.bandpass_high_hz,
            line_noise_hz=current.line_noise_hz,
            notch_quality=current.notch_quality,
        )
        self.store_lfp_filter_settings(self._applied_lfp_filter_settings)
        self.mark_lfp_filter_settings_pending()
        self.project_changed.emit()
        if self.lfp_fig is None:
            if show_filtered:
                self.plot_lfp()
            return
        if show_filtered and not self._filtered_coarse_ready(
            self._applied_lfp_filter_settings
        ):
            self._start_filtered_coarse(
                self._applied_lfp_filter_settings,
                self._apply_ready_filtered_view,
            )
            return
        if not show_filtered:
            self._cancel_lfp_coarse_workers()
        self.lfp_fig.set_lfp_signal_view(show_filtered)
        self.update_current_time_marker()
        self.update_lfp_peak_artist()
        self.invalidate_current_time_backgrounds("lfp")

    def update_lfp_peak_artist(self) -> None:
        """Draw one second around every persisted LFP peak event."""
        fig = self.lfp_fig
        canvas = self.lfp_canvas
        if fig is None or canvas is None or not fig.axes:
            self.invalidate_current_time_backgrounds("lfp")
            return

        channel = self.selected_channel(self.lfp_channel_selector)
        filtered = bool(self.signal_view_selector.currentData())
        if channel is not None:
            dataset = self.ensure_lfp_dataset()
            local_times: list[float] = []
            local_values: list[float] = []

            markers = self.marker_store.all() if self.marker_store is not None else ()
            for marker in markers:
                if marker.kind != MarkerKind.LFP_PEAK:
                    continue
                marker_channel = marker.payload.get("channel")
                if marker_channel is not None and int(marker_channel) != channel:
                    continue
                peak_record_time = marker_record_time(
                    marker, self.sync_state.time_offset_sec
                )
                if peak_record_time is None:
                    continue
                segment = dataset.segment(
                    channel,
                    peak_record_time - 1.0,
                    peak_record_time + 1.0,
                    self.current_lfp_filter_settings(),
                )
                local_times.extend(segment.record_time_s)
                local_values.extend(segment.values)
                local_times.append(np.nan)
                local_values.append(np.nan)

            fig.set_lfp_peak_samples(
                channel,
                filtered,
                np.asarray(local_times, dtype=float),
                np.asarray(local_values, dtype=float),
            )

        self.invalidate_current_time_backgrounds("lfp")
        canvas.draw_idle()

    def set_line_noise_hz(self, line_noise_hz):
        """Set line noise hz."""
        next_value = 60.0 if line_noise_hz is None else float(line_noise_hz)
        if self.data_state.line_noise_hz == next_value:
            return

        self.data_state.line_noise_hz = next_value
        self.update_notch_control_text()
        if self._applied_lfp_filter_settings.line_noise_hz is not None:
            current = self._applied_lfp_filter_settings
            self._applied_lfp_filter_settings = signal_func.LfpFilterSettings(
                show_filtered=current.show_filtered,
                bandpass_enabled=current.bandpass_enabled,
                bandpass_low_hz=current.bandpass_low_hz,
                bandpass_high_hz=current.bandpass_high_hz,
                line_noise_hz=next_value,
                notch_quality=current.notch_quality,
            )
            self.store_lfp_filter_settings(self._applied_lfp_filter_settings)
            self.refresh_lfp_processing()
        self.mark_lfp_filter_settings_pending()

    def refresh_lfp_processing(self, *_args):
        """Refresh lfp processing."""
        if not (self.data_state.lfp_info and self.data_state.lfp_info.get("path")):
            return

        current_xlim = self.data_state.timeline_xlim
        self.lfp_fig = None
        self.lfp_callback_connected = False
        self.invalidate_current_time_backgrounds("lfp")
        self.plot_lfp()

        if current_xlim is not None:
            self.set_shared_xlim(*current_xlim, source="timeline")

    def current_lfp_record_xlim(self):
        selected_xlim = self.data_state.timeline_xlim
        if selected_xlim is None and self.lfp_fig is not None:
            selected_xlim = self.lfp_fig.lfp_full_xlim

        if selected_xlim is None:
            raise ValueError("Please select an LFP time range first.")

        left, right = sorted((float(selected_xlim[0]), float(selected_xlim[1])))
        return left, right

    def available_lfp_channels(self):
        dataset = self.data_state.lfp_dataset
        return [] if dataset is None else dataset.channels

    def ensure_lfp_dataset(self):
        """Return the already prepared shared dataset."""
        dataset = self.data_state.lfp_dataset
        if dataset is None:
            raise ValueError("Please import LFP CSV data first.")
        return dataset

    def plot_lfp(self):
        """Plot lfp.

        Args:
            None.
        """
        if not (self.data_state.lfp_info and self.data_state.lfp_info.get("path")):
            return

        channel = self.selected_channel(self.lfp_channel_selector)
        self.data_state.selected_lfp_channel = channel
        settings = self.current_lfp_filter_settings()
        if (
            channel is not None
            and settings.show_filtered
            and not self._filtered_coarse_ready(settings, channel)
        ):
            self._start_filtered_coarse(settings, self.plot_lfp, channel)
            return
        created_figure = False
        try:
            if self.lfp_fig is None:
                self.lfp_fig = draw.LFP(
                    channels=channel,
                    step=self.data_state.lfp_step,
                    filter_settings=self.current_lfp_filter_settings(),
                    dataset=self.ensure_lfp_dataset(),
                )
                created_figure = True
            elif self.lfp_fig is not None and channel is not None:
                self.lfp_fig.set_lfp_channel(channel)
                self.invalidate_current_time_backgrounds("lfp")
        except Exception as error:
            QMessageBox.warning(self, "LFP plot failed", str(error))
            return

        if created_figure or self.lfp_canvas is None:
            self.set_figure(self.lfp_waveform_area, "lfp_canvas", self.lfp_fig)
            # The Qt canvas now has its real on-screen width, so recompute
            # automatic LFP sampling once instead of keeping the nominal
            # pre-widget Figure width.
            self.lfp_fig.refresh_lfp_plot(recalculate_auto=True)

        if not self.lfp_callback_connected:
            self.lfp_fig.add_lfp_xlim_callback(
                lambda value: self.on_plot_xlim_changed(value, "lfp")
            )
            self.lfp_callback_connected = True

        self.create_or_update_timeline()
        self.update_event_interval_artists()
        self.update_lfp_peak_artist()
        self.update_current_time_marker()

    def plot_axis(self):
        """Plot axis.

        Args:
            None.
        """
        dataset = self.data_state.axis_dataset
        if dataset is None:
            return

        try:
            self.axis_fig = draw.accelerator(
                dataset=dataset,
                compact=True,
                step=self.data_state.axis_step,
            )
        except Exception as error:
            QMessageBox.warning(self, "3-axis plot failed", str(error))
            return

        self.set_figure(self.axis_waveform_area, "axis_canvas", self.axis_fig)

        if not self.axis_callback_connected:
            self.axis_fig.add_axis_xlim_callback(
                lambda value: self.on_plot_xlim_changed(value, "axis")
            )
            self.axis_callback_connected = True

        self.create_or_update_timeline()
        self.update_event_interval_artists()
        self.update_current_time_marker()

    def set_lfp_info(self, info):
        """Compatibility entry point that prepares and installs an LFP dataset."""
        dataset = self.data_state.load_lfp_info(info)
        self.set_lfp_dataset(dataset)

    def set_lfp_dataset(self, dataset):
        """Atomically install a prepared LFP dataset and refresh its controls."""
        self._cancel_lfp_coarse_workers()
        previous_dataset = self.data_state.lfp_dataset
        if previous_dataset is not None and previous_dataset is not dataset:
            previous_dataset.close(wait=True)
        self.data_state.lfp_dataset = dataset
        self.lfp_fig = None
        self.lfp_callback_connected = False
        if dataset is None:
            self.lfp_file_label.setText("LFP CSV: not loaded")
            self.lfp_channel_selector.blockSignals(True)
            self.lfp_channel_selector.clear()
            self.lfp_channel_selector.addItem("No LFP channel")
            self.lfp_channel_selector.setEnabled(False)
            self.spectrum_button.setEnabled(False)
            self.spectrogram_button.setEnabled(False)
            self.lfp_channel_selector.blockSignals(False)
            return

        info = dataset.info
        self.lfp_file_label.setText(f"LFP CSV: {info['filename']}")

        self.lfp_channel_selector.blockSignals(True)
        self.lfp_channel_selector.clear()

        channels = info.get("channels", [])

        if channels:
            for channel in channels:
                self.lfp_channel_selector.addItem(f"Channel {channel}", channel)

            selected_channel = self.data_state.selected_lfp_channel
            if selected_channel in channels:
                self.lfp_channel_selector.setCurrentIndex(
                    channels.index(selected_channel)
                )

            self.lfp_channel_selector.setEnabled(True)
            self.spectrum_button.setEnabled(True)
            self.spectrogram_button.setEnabled(True)
        else:
            self.lfp_channel_selector.addItem("No LFP channel")
            self.lfp_channel_selector.setEnabled(False)
            self.spectrum_button.setEnabled(False)
            self.spectrogram_button.setEnabled(False)

        self.lfp_channel_selector.blockSignals(False)
        self.plot_lfp()

    def _lfp_coarse_step(self, channel):
        dataset = self.ensure_lfp_dataset()
        sample_count = dataset.source.sample_count(channel)
        return max(
            resolve_plot_step(sample_count, self.data_state.lfp_step),
            1,
        )

    def _filtered_coarse_ready(self, settings, channel=None):
        dataset = self.data_state.lfp_dataset
        if dataset is None:
            return False
        if channel is None:
            channel = self.selected_channel(self.lfp_channel_selector)
        if channel is None:
            return False
        step = self._lfp_coarse_step(channel)
        return dataset.source.coarse_is_ready(step, settings)

    def _start_filtered_coarse(self, settings, callback, channel=None):
        dataset = self.ensure_lfp_dataset()
        if channel is None:
            channel = self.selected_channel(self.lfp_channel_selector)
        if channel is None:
            return
        step = self._lfp_coarse_step(channel)
        key = (dataset.source.identity_token(), step, settings)
        if (
            key == self._lfp_coarse_key
            and any(worker.isRunning() for worker in self._lfp_coarse_workers.values())
        ):
            return
        request_id = uuid.uuid4().hex
        self._cancel_lfp_coarse_workers()
        self._lfp_coarse_request_id = request_id
        self._lfp_coarse_key = key
        worker = signal_func.LfpCoarseWorker(
            request_id,
            dataset,
            channel,
            step,
            settings,
        )
        self._lfp_coarse_workers[request_id] = worker
        progress = QProgressDialog(
            "Building filtered overview…",
            "Cancel",
            0,
            100,
            self,
        )
        progress.setWindowTitle("Filtered LFP")
        progress.setWindowModality(Qt.WindowModality.NonModal)
        progress.setAutoClose(False)
        self._lfp_coarse_progress = progress
        worker.progress.connect(self._update_lfp_coarse_progress)
        worker.completed.connect(
            lambda result_id, identity, _result: self._finish_lfp_coarse(
                result_id,
                identity,
                settings,
                callback,
            )
        )
        worker.failed.connect(self._fail_lfp_coarse)
        worker.canceled.connect(
            lambda result_id, _identity: self._complete_lfp_coarse_request(
                result_id
            )
        )
        progress.canceled.connect(worker.cancel)
        worker.finished.connect(
            lambda result_id=request_id: self._discard_lfp_coarse_worker(
                result_id
            )
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()
        progress.show()

    def _lfp_coarse_result_is_current(self, request_id, identity):
        dataset = self.data_state.lfp_dataset
        if (
            request_id != self._lfp_coarse_request_id
            or not widget_is_valid(self)
            or dataset is None
        ):
            return False
        try:
            return dataset.source.identity_token() == identity
        except OSError:
            return False

    def _update_lfp_coarse_progress(self, request_id, value):
        if request_id != self._lfp_coarse_request_id:
            return
        if self._lfp_coarse_progress is not None and widget_is_valid(
            self._lfp_coarse_progress
        ):
            self._lfp_coarse_progress.setValue(value)

    def _finish_lfp_coarse(
        self,
        request_id,
        identity,
        settings,
        callback,
    ):
        if not self._lfp_coarse_result_is_current(request_id, identity):
            return
        if settings != self.current_lfp_filter_settings():
            self._complete_lfp_coarse_request(request_id)
            return
        self._complete_lfp_coarse_request(request_id)
        callback()

    def _fail_lfp_coarse(self, request_id, identity, message):
        if not self._lfp_coarse_result_is_current(request_id, identity):
            return
        self._complete_lfp_coarse_request(request_id)
        QMessageBox.warning(self, "Filtered LFP failed", message)

    def _complete_lfp_coarse_request(self, request_id):
        if request_id != self._lfp_coarse_request_id:
            return
        if self._lfp_coarse_progress is not None and widget_is_valid(
            self._lfp_coarse_progress
        ):
            self._lfp_coarse_progress.close()
        self._lfp_coarse_progress = None
        self._lfp_coarse_key = None

    def _discard_lfp_coarse_worker(self, request_id):
        self._lfp_coarse_workers.pop(request_id, None)

    def _cancel_lfp_coarse_workers(self, wait=False):
        workers = list(self._lfp_coarse_workers.values())
        for worker in workers:
            worker.cancel()
        if wait:
            for worker in workers:
                worker.wait(10_000)
        self._lfp_coarse_key = None
        return not any(worker.isRunning() for worker in workers)

    def _apply_ready_filtered_view(self):
        if self.lfp_fig is None:
            self.plot_lfp()
            return
        self.lfp_fig.set_lfp_signal_view(True)
        self.update_current_time_marker()
        self.update_lfp_peak_artist()

    def stop_background_work(self, wait=False):
        analysis_stopped = self._cancel_lfp_analysis_workers(wait=wait)
        coarse_stopped = self._cancel_lfp_coarse_workers(wait=wait)
        return analysis_stopped and coarse_stopped

    def set_axis_info(self, info):
        """Compatibility entry point that prepares and installs an axis dataset."""
        dataset = self.data_state.load_axis_info(info)
        self.set_axis_dataset(dataset)

    def set_axis_dataset(self, dataset):
        """Atomically install a prepared axis dataset and refresh its plot."""
        self.data_state.axis_dataset = dataset
        self.axis_fig = None
        self.axis_callback_connected = False
        if dataset is None:
            self.axis_file_label.setText("3-axis CSV: not loaded")
            return
        info = dataset.info
        self.axis_file_label.setText(f"3-axis CSV: {info['filename']} (channel 260)")
        self.plot_axis()

    def set_plot_step(self, plot_name, step):
        """Set plot step."""
        step_attribute, info_attribute, figure_attribute, callback_attribute, plot = {
            "lfp": (
                "lfp_step",
                "lfp_info",
                "lfp_fig",
                "lfp_callback_connected",
                self.plot_lfp,
            ),
            "axis": (
                "axis_step",
                "axis_info",
                "axis_fig",
                "axis_callback_connected",
                self.plot_axis,
            ),
        }[plot_name]
        step = None if step is None else max(int(step), 0)
        if getattr(self.data_state, step_attribute) == step:
            return

        setattr(self.data_state, step_attribute, step)
        self.project_changed.emit()
        info = getattr(self.data_state, info_attribute)
        if not (info and info.get("path")):
            return

        current_xlim = self.data_state.timeline_xlim
        setattr(self, figure_attribute, None)
        setattr(self, callback_attribute, False)
        plot()

        if current_xlim is not None:
            self.set_shared_xlim(*current_xlim, source="timeline")
