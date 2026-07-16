"""LFP analysis dialogs and figure creation used by ``LfpPanel``."""

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDoubleSpinBox, QLabel, QMessageBox, QVBoxLayout
from matplotlib.figure import Figure

from .. import signal_data as signal_func
from ..charts.chart_helpers import format_signal_label, resolve_plot_step
from ..signal_data import readers as read
from ..synchronization.time_conversion import relative_time


class LfpAnalysisMixin:
    def create_time_spinbox(self, value, minimum, maximum):
        """Create time spinbox.
    
        Args:
            value: New value to store or apply.
            minimum: Input used by this operation.
            maximum: Input used by this operation.
        """
        spinbox = QDoubleSpinBox()
        spinbox.setDecimals(4)
        spinbox.setRange(float(minimum), float(maximum))
        spinbox.setSingleStep(0.1)
        spinbox.setValue(float(value))
        spinbox.setSuffix(" s")
        return spinbox
    
    def full_lfp_record_xlim(self):
        """Provide full lfp record xlim functionality.
    
        Args:
            None.
        """
        if self.lfp_fig is not None:
            return self.lfp_fig.lfp_full_xlim
    
        if not (self.data_state.lfp_info and self.data_state.lfp_info.get("path")):
            raise ValueError("Please import LFP CSV data first.")
    
        data = read.read_signal_csv(self.data_state.lfp_info["path"])
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
        """Set tings from processing controls.
    
        Args:
            signal_selector: Input used by this operation.
            bandpass_checkbox: Input used by this operation.
            low_spin: Input used by this operation.
            high_spin: Input used by this operation.
            notch_checkbox: Input used by this operation.
        """
        line_noise_hz = self.data_state.line_noise_hz if notch_checkbox.isChecked() else None
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
                    "sync time" if self.sync_state.record_time_origin_sec is not None else "time",
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
        """Open lfp analysis dialog.
    
        Args:
            title: Dialog title displayed to the user.
            channel: LFP channel identifier.
            left: Input used by this operation.
            right: Input used by this operation.
            segment: Input used by this operation.
            settings: Configuration settings for this operation.
            figure: Matplotlib figure to use or update.
            size: Input used by this operation.
        """
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowTitle(title)
        dialog.resize(*size)
    
        display_left = relative_time(left, self.sync_state.record_time_origin_sec)
        display_right = relative_time(right, self.sync_state.record_time_origin_sec)
        time_mode = "sync time" if self.sync_state.record_time_origin_sec is not None else "time"
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
        """Remove the reference to spectrum dialog.
    
        Args:
            dialog: Input used by this operation.
        """
        if dialog in self.spectrum_dialogs:
            self.spectrum_dialogs.remove(dialog)
    
    def create_power_spectrum_figure(self, channel, frequencies, power):
        """Create power spectrum figure.
    
        Args:
            channel: LFP channel identifier.
            frequencies: Input used by this operation.
            power: Input used by this operation.
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
        """Create lfp waveform figure.
    
        Args:
            channel: LFP channel identifier.
            segment: Input used by this operation.
            settings: Configuration settings for this operation.
            time_mode: Input used by this operation.
            info: Metadata or state information to store or use.
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
        ax.set_ylabel(format_signal_label(info["value_unit"]))
        ax.grid(True, linewidth=0.4, alpha=0.35)
        return figure
    
    def annotate_lfp_figure(self, figure, channel, segment, settings):
        """Provide annotate lfp figure functionality.
    
        Args:
            figure: Matplotlib figure to use or update.
            channel: LFP channel identifier.
            segment: Input used by this operation.
            settings: Configuration settings for this operation.
        """
        filename = self.data_state.lfp_info.get("filename", "LFP") if self.data_state.lfp_info else "LFP"
        time_mode = "Sync time" if self.sync_state.record_time_origin_sec is not None else "Time"
        display_left = relative_time(
            float(segment.record_time_s[0]), self.sync_state.record_time_origin_sec
        )
        display_right = relative_time(
            float(segment.record_time_s[-1]), self.sync_state.record_time_origin_sec
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
        """Create spectrogram figure.
    
        Args:
            channel: LFP channel identifier.
            segment: Input used by this operation.
            frequencies: Input used by this operation.
            times: Input used by this operation.
            power: Input used by this operation.
            time_mode: Input used by this operation.
        """
        figure = Figure(figsize=(8.0, 4.8), constrained_layout=True)
        ax = figure.add_subplot(111)
        plot_times = times + relative_time(
            float(segment.record_time_s[0]), self.sync_state.record_time_origin_sec
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
