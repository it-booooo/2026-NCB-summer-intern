from dataclasses import dataclass
from typing import Callable


TARGET_PLOT_POINTS = 5000


def resolve_plot_step(data_length: int, step: int | None) -> int:
    if step is None:
        return max(data_length // TARGET_PLOT_POINTS, 1)
    return max(int(step), 0)


def format_signal_label(unit):
    return f"Signal ({unit})" if unit else "Signal"


@dataclass
class XNavigation:
    set_xlim: Callable
    reset_x_zoom: Callable
    add_xlim_callback: Callable


def install_x_navigation(fig, ax, full_xlim) -> XNavigation:
    """Attach shared wheel-zoom, drag-pan, and reset behavior to a figure."""
    ax.set_xlim(full_xlim)
    ax.autoscale(enable=False, axis="x")
    pan_state: dict[str, float] = {}
    xlim_callbacks: list[Callable[[tuple[float, float]], None]] = []

    def clamp_xlim(left: float, right: float) -> tuple[float, float]:
        full_left, full_right = full_xlim
        full_width = full_right - full_left
        width = right - left

        if width >= full_width:
            return full_xlim

        if left < full_left:
            right += full_left - left
            left = full_left

        if right > full_right:
            left -= right - full_right
            right = full_right

        return max(left, full_left), min(right, full_right)

    def set_xlim(left: float, right: float, *, emit: bool = True) -> None:
        next_xlim = clamp_xlim(left, right)
        ax.set_xlim(next_xlim)

        if emit:
            for callback in xlim_callbacks:
                callback(next_xlim)

        fig.canvas.draw_idle()

    def reset_x_zoom() -> None:
        set_xlim(*full_xlim)

    def add_xlim_callback(callback) -> None:
        xlim_callbacks.append(callback)

    def event_xdata(event) -> float | None:
        if event.xdata is not None:
            return float(event.xdata)
        if event.x is None or event.y is None:
            return None
        return float(ax.transData.inverted().transform((event.x, event.y))[0])

    def zoom_x(event) -> None:
        if event.inaxes != ax:
            return

        left, right = ax.get_xlim()
        width = right - left
        if width <= 0:
            return

        full_width = full_xlim[1] - full_xlim[0]
        min_width = max(full_width / 10000, 1e-6)

        if event.button == "up":
            scale = 0.8
        elif event.button == "down":
            scale = 1.25
        else:
            return

        next_width = min(max(width * scale, min_width), full_width)
        center = event.xdata if event.xdata is not None else left + width / 2
        left_fraction = (center - left) / width
        next_left = center - next_width * left_fraction
        next_right = next_left + next_width

        set_xlim(next_left, next_right)

    def handle_double_click(event) -> None:
        if event.inaxes == ax and event.dblclick:
            reset_x_zoom()
            pan_state.clear()

    def start_x_pan(event) -> None:
        if event.inaxes != ax or event.button != 1 or event.dblclick:
            return

        xdata = event_xdata(event)
        if xdata is None:
            return

        left, right = ax.get_xlim()
        pan_state["x"] = xdata
        pan_state["left"] = left
        pan_state["right"] = right

    def drag_x_pan(event) -> None:
        if not pan_state:
            return

        xdata = event_xdata(event)
        if xdata is None:
            return

        dx = xdata - pan_state["x"]
        set_xlim(pan_state["left"] - dx, pan_state["right"] - dx)

    def stop_x_pan(event) -> None:
        pan_state.clear()

    fig.canvas.mpl_connect("scroll_event", zoom_x)
    fig.canvas.mpl_connect("button_press_event", handle_double_click)
    fig.canvas.mpl_connect("button_press_event", start_x_pan)
    fig.canvas.mpl_connect("motion_notify_event", drag_x_pan)
    fig.canvas.mpl_connect("button_release_event", stop_x_pan)

    return XNavigation(
        set_xlim=set_xlim,
        reset_x_zoom=reset_x_zoom,
        add_xlim_callback=add_xlim_callback,
    )
