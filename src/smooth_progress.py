"""A progress dialog that advances continuously and never visually stalls.

Background workers report progress in coarse milestones with long silent
phases in between -- for example ``LfpAnalysisWorker`` reports ``55`` and then
renders a segment in a subprocess without any further updates until it reports
``100``. Driving a plain :class:`QProgressDialog` with those values makes the
bar freeze on the last milestone (typically 55%) and then jump straight to
done.

``SmoothProgressDialog`` decouples the *reported* target from the *displayed*
value. A timer eases the displayed value toward each reported target and, once
it has caught up, creeps gently onward so the bar keeps moving during silent
phases. Reported completion snaps immediately to the maximum, and the value
never moves backwards.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QProgressDialog


class SmoothProgressDialog(QProgressDialog):
    """``QProgressDialog`` whose bar animates smoothly between milestones."""

    _TICK_MS = 40
    # Fraction of the remaining distance to the reported target closed per tick
    # while catching up, with a floor so motion is always visible.
    _EASE_FRACTION = 0.25
    _MIN_EASE_STEP = 0.5
    # While waiting on a silent phase, creep toward this fraction of the gap
    # between the last milestone and the maximum, so the bar keeps moving
    # without overtaking the next real milestone too eagerly.
    _CREEP_CEILING_FRACTION = 0.75
    _CREEP_FRACTION = 0.01

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Hold at 100% on completion instead of snapping back to 0%; callers
        # dismiss the dialog explicitly once the work finishes.
        self.setAutoReset(False)
        self._minimum = float(self.minimum())
        self._maximum = float(self.maximum())
        self._target = self._minimum
        self._display = self._minimum
        self._finished = False
        self._timer = QTimer(self)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self._advance)
        self._timer.start()
        super().setValue(int(round(self._display)))

    def setValue(self, value):
        """Record a reported target instead of showing it immediately."""

        target = float(value)
        if target >= self._maximum:
            # Completion: snap to the end and stop animating.
            self._finished = True
            self._display = self._maximum
            self._target = self._maximum
            self._timer.stop()
            super().setValue(int(self._maximum))
            return
        # Never let a stale or out-of-order report drag the bar backwards.
        if target > self._target:
            self._target = target

    def reset(self):
        self._timer.stop()
        super().reset()

    def _advance(self):
        if self._finished:
            return
        if self._display < self._target:
            step = max(
                self._MIN_EASE_STEP,
                (self._target - self._display) * self._EASE_FRACTION,
            )
            self._display = min(self._target, self._display + step)
        else:
            ceiling = self._target + (
                self._maximum - self._target
            ) * self._CREEP_CEILING_FRACTION
            if self._display < ceiling:
                self._display += (ceiling - self._display) * self._CREEP_FRACTION
        shown = int(round(self._display))
        if shown != self.value():
            super().setValue(shown)
