from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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

from ..signal_processing import LfpFilterSettings
from ..time_utils import absolute_time, relative_time


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
        display_full_left = relative_time(full_left, panel.sync_time_origin_sec)
        display_full_right = relative_time(full_right, panel.sync_time_origin_sec)
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
        self.notch_checkbox = QCheckBox(
            f"Notch {panel.format_line_noise_label()}"
        )
        self.notch_checkbox.setChecked(panel.notch_checkbox.isChecked())

        bandpass_layout = QHBoxLayout()
        bandpass_layout.setContentsMargins(0, 0, 0, 0)
        bandpass_layout.addWidget(QLabel("Low"))
        bandpass_layout.addWidget(self.low_spin)
        bandpass_layout.addWidget(QLabel("High"))
        bandpass_layout.addWidget(self.high_spin)

        time_label = "Sync time" if panel.sync_time_origin_sec is not None else "Time"
        settings_form = QFormLayout()
        settings_form.addRow("Channel", self.channel_selector)
        settings_form.addRow(f"Start {time_label}", self.start_spin)
        settings_form.addRow(f"End {time_label}", self.end_spin)
        settings_form.addRow("Signal", self.signal_selector)
        settings_form.addRow("", self.bandpass_checkbox)
        settings_form.addRow("Bandpass range", bandpass_layout)
        settings_form.addRow("", self.notch_checkbox)

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
        self.update_processing_controls()

    def update_processing_controls(self, *_args):
        """Describe update_processing_controls.

        Args:
            *_args: Input accepted by this function.

        Returns:
            The value produced by this function, if any.
        """
        processed = bool(self.signal_selector.currentData())
        self.bandpass_checkbox.setEnabled(processed)
        self.notch_checkbox.setEnabled(processed)
        bandpass_enabled = processed and self.bandpass_checkbox.isChecked()
        self.low_spin.setEnabled(bandpass_enabled)
        self.high_spin.setEnabled(bandpass_enabled)

    def choose_destination(self):
        """Describe choose_destination.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
        """
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select LFP Image Output Folder",
            self.destination_edit.text().strip(),
            QFileDialog.Option.ShowDirsOnly,
        )
        if directory:
            self.destination_edit.setText(directory)

    def selected_image_types(self):
        """Describe selected_image_types.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
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
        """Describe validate_and_accept.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
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
        """Describe options.

        Args:
            None.

        Returns:
            The value produced by this function, if any.
        """
        start = absolute_time(
            self.start_spin.value(), self.panel.sync_time_origin_sec
        )
        end = absolute_time(self.end_spin.value(), self.panel.sync_time_origin_sec)
        left, right = sorted((start, end))
        settings = self.panel.settings_from_processing_controls(
            self.signal_selector,
            self.bandpass_checkbox,
            self.low_spin,
            self.high_spin,
            self.notch_checkbox,
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
