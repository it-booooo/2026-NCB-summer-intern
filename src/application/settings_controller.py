from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QInputDialog,
    QVBoxLayout,
)


class AnalysisSettingsController:
    """Own dialogs that mutate analysis and plotting settings."""

    def __init__(
        self,
        *,
        parent,
        data_state,
        analysis_settings,
        lfp_panel,
        show_opencl_status,
    ):
        self.parent = parent
        self.data_state = data_state
        self.analysis_settings = analysis_settings
        self.lfp_panel = lfp_panel
        self.show_opencl_status = show_opencl_status

    def set_plot_step(self, plot_name):
        title, step_attribute = {
            "lfp": ("Set LFP step", "lfp_step"),
            "axis": ("Set 3-axis step", "axis_step"),
        }[plot_name]
        current_step = getattr(self.data_state, step_attribute)
        step, accepted = QInputDialog.getInt(
            self.parent,
            title,
            "Step (-1 auto, 0 all):",
            -1 if current_step is None else int(current_step),
            -1,
            1_000_000,
            1,
        )
        if accepted:
            self.lfp_panel.set_plot_step(
                plot_name, None if step == -1 else step
            )

    def set_power_noise_frequency(self):
        items = ["60 Hz", "50 Hz"]
        values = [60.0, 50.0]
        current_index = 1 if self.data_state.line_noise_hz == 50.0 else 0
        text, accepted = QInputDialog.getItem(
            self.parent,
            "Set power noise frequency",
            "Power noise filter:",
            items,
            current_index,
            False,
        )
        if accepted:
            self.lfp_panel.set_line_noise_hz(values[items.index(text)])

    def set_lfp_peak_thresholds(self):
        dialog = QDialog(self.parent)
        dialog.setWindowTitle("Set LFP peak thresholds")

        height_input = QDoubleSpinBox(dialog)
        prominence_input = QDoubleSpinBox(dialog)
        min_distance_input = QDoubleSpinBox(dialog)
        for spinbox in (height_input, prominence_input):
            spinbox.setDecimals(2)
            spinbox.setRange(0.0, 100.0)
            spinbox.setSingleStep(0.1)
            spinbox.setSuffix(" σ")
        min_distance_input.setDecimals(3)
        min_distance_input.setRange(0.01, 100.0)
        min_distance_input.setSingleStep(0.01)
        min_distance_input.setSuffix(" sec")

        height_input.setValue(self.analysis_settings.lfp_peak_height_sigma)
        prominence_input.setValue(
            self.analysis_settings.lfp_peak_prominence_sigma
        )
        min_distance_input.setValue(
            self.analysis_settings.lfp_peak_min_distance_sec
        )

        form = QFormLayout()
        form.addRow("Peak height threshold:", height_input)
        form.addRow("Peak prominence threshold:", prominence_input)
        form.addRow("Minimum peak distance:", min_distance_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        layout = QVBoxLayout(dialog)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.analysis_settings.lfp_peak_height_sigma = height_input.value()
        self.analysis_settings.lfp_peak_prominence_sigma = (
            prominence_input.value()
        )
        self.analysis_settings.lfp_peak_min_distance_sec = (
            min_distance_input.value()
        )
