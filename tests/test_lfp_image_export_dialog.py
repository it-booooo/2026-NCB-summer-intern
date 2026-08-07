import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QMessageBox,
    QWidget,
)

# Avoid importing every export controller dependency through the package init.
original_data_export_package = sys.modules.get("src.data_export")
data_export_package = types.ModuleType("src.data_export")
data_export_package.__path__ = [
    str(Path(__file__).parents[1] / "src" / "data_export")
]
sys.modules["src.data_export"] = data_export_package

from src.data_export.lfp_image_dialog import LfpImageExportDialog
from src.signal_data import LfpFilterSettings

if original_data_export_package is None:
    sys.modules.pop("src.data_export", None)
else:
    sys.modules["src.data_export"] = original_data_export_package


class _ExportPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.sync_state = SimpleNamespace(record_time_origin_sec=None)
        self.lfp_channel_selector = QComboBox()
        self.lfp_channel_selector.addItem("Channel 2", 2)
        self.signal_view_selector = QComboBox()
        self.signal_view_selector.addItem("Raw", False)
        self.bandpass_checkbox = QCheckBox()
        self.bandpass_low_spin = self.create_frequency_spinbox(1.0)
        self.bandpass_high_spin = self.create_frequency_spinbox(100.0)
        self.filter_method_selector = QComboBox()
        self.filter_method_selector.addItem("None", "none")
        self.line_frequencies_edit = QLineEdit("60")
        self.notch_quality_spin = QDoubleSpinBox()
        self.notch_quality_spin.setValue(30.0)
        self.regression_window_spin = QDoubleSpinBox()
        self.regression_window_spin.setValue(4.0)
        self.regression_overlap_spin = QDoubleSpinBox()
        self.regression_overlap_spin.setValue(50.0)
        self.regression_all_harmonics_checkbox = QCheckBox()

    @staticmethod
    def available_lfp_channels():
        return [2]

    @staticmethod
    def full_lfp_record_xlim():
        return 0.0, 10.0

    @staticmethod
    def selected_channel(selector):
        return int(selector.currentData())

    @staticmethod
    def create_time_spinbox(value, minimum, maximum):
        spinbox = QDoubleSpinBox()
        spinbox.setRange(float(minimum), float(maximum))
        spinbox.setValue(float(value))
        return spinbox

    @staticmethod
    def create_frequency_spinbox(value):
        spinbox = QDoubleSpinBox()
        spinbox.setRange(0.01, 10_000.0)
        spinbox.setValue(float(value))
        return spinbox

    @staticmethod
    def settings_from_processing_controls(
        signal_selector,
        bandpass_checkbox,
        low_spin,
        high_spin,
        *_args,
    ):
        return LfpFilterSettings(
            show_filtered=bool(signal_selector.currentData()),
            bandpass_enabled=bandpass_checkbox.isChecked(),
            bandpass_low_hz=float(low_spin.value()),
            bandpass_high_hz=float(high_spin.value()),
        )


class LfpImageExportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.panel = _ExportPanel()
        self.dialog = LfpImageExportDialog(
            self.panel,
            self.directory.name,
        )

    def tearDown(self):
        self.dialog.close()
        self.panel.close()
        self.app.processEvents()
        self.directory.cleanup()

    def test_auto_and_custom_spectrogram_export_options(self):
        self.assertTrue(self.dialog.spectrogram_auto_scale_checkbox.isChecked())
        self.assertFalse(self.dialog.spectrogram_color_min_spin.isEnabled())
        self.assertFalse(self.dialog.spectrogram_color_max_spin.isEnabled())
        self.assertIsNone(self.dialog.options().spectrogram_color_limits_db)

        self.dialog.spectrogram_auto_scale_checkbox.setChecked(False)
        self.dialog.spectrogram_color_min_spin.setValue(-80.0)
        self.dialog.spectrogram_color_max_spin.setValue(-20.0)

        self.assertTrue(self.dialog.spectrogram_color_min_spin.isEnabled())
        self.assertTrue(self.dialog.spectrogram_color_max_spin.isEnabled())
        self.assertEqual(
            self.dialog.options().spectrogram_color_limits_db,
            (-80.0, -20.0),
        )

    def test_reversed_custom_spectrogram_scale_is_rejected(self):
        self.dialog.spectrogram_auto_scale_checkbox.setChecked(False)
        self.dialog.spectrogram_color_min_spin.setValue(-20.0)
        self.dialog.spectrogram_color_max_spin.setValue(-80.0)

        with patch.object(QMessageBox, "warning") as warning:
            self.dialog.validate_and_accept()

        warning.assert_called_once()
        self.assertNotEqual(
            self.dialog.result(),
            self.dialog.DialogCode.Accepted,
        )


if __name__ == "__main__":
    unittest.main()
