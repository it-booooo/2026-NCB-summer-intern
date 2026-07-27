import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import matplotlib

matplotlib.use("Agg")

from benchmarks.signal_csv_fixture import SignalFixtureConfig, generate_signal_csv
from src.charts.acceleration_chart import accelerator
from src.charts.lfp_chart import LFP
from src.signal_data import LfpDataset, LfpFilterSettings, parse_lfp_csv_info
from src.signal_data.readers import read_signal_csv as actual_read_signal_csv
from src.signal_data.source import _SOURCES


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

    def tearDown(self):
        _SOURCES.clear()
        self.directory.cleanup()

    def test_dataset_reads_only_selected_channel_and_reuses_it(self):
        calls = []

        def recording_reader(path, requested_channels=None, metadata=None):
            calls.append(tuple(requested_channels or ()))
            return actual_read_signal_csv(path, requested_channels, metadata)

        with patch("src.signal_data.source.read_signal_csv", recording_reader):
            dataset = LfpDataset.from_csv(self.info)
            dataset.signal_values(260)
            dataset.signal_values(260, LfpFilterSettings(show_filtered=True))
            dataset.signal_values(5)
            dataset.signal_values(260)

        self.assertEqual(calls, [(260,), (5,)])

    def test_lfp_figure_keeps_one_line_when_channel_and_view_change(self):
        calls = []

        def recording_reader(path, requested_channels=None, metadata=None):
            calls.append(tuple(requested_channels or ()))
            return actual_read_signal_csv(path, requested_channels, metadata)

        with patch("src.signal_data.source.read_signal_csv", recording_reader):
            dataset = LfpDataset.from_csv(self.info)
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
            self.assertEqual(calls, [(260,)])

            figure.set_lfp_channel(5)
            self.assertEqual(figure.current_channel, 5)
            self.assertEqual(len(figure.axes[0].lines), 1)
            self.assertEqual(calls, [(260,), (5,)])

            # Rebuilding only to change plot step must reuse parsed channel data.
            stepped = LFP(info=self.info, channels=5, step=2, dataset=dataset)
            self.assertEqual(stepped.lfp_plot_step, 2)
            self.assertEqual(calls, [(260,), (5,)])

    def test_acceleration_rebuild_reuses_path_and_channel_cache(self):
        calls = []

        def recording_reader(path, requested_channels=None, metadata=None):
            calls.append(tuple(requested_channels or ()))
            return actual_read_signal_csv(path, requested_channels, metadata)

        with patch("src.signal_data.source.read_signal_csv", recording_reader):
            first = accelerator(info=self.info, compact=True, step=1)
            second = accelerator(info=self.info, compact=True, step=4)

        self.assertEqual(first.axis_plot_step, 1)
        self.assertEqual(second.axis_plot_step, 4)
        self.assertEqual(calls, [(260,)])


if __name__ == "__main__":
    unittest.main()
