"""Reusable controls for the LFP panel."""

from PySide6.QtWidgets import QComboBox
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter

from ..charts.chart_helpers import clamp_xlim, format_time_tick
from ..synchronization.time_conversion import relative_time


class PlaybackAwareComboBox(QComboBox):
    def showPopup(self):
        """Show the popup menu for this widget.

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
        """Provide on changed functionality.

        Args:
            callback: Function invoked when the operation completes or changes.
        """
        self.callbacks.append(callback)

    def set_time_origin(self, origin_sec):
        """Set time origin.

        Args:
            origin_sec: Input used by this operation.
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
        """Set val.

        Args:
            value: New value to store or apply.
            emit: Input used by this operation.
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
        """Update artists.

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
        """Provide on press functionality.

        Args:
            event: Event record to process.
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
        """Provide on motion functionality.

        Args:
            event: Event record to process.
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
        """Provide on release functionality.

        Args:
            event: Event record to process.
        """
        self.drag_state = None

