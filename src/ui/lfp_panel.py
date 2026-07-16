from .. import plotting as draw
import numpy as np
from .. import signal_processing as signal_func
from ..data_io import csv_loader
from ..data_io import readers as read
from ..plotting.plot_utils import (
    clamp_xlim,
    format_signal_label,
    format_time_tick,
    resolve_plot_step,
)
from ..state import DataState, SyncState
from ..time_utils import relative_time
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter


class PlaybackAwareComboBox(QComboBox):
    def showPopup(self):
        """Describe showPopup.

        Args:
            None.
        """
        view = self.view()
        if view is not None:
            contents_width = view.sizeHintForColumn(0)
            scrollbar_width = view.verticalScrollBar().sizeHint().width()
            view.setMinimumWidth(
                max(self.width(), contents_width + scrollbar_width + 24)
            )
        super().showPopup()


class SharedTimelineSlider:
    def __init__(self, ax, full_xlim, valinit):
        self.ax = ax
        self.full_xlim = full_xlim
        self.val = valinit
        self.callbacks = []
        self.drag_state = None
        self.time_origin_sec = None
        self.min_width = max((full_xlim[1] - full_xlim[0]) / 10000, 1e-6)

        self.ax.set_xlim(full_xlim)
        self.ax.set_ylim(0, 1)
        self.ax.set_yticks([])
        self.ax.tick_params(axis="x", labelsize=6, pad=0)
        for spine in self.ax.spines.values():
            spine.set_visible(False)

        self.track = Rectangle(
            (full_xlim[0], 0.35),
            full_xlim[1] - full_xlim[0],
            0.3,
            facecolor="#e6e6e6",
            edgecolor="none",
        )
        self.poly = Rectangle(
            (valinit[0], 0.35),
            valinit[1] - valinit[0],
            0.3,
            facecolor="#4c78a8",
            alpha=0.85,
            edgecolor="none",
        )
        handle_style = {
            "marker": "o",
            "markersize": 6,
            "markerfacecolor": "#ffffff",
            "markeredgecolor": "#c0c0c0",
            "markeredgewidth": 1.0,
            "linestyle": "None",
            "zorder": 3,
        }
        self.left_handle = self.ax.plot([valinit[0]], [0.5], **handle_style)[0]
        self.right_handle = self.ax.plot([valinit[1]], [0.5], **handle_style)[0]
        self.label = self.ax.text(
            full_xlim[0],
            0.5,
            "Time",
            fontsize=6,
            ha="right",
            va="center",
        )
        self.valtext = self.ax.text(
            0.5,
            1.02,
            "",
            fontsize=6,
            ha="center",
            va="bottom",
            transform=self.ax.transAxes,
        )

        self.ax.add_patch(self.track)
        self.ax.add_patch(self.poly)
        self.update_artists()

        canvas = self.ax.figure.canvas
        canvas.mpl_connect("button_press_event", self.on_press)
        canvas.mpl_connect("motion_notify_event", self.on_motion)
        canvas.mpl_connect("button_release_event", self.on_release)

    def on_changed(self, callback):
        """Describe on_changed.

        Args:
            callback: Input accepted by this method.
        """
        self.callbacks.append(callback)

    def set_time_origin(self, origin_sec):
        """Describe set_time_origin.

        Args:
            origin_sec: Input accepted by this method.
        """
        self.time_origin_sec = None if origin_sec is None else float(origin_sec)
        self.ax.xaxis.set_major_formatter(
            FuncFormatter(
                lambda value, pos: format_time_tick(value, self.time_origin_sec)
            )
        )
        self.label.set_text("Sync t" if self.time_origin_sec is not None else "Time")
        self.update_artists()
        self.ax.figure.canvas.draw_idle()

    def set_val(self, value, emit=True):
        """Describe set_val.

        Args:
            value: Input accepted by this method.
            emit: Input accepted by this method.
        """
        left, right = clamp_xlim(float(value[0]), float(value[1]), self.full_xlim)
        if right - left < self.min_width:
            right = left + self.min_width
            left, right = clamp_xlim(left, right, self.full_xlim)

        self.val = (left, right)
        self.update_artists()
        self.ax.figure.canvas.draw_idle()

        if emit:
            for callback in self.callbacks:
                callback(self.val)

    def update_artists(self):
        """Describe update_artists.

        Args:
            None.
        """
        left, right = self.val
        self.poly.set_x(left)
        self.poly.set_width(right - left)
        self.left_handle.set_data([left], [0.5])
        self.right_handle.set_data([right], [0.5])
        display_left = relative_time(left, self.time_origin_sec)
        display_right = relative_time(right, self.time_origin_sec)
        self.valtext.set_text(f"({display_left:.2f} s, {display_right:.2f} s)")

    def on_press(self, event):
        """Describe on_press.

        Args:
            event: Input accepted by this method.
        """
        if event.inaxes != self.ax or event.button != 1 or event.xdata is None:
            return

        left, right = self.val
        full_width = self.full_xlim[1] - self.full_xlim[0]
        handle_margin = max(full_width * 0.01, self.min_width)

        if abs(event.xdata - left) <= handle_margin:
            mode = "left"
        elif abs(event.xdata - right) <= handle_margin:
            mode = "right"
        elif left < event.xdata < right:
            mode = "pan"
        else:
            return

        self.drag_state = {
            "mode": mode,
            "x": float(event.xdata),
            "left": left,
            "right": right,
        }

    def on_motion(self, event):
        """Describe on_motion.

        Args:
            event: Input accepted by this method.
        """
        if self.drag_state is None or event.xdata is None:
            return

        mode = self.drag_state["mode"]
        xdata = float(event.xdata)
        left = self.drag_state["left"]
        right = self.drag_state["right"]

        if mode == "left":
            next_left = min(xdata, right - self.min_width)
            self.set_val((next_left, right))
        elif mode == "right":
            next_right = max(xdata, left + self.min_width)
            self.set_val((left, next_right))
        elif mode == "pan":
            dx = xdata - self.drag_state["x"]
            self.set_val((left + dx, right + dx))

    def on_release(self, event):
        """Describe on_release.

        Args:
            event: Input accepted by this method.
        """
        self.drag_state = None


