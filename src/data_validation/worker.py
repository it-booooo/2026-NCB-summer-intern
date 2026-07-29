"""Background worker for complete chunked signal validation."""

import threading

from PySide6.QtCore import QThread, Signal

from ..background_requests import source_identity_for_info
from ..signal_data.source import CacheBuildCancelled
from .input_checks import check


class DataCheckWorker(QThread):
    progress = Signal(object, int)
    completed = Signal(object, object, object)
    failed = Signal(object, object, str)
    canceled = Signal(object, object)

    def __init__(self, request_id, info, output_path):
        super().__init__()
        self.request_id = request_id
        self.info = dict(info)
        self.output_path = output_path
        self.source_identity = source_identity_for_info(info)
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            output = check(
                self.info,
                self.output_path,
                cancel_event=self.cancel_event,
                progress_callback=lambda value: self.progress.emit(
                    self.request_id,
                    round(float(value) * 100),
                ),
            )
        except CacheBuildCancelled:
            self.canceled.emit(self.request_id, self.source_identity)
            return
        except Exception as error:
            self.failed.emit(
                self.request_id,
                self.source_identity,
                str(error),
            )
            return
        self.completed.emit(
            self.request_id,
            self.source_identity,
            output,
        )
