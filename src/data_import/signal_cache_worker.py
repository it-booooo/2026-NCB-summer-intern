"""Cancelable background construction of signal memmap and coarse caches."""

import threading

from PySide6.QtCore import QThread, Signal

from ..signal_data import CacheBuildCancelled, LfpFilterSettings


class SignalCacheWorker(QThread):
    """Return only request metadata and a prepared dataset."""

    completed = Signal(object, object, object)
    failed = Signal(object, object, str)
    progress = Signal(object, int)
    canceled = Signal(object, object)

    def __init__(self, request_id, dataset, configured_step=None):
        super().__init__()
        self.request_id = request_id
        self.dataset = dataset
        self.configured_step = configured_step
        self.source_identity = dataset.source.identity_token()
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            self.progress.emit(self.request_id, 0)
            channel = self.dataset.channels[0]
            self.dataset.source.ensure_cache(
                channel,
                self.cancel_event,
                lambda value: self.progress.emit(
                    self.request_id,
                    round(float(value) * 85),
                ),
            )
            if hasattr(self.dataset, "coarse_values"):
                sample_count = self.dataset.source.sample_count(channel)
                if self.configured_step is None:
                    step = max(sample_count // 5_000, 1)
                else:
                    step = max(int(self.configured_step), 1)
                self.dataset.source.coarse(
                    channel,
                    step,
                    cancel_event=self.cancel_event,
                    progress_callback=lambda value: self.progress.emit(
                        self.request_id,
                        85 + round(float(value) * 15),
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
        self.progress.emit(self.request_id, 100)
        self.completed.emit(
            self.request_id,
            self.source_identity,
            self.dataset,
        )


class ProjectSignalCacheWorker(QThread):
    """Prepare every signal dataset in staged project data."""

    completed = Signal(object, object, object)
    failed = Signal(object, str)
    progress = Signal(object, int)
    canceled = Signal(object)

    def __init__(self, request_id, staged):
        super().__init__()
        self.request_id = request_id
        self.staged = staged
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        datasets = [
            dataset
            for dataset in (
                self.staged.get("lfp_dataset"),
                self.staged.get("three_axis_dataset"),
            )
            if dataset is not None
        ]
        identities = {
            id(dataset): dataset.source.identity_token()
            for dataset in datasets
        }
        try:
            for dataset_index, dataset in enumerate(datasets):
                base = dataset_index / max(len(datasets), 1)
                scale = 1.0 / max(len(datasets), 1)
                channel = dataset.channels[0]
                dataset.source.ensure_cache(
                    channel,
                    self.cancel_event,
                    lambda value, base=base, scale=scale: self.progress.emit(
                        self.request_id,
                        round((base + value * scale * 0.75) * 100),
                    ),
                )
                if hasattr(dataset, "coarse_values"):
                    sample_count = dataset.source.sample_count(channel)
                    configured = self.staged.get("data", {}).get("lfp_step")
                    step = (
                        max(sample_count // 5_000, 1)
                        if configured is None
                        else max(int(configured), 1)
                    )
                    dataset.source.coarse(
                        channel,
                        step,
                        cancel_event=self.cancel_event,
                    )
                    settings_data = self.staged.get("data", {}).get(
                        "lfp_filter_settings",
                        {},
                    )
                    if settings_data.get("show_filtered", False):
                        settings = LfpFilterSettings(
                            show_filtered=True,
                            bandpass_enabled=bool(
                                settings_data.get("bandpass_enabled", False)
                            ),
                            bandpass_low_hz=float(
                                settings_data.get("bandpass_low_hz", 1.0)
                            ),
                            bandpass_high_hz=float(
                                settings_data.get("bandpass_high_hz", 100.0)
                            ),
                            line_noise_hz=settings_data.get(
                                "line_noise_hz",
                                60.0,
                            ),
                            notch_quality=float(
                                settings_data.get("notch_quality", 30.0)
                            ),
                        )
                        dataset.source.coarse(
                            channel,
                            step,
                            settings,
                            cancel_event=self.cancel_event,
                            progress_callback=lambda value, base=base, scale=scale: (
                                self.progress.emit(
                                    self.request_id,
                                    round(
                                        (base + scale * (0.75 + value * 0.25))
                                        * 100
                                    ),
                                )
                            ),
                        )
                self.progress.emit(
                    self.request_id,
                    round((base + scale) * 100),
                )
        except CacheBuildCancelled:
            self.canceled.emit(self.request_id)
            return
        except Exception as error:
            self.failed.emit(self.request_id, str(error))
            return
        self.completed.emit(self.request_id, identities, self.staged)
