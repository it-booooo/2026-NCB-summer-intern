"""Detect and record main-thread (GUI) stalls.

When the Qt event loop stops processing events for more than a few seconds the
window manager paints the application as "Not Responding".  Reproducing such a
freeze under a debugger is awkward, so this watchdog keeps a heartbeat on the
GUI thread and, from an independent background thread, dumps the stack of every
thread the instant a stall is detected.

Because ``faulthandler`` can only see Python frames, a stall inside native Qt
code (painting, layout, a modal loop) shows up as a bare ``app.exec()`` with no
hint of *what* is stuck.  To recover that, a lightweight event probe records the
type and receiver of the event the GUI thread is currently dispatching, and the
stall report names it -- e.g. "processing Paint on QLabel for 5.1s".
"""

from __future__ import annotations

import faulthandler
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer


# A few event types worth naming in the report; everything else is shown by
# its numeric ``QEvent.Type`` value.
_EVENT_NAMES = {
    int(QEvent.Type.Paint): "Paint",
    int(QEvent.Type.Resize): "Resize",
    int(QEvent.Type.Show): "Show",
    int(QEvent.Type.Move): "Move",
    int(QEvent.Type.LayoutRequest): "LayoutRequest",
    int(QEvent.Type.UpdateRequest): "UpdateRequest",
    int(QEvent.Type.UpdateLater): "UpdateLater",
    int(QEvent.Type.Timer): "Timer",
    int(QEvent.Type.MetaCall): "MetaCall",
    int(QEvent.Type.DeferredDelete): "DeferredDelete",
    int(QEvent.Type.MouseButtonPress): "MouseButtonPress",
    int(QEvent.Type.MouseButtonRelease): "MouseButtonRelease",
    int(QEvent.Type.Close): "Close",
    int(QEvent.Type.WindowActivate): "WindowActivate",
    int(QEvent.Type.Wheel): "Wheel",
}


class _EventProbe(QObject):
    """Record the event the GUI thread is about to dispatch, as cheaply as it can."""

    def __init__(self, state):
        super().__init__()
        self._state = state

    def eventFilter(self, obj, event):
        # Runs for every event on the GUI thread -- keep it to plain attribute
        # writes (atomic under the GIL); no locks, no calls that might touch a
        # half-deleted C++ object.
        try:
            self._state["ev_type"] = int(event.type())
            self._state["ev_recv"] = type(obj).__name__
            self._state["ev_started"] = time.monotonic()
        except Exception:
            pass
        return False


def _describe_event(state):
    ev_type = state.get("ev_type")
    if ev_type is None:
        return "no event captured"
    name = _EVENT_NAMES.get(ev_type, f"QEvent({ev_type})")
    receiver = state.get("ev_recv", "?")
    started = state.get("ev_started")
    held = "" if started is None else f" for {time.monotonic() - started:.1f}s"
    return f"{name} on {receiver}{held}"


def install_gui_stall_watchdog(
    app,
    *,
    log_path,
    stall_seconds: float = 5.0,
    heartbeat_ms: int = 500,
):
    """Log every thread's stack, plus the stuck event, whenever the GUI stalls.

    Args:
        app: The ``QApplication`` the watchdog attaches its lifetime to.
        log_path: File that stall reports are appended to.
        stall_seconds: Silence on the GUI thread that counts as a stall.
        heartbeat_ms: How often the GUI thread refreshes its heartbeat.
    """

    log_path = Path(log_path)
    state = {"last_beat": time.monotonic(), "dumped": False}
    lock = threading.Lock()

    try:
        faulthandler.enable()
    except (RuntimeError, ValueError):
        pass

    probe = _EventProbe(state)
    app.installEventFilter(probe)

    def beat():
        with lock:
            state["last_beat"] = time.monotonic()
            state["dumped"] = False

    timer = QTimer()
    timer.setInterval(int(heartbeat_ms))
    timer.timeout.connect(beat)
    timer.start()

    def watch():
        while True:
            time.sleep(1.0)
            with lock:
                idle = time.monotonic() - state["last_beat"]
                if idle < stall_seconds or state["dumped"]:
                    continue
                state["dumped"] = True
            try:
                with open(log_path, "a", encoding="utf-8") as handle:
                    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    handle.write(
                        f"\n===== GUI thread stalled ~{idle:.1f}s "
                        f"@ {stamp} =====\n"
                    )
                    handle.write(
                        f"Stuck dispatching: {_describe_event(state)}\n"
                    )
                    handle.flush()
                    faulthandler.dump_traceback(file=handle, all_threads=True)
                    handle.flush()
            except OSError:
                pass

    thread = threading.Thread(
        target=watch,
        name="gui-stall-watchdog",
        daemon=True,
    )
    thread.start()

    # Keep strong references so nothing is garbage collected.
    app._gui_watchdog_timer = timer
    app._gui_watchdog_thread = thread
    app._gui_watchdog_probe = probe
    return log_path
