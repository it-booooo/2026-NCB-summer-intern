import draw_function as draw
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter


class PlaybackAwareComboBox(QComboBox):
    def showPopup(self):
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
        self.ax.tick_params(axis="x", labelsize=7, pad=1)
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
        self.left_handle = self.ax.plot(
            [valinit[0]],
            [0.5],
            marker="o",
            markersize=7,
            markerfacecolor="#ffffff",
            markeredgecolor="#c0c0c0",
            markeredgewidth=1.0,
            linestyle="None",
            zorder=3,
        )[0]
        self.right_handle = self.ax.plot(
            [valinit[1]],
            [0.5],
            marker="o",
            markersize=7,
            markerfacecolor="#ffffff",
            markeredgecolor="#c0c0c0",
            markeredgewidth=1.0,
            linestyle="None",
            zorder=3,
        )[0]
        self.label = self.ax.text(
            full_xlim[0],
            0.5,
            "Time",
            fontsize=7,
            ha="right",
            va="center",
        )
        self.valtext = self.ax.text(
            0.5,
            1.02,
            "",
            fontsize=7,
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
        self.callbacks.append(callback)

    def set_time_origin(self, origin_sec):
        self.time_origin_sec = None if origin_sec is None else float(origin_sec)
        self.ax.xaxis.set_major_formatter(
            FuncFormatter(lambda value, pos: self.format_time_tick(value))
        )
        self.label.set_text("Sync t" if self.time_origin_sec is not None else "Time")
        self.update_artists()
        self.ax.figure.canvas.draw_idle()

    def display_time(self, value):
        if self.time_origin_sec is None:
            return float(value)

        return float(value) - self.time_origin_sec

    def format_time_tick(self, value):
        value = self.display_time(value)
        if abs(value) < 0.0005:
            value = 0.0

        abs_value = abs(value)
        if abs_value >= 100:
            return f"{value:.0f}"
        if abs_value >= 10:
            return f"{value:.1f}"
        return f"{value:.2f}"

    def clamp_xlim(self, left, right):
        full_left, full_right = self.full_xlim
        full_width = full_right - full_left
        width = right - left

        if width >= full_width:
            return full_left, full_right

        if left < full_left:
            right += full_left - left
            left = full_left

        if right > full_right:
            left -= right - full_right
            right = full_right

        return max(left, full_left), min(right, full_right)

    def set_val(self, value, emit=True):
        left, right = self.clamp_xlim(float(value[0]), float(value[1]))
        if right - left < self.min_width:
            right = left + self.min_width
            left, right = self.clamp_xlim(left, right)

        self.val = (left, right)
        self.update_artists()
        self.ax.figure.canvas.draw_idle()

        if emit:
            for callback in self.callbacks:
                callback(self.val)

    def update_artists(self):
        left, right = self.val
        self.poly.set_x(left)
        self.poly.set_width(right - left)
        self.left_handle.set_data([left], [0.5])
        self.right_handle.set_data([right], [0.5])
        display_left = self.display_time(left)
        display_right = self.display_time(right)
        self.valtext.set_text(f"({display_left:.2f} s, {display_right:.2f} s)")

    def on_press(self, event):
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
        self.drag_state = None


class LfpPanel(QWidget):
    time_selected = Signal(float)

    DEFAULT_PLAYBACK_WINDOW_SEC = 30.0
    PLAYBACK_CURSOR_FRACTION = 0.35
    PLAYBACK_EDGE_MARGIN_FRACTION = 0.18

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(270)

        self.lfp_path = None
        self.axis_path = None
        self.lfp_canvas = None
        self.axis_canvas = None
        self.timeline_canvas = None
        self.timeline_fig = None
        self.timeline_slider = None
        self.timeline_full_xlim = None
        self.lfp_info = None
        self.axis_info = None
        self.lfp_fig = None
        self.axis_fig = None
        self.lfp_step = None
        self.axis_step = None
        self.updating_timeline = False
        self.lfp_callback_connected = False
        self.axis_callback_connected = False
        self.current_record_time_sec = None
        self.current_time_lines = {}
        self.current_time_backgrounds = {}
        self.sync_time_origin_sec = None
        self.click_seek_state = None

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

        self.follow_video_checkbox = QCheckBox("Follow video playback")
        self.follow_video_checkbox.setChecked(True)
        self.follow_video_checkbox.setToolTip(
            "Auto-pan the waveform time window while the video is playing."
        )

        waveform_grid = QGridLayout()
        waveform_grid.setVerticalSpacing(8)
        waveform_grid.setColumnStretch(1, 1)
        waveform_grid.setRowStretch(0, 1)
        waveform_grid.setRowStretch(1, 1)

        self.lfp_waveform_area = self.create_waveform_area(
            "Import LFP CSV to show waveform"
        )
        self.axis_waveform_area = self.create_waveform_area(
            "Import 3-axis CSV to show waveform"
        )

        waveform_grid.addWidget(QLabel("LFP"), 0, 0)
        waveform_grid.addWidget(self.lfp_waveform_area, 0, 1)

        waveform_grid.addWidget(QLabel("3-axis"), 1, 0)
        waveform_grid.addWidget(self.axis_waveform_area, 1, 1)

        self.timeline_area = self.create_waveform_area("Shared time range")
        self.timeline_area.setFixedHeight(58)

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 4, 8, 6)
        layout.setSpacing(4)

        layout.addWidget(self.lfp_file_label)

        channel_layout = QHBoxLayout()
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.setSpacing(8)
        channel_layout.addWidget(self.lfp_channel_selector)
        channel_layout.addStretch()
        channel_layout.addWidget(self.follow_video_checkbox)
        layout.addLayout(channel_layout)

        layout.addWidget(self.axis_file_label)
        layout.addLayout(waveform_grid, stretch=1)
        layout.addWidget(self.timeline_area)

        self.setLayout(layout)

    def create_waveform_area(self, text):
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
        limits = []

        if self.lfp_fig is not None:
            limits.append(self.lfp_fig.lfp_full_xlim)

        if self.axis_fig is not None:
            limits.append(self.axis_fig.axis_full_xlim)

        if not limits:
            return None

        return min(limit[0] for limit in limits), max(limit[1] for limit in limits)

    def set_shared_xlim(self, left, right, source=None):
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
        if self.updating_timeline:
            return

        left, right = value
        self.set_shared_xlim(float(left), float(right), source=source)

    def on_timeline_changed(self, value):
        left, right = value
        self.set_shared_xlim(float(left), float(right), source="timeline")

    def current_timeline_xlim(self):
        if self.timeline_slider is None:
            return None

        left, right = self.timeline_slider.val
        return float(left), float(right)

    def should_follow_video_playback(self):
        return self.follow_video_checkbox.isChecked()

    def set_sync_time_origin(self, origin_sec):
        next_origin = None if origin_sec is None else float(origin_sec)
        if self.sync_time_origin_sec == next_origin:
            return

        self.sync_time_origin_sec = next_origin
        self.apply_sync_time_axis_formatters()

    def display_time(self, record_time_sec):
        if self.sync_time_origin_sec is None:
            return float(record_time_sec)

        return float(record_time_sec) - self.sync_time_origin_sec

    def format_sync_time_tick(self, value):
        value = self.display_time(value)
        if abs(value) < 0.0005:
            value = 0.0

        abs_value = abs(value)
        if abs_value >= 100:
            return f"{value:.0f}"
        if abs_value >= 10:
            return f"{value:.1f}"
        return f"{value:.2f}"

    def apply_sync_time_axis_formatters(self):
        formatter = FuncFormatter(
            lambda value, pos: self.format_sync_time_tick(value)
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
        canvas.mpl_connect("draw_event", self.on_canvas_draw)
        canvas.mpl_connect("button_press_event", self.on_canvas_press)
        canvas.mpl_connect("button_release_event", self.on_canvas_release)

    def is_seekable_axis(self, ax):
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

    def clamp_playback_xlim(self, left, right, full_xlim):
        full_left, full_right = full_xlim
        full_width = full_right - full_left
        width = right - left

        if full_width <= 0 or width >= full_width:
            return full_left, full_right

        if left < full_left:
            right += full_left - left
            left = full_left

        if right > full_right:
            left -= right - full_right
            right = full_right

        return max(left, full_left), min(right, full_right)

    def follow_current_time_marker(self):
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
            next_left, next_right = self.clamp_playback_xlim(
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

        fig = Figure(figsize=(8, 0.66), constrained_layout=False)
        slider_ax = fig.add_axes((0.12, 0.36, 0.76, 0.28))
        slider = SharedTimelineSlider(
            slider_ax,
            full_xlim,
            full_xlim,
        )
        slider.set_time_origin(self.sync_time_origin_sec)
        slider.on_changed(self.on_timeline_changed)

        canvas = FigureCanvas(fig)
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        canvas.setFixedHeight(54)
        self.connect_canvas_events(canvas)
        layout.addWidget(canvas)

        self.timeline_fig = fig
        self.timeline_slider = slider
        self.timeline_canvas = canvas
        self.timeline_full_xlim = full_xlim
        self.invalidate_current_time_backgrounds()
        canvas.draw_idle()

        self.set_shared_xlim(*full_xlim, source="timeline")
        self.update_current_time_marker()

    def set_current_time_marker(self, record_time_sec, follow_playback=False):
        self.current_record_time_sec = record_time_sec

        if follow_playback:
            self.follow_current_time_marker()

        self.update_current_time_marker()

    def clear_current_time_marker(self):
        self.current_record_time_sec = None
        for line in self.current_time_lines.values():
            line.remove()
        self.current_time_lines = {}
        self.invalidate_current_time_backgrounds()

        for canvas in [self.lfp_canvas, self.axis_canvas, self.timeline_canvas]:
            if canvas is not None:
                canvas.draw_idle()

    def update_current_time_marker(self):
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
                line.set_xdata([
                    self.current_record_time_sec,
                    self.current_record_time_sec,
                ])

            self.draw_marker_line(key, canvas, ax, line)

    def selected_channel(self, selector):
        channel = selector.currentData()
        if channel is None:
            return None

        try:
            return int(channel)
        except (TypeError, ValueError):
            return None

    def plot_lfp(self):
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
        self.update_current_time_marker()

    def plot_axis(self):
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
        self.update_current_time_marker()

    def set_lfp_info(self, info):
        self.lfp_info = info
        self.lfp_path = info["path"]
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
        else:
            self.lfp_channel_selector.addItem("No LFP channel")
            self.lfp_channel_selector.setEnabled(False)

        self.lfp_channel_selector.blockSignals(False)
        self.plot_lfp()

    def set_axis_info(self, info):
        self.axis_info = info
        self.axis_path = info["path"]
        self.axis_fig = None
        self.axis_callback_connected = False
        self.axis_file_label.setText(f"3-axis CSV: {info['filename']} (channel 260)")
        self.plot_axis()

    def set_lfp_step(self, step):
        step = None if step is None else max(int(step), 0)
        if self.lfp_step == step:
            return

        self.lfp_step = step
        if not self.lfp_path:
            return

        current_xlim = self.current_timeline_xlim()
        self.lfp_fig = None
        self.lfp_callback_connected = False
        self.plot_lfp()

        if current_xlim is not None:
            self.set_shared_xlim(*current_xlim, source="timeline")

    def set_axis_step(self, step):
        step = None if step is None else max(int(step), 0)
        if self.axis_step == step:
            return

        self.axis_step = step
        if not self.axis_path:
            return

        current_xlim = self.current_timeline_xlim()
        self.axis_fig = None
        self.axis_callback_connected = False
        self.plot_axis()

        if current_xlim is not None:
            self.set_shared_xlim(*current_xlim, source="timeline")
