import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.app_state import DataState
from src.signal_data import LfpFilterSettings

# Import the focused widget without loading unrelated optional UI modules.
ui_package = types.ModuleType("src.ui")
ui_package.__path__ = [str(Path(__file__).parents[1] / "src" / "ui")]
sys.modules.setdefault("src.ui", ui_package)

from src.ui.wave_panel import WavePanel  # noqa: E402


class LfpFilterStateFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_wave_panel_preserves_the_existing_60_hz_ui_default(self):
        panel = WavePanel()
        try:
            settings = panel.current_lfp_filter_settings()

            self.assertEqual(panel.line_frequencies_edit.text(), "60")
            self.assertEqual(settings.line_noise_hz, 60.0)
            self.assertEqual(settings.line_noise_frequencies_hz, (60.0,))
            self.assertIs(panel.data_state.lfp_filter_settings, settings)
        finally:
            panel.close()
            panel.deleteLater()
            self.app.processEvents()

    def test_store_writes_the_settings_object_directly_to_data_state(self):
        settings = LfpFilterSettings(
            show_filtered=True,
            line_noise_method="none",
        )
        host = SimpleNamespace(
            data_state=DataState(),
            project_changed=Mock(),
        )

        WavePanel.store_lfp_filter_settings(host, settings)

        self.assertIs(host.data_state.lfp_filter_settings, settings)
        host.project_changed.emit.assert_called_once_with()

    def test_ready_project_cache_is_green_before_timeline_creation(self):
        dataset = Mock()
        dataset.record_bounds_s.return_value = (12.5, 98.0)
        host = SimpleNamespace(
            data_state=SimpleNamespace(lfp_dataset=dataset),
            _lfp_filter_completed_ranges=[],
            _set_lfp_filter_status=Mock(),
        )

        WavePanel._mark_lfp_filter_complete(host, channel=4)

        dataset.record_bounds_s.assert_called_once_with(4)
        self.assertEqual(host._lfp_filter_completed_ranges, [(12.5, 98.0)])
        host._set_lfp_filter_status.assert_called_once_with(True)


if __name__ == "__main__":
    unittest.main()
