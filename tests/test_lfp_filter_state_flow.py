import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLabel

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

    def test_cached_channel_is_ready_while_other_channels_are_missing(self):
        settings = LfpFilterSettings(show_filtered=True)
        source = Mock()
        source.coarse_is_ready.return_value = True
        host = SimpleNamespace(
            data_state=SimpleNamespace(lfp_dataset=SimpleNamespace(source=source)),
            selected_channel=Mock(return_value=7),
            lfp_channel_selector=object(),
            _lfp_coarse_step=Mock(return_value=4),
        )

        self.assertTrue(WavePanel._filtered_coarse_ready(host, settings))

        source.coarse_is_ready.assert_called_once_with(4, settings, 7)

    def test_background_channel_chunks_never_reach_a_different_plot(self):
        host = SimpleNamespace(
            _lfp_coarse_request_id="request",
            _lfp_coarse_channel=3,
            selected_channel=Mock(return_value=8),
            lfp_channel_selector=object(),
            _lfp_filter_completed_ranges=[],
            _set_lfp_filter_status=Mock(),
            lfp_fig=Mock(),
        )

        WavePanel._update_lfp_coarse_range(
            host,
            "request",
            {
                "point_start": 0,
                "time_us": [0.0, 1_000_000.0],
                "values": [1.0, 2.0],
            },
        )

        host.lfp_fig.append_lfp_partial_filtered.assert_not_called()
        self.assertEqual(host._lfp_filter_completed_ranges, [])

    def test_cpu_filter_fallback_is_reported_once_per_settings(self):
        settings = LfpFilterSettings(
            show_filtered=True,
            line_noise_method="regression",
            line_noise_frequencies_hz=(60.0,),
        )
        source = Mock()
        source.sample_count.return_value = 45_000_000
        source.identity_token.return_value = ("source", 1, 2)
        dataset = SimpleNamespace(source=source)
        host = SimpleNamespace(_lfp_cpu_fallback_warned=set())

        with (
            patch(
                "src.ui.wave_panel.signal_func.filter_backend",
                return_value="cpu",
            ),
            patch(
                "src.ui.wave_panel.signal_func.opencl_status",
                return_value={"reason": "no OpenCL platform"},
            ),
            patch("src.ui.wave_panel.QMessageBox.warning") as warning,
        ):
            for _ in range(3):
                WavePanel._warn_once_about_cpu_filter_fallback(
                    host, dataset, 1, settings
                )

        self.assertEqual(warning.call_count, 1)
        self.assertIn("no OpenCL platform", warning.call_args.args[2])

    def test_gpu_filter_runs_report_nothing(self):
        settings = LfpFilterSettings(show_filtered=True)
        source = Mock()
        source.sample_count.return_value = 45_000_000
        source.identity_token.return_value = ("source", 1, 2)
        host = SimpleNamespace(_lfp_cpu_fallback_warned=set())

        with (
            patch(
                "src.ui.wave_panel.signal_func.filter_backend",
                return_value="opencl",
            ),
            patch("src.ui.wave_panel.QMessageBox.warning") as warning,
        ):
            WavePanel._warn_once_about_cpu_filter_fallback(
                host, SimpleNamespace(source=source), 1, settings
            )

        warning.assert_not_called()
        self.assertEqual(host._lfp_cpu_fallback_warned, set())

    def test_switching_channel_does_not_restart_the_running_build(self):
        settings = LfpFilterSettings(show_filtered=True)
        source = Mock()
        source.identity_token.return_value = ("source",)
        host = SimpleNamespace(
            _lfp_coarse_step=Mock(return_value=4),
            _lfp_coarse_key=(("source",), 4, settings),
            _lfp_coarse_workers={"request": Mock()},
            _lfp_coarse_channel=1,
            _lfp_partial_channel=1,
            _retarget_lfp_coarse_workers=Mock(),
            _show_raw_until_filter_is_ready=Mock(),
            _cancel_lfp_coarse_workers=Mock(),
            lfp_fig=Mock(),
        )

        WavePanel._start_incremental_filtered_display(
            host, SimpleNamespace(source=source), 7, settings
        )

        host._cancel_lfp_coarse_workers.assert_not_called()
        host._retarget_lfp_coarse_workers.assert_called_once_with(7)
        host._show_raw_until_filter_is_ready.assert_called_once_with(7, settings)
        self.assertEqual(host._lfp_coarse_channel, 7)

    def test_publishing_the_displayed_channel_switches_it_to_filtered(self):
        settings = LfpFilterSettings(show_filtered=True)
        host = SimpleNamespace(
            _lfp_coarse_request_id="request",
            lfp_channel_selector=object(),
            selected_channel=Mock(return_value=7),
            current_lfp_filter_settings=Mock(return_value=settings),
            _mark_lfp_filter_complete=Mock(),
            invalidate_current_time_backgrounds=Mock(),
            update_current_time_marker=Mock(),
            update_lfp_peak_artist=Mock(),
            refresh_lfp_channel_readiness=Mock(),
            lfp_fig=Mock(),
        )

        WavePanel._lfp_coarse_channels_published(host, "request", [5, 7, 9])

        host._mark_lfp_filter_complete.assert_called_once_with(7)
        host.lfp_fig.set_lfp_signal_view.assert_called_once_with(True)

    def test_publishing_other_channels_leaves_the_plot_alone(self):
        settings = LfpFilterSettings(show_filtered=True)
        host = SimpleNamespace(
            _lfp_coarse_request_id="request",
            lfp_channel_selector=object(),
            selected_channel=Mock(return_value=7),
            current_lfp_filter_settings=Mock(return_value=settings),
            _mark_lfp_filter_complete=Mock(),
            invalidate_current_time_backgrounds=Mock(),
            update_current_time_marker=Mock(),
            update_lfp_peak_artist=Mock(),
            refresh_lfp_channel_readiness=Mock(),
            lfp_fig=Mock(),
        )

        WavePanel._lfp_coarse_channels_published(host, "request", [1, 2, 3])

        host._mark_lfp_filter_complete.assert_not_called()
        host.lfp_fig.set_lfp_signal_view.assert_not_called()

    def test_first_chunk_after_a_retarget_replaces_the_raw_stand_in(self):
        settings = LfpFilterSettings(show_filtered=True)
        host = SimpleNamespace(
            _lfp_coarse_request_id="request",
            _lfp_partial_channel=None,
            lfp_channel_selector=object(),
            selected_channel=Mock(return_value=7),
            current_lfp_filter_settings=Mock(return_value=settings),
            _begin_lfp_partial_channel=Mock(),
            _lfp_filter_completed_ranges=[],
            _set_lfp_filter_status=Mock(),
            lfp_fig=Mock(),
        )

        WavePanel._update_lfp_coarse_range(
            host,
            "request",
            {
                "channel": 7,
                "point_start": 0,
                "time_us": [0.0, 1_000_000.0],
                "values": [1.0, 2.0],
            },
        )

        host._begin_lfp_partial_channel.assert_called_once_with(7, settings)
        host.lfp_fig.append_lfp_partial_filtered.assert_called_once()

    def test_further_chunks_keep_the_same_partial_channel(self):
        settings = LfpFilterSettings(show_filtered=True)
        host = SimpleNamespace(
            _lfp_coarse_request_id="request",
            _lfp_partial_channel=7,
            lfp_channel_selector=object(),
            selected_channel=Mock(return_value=7),
            current_lfp_filter_settings=Mock(return_value=settings),
            _begin_lfp_partial_channel=Mock(),
            _lfp_filter_completed_ranges=[],
            _set_lfp_filter_status=Mock(),
            lfp_fig=Mock(),
        )

        WavePanel._update_lfp_coarse_range(
            host,
            "request",
            {
                "channel": 7,
                "point_start": 0,
                "time_us": [0.0, 1_000_000.0],
                "values": [1.0, 2.0],
            },
        )

        host._begin_lfp_partial_channel.assert_not_called()
        host.lfp_fig.append_lfp_partial_filtered.assert_called_once()

    @staticmethod
    def _readiness_host(selected, ready, channels, settings, building=True):
        source = Mock()
        source.coarse_ready_channels.return_value = list(ready)
        label = QLabel("")
        selector = QComboBox()
        for channel in channels:
            selector.addItem(f"Channel {channel}", channel)
        host = SimpleNamespace(
            data_state=SimpleNamespace(
                lfp_dataset=SimpleNamespace(source=source)
            ),
            available_lfp_channels=Mock(return_value=list(channels)),
            current_lfp_filter_settings=Mock(return_value=settings),
            selected_channel=Mock(return_value=selected),
            lfp_channel_selector=selector,
            lfp_channel_status_label=label,
            _lfp_coarse_step=Mock(return_value=9),
            _lfp_coarse_workers={"request": object()} if building else {},
            _lfp_partial_channel=None,
        )
        for name in (
            "_filtered_ready_channels",
            "_mark_ready_channels_in_selector",
        ):
            setattr(
                host,
                name,
                types.MethodType(getattr(WavePanel, name), host),
            )
        return host

    def test_readiness_is_hidden_while_the_raw_signal_is_shown(self):
        settings = LfpFilterSettings(show_filtered=False)
        host = self._readiness_host(1, [], [1, 2, 3], settings)

        WavePanel.refresh_lfp_channel_readiness(host)

        self.assertFalse(host.lfp_channel_status_label.isVisible())
        self.assertEqual(host.lfp_channel_selector.itemText(1), "Channel 2")

    def test_readiness_counts_channels_still_being_prepared(self):
        settings = LfpFilterSettings(show_filtered=True)
        host = self._readiness_host(3, [1, 2], [1, 2, 3, 4], settings)

        WavePanel.refresh_lfp_channel_readiness(host)

        self.assertEqual(
            host.lfp_channel_status_label.text(),
            "Preparing channels 2/4 - channel 3 showing raw",
        )
        self.assertEqual(host.lfp_channel_selector.itemText(0), "Channel 1")
        self.assertEqual(host.lfp_channel_selector.itemText(2), "Channel 3 ...")

    def test_readiness_says_when_the_shown_channel_is_being_filtered(self):
        settings = LfpFilterSettings(show_filtered=True)
        host = self._readiness_host(3, [1, 2], [1, 2, 3, 4], settings)
        host._lfp_partial_channel = 3

        WavePanel.refresh_lfp_channel_readiness(host)

        self.assertEqual(
            host.lfp_channel_status_label.text(),
            "Preparing channels 2/4 - channel 3 filtering now",
        )

    def test_readiness_reports_a_cached_channel_during_a_background_build(self):
        settings = LfpFilterSettings(show_filtered=True)
        host = self._readiness_host(1, [1, 2], [1, 2, 3, 4], settings)

        WavePanel.refresh_lfp_channel_readiness(host)

        self.assertEqual(
            host.lfp_channel_status_label.text(),
            "Preparing channels 2/4 in background",
        )

    def test_readiness_drops_the_markers_once_every_channel_is_cached(self):
        settings = LfpFilterSettings(show_filtered=True)
        host = self._readiness_host(2, [1, 2, 3, 4], [1, 2, 3, 4], settings)

        WavePanel.refresh_lfp_channel_readiness(host)

        self.assertEqual(
            host.lfp_channel_status_label.text(), "All 4 channels filtered"
        )
        for index in range(4):
            self.assertNotIn("...", host.lfp_channel_selector.itemText(index))

    def test_readiness_reports_a_stalled_build_without_claiming_progress(self):
        settings = LfpFilterSettings(show_filtered=True)
        host = self._readiness_host(
            2, [1, 2], [1, 2, 3, 4], settings, building=False
        )

        WavePanel.refresh_lfp_channel_readiness(host)

        self.assertEqual(
            host.lfp_channel_status_label.text(), "2/4 channels filtered"
        )


if __name__ == "__main__":
    unittest.main()
