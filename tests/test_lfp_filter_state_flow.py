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

    def test_finished_worker_only_removes_its_registry_entry(self):
        host = SimpleNamespace(
            _lfp_coarse_workers={"request": object()},
        )

        WavePanel._discard_lfp_coarse_worker(host, "request")

        self.assertEqual(host._lfp_coarse_workers, {})

    def test_completed_cache_is_not_applied_after_settings_change(self):
        notch = LfpFilterSettings(
            show_filtered=True,
            line_noise_method="notch",
            line_noise_frequencies_hz=(60.0,),
        )
        regression = LfpFilterSettings(
            show_filtered=True,
            line_noise_method="regression",
            line_noise_frequencies_hz=(60.0,),
        )
        host = SimpleNamespace(
            _lfp_coarse_request_id="request",
            _lfp_coarse_key=("source", 3, 1, notch),
            _lfp_coarse_result_is_current=Mock(return_value=True),
            current_lfp_filter_settings=Mock(return_value=regression),
            _mark_lfp_filter_complete=Mock(),
            update_current_time_marker=Mock(),
            update_lfp_peak_artist=Mock(),
            lfp_fig=Mock(),
        )

        WavePanel._finish_lfp_coarse(
            host,
            "request",
            ("source",),
            {"channel": 3, "settings": notch},
        )

        host._mark_lfp_filter_complete.assert_not_called()
        host.lfp_fig.set_lfp_signal_view.assert_not_called()
        self.assertIsNone(host._lfp_coarse_request_id)
        self.assertIsNone(host._lfp_coarse_key)


if __name__ == "__main__":
    unittest.main()
