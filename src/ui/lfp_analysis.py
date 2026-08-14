"""LFP analysis dialogs and figure creation used by ``WavePanel``."""

import uuid

from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

from .. import signal_data as signal_func
from ..background_requests import widget_is_valid
from ..smooth_progress import SmoothProgressDialog
from ..charts.chart_helpers import format_signal_label, resolve_plot_step
from ..synchronization.time_conversion import relative_time


class _HorizontalPixmapScrollArea(QScrollArea):
    """Fit a high-resolution plot vertically and scroll it only horizontally."""

    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self._source_pixmap = pixmap
        self._scaled_height = 0
        self.image_label = QLabel()
        self.image_label.setPixmap(pixmap)
        # Deliberately NOT setScaledContents(True): that rescales the entire
        # high-resolution source pixmap in native code on *every* paint event,
        # which stalls the GUI thread for seconds on a large figure (the window
        # shows "Not Responding").  We instead rescale once whenever the
        # viewport height changes, and every subsequent paint is a plain blit.
        self.setWidget(self.image_label)
        self.setWidgetResizable(False)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_pixmap_height()

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_pixmap_height()

    def _target_height(self):
        """Height to scale to, derived only from the scroll area's own size.

        Reading ``viewport().height()`` here would be circular: the label width
        we set from the height decides whether a horizontal scrollbar appears,
        the scrollbar changes the viewport height, and that would feed back into
        the next call -- an endless appear/disappear oscillation that locks the
        GUI thread.  Instead we compute from ``self.height()`` (stable, set by
        the dialog layout) and *always* reserve the scrollbar's height once the
        image is wider than the frame, so the result never depends on the
        scrollbar's current visibility.
        """
        if self._source_pixmap.height() <= 0:
            return 0
        aspect_ratio = self._source_pixmap.width() / self._source_pixmap.height()
        frame = 2 * self.frameWidth()
        available_height = self.height() - frame
        available_width = self.width() - frame
        if available_height <= 0:
            return 0
        scrollbar_height = self.horizontalScrollBar().sizeHint().height()
        if round(available_height * aspect_ratio) > available_width:
            available_height -= scrollbar_height
        return max(1, available_height)

    def fit_pixmap_height(self):
        """Rescale the pixmap once to a stable target height, preserving aspect."""
        if self._source_pixmap.isNull():
            return
        target_height = self._target_height()
        if target_height <= 0 or target_height == self._scaled_height:
            return
        # Scale to *physical* pixels (logical height x devicePixelRatio) and tag
        # the result with that ratio.  Without this the pixmap only carries as
        # many pixels as there are logical points, so on a HiDPI display (125% /
        # 150% Windows scaling) Qt upscales it and the plot looks blurry.
        # Smooth (bilinear) scaling keeps text and thin lines crisp; the
        # ``_scaled_height`` guard runs this at most once per height change --
        # never per paint -- so it cannot stall the GUI.
        ratio = self.devicePixelRatioF()
        physical_height = max(1, round(target_height * ratio))
        scaled = self._source_pixmap.scaledToHeight(
            physical_height,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(ratio)
        self._scaled_height = target_height
        self.image_label.setPixmap(scaled)
        self.image_label.setFixedSize(
            max(1, round(scaled.width() / ratio)),
            max(1, round(scaled.height() / ratio)),
        )

    def clear_pixmap(self):
        self.image_label.clear()
        self._source_pixmap = QPixmap()
        self._scaled_height = 0


class LfpAnalysisMixin:
    def create_time_spinbox(self, value, minimum, maximum):
        """Create time spinbox.

        Args:
            value: New value to store or apply.
        """
        spinbox = QDoubleSpinBox()
        spinbox.setDecimals(4)
        spinbox.setRange(float(minimum), float(maximum))
        spinbox.setSingleStep(0.1)
        spinbox.setValue(float(value))
        spinbox.setSuffix(" s")
        return spinbox
    
    def full_lfp_record_xlim(self):
        if self.lfp_fig is not None:
            return self.lfp_fig.lfp_full_xlim
    
        if not (self.data_state.lfp_info and self.data_state.lfp_info.get("path")):
            raise ValueError("Please import LFP CSV data first.")
    
        dataset = self.ensure_lfp_dataset()
        channels = dataset.channels
        if not channels:
            raise ValueError("LFP CSV does not contain samples.")
        return dataset.record_bounds_s(channels[0])
    
    def settings_from_processing_controls(
        self,
        signal_selector,
        bandpass_checkbox,
        low_spin,
        high_spin,
        method_selector,
        line_frequencies_edit,
        notch_quality_spin,
        regression_window_spin,
        regression_overlap_spin,
        regression_all_harmonics_checkbox,
    ):
        """Set tings from processing controls."""
        method = str(method_selector.currentData())
        frequencies = (
            ()
            if method == "none"
            else signal_func.parse_line_noise_frequencies(
                line_frequencies_edit.text()
            )
        )
        if method != "none" and not frequencies:
            raise ValueError("Enter at least one line-noise frequency.")
        line_noise_hz = frequencies[0] if frequencies else None
    
        return signal_func.LfpFilterSettings(
            show_filtered=bool(signal_selector.currentData()),
            bandpass_enabled=bandpass_checkbox.isChecked(),
            bandpass_low_hz=float(low_spin.value()),
            bandpass_high_hz=float(high_spin.value()),
            line_noise_hz=line_noise_hz,
            notch_quality=float(notch_quality_spin.value()),
            line_noise_method=method,
            regression_window_seconds=float(regression_window_spin.value()),
            regression_overlap=float(regression_overlap_spin.value()) / 100.0,
            regression_harmonics=1,
            regression_all_harmonics=(
                regression_all_harmonics_checkbox.isChecked()
            ),
            line_noise_frequencies_hz=frequencies,
        )
    
    def _prepare_lfp_analysis(self, failure_title):
        """Validate the selection without running signal work on the GUI thread."""
        if not (self.data_state.lfp_info and self.data_state.lfp_info.get("path")):
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
        except Exception as error:
            QMessageBox.warning(self, failure_title, str(error))
            return None

        return channel, left, right, settings
    
    def show_lfp_analysis(
        self,
        analysis_type,
        *,
        spectrogram_color_limits_db=None,
    ):
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
            return False
    
        channel, left, right, settings = analysis
        dataset = self.ensure_lfp_dataset()
        request_id = uuid.uuid4().hex
        self._cancel_lfp_analysis_workers()
        self._lfp_analysis_request_id = request_id
        worker = signal_func.LfpAnalysisWorker(
            request_id,
            dataset,
            channel,
            left,
            right,
            settings,
            analysis_type,
            self.sync_state.record_time_origin_sec,
            spectrogram_color_limits_db,
        )
        workers = getattr(self, "_lfp_analysis_workers", {})
        self._lfp_analysis_workers = workers
        workers[request_id] = worker
        progress = SmoothProgressDialog(
            "Preparing LFP analysis…",
            "Cancel",
            0,
            100,
            self,
        )
        progress.setWindowTitle(dialog_title)
        progress.setWindowModality(Qt.WindowModality.NonModal)
        progress.setAutoClose(False)
        self._lfp_analysis_progress = progress

        worker.progress.connect(
            lambda result_id, value: self._update_lfp_analysis_progress(
                result_id, value
            )
        )
        worker.completed.connect(
            lambda result_id, identity, result: self._finish_lfp_analysis(
                result_id,
                identity,
                result,
                analysis_type=analysis_type,
                failure_title=failure_title,
                dialog_title=dialog_title,
                dialog_size=dialog_size,
                channel=channel,
                left=left,
                right=right,
                settings=settings,
                spectrogram_color_limits_db=spectrogram_color_limits_db,
            )
        )
        worker.failed.connect(
            lambda result_id, identity, message: self._fail_lfp_analysis(
                result_id,
                identity,
                failure_title,
                message,
            )
        )
        worker.canceled.connect(
            lambda result_id, _identity: self._complete_lfp_analysis_request(
                result_id
            )
        )
        progress.canceled.connect(worker.cancel)
        worker.finished.connect(
            lambda result_id=request_id: self._discard_lfp_analysis_worker(
                result_id
            )
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()
        progress.show()
        return True

    def _analysis_result_is_current(self, request_id, identity):
        if (
            request_id != getattr(self, "_lfp_analysis_request_id", None)
            or not widget_is_valid(self)
        ):
            return False
        dataset = self.data_state.lfp_dataset
        if dataset is None:
            return False
        try:
            return dataset.source.identity_token() == identity
        except OSError:
            return False

    def _update_lfp_analysis_progress(self, request_id, value):
        if request_id != getattr(self, "_lfp_analysis_request_id", None):
            return
        progress = getattr(self, "_lfp_analysis_progress", None)
        if progress is not None and widget_is_valid(progress):
            progress.setValue(value)

    def _finish_lfp_analysis(
        self,
        request_id,
        identity,
        result,
        *,
        analysis_type,
        failure_title,
        dialog_title,
        dialog_size,
        channel,
        left,
        right,
        settings,
        spectrogram_color_limits_db=None,
    ):
        if not self._analysis_result_is_current(request_id, identity):
            result.clear()
            return
        sample_count = result["sample_count"]
        sample_rate_hz = result["sample_rate_hz"]
        rendered_color_limits_db = result.get(
            "spectrogram_color_limits_db"
        )
        try:
            image_png = result.pop("image_png")
            image = QImage.fromData(image_png, "PNG")
            del image_png
            if image.isNull():
                raise ValueError("Analysis process returned an invalid image.")
            pixmap = QPixmap.fromImage(image)
            del image
        except Exception as error:
            result.clear()
            self._complete_lfp_analysis_request(request_id)
            QMessageBox.warning(self, failure_title, str(error))
            return
        result.clear()
        self._complete_lfp_analysis_request(request_id)
        self.open_lfp_analysis_dialog(
            f"{dialog_title} - Channel {channel}",
            channel,
            left,
            right,
            sample_count,
            sample_rate_hz,
            settings,
            pixmap,
            dialog_size,
            analysis_type=analysis_type,
            spectrogram_auto_scale=(spectrogram_color_limits_db is None),
            spectrogram_color_limits_db=rendered_color_limits_db,
        )

    def _fail_lfp_analysis(
        self,
        request_id,
        identity,
        failure_title,
        message,
    ):
        if not self._analysis_result_is_current(request_id, identity):
            return
        self._complete_lfp_analysis_request(request_id)
        QMessageBox.warning(self, failure_title, message)

    def _complete_lfp_analysis_request(self, request_id):
        if request_id != getattr(self, "_lfp_analysis_request_id", None):
            return
        progress = getattr(self, "_lfp_analysis_progress", None)
        if progress is not None and widget_is_valid(progress):
            progress.close()
        self._lfp_analysis_progress = None

    def _discard_lfp_analysis_worker(self, request_id):
        workers = getattr(self, "_lfp_analysis_workers", {})
        workers.pop(request_id, None)

    def _cancel_lfp_analysis_workers(self, wait=False):
        workers = list(getattr(self, "_lfp_analysis_workers", {}).values())
        for worker in workers:
            worker.cancel()
        if wait:
            for worker in workers:
                worker.wait(10_000)
        return not any(worker.isRunning() for worker in workers)
    
    def open_lfp_analysis_dialog(
        self,
        title,
        channel,
        left,
        right,
        sample_count,
        sample_rate_hz,
        settings,
        pixmap,
        size,
        *,
        analysis_type=None,
        spectrogram_auto_scale=True,
        spectrogram_color_limits_db=None,
    ):
        """Open lfp analysis dialog.

        Args:
            title: Dialog title displayed to the user.
            channel: LFP channel identifier.
            pixmap: Static rendering of the completed Matplotlib figure.
        """
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setModal(False)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setWindowTitle(title)
        display_left = relative_time(left, self.sync_state.record_time_origin_sec)
        display_right = relative_time(right, self.sync_state.record_time_origin_sec)
        time_mode = "sync time" if self.sync_state.record_time_origin_sec is not None else "time"
        status = QLabel(
            f"Channel {channel} | {signal_func.filter_description(settings)} | "
            f"{time_mode}: {display_left:.2f}-{display_right:.2f} s | "
            f"samples={sample_count} | Fs={sample_rate_hz:g} Hz"
        )

        scroll_area = _HorizontalPixmapScrollArea(pixmap)
        image_label = scroll_area.image_label

        layout = QVBoxLayout()
        layout.addWidget(status)
        if analysis_type == "spectrogram":
            self._add_spectrogram_scale_controls(
                layout,
                dialog,
                auto_scale=spectrogram_auto_scale,
                color_limits_db=spectrogram_color_limits_db,
            )
        layout.addWidget(scroll_area)
        dialog.setLayout(layout)
        dialog._lfp_image_label = image_label
        dialog._lfp_scroll_area = scroll_area

        available = dialog.screen().availableGeometry()
        max_width = round(available.width() * 0.9)
        max_height = round(available.height() * 0.9)
        window_height = min(size[1], max_height)
        # Size the window to the rendered image's aspect ratio so a longer
        # recording opens a wider window instead of hiding the extra time
        # behind the horizontal scrollbar.  Clamp to the screen; anything wider
        # than the clamp still scrolls horizontally.
        if not pixmap.isNull() and pixmap.height() > 0:
            aspect_ratio = pixmap.width() / pixmap.height()
            # Approximate the non-image chrome (status line, optional scale
            # controls, layout margins) so the image itself drives the width.
            chrome_height = 96 if analysis_type == "spectrogram" else 64
            content_height = max(1, window_height - chrome_height)
            image_width = round(content_height * aspect_ratio)
            window_width = min(max(image_width + 24, size[0]), max_width)
        else:
            window_width = min(size[0], max_width)
        dialog.resize(window_width, window_height)
    
        self.spectrum_dialogs.append(dialog)
        dialog.finished.connect(self.forget_spectrum_dialog)
        dialog.show()
        scroll_area.fit_pixmap_height()
        dialog.raise_()
        dialog.activateWindow()

    def _add_spectrogram_scale_controls(
        self,
        layout,
        dialog,
        *,
        auto_scale,
        color_limits_db,
    ):
        """Add automatic and custom PSD color-scale controls to a dialog."""
        if color_limits_db is None:
            color_limits_db = (-120.0, 0.0)
        color_low, color_high = map(float, color_limits_db)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("PSD color scale"))
        auto_checkbox = QCheckBox("Auto")
        auto_checkbox.setChecked(bool(auto_scale))
        auto_checkbox.setToolTip(
            "Automatically scale colors from PSD values in the visible frequency band."
        )
        controls.addWidget(auto_checkbox)

        minimum_spin = self._create_spectrogram_db_spinbox(color_low)
        maximum_spin = self._create_spectrogram_db_spinbox(color_high)
        controls.addWidget(QLabel("Min"))
        controls.addWidget(minimum_spin)
        controls.addWidget(QLabel("Max"))
        controls.addWidget(maximum_spin)

        apply_button = QPushButton("Apply")
        apply_button.setToolTip("Rerender the spectrogram with this color scale.")
        controls.addWidget(apply_button)
        controls.addStretch()
        layout.addLayout(controls)

        def update_manual_controls(automatic):
            minimum_spin.setEnabled(not automatic)
            maximum_spin.setEnabled(not automatic)

        auto_checkbox.toggled.connect(update_manual_controls)
        update_manual_controls(auto_checkbox.isChecked())
        apply_button.clicked.connect(
            lambda _checked=False: self._apply_spectrogram_scale(
                dialog,
                auto_checkbox,
                minimum_spin,
                maximum_spin,
            )
        )

        dialog._spectrogram_auto_scale = auto_checkbox
        dialog._spectrogram_color_min = minimum_spin
        dialog._spectrogram_color_max = maximum_spin
        dialog._spectrogram_scale_apply = apply_button

    @staticmethod
    def _create_spectrogram_db_spinbox(value):
        spinbox = QDoubleSpinBox()
        spinbox.setDecimals(2)
        spinbox.setRange(-1_000_000.0, 1_000_000.0)
        spinbox.setSingleStep(1.0)
        spinbox.setSuffix(" dB")
        spinbox.setValue(float(value))
        spinbox.setMaximumWidth(120)
        return spinbox

    def _apply_spectrogram_scale(
        self,
        dialog,
        auto_checkbox,
        minimum_spin,
        maximum_spin,
    ):
        """Validate the selected color scale and rerun the spectrogram render."""
        color_limits_db = None
        if not auto_checkbox.isChecked():
            color_low = float(minimum_spin.value())
            color_high = float(maximum_spin.value())
            if color_low >= color_high:
                QMessageBox.warning(
                    dialog,
                    "Invalid color scale",
                    "Minimum PSD must be below maximum PSD.",
                )
                return False
            color_limits_db = (color_low, color_high)

        started = self.show_lfp_analysis(
            "spectrogram",
            spectrogram_color_limits_db=color_limits_db,
        )
        if started:
            dialog.close()
        return bool(started)
    
    def forget_spectrum_dialog(self, dialog_or_result=0):
        """Release the static image and every owned dialog reference."""
        dialog = (
            dialog_or_result
            if isinstance(dialog_or_result, QDialog)
            else self.sender()
        )
        if dialog is None:
            return
        if dialog in self.spectrum_dialogs:
            self.spectrum_dialogs.remove(dialog)
        image_label = getattr(dialog, "_lfp_image_label", None)
        if image_label is not None:
            image_label.clear()
            image_label.deleteLater()
        scroll_area = getattr(dialog, "_lfp_scroll_area", None)
        if scroll_area is not None:
            scroll_area.clear_pixmap()
            scroll_area.takeWidget()
            scroll_area.deleteLater()
        dialog._lfp_image_label = None
        dialog._lfp_scroll_area = None

    @staticmethod
    def _figure_to_pixmap(figure):
        """Render a Figure to an owning Qt image without retaining Matplotlib."""
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        canvas = FigureCanvasAgg(figure)
        canvas.draw()
        width, height = canvas.get_width_height()
        image = QImage(
            canvas.buffer_rgba(),
            width,
            height,
            QImage.Format.Format_RGBA8888,
        ).copy()
        return QPixmap.fromImage(image)

    @staticmethod
    def _dispose_figure(figure):
        """Clear artists and detach the renderer's Figure reference cycle."""
        canvas = figure.canvas
        figure.clear()
        figure.set_canvas(None)
        if canvas is not None:
            canvas.figure = None
    
    def create_lfp_waveform_figure(self, channel, segment, settings, time_mode):
        """Create lfp waveform figure.

        Args:
            channel: LFP channel identifier.
        """
        duration_sec = abs(
            float(segment.record_time_s[-1]) - float(segment.record_time_s[0])
        )
        figure_width = min(24.0, 8.0 + duration_sec / 120.0)
        figure = Figure(figsize=(figure_width, 4.8), constrained_layout=True)
        ax = figure.add_subplot(111)
    
        plot_step = resolve_plot_step(segment.sample_count, self.data_state.lfp_step)
        if plot_step == 0 or segment.sample_count <= plot_step:
            plot_index = slice(None)
        else:
            plot_index = slice(None, None, plot_step)
    
        if self.sync_state.record_time_origin_sec is None:
            plot_times = segment.record_time_s
        else:
            plot_times = segment.record_time_s - self.sync_state.record_time_origin_sec
    
        ax.plot(
            plot_times[plot_index],
            segment.values[plot_index],
            linewidth=0.6,
            color="#1f77b4",
        )
        ax.set_title(f"LFP Waveform - Channel {channel}")
        ax.set_xlabel(f"{time_mode} (s)")
        value_unit = self.ensure_lfp_dataset().info["value_unit"]
        ax.set_ylabel(format_signal_label(value_unit))
        ax.grid(True, linewidth=0.4, alpha=0.35)
        return figure
    
    def annotate_lfp_figure(
        self,
        figure,
        channel,
        start_time_s,
        end_time_s,
        settings,
    ):
        filename = self.data_state.lfp_info.get("filename", "LFP") if self.data_state.lfp_info else "LFP"
        time_mode = "Sync time" if self.sync_state.record_time_origin_sec is not None else "Time"
        display_left = relative_time(
            float(start_time_s), self.sync_state.record_time_origin_sec
        )
        display_right = relative_time(
            float(end_time_s), self.sync_state.record_time_origin_sec
        )
        processing = signal_func.filter_description(settings)
        figure.suptitle(
            f"File: {filename} | Channel {channel} | {processing}\n"
            f"{time_mode}: {display_left:.3f}-{display_right:.3f} s",
            fontsize=8,
        )
