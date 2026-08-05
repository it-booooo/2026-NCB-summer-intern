from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..signal_data import LfpFilterSettings
from ..synchronization.time_conversion import absolute_time, relative_time


@dataclass(frozen=True)
class LfpImageExportOptions:
    channel: int
    left: float
    right: float
    settings: LfpFilterSettings
    image_types: tuple[str, ...]
    dpi: int
    directory: Path


class LfpImageExportDialog(QDialog):
    """Collect the shared settings for a batch of LFP image exports."""

    def __init__(self, panel, default_directory, parent=None):
        super().__init__(parent or panel)
        self.panel = panel
        self.setWindowTitle("Export LFP Images")
        self.setMinimumWidth(540)

        channels = panel.available_lfp_channels()
        if not channels:
            raise ValueError("The imported LFP CSV does not list available channels.")

        full_left, full_right = panel.full_lfp_record_xlim()
        display_full_left = relative_time(full_left, panel.sync_state.record_time_origin_sec)
        display_full_right = relative_time(full_right, panel.sync_state.record_time_origin_sec)
        display_min, display_max = sorted((display_full_left, display_full_right))

        self.channel_selector = QComboBox()
        selected_channel = panel.selected_channel(panel.lfp_channel_selector)
        for channel in channels:
            self.channel_selector.addItem(f"Channel {channel}", channel)
        if selected_channel in channels:
            self.channel_selector.setCurrentIndex(channels.index(selected_channel))

        self.start_spin = panel.create_time_spinbox(
            display_full_left, display_min, display_max
        )
        self.end_spin = panel.create_time_spinbox(
            display_full_right, display_min, display_max
        )

        self.signal_selector = QComboBox()
        self.signal_selector.addItem("Raw", False)
        self.signal_selector.addItem("Processed", True)
        self.signal_selector.setCurrentIndex(
            1 if bool(panel.signal_view_selector.currentData()) else 0
        )

        self.bandpass_checkbox = QCheckBox("Bandpass")
        self.bandpass_checkbox.setChecked(panel.bandpass_checkbox.isChecked())
        self.low_spin = panel.create_frequency_spinbox(panel.bandpass_low_spin.value())
        self.high_spin = panel.create_frequency_spinbox(
            panel.bandpass_high_spin.value()
        )
        self.method_selector = QComboBox()
        self.method_selector.addItem("None", "none")
        self.method_selector.addItem("Notch filter", "notch")
        self.method_selector.addItem("Sinusoidal regression", "regression")
        self.method_selector.setCurrentIndex(
            self.method_selector.findData(panel.filter_method_selector.currentData())
        )
        self.line_frequencies_edit = QLineEdit(panel.line_frequencies_edit.text())
        self.line_frequencies_edit.setPlaceholderText("e.g. 60, 120")
        self.line_frequencies_edit.setToolTip(
            "Enter one or more frequencies in Hz, separated by commas or spaces."
        )
        self.notch_quality_spin = QDoubleSpinBox()
        self.notch_quality_spin.setRange(1.0, 1000.0)
        self.notch_quality_spin.setValue(panel.notch_quality_spin.value())
        self.regression_window_spin = QDoubleSpinBox()
        self.regression_window_spin.setRange(0.1, 3600.0)
        self.regression_window_spin.setValue(panel.regression_window_spin.value())
        self.regression_window_spin.setSuffix(" s")
        self.regression_overlap_spin = QDoubleSpinBox()
        self.regression_overlap_spin.setRange(0.0, 95.0)
        self.regression_overlap_spin.setValue(panel.regression_overlap_spin.value())
        self.regression_overlap_spin.setSuffix(" %")
        self.regression_all_harmonics_checkbox = QCheckBox(
            "Remove all harmonics below Nyquist"
        )
        self.regression_all_harmonics_checkbox.setChecked(
            panel.regression_all_harmonics_checkbox.isChecked()
        )
        self.regression_all_harmonics_checkbox.setToolTip(
            "Automatically include every integer multiple of each entered frequency."
        )

        bandpass_layout = QHBoxLayout()
        bandpass_layout.setContentsMargins(0, 0, 0, 0)
        bandpass_layout.addWidget(QLabel("Low"))
        bandpass_layout.addWidget(self.low_spin)
        bandpass_layout.addWidget(QLabel("High"))
        bandpass_layout.addWidget(self.high_spin)

        time_label = "Sync time" if panel.sync_state.record_time_origin_sec is not None else "Time"
        settings_form = QFormLayout()
        settings_form.addRow("Channel", self.channel_selector)
        settings_form.addRow(f"Start {time_label}", self.start_spin)
        settings_form.addRow(f"End {time_label}", self.end_spin)
        settings_form.addRow("Signal", self.signal_selector)
        settings_form.addRow("", self.bandpass_checkbox)
        settings_form.addRow("Bandpass range", bandpass_layout)
        settings_form.addRow("Line-noise method", self.method_selector)
        settings_form.addRow("Line frequencies", self.line_frequencies_edit)
        settings_form.addRow("Notch Q", self.notch_quality_spin)
        settings_form.addRow("Regression window", self.regression_window_spin)
        settings_form.addRow("Regression overlap", self.regression_overlap_spin)
        settings_form.addRow("", self.regression_all_harmonics_checkbox)

        settings_group = QGroupBox("Signal and time range")
        settings_group.setLayout(settings_form)

        self.waveform_checkbox = QCheckBox("LFP waveform")
        self.power_checkbox = QCheckBox("Power spectrum")
        self.spectrogram_checkbox = QCheckBox("Spectrogram")
        for checkbox in (
            self.waveform_checkbox,
            self.power_checkbox,
            self.spectrogram_checkbox,
        ):
            checkbox.setChecked(True)

        # self.dpi_spin = QSpinBox()
        # self.dpi_spin.setRange(72, 1200)
        # self.dpi_spin.setValue(300)
        # self.dpi_spin.setSuffix(" dpi")

        image_layout = QVBoxLayout()
        image_layout.addWidget(self.waveform_checkbox)
        image_layout.addWidget(self.power_checkbox)
        image_layout.addWidget(self.spectrogram_checkbox)
        # image_form = QFormLayout()
        # image_form.addRow("Resolution", self.dpi_spin)
        # image_layout.addLayout(image_form)

        image_group = QGroupBox("Images to export")
        image_group.setLayout(image_layout)

        self.destination_edit = QLineEdit(str(default_directory))
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self.choose_destination)
        destination_layout = QHBoxLayout()
        destination_layout.addWidget(self.destination_edit, stretch=1)
        destination_layout.addWidget(browse_button)

        destination_group = QGroupBox("Output folder")
        destination_group.setLayout(destination_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        export_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        export_button.setText("Export")
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(settings_group)
        layout.addWidget(image_group)
        layout.addWidget(destination_group)
        layout.addWidget(buttons)
        self.setLayout(layout)

        self.signal_selector.currentIndexChanged.connect(
            self.update_processing_controls
        )
        self.bandpass_checkbox.toggled.connect(self.update_processing_controls)
        self.method_selector.currentIndexChanged.connect(
            self.update_processing_controls
        )
        self.update_processing_controls()

    def update_processing_controls(self, *_args):
        """Update processing controls."""
        processed = bool(self.signal_selector.currentData())
        self.bandpass_checkbox.setEnabled(processed)
        bandpass_enabled = processed and self.bandpass_checkbox.isChecked()
        self.low_spin.setEnabled(bandpass_enabled)
        self.high_spin.setEnabled(bandpass_enabled)
        self.method_selector.setEnabled(processed)
        method = self.method_selector.currentData() if processed else "none"
        active = method in {"notch", "regression"}
        self.line_frequencies_edit.setEnabled(active)
        self.notch_quality_spin.setEnabled(method == "notch")
        regression = method == "regression"
        self.regression_window_spin.setEnabled(regression)
        self.regression_overlap_spin.setEnabled(regression)
        self.regression_all_harmonics_checkbox.setEnabled(regression)

    def choose_destination(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select LFP Image Output Folder",
            self.destination_edit.text().strip(),
            QFileDialog.Option.ShowDirsOnly,
        )
        if directory:
            self.destination_edit.setText(directory)

    def selected_image_types(self):
        """Select ed image types.

        Args:
            None.
        """
        selected = []
        for name, checkbox in (
            ("waveform", self.waveform_checkbox),
            ("power_spectrum", self.power_checkbox),
            ("spectrogram", self.spectrogram_checkbox),
        ):
            if checkbox.isChecked():
                selected.append(name)
        return tuple(selected)

    def validate_and_accept(self):
        """Validate and accept.

        Args:
            None.
        """
        if not self.selected_image_types():
            QMessageBox.warning(
                self,
                "No images selected",
                "Select at least one LFP image to export.",
            )
            return

        if self.start_spin.value() == self.end_spin.value():
            QMessageBox.warning(
                self,
                "Invalid time range",
                "Start and end time must be different.",
            )
            return

        if (
            bool(self.signal_selector.currentData())
            and self.bandpass_checkbox.isChecked()
            and self.low_spin.value() >= self.high_spin.value()
        ):
            QMessageBox.warning(
                self,
                "Invalid bandpass range",
                "The high cutoff must be greater than the low cutoff.",
            )
            return

        try:
            self.panel.settings_from_processing_controls(
                self.signal_selector,
                self.bandpass_checkbox,
                self.low_spin,
                self.high_spin,
                self.method_selector,
                self.line_frequencies_edit,
                self.notch_quality_spin,
                self.regression_window_spin,
                self.regression_overlap_spin,
                self.regression_all_harmonics_checkbox,
            )
        except ValueError as error:
            QMessageBox.warning(
                self,
                "Invalid line-noise frequencies",
                str(error),
            )
            return

        directory_text = self.destination_edit.text().strip()
        if not directory_text or not Path(directory_text).is_dir():
            QMessageBox.warning(
                self,
                "Invalid output folder",
                "Choose an existing folder for the exported images.",
            )
            return

        self.accept()

    def options(self):
        start = absolute_time(
            self.start_spin.value(), self.panel.sync_state.record_time_origin_sec
        )
        end = absolute_time(self.end_spin.value(), self.panel.sync_state.record_time_origin_sec)
        left, right = sorted((start, end))
        settings = self.panel.settings_from_processing_controls(
            self.signal_selector,
            self.bandpass_checkbox,
            self.low_spin,
            self.high_spin,
            self.method_selector,
            self.line_frequencies_edit,
            self.notch_quality_spin,
            self.regression_window_spin,
            self.regression_overlap_spin,
            self.regression_all_harmonics_checkbox,
        )
        return LfpImageExportOptions(
            channel=int(self.channel_selector.currentData()),
            left=left,
            right=right,
            settings=settings,
            image_types=self.selected_image_types(),
            dpi=300,
            directory=Path(self.destination_edit.text().strip()),
        )
