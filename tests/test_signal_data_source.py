import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import matplotlib
import numpy as np

matplotlib.use("Agg")

from benchmarks.signal_csv_fixture import SignalFixtureConfig, generate_signal_csv
from src.charts.acceleration_chart import accelerator
from src.charts.lfp_chart import LFP
from src.signal_data import LfpDataset, LfpFilterSettings, parse_lfp_csv_info
from src.signal_data import lfp_dataset as lfp_dataset_module
from src.signal_data.source import SignalDataSource, _SOURCES


class SignalDataSourceTests(unittest.TestCase):
    def setUp(self):
        _SOURCES.clear()
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "eight-channels.csv"
        generate_signal_csv(
            self.path,
            SignalFixtureConfig(
                sample_rate_hz=100,
                duration_s=1,
                channels=(2, 5, 8, 13, 21, 34, 55, 260),
            ),
        )
        self.info = parse_lfp_csv_info(self.path)
        self.info["_signal_cache_root"] = str(
            Path(self.directory.name) / "signal-cache"
        )

    def tearDown(self):
        _SOURCES.clear()
        self.directory.cleanup()

    def test_dataset_reads_only_selected_channel_and_reuses_it(self):
        calls = []
        original = SignalDataSource._convert_csv

        def recording_convert(source, directory, channel, *, cancel_event):
            calls.append(channel)
            return original(
                source, directory, channel, cancel_event=cancel_event
            )

        with patch.object(SignalDataSource, "_convert_csv", recording_convert):
            dataset = LfpDataset.from_csv(self.info)
            self.dataset = dataset
            dataset.overview_values(260)
            dataset.overview_values(260, LfpFilterSettings(show_filtered=True))
            dataset.overview_values(5)
            dataset.overview_values(260)

        self.assertEqual(calls, [260, 5])

    def test_lfp_figure_keeps_one_line_when_channel_and_view_change(self):
        calls = []
        original = SignalDataSource._convert_csv

        def recording_convert(source, directory, channel, *, cancel_event):
            calls.append(channel)
            return original(
                source, directory, channel, cancel_event=cancel_event
            )

        with patch.object(SignalDataSource, "_convert_csv", recording_convert):
            dataset = LfpDataset.from_csv(self.info)
            self.dataset = dataset
            figure = LFP(
                info=self.info,
                channels=260,
                dataset=dataset,
                filter_settings=LfpFilterSettings(show_filtered=False),
            )
            self.assertEqual(len(figure.axes[0].lines), 1)
            self.assertEqual(figure.current_channel, 260)
            self.assertEqual(figure.current_view, "raw")

            figure.set_lfp_signal_view(True)
            self.assertEqual(figure.current_view, "filtered")
            self.assertEqual(calls, [260])

            original_line_times = figure.line.get_xdata().copy()
            with patch.object(dataset, "segment", wraps=dataset.segment) as segment:
                figure.set_lfp_xlim(0.2, 0.4)
                segment.assert_not_called()
            np.testing.assert_array_equal(figure.line.get_xdata(), original_line_times)

            callback = Mock()
            figure.add_lfp_xlim_callback(callback)
            figure.set_lfp_channel(5)
            self.assertEqual(figure.current_channel, 5)
            self.assertEqual(len(figure.axes[0].lines), 1)
            self.assertIn(260, calls)
            self.assertIn(5, calls)
            self.assertEqual(len(calls), len(set(calls)))

            figure.set_lfp_xlim(*figure.lfp_full_xlim, emit=False)
            callback.assert_not_called()
            displayed_times = figure.line.get_xdata()
            self.assertLessEqual(displayed_times[0], figure.lfp_full_xlim[0])
            self.assertGreater(
                displayed_times[-1],
                figure.lfp_full_xlim[1] * 0.9,
            )

            # Rebuilding only to change plot step must reuse parsed channel data.
            stepped = LFP(info=self.info, channels=5, step=2, dataset=dataset)
            self.assertEqual(stepped.lfp_plot_step, 1)
            self.assertIn(260, calls)
            self.assertIn(5, calls)

    def test_segment_lru_stays_within_byte_budget(self):
        dataset = LfpDataset.from_csv(self.info)
        self.dataset = dataset
        with patch.object(lfp_dataset_module, "SEGMENT_CACHE_MAX_BYTES", 200):
            dataset.segment(2, 0.0, 0.09, None)
            dataset.segment(5, 0.0, 0.09, None)

        self.assertLessEqual(dataset._segment_cache_bytes, 200)
        self.assertEqual(len(dataset._segment_cache), 1)

    def test_acceleration_rebuild_reuses_path_and_channel_cache(self):
        calls = []
        original = SignalDataSource._convert_csv

        def recording_convert(source, directory, channel, *, cancel_event):
            calls.append(channel)
            return original(
                source, directory, channel, cancel_event=cancel_event
            )

        with patch.object(SignalDataSource, "_convert_csv", recording_convert):
            first = accelerator(info=self.info, compact=True, step=1)
            second = accelerator(info=self.info, compact=True, step=4)

        self.assertEqual(first.axis_plot_step, 1)
        self.assertEqual(second.axis_plot_step, 4)
        self.assertEqual(calls, [260])


if __name__ == "__main__":
    unittest.main()
