import draw_function as draw
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle


class SharedTimelineSlider:
    def __init__(self, ax, full_xlim, valinit):
        self.ax = ax
        self.full_xlim = full_xlim
        self.val = valinit
        self.callbacks = []
        self.drag_state = None
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
            fontsize=8,
            ha="right",
            va="center",
        )
        self.valtext = self.ax.text(
            0.5,
            1.05,
            "",
            fontsize=8,
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
        self.valtext.set_text(f"({left:.2f} s, {right:.2f} s)")

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
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(380)

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

        self.lfp_file_label = QLabel("LFP CSV: Not imported")
        self.axis_file_label = QLabel("3-axis CSV: Not imported")

        self.lfp_channel_selector = QComboBox()
        self.lfp_channel_selector.addItem("No LFP channel")
        self.lfp_channel_selector.setEnabled(False)
        self.lfp_channel_selector.currentIndexChanged.connect(self.plot_lfp)

        waveform_grid = QGridLayout()
        waveform_grid.setVerticalSpacing(8)
        waveform_grid.setColumnStretch(1, 1)
        waveform_grid.setRowStretch(0, 2)
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
        layout.addWidget(self.lfp_channel_selector)

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
        layout.addWidget(canvas)
        setattr(self, canvas_attr, canvas)
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

        fig = Figure(figsize=(8, 0.7), constrained_layout=False)
        slider_ax = fig.add_axes((0.12, 0.28, 0.76, 0.32))
        slider = SharedTimelineSlider(
            slider_ax,
            full_xlim,
            full_xlim,
        )
        slider.on_changed(self.on_timeline_changed)

        canvas = FigureCanvas(fig)
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        canvas.setFixedHeight(54)
        layout.addWidget(canvas)

        self.timeline_fig = fig
        self.timeline_slider = slider
        self.timeline_canvas = canvas
        self.timeline_full_xlim = full_xlim
        canvas.draw_idle()

        self.set_shared_xlim(*full_xlim, source="timeline")

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
        try:
            if self.lfp_fig is None:
                self.lfp_fig = draw.LFP(
                    info=self.lfp_info,
                    channels=channel,
                    step=self.lfp_step,
                )
            elif self.lfp_fig is not None and channel is not None:
                self.lfp_fig.set_lfp_channel(channel)
        except Exception as error:
            QMessageBox.warning(self, "LFP plot failed", str(error))
            return

        self.set_figure(self.lfp_waveform_area, "lfp_canvas", self.lfp_fig)

        if not self.lfp_callback_connected:
            self.lfp_fig.add_lfp_xlim_callback(
                lambda value: self.on_plot_xlim_changed(value, "lfp")
            )
            self.lfp_callback_connected = True

        self.create_or_update_timeline()

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