class LfpPanel(QWidget):
    time_selected = Signal(float)

    DEFAULT_PLAYBACK_WINDOW_SEC = 30.0
    PLAYBACK_CURSOR_FRACTION = 0.35
    PLAYBACK_EDGE_MARGIN_FRACTION = 0.18

    def __init__(self, data_state=None, sync_state=None):
        super().__init__()
        self.data_state = data_state or DataState()
        self.sync_state = sync_state or SyncState()
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
        self.follow_video_checkbox.setChecked(True)
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

        self._applied_lfp_filter_settings = self.pending_lfp_filter_settings()
        for control, signal in (
            (self.bandpass_checkbox, self.bandpass_checkbox.stateChanged),
            (self.bandpass_low_spin, self.bandpass_low_spin.valueChanged),
            (self.bandpass_high_spin, self.bandpass_high_spin.valueChanged),
            (self.notch_checkbox, self.notch_checkbox.stateChanged),
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

    @property
    def lfp_info(self):
        """Describe lfp_info.

        Args:
            None.
        """
        return self.data_state.lfp_info

    @lfp_info.setter
    def lfp_info(self, info):
        """Describe lfp_info.

        Args:
            info: Input accepted by this method.
        """
        self.data_state.lfp_info = info

    @property
    def axis_info(self):
        """Describe axis_info.

        Args:
            None.
        """
        return self.data_state.axis_info

    @axis_info.setter
    def axis_info(self, info):
        """Describe axis_info.

        Args:
            info: Input accepted by this method.
        """
        self.data_state.axis_info = info

    @property
    def lfp_path(self):
        """Describe lfp_path.

        Args:
            None.
        """
        return self.lfp_info.get("path") if self.lfp_info else None

    @property
    def axis_path(self):
        """Describe axis_path.

        Args:
            None.
        """
        return self.axis_info.get("path") if self.axis_info else None

    @property
    def lfp_step(self):
        """Describe lfp_step.

        Args:
            None.
        """
        return self.data_state.lfp_step

    @lfp_step.setter
    def lfp_step(self, step):
        """Describe lfp_step.

        Args:
            step: Input accepted by this method.
        """
        self.data_state.lfp_step = step

    @property
    def axis_step(self):
        """Describe axis_step.

        Args:
            None.
        """
        return self.data_state.axis_step

    @axis_step.setter
    def axis_step(self, step):
        """Describe axis_step.

        Args:
            step: Input accepted by this method.
        """
        self.data_state.axis_step = step

    @property
    def line_noise_hz(self):
        """Describe line_noise_hz.

        Args:
            None.
        """
        return self.data_state.line_noise_hz

    @line_noise_hz.setter
    def line_noise_hz(self, frequency):
        """Describe line_noise_hz.

        Args:
            frequency: Input accepted by this method.
        """
        self.data_state.line_noise_hz = float(frequency)

    @property
    def sync_time_origin_sec(self):
        """Describe sync_time_origin_sec.

        Args:
            None.
        """
        return self.sync_state.record_time_origin_sec

    @sync_time_origin_sec.setter
    def sync_time_origin_sec(self, origin_sec):
        """Describe sync_time_origin_sec.

        Args:
            origin_sec: Input accepted by this method.
        """
        self.sync_state.record_time_origin_sec = origin_sec

    @property
    def current_record_time_sec(self):
        """Describe current_record_time_sec.

        Args:
            None.
        """
        return self.sync_state.current_record_time_sec

    @current_record_time_sec.setter
    def current_record_time_sec(self, time_sec):
        """Describe current_record_time_sec.

        Args:
            time_sec: Input accepted by this method.
        """
        self.sync_state.current_record_time_sec = time_sec

    @property
    def event_intervals(self):
        """Describe event_intervals.

        Args:
            None.
        """
        return self.sync_state.event_intervals

    @event_intervals.setter
    def event_intervals(self, intervals):
        """Describe event_intervals.

        Args:
            intervals: Input accepted by this method.
        """
        self.sync_state.event_intervals = list(intervals)

    def create_frequency_spinbox(self, value):
        """Describe create_frequency_spinbox.

        Args:
            value: Input accepted by this method.
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
        """Describe format_line_noise_label.

        Args:
            None.
        """
        return f"{self.line_noise_hz:g} Hz" if self.line_noise_hz else "not set"

    def update_notch_control_text(self):
        """Describe update_notch_control_text.

        Args:
            None.
        """
        label = self.format_line_noise_label()
        self.notch_checkbox.setText(f"Notch {label}")
        self.notch_checkbox.setToolTip(
            f"Apply {label} power-line noise notch filter when Filtered is selected."
        )

    def create_waveform_area(self, text):
        """Describe create_waveform_area.

        Args:
            text: Input accepted by this method.
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
        """Describe set_figure.

        Args:
            frame: Input accepted by this method.
            canvas_attr: Input accepted by this method.
            fig: Input accepted by this method.
        """
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
        """Describe timeline_limits.

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
        """Describe set_shared_xlim.

        Args:
            left: Input accepted by this method.
            right: Input accepted by this method.
            source: Input accepted by this method.
        """
        if self.updating_timeline:
            return

        self.updating_timeline = True

        if self.lfp_fig is not None and source != "lfp":
            self.lfp_fig.set_lfp_xlim(left, right, emit=False)

        if self.axis_fig is not None and source != "axis":
            self.axis_fig.set_axis_xlim(left, right, emit=False)

        if self.timeline_slider is not None and source != "timeline":
            self.timeline_slider.set_val((left, right), emit=False)

        self.invalidate_current_time_backgrounds()
        self.updating_timeline = False

    def on_plot_xlim_changed(self, value, source):
        """Describe on_plot_xlim_changed.

        Args:
            value: Input accepted by this method.
            source: Input accepted by this method.
        """
        if self.updating_timeline:
            return

        left, right = value
        self.set_shared_xlim(float(left), float(right), source=source)

    def current_timeline_xlim(self):
        """Describe current_timeline_xlim.

        Args:
            None.
        """
        if self.timeline_slider is None:
            return None

        left, right = self.timeline_slider.val
        return float(left), float(right)

    def should_follow_video_playback(self):
        """Describe should_follow_video_playback.

        Args:
            None.
        """
        return self.follow_video_checkbox.isChecked()

    def set_sync_time_origin(self, origin_sec):
        """Describe set_sync_time_origin.

        Args:
            origin_sec: Input accepted by this method.
        """
        next_origin = None if origin_sec is None else float(origin_sec)
        if self.sync_time_origin_sec == next_origin:
            return

        self.sync_time_origin_sec = next_origin
        self.apply_sync_time_axis_formatters()

    def apply_sync_time_axis_formatters(self):
        """Describe apply_sync_time_axis_formatters.

        Args:
            None.
        """
        formatter = FuncFormatter(
            lambda value, pos: format_time_tick(value, self.sync_time_origin_sec)
        )

        for _key, fig, canvas in self.figure_items():
            if fig is None or canvas is None or not fig.axes:
                continue

            fig.axes[0].xaxis.set_major_formatter(formatter)
            canvas.draw_idle()

        if self.timeline_slider is not None:
            self.timeline_slider.set_time_origin(self.sync_time_origin_sec)

        self.invalidate_current_time_backgrounds()

    def connect_canvas_events(self, canvas):
        """Describe connect_canvas_events.

        Args:
            canvas: Input accepted by this method.
        """
        canvas.mpl_connect("draw_event", self.on_canvas_draw)
        canvas.mpl_connect("button_press_event", self.on_canvas_press)
        canvas.mpl_connect("button_release_event", self.on_canvas_release)

    def is_seekable_axis(self, ax):
        """Describe is_seekable_axis.

        Args:
            ax: Input accepted by this method.
        """
        return any(
            fig is not None and fig.axes and ax is fig.axes[0]
            for _key, fig, _canvas in self.figure_items()
        )

    def on_canvas_press(self, event):
        """Describe on_canvas_press.

        Args:
            event: Input accepted by this method.
        """
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
        """Describe on_canvas_release.

        Args:
            event: Input accepted by this method.
        """
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

    def follow_current_time_marker(self):
        """Describe follow_current_time_marker.

        Args:
            None.
        """
        if (
            self.current_record_time_sec is None
            or not self.should_follow_video_playback()
        ):
            return

        full_xlim = self.timeline_full_xlim or self.timeline_limits()
        if full_xlim is None:
            return

        full_left, full_right = full_xlim
        full_width = full_right - full_left
        if full_width <= 0:
            return

        current_xlim = self.current_timeline_xlim() or full_xlim
        left, right = current_xlim
        current_width = max(right - left, 1e-6)
        default_width = min(self.DEFAULT_PLAYBACK_WINDOW_SEC, full_width)

        if current_width >= full_width * 0.98:
            target_width = default_width
            force_recenter = target_width < current_width
        else:
            target_width = min(current_width, full_width)
            force_recenter = False

        if target_width >= full_width:
            next_left, next_right = full_left, full_right
        else:
            cursor_time = min(
                max(float(self.current_record_time_sec), full_left),
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
        """Describe figure_items.

        Args:
            None.
        """
        return [
            ("lfp", self.lfp_fig, self.lfp_canvas),
            ("axis", self.axis_fig, self.axis_canvas),
            ("timeline", self.timeline_fig, self.timeline_canvas),
        ]

    def invalidate_current_time_backgrounds(self, key=None):
        """Describe invalidate_current_time_backgrounds.

        Args:
            key: Input accepted by this method.
        """
        if key is None:
            self.current_time_backgrounds = {}
            return

        self.current_time_backgrounds.pop(key, None)

    def background_signature(self, canvas, ax):
        """Describe background_signature.

        Args:
            canvas: Input accepted by this method.
            ax: Input accepted by this method.
        """
        return (
            canvas.get_width_height(),
            tuple(round(value, 6) for value in ax.bbox.bounds),
            tuple(round(value, 9) for value in ax.get_xlim()),
            tuple(round(value, 9) for value in ax.get_ylim()),
        )

    def supports_marker_blit(self, canvas):
        """Describe supports_marker_blit.

        Args:
            canvas: Input accepted by this method.
        """
        return all(
            hasattr(canvas, name)
            for name in ("copy_from_bbox", "restore_region", "blit")
        )

    def on_canvas_draw(self, event):
        """Describe on_canvas_draw.

        Args:
            event: Input accepted by this method.
        """
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
        """Describe draw_marker_line.

        Args:
            key: Input accepted by this method.
            canvas: Input accepted by this method.
            ax: Input accepted by this method.
            line: Input accepted by this method.
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
        """Describe create_or_update_timeline.

        Args:
            None.
        """
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

        full_xlim = self.timeline_limits()
        if full_xlim is None:
            return

        if self.timeline_full_xlim == full_xlim and self.timeline_slider is not None:
            current_xlim = self.current_timeline_xlim()
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
        slider.set_time_origin(self.sync_time_origin_sec)
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

    def set_current_time_marker(self, record_time_sec, follow_playback=False):
        """Describe set_current_time_marker.

        Args:
            record_time_sec: Input accepted by this method.
            follow_playback: Input accepted by this method.
        """
        self.current_record_time_sec = record_time_sec

        if follow_playback:
            self.follow_current_time_marker()

        self.update_current_time_marker()

    def clear_current_time_marker(self):
        """Describe clear_current_time_marker.

        Args:
            None.
        """
        self.current_record_time_sec = None
        for line in self.current_time_lines.values():
            line.remove()
        self.current_time_lines = {}
        self.invalidate_current_time_backgrounds()

        for canvas in [self.lfp_canvas, self.axis_canvas, self.timeline_canvas]:
            if canvas is not None:
                canvas.draw_idle()

    def set_event_intervals(self, intervals):
        """Describe set_event_intervals.

        Args:
            intervals: Input accepted by this method.
        """
        self.event_intervals = [dict(interval) for interval in intervals]
        self.update_event_interval_artists()

    def clear_event_interval_artists(self):
        """Describe clear_event_interval_artists.

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
        """Describe update_event_interval_artists.

        Args:
            None.
        """
        self.clear_event_interval_artists()

        for key, fig, canvas in self.figure_items():
            if fig is None or canvas is None or not fig.axes:
                continue

            ax = fig.axes[0]
            for interval in self.event_intervals:
                start_sec = float(interval["record_start_sec"])
                end_sec = float(interval["record_end_sec"])
                if end_sec <= start_sec:
                    continue

                event_type = interval.get("event_type", "behavior")
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
        """Describe update_current_time_marker.

        Args:
            None.
        """
        if self.current_record_time_sec is None:
            return

        for key, fig, canvas in self.figure_items():
            if fig is None or canvas is None or not fig.axes:
                continue

            ax = fig.axes[0]
            line = self.current_time_lines.get(key)
            if line is None or line.axes is not ax:
                line = ax.axvline(
                    self.current_record_time_sec,
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
                        self.current_record_time_sec,
                        self.current_record_time_sec,
                    ]
                )

            self.draw_marker_line(key, canvas, ax, line)

    def selected_channel(self, selector):
        """Describe selected_channel.

        Args:
            selector: Input accepted by this method.
        """
        channel = selector.currentData()
        if channel is None:
            return None

        try:
            return int(channel)
        except (TypeError, ValueError):
            return None

    def current_lfp_filter_settings(self):
        """Describe current_lfp_filter_settings.

        Args:
            None.
        """
        return self._applied_lfp_filter_settings

    def pending_lfp_filter_settings(self):
        """Describe pending_lfp_filter_settings.

        Args:
            None.
        """
        return self.settings_from_processing_controls(
            self.signal_view_selector,
            self.bandpass_checkbox,
            self.bandpass_low_spin,
            self.bandpass_high_spin,
            self.notch_checkbox,
        )

    def mark_lfp_filter_settings_pending(self, *_args):
        """Describe mark_lfp_filter_settings_pending.

        Args:
            *_args: Input accepted by this method.
        """
        self.apply_filter_button.setEnabled(
            self.pending_lfp_filter_settings() != self._applied_lfp_filter_settings
        )

    def apply_lfp_filter_settings(self):
        """Describe apply_lfp_filter_settings.

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
        self.apply_filter_button.setEnabled(False)
        self.refresh_lfp_processing()

    def switch_lfp_signal_view(self, *_args):
        """Describe switch_lfp_signal_view.

        Args:
            *_args: Input accepted by this method.
        """
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
        self.mark_lfp_filter_settings_pending()
        if self.lfp_fig is None:
            return
        self.lfp_fig.set_lfp_signal_view(show_filtered)
        self.invalidate_current_time_backgrounds("lfp")

    def set_line_noise_hz(self, line_noise_hz):
        """Describe set_line_noise_hz.

        Args:
            line_noise_hz: Input accepted by this method.
        """
        next_value = 60.0 if line_noise_hz is None else float(line_noise_hz)
        if self.line_noise_hz == next_value:
            return

        self.line_noise_hz = next_value
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
            self.refresh_lfp_processing()
        self.mark_lfp_filter_settings_pending()

    def refresh_lfp_processing(self, *_args):
        """Describe refresh_lfp_processing.

        Args:
            *_args: Input accepted by this method.
        """
        if not self.lfp_path:
            return

        current_xlim = self.current_timeline_xlim()
        self.lfp_fig = None
        self.lfp_callback_connected = False
        self.invalidate_current_time_backgrounds("lfp")
        self.plot_lfp()

        if current_xlim is not None:
            self.set_shared_xlim(*current_xlim, source="timeline")

    def current_lfp_record_xlim(self):
        """Describe current_lfp_record_xlim.

        Args:
            None.
        """
        selected_xlim = self.current_timeline_xlim()
        if selected_xlim is None and self.lfp_fig is not None:
            selected_xlim = self.lfp_fig.lfp_full_xlim

        if selected_xlim is None:
            raise ValueError("Please select an LFP time range first.")

        left, right = sorted((float(selected_xlim[0]), float(selected_xlim[1])))
        return left, right

    def available_lfp_channels(self):
        """Describe available_lfp_channels.

        Args:
            None.
        """
        channels = self.lfp_info.get("channels", []) if self.lfp_info else []
        return [int(channel) for channel in channels]

    def load_lfp_segment(self, channel, left, right, settings):
        """Describe load_lfp_segment.

        Args:
            channel: Input accepted by this method.
            left: Input accepted by this method.
            right: Input accepted by this method.
            settings: Input accepted by this method.
        """
        data = read.read_signal_csv(self.lfp_path, requested_channels=[channel])
        column = f"channel_{channel}"
        if column not in data:
            raise ValueError(f"LFP CSV does not include channel {channel}.")

        time_us = data["time_us"].to_numpy(dtype=float)
        values = data[column].to_numpy(dtype=float)
        sample_rate_hz = signal_func.sample_rate_for_channel(
            self.lfp_info,
            time_us,
            channel,
        )
        return signal_func.prepare_lfp_segment(
            time_us,
            values,
            sample_rate_hz,
            left,
            right,
            settings,
        )

    def create_time_spinbox(self, value, minimum, maximum):
        """Describe create_time_spinbox.

        Args:
            value: Input accepted by this method.
            minimum: Input accepted by this method.
            maximum: Input accepted by this method.
        """
        spinbox = QDoubleSpinBox()
        spinbox.setDecimals(4)
        spinbox.setRange(float(minimum), float(maximum))
        spinbox.setSingleStep(0.1)
        spinbox.setValue(float(value))
        spinbox.setSuffix(" s")
        return spinbox

    def full_lfp_record_xlim(self):
        """Describe full_lfp_record_xlim.

        Args:
            None.
        """
        if self.lfp_fig is not None:
            return self.lfp_fig.lfp_full_xlim

        if not self.lfp_path:
            raise ValueError("Please import LFP CSV data first.")

        data = read.read_signal_csv(self.lfp_path)
        time_s = data["time_us"].to_numpy(dtype=float) / 1e6
        if time_s.size == 0:
            raise ValueError("LFP CSV does not contain samples.")

        return float(time_s[0]), float(time_s[-1])

    def settings_from_processing_controls(
        self,
        signal_selector,
        bandpass_checkbox,
        low_spin,
        high_spin,
        notch_checkbox,
    ):
        """Describe settings_from_processing_controls.

        Args:
            signal_selector: Input accepted by this method.
            bandpass_checkbox: Input accepted by this method.
            low_spin: Input accepted by this method.
            high_spin: Input accepted by this method.
            notch_checkbox: Input accepted by this method.
        """
        line_noise_hz = self.line_noise_hz if notch_checkbox.isChecked() else None
        if line_noise_hz is not None:
            line_noise_hz = float(line_noise_hz)

        return signal_func.LfpFilterSettings(
            show_filtered=bool(signal_selector.currentData()),
            bandpass_enabled=bandpass_checkbox.isChecked(),
            bandpass_low_hz=float(low_spin.value()),
            bandpass_high_hz=float(high_spin.value()),
            line_noise_hz=line_noise_hz,
        )

    def _prepare_lfp_analysis(self, failure_title):
        """Validate the current selection and load one shared analysis segment."""
        if not self.lfp_path:
            QMessageBox.information(
                self,
                "No LFP data",
                "Please import LFP CSV data first.",
            )
            return None

        channel = self.selected_channel(self.lfp_channel_selector)
        if channel is None:
            QMessageBox.warning(
                self,
                "No LFP channel",
                "Please select an LFP channel first.",
            )
            return None

        settings = self.current_lfp_filter_settings()
        try:
            left, right = self.current_lfp_record_xlim()
            segment = self.load_lfp_segment(channel, left, right, settings)
        except Exception as error:
            QMessageBox.warning(self, failure_title, str(error))
            return None

        return channel, left, right, segment, settings

    def show_lfp_analysis(self, analysis_type):
        """Calculate and display the selected frequency-domain analysis."""
        failure_title, dialog_title, dialog_size = {
            "power_spectrum": (
                "Power spectrum failed",
                "LFP Power Spectrum",
                (780, 520),
            ),
            "spectrogram": (
                "Spectrogram failed",
                "LFP Spectrogram",
                (820, 560),
            ),
        }[analysis_type]

        analysis = self._prepare_lfp_analysis(failure_title)
        if analysis is None:
            return

        channel, left, right, segment, settings = analysis
        try:
            if analysis_type == "power_spectrum":
                frequencies, power = signal_func.compute_power_spectrum(
                    segment.values,
                    segment.sample_rate_hz,
                )
                figure = self.create_power_spectrum_figure(channel, frequencies, power)
            else:
                frequencies, times, power = signal_func.compute_time_frequency(
                    segment.values,
                    segment.sample_rate_hz,
                )
                figure = self.create_spectrogram_figure(
                    channel,
                    segment,
                    frequencies,
                    times,
                    power,
                    "sync time" if self.sync_time_origin_sec is not None else "time",
                )
        except Exception as error:
            QMessageBox.warning(self, failure_title, str(error))
            return

        self.open_lfp_analysis_dialog(
            f"{dialog_title} - Channel {channel}",
            channel,
            left,
            right,
            segment,
            settings,
            figure,
            dialog_size,
        )

    def open_lfp_analysis_dialog(
        self,
        title,
        channel,
        left,
        right,
        segment,
        settings,
        figure,
        size,
    ):
        """Describe open_lfp_analysis_dialog.

        Args:
            title: Input accepted by this method.
            channel: Input accepted by this method.
            left: Input accepted by this method.
            right: Input accepted by this method.
            segment: Input accepted by this method.
            settings: Input accepted by this method.
            figure: Input accepted by this method.
            size: Input accepted by this method.
        """
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowTitle(title)
        dialog.resize(*size)

        display_left = relative_time(left, self.sync_time_origin_sec)
        display_right = relative_time(right, self.sync_time_origin_sec)
        time_mode = "sync time" if self.sync_time_origin_sec is not None else "time"
        status = QLabel(
            f"Channel {channel} | {signal_func.filter_description(settings)} | "
            f"{time_mode}: {display_left:.2f}-{display_right:.2f} s | "
            f"samples={segment.sample_count} | Fs={segment.sample_rate_hz:g} Hz"
        )

        canvas = FigureCanvas(figure)
        layout = QVBoxLayout()
        layout.addWidget(status)
        layout.addWidget(canvas)
        dialog.setLayout(layout)

        self.spectrum_dialogs.append(dialog)
        dialog.destroyed.connect(
            lambda _obj=None, item=dialog: self.forget_spectrum_dialog(item)
        )
        dialog.show()

    def forget_spectrum_dialog(self, dialog):
        """Describe forget_spectrum_dialog.

        Args:
            dialog: Input accepted by this method.
        """
        if dialog in self.spectrum_dialogs:
            self.spectrum_dialogs.remove(dialog)

    def create_power_spectrum_figure(self, channel, frequencies, power):
        """Describe create_power_spectrum_figure.

        Args:
            channel: Input accepted by this method.
            frequencies: Input accepted by this method.
            power: Input accepted by this method.
        """
        figure = Figure(figsize=(7.6, 4.4), constrained_layout=True)
        ax = figure.add_subplot(111)
        positive_power = np.maximum(power, np.finfo(float).tiny)
        ax.semilogy(frequencies, positive_power, linewidth=0.8, color="#1f77b4")
        ax.set_title(f"LFP Power Spectrum - Channel {channel}")
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Power spectral density")
        ax.grid(True, linewidth=0.4, alpha=0.35)
        return figure

    def create_lfp_waveform_figure(self, channel, segment, settings, time_mode,info):
        """Describe create_lfp_waveform_figure.

        Args:
            channel: Input accepted by this method.
            segment: Input accepted by this method.
            settings: Input accepted by this method.
            time_mode: Input accepted by this method.
            info: Input accepted by this method.
        """
        duration_sec = abs(
            float(segment.record_time_s[-1]) - float(segment.record_time_s[0])
        )
        figure_width = min(24.0, 8.0 + duration_sec / 120.0)
        figure = Figure(figsize=(figure_width, 4.8), constrained_layout=True)
        ax = figure.add_subplot(111)

        plot_step = resolve_plot_step(segment.sample_count, self.lfp_step)
        if plot_step == 0 or segment.sample_count <= plot_step:
            plot_index = slice(None)
        else:
            plot_index = slice(None, None, plot_step)

        if self.sync_time_origin_sec is None:
            plot_times = segment.record_time_s
        else:
            plot_times = segment.record_time_s - self.sync_time_origin_sec

        ax.plot(
            plot_times[plot_index],
            segment.values[plot_index],
            linewidth=0.6,
            color="#1f77b4",
        )
        ax.set_title(f"LFP Waveform - Channel {channel}")
        ax.set_xlabel(f"{time_mode} (s)")
        ax.set_ylabel(format_signal_label(info["value_unit"]))
        ax.grid(True, linewidth=0.4, alpha=0.35)
        return figure

    def annotate_lfp_figure(self, figure, channel, segment, settings):
        """Describe annotate_lfp_figure.

        Args:
            figure: Input accepted by this method.
            channel: Input accepted by this method.
            segment: Input accepted by this method.
            settings: Input accepted by this method.
        """
        filename = self.lfp_info.get("filename", "LFP") if self.lfp_info else "LFP"
        time_mode = "Sync time" if self.sync_time_origin_sec is not None else "Time"
        display_left = relative_time(
            float(segment.record_time_s[0]), self.sync_time_origin_sec
        )
        display_right = relative_time(
            float(segment.record_time_s[-1]), self.sync_time_origin_sec
        )
        processing = signal_func.filter_description(settings)
        figure.suptitle(
            f"File: {filename} | Channel {channel} | {processing}\n"
            f"{time_mode}: {display_left:.3f}-{display_right:.3f} s",
            fontsize=8,
        )

    def create_spectrogram_figure(
        self,
        channel,
        segment,
        frequencies,
        times,
        power,
        time_mode,
    ):
        """Describe create_spectrogram_figure.

        Args:
            channel: Input accepted by this method.
            segment: Input accepted by this method.
            frequencies: Input accepted by this method.
            times: Input accepted by this method.
            power: Input accepted by this method.
            time_mode: Input accepted by this method.
        """
        figure = Figure(figsize=(8.0, 4.8), constrained_layout=True)
        ax = figure.add_subplot(111)
        plot_times = times + relative_time(
            float(segment.record_time_s[0]), self.sync_time_origin_sec
        )
        power_db = 10.0 * np.log10(np.maximum(power, np.finfo(float).tiny))
        mesh = ax.pcolormesh(
            plot_times,
            frequencies,
            power_db,
            shading="auto",
            cmap="viridis",
        )
        figure.colorbar(mesh, ax=ax, label="PSD (dB/Hz)")
        ax.set_title(f"LFP Spectrogram - Channel {channel}")
        ax.set_xlabel(f"{time_mode} (s)")
        ax.set_ylabel("Frequency (Hz)")
        return figure

    def plot_lfp(self):
        """Describe plot_lfp.

        Args:
            None.
        """
        if not self.lfp_path:
            return

        channel = self.selected_channel(self.lfp_channel_selector)
        created_figure = False
        try:
            if self.lfp_fig is None:
                self.lfp_fig = draw.LFP(
                    info=self.lfp_info,
                    channels=channel,
                    step=self.lfp_step,
                    filter_settings=self.current_lfp_filter_settings(),
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

        if not self.lfp_callback_connected:
            self.lfp_fig.add_lfp_xlim_callback(
                lambda value: self.on_plot_xlim_changed(value, "lfp")
            )
            self.lfp_callback_connected = True

        self.create_or_update_timeline()
        self.update_event_interval_artists()
        self.update_current_time_marker()

    def plot_axis(self):
        """Describe plot_axis.

        Args:
            None.
        """
        if not self.axis_path:
            return

        try:
            self.axis_fig = draw.accelerator(
                info=self.axis_info,
                compact=True,
                step=self.axis_step,
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
        """Describe set_lfp_info.

        Args:
            info: Input accepted by this method.
        """
        self.lfp_info = info
        self.lfp_fig = None
        self.lfp_callback_connected = False
        self.lfp_file_label.setText(f"LFP CSV: {info['filename']}")

        self.lfp_channel_selector.blockSignals(True)
        self.lfp_channel_selector.clear()

        channels = info.get("channels", [])

        if channels:
            for channel in channels:
                self.lfp_channel_selector.addItem(f"Channel {channel}", channel)

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

    def set_axis_info(self, info):
        """Describe set_axis_info.

        Args:
            info: Input accepted by this method.
        """
        self.axis_info = info
        self.axis_fig = None
        self.axis_callback_connected = False
        self.axis_file_label.setText(f"3-axis CSV: {info['filename']} (channel 260)")
        self.plot_axis()

    def set_plot_step(self, plot_name, step):
        """Describe set_plot_step.

        Args:
            plot_name: Input accepted by this method.
            step: Input accepted by this method.
        """
        step_attribute, path_attribute, figure_attribute, callback_attribute, plot = {
            "lfp": (
                "lfp_step",
                "lfp_path",
                "lfp_fig",
                "lfp_callback_connected",
                self.plot_lfp,
            ),
            "axis": (
                "axis_step",
                "axis_path",
                "axis_fig",
                "axis_callback_connected",
                self.plot_axis,
            ),
        }[plot_name]
        step = None if step is None else max(int(step), 0)
        if getattr(self, step_attribute) == step:
            return

        setattr(self, step_attribute, step)
        if not getattr(self, path_attribute):
            return

        current_xlim = self.current_timeline_xlim()
        setattr(self, figure_attribute, None)
        setattr(self, callback_attribute, False)
        plot()

        if current_xlim is not None:
            self.set_shared_xlim(*current_xlim, source="timeline")
