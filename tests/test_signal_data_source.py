import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import matplotlib
import numpy as np

matplotlib.use("Agg")

from benchmarks.signal_csv_fixture import SignalFixtureConfig, generate_signal_csv
from src.charts.three_axis_chart import create_three_axis_figure
from src.charts.lfp_chart import LFP
from src.plot_steps import resolve_visible_plot_step
from src.signal_data import (
    LfpDataset,
    LfpFilterSettings,
    SignalDataset,
    parse_signal_csv_info,
)
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
        self.info = parse_signal_csv_info(self.path)
        self.info["_signal_cache_root"] = str(
            Path(self.directory.name) / "signal-cache"
        )

    def tearDown(self):
        _SOURCES.clear()
        self.directory.cleanup()

    def test_lfp_dataset_extends_signal_dataset(self):
        dataset = LfpDataset.from_csv(self.info)

        self.assertIsInstance(dataset, SignalDataset)
        self.assertEqual(dataset.channels, [2, 5, 8, 13, 21, 34, 55, 260])

    def test_visible_auto_step_depends_on_samples_and_pixels(self):
        self.assertEqual(resolve_visible_plot_step(1_000_000, None, 1000), 500)
        self.assertEqual(resolve_visible_plot_step(10_000, None, 1000), 5)
        self.assertEqual(resolve_visible_plot_step(1_000_000, None, 2000), 250)
        self.assertEqual(resolve_visible_plot_step(1_000_000, 0, 1), 1)
        self.assertEqual(resolve_visible_plot_step(1_000_000, 100, 1), 100)
        with self.assertRaises(ValueError):
            resolve_visible_plot_step(10, -2, 100)

    def test_plot_segment_zero_and_positive_steps_match_raw_slicing(self):
        dataset = LfpDataset.from_csv(self.info)
        all_times, all_values, all_stride = dataset.plot_segment(
            5, 0.2, 0.8, 0, 1, LfpFilterSettings(show_filtered=False)
        )
        stepped_times, stepped_values, stride = dataset.plot_segment(
            5, 0.2, 0.8, 4, 1, LfpFilterSettings(show_filtered=False)
        )
        self.assertEqual(all_stride, 1)
        self.assertEqual(stride, 4)
        np.testing.assert_array_equal(stepped_times, all_times[::4])
        np.testing.assert_allclose(stepped_values, all_values[::4])

    def test_filtered_plot_segment_processes_full_resolution_before_stride(self):
        dataset = LfpDataset.from_csv(self.info)
        settings = LfpFilterSettings(show_filtered=True)
        with (
            patch.object(dataset, "segment", wraps=dataset.segment) as segment,
            patch.object(
                dataset.source, "sampled_segment", wraps=dataset.source.sampled_segment
            ) as sampled,
        ):
            times, values, stride = dataset.plot_segment(
                5, 0.1, 0.9, 5, 100, settings
            )
        segment.assert_called_once_with(5, 0.1, 0.9, settings)
        sampled.assert_not_called()
        full = dataset.segment(5, 0.1, 0.9, settings)
        np.testing.assert_array_equal(times, full.record_time_s[::5])
        np.testing.assert_allclose(values, full.values[::5])
        self.assertEqual(stride, 5)

    def test_dataset_scans_once_and_reuses_all_channel_memmaps(self):
        calls = []
        original = SignalDataSource._convert_csv

        def recording_convert(
            source,
            directory,
            channel,
            *,
            cancel_event,
            progress_callback=None,
        ):
            calls.append(channel)
            return original(
                source,
                directory,
                channel,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
            )

        with patch.object(SignalDataSource, "_convert_csv", recording_convert):
            dataset = LfpDataset.from_csv(self.info)
            self.dataset = dataset
            dataset.overview_values(260)
            dataset.overview_values(260, LfpFilterSettings(show_filtered=True))
            dataset.overview_values(5)
            dataset.overview_values(260)

        self.assertEqual(calls, [260])

    def test_lfp_figure_keeps_one_line_when_channel_and_view_change(self):
        calls = []
        original = SignalDataSource._convert_csv

        def recording_convert(
            source,
            directory,
            channel,
            *,
            cancel_event,
            progress_callback=None,
        ):
            calls.append(channel)
            return original(
                source,
                directory,
                channel,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
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
            self.assertNotIn(5, calls)
            self.assertEqual(calls, [260])

            figure.set_lfp_xlim(*figure.lfp_full_xlim, emit=False)
            callback.assert_not_called()
            figure.refresh_lfp_plot()
            displayed_times = figure.line.get_xdata()
            self.assertLessEqual(displayed_times[0], figure.lfp_full_xlim[0])
            self.assertGreater(
                displayed_times[-1],
                figure.lfp_full_xlim[1] * 0.9,
            )

            # Rebuilding only to change plot step must reuse parsed channel data.
            stepped = LFP(info=self.info, channels=5, step=2, dataset=dataset)
            self.assertEqual(stepped.lfp_plot_step, 2)
            self.assertEqual(calls, [260])

    def test_partial_filter_results_replace_base_data_used_by_peak_overlay(self):
        dataset = LfpDataset.from_csv(self.info)
        figure = LFP(
            info=self.info,
            channels=260,
            dataset=dataset,
            filter_settings=LfpFilterSettings(show_filtered=False),
        )
        regression = LfpFilterSettings(
            show_filtered=True,
            line_noise_method="regression",
            line_noise_frequencies_hz=(60.0,),
        )
        figure.set_lfp_filter_settings(regression)
        figure.begin_lfp_partial_filtered()
        figure.append_lfp_partial_filtered(
            0,
            np.asarray([1_000_000.0, 2_000_000.0]),
            np.asarray([101.0, 102.0]),
        )

        figure.set_lfp_peak_samples(
            260,
            True,
            np.asarray([1.5]),
            np.asarray([103.0]),
        )

        np.testing.assert_array_equal(
            figure.line.get_ydata(),
            np.asarray([101.0, 103.0, 102.0]),
        )

    def test_xlim_change_does_not_reload_or_recalculate_step(self):
        dataset = LfpDataset.from_csv(self.info)
        figure = LFP(channels=5, step=None, dataset=dataset)
        original_step = figure.lfp_plot_step
        original_times = figure.line.get_xdata().copy()
        with patch.object(
            dataset, "coarse_values", wraps=dataset.coarse_values
        ) as coarse_values:
            figure.set_lfp_xlim(0.2, 0.8)
            figure.set_lfp_xlim(0.3, 0.6)
            coarse_values.assert_not_called()
        self.assertEqual(figure.lfp_plot_step, original_step)
        np.testing.assert_array_equal(figure.line.get_xdata(), original_times)

    def test_auto_step_stays_fixed_when_channel_changes(self):
        dataset = LfpDataset.from_csv(self.info)
        figure = LFP(channels=5, step=None, dataset=dataset)
        fixed_stride = figure.lfp_plot_step
        with patch.object(
            dataset, "coarse_values", wraps=dataset.coarse_values
        ) as coarse_values:
            figure.set_lfp_channel(8)

        self.assertEqual(figure.lfp_plot_step, fixed_stride)
        self.assertEqual(coarse_values.call_args.args[1], fixed_stride)

    def test_lfp_auto_step_targets_5000_points_for_the_full_recording(self):
        dataset = LfpDataset.from_csv(self.info)
        with (
            patch.object(dataset.source, "sample_count", return_value=1_000_000),
            patch.object(
                dataset,
                "coarse_values",
                return_value=(
                    np.asarray([0.0, 1_000_000.0]),
                    np.asarray([0.0, 1.0]),
                ),
            ) as coarse_values,
        ):
            figure = LFP(channels=5, step=None, dataset=dataset)

        self.assertEqual(figure.lfp_plot_step, 200)
        self.assertEqual(coarse_values.call_args.args[1], 200)

    def test_segment_lru_stays_within_byte_budget(self):
        dataset = LfpDataset.from_csv(self.info)
        self.dataset = dataset
        with patch.object(lfp_dataset_module, "SEGMENT_CACHE_MAX_BYTES", 200):
            dataset.segment(2, 0.0, 0.09, None)
            dataset.segment(5, 0.0, 0.09, None)

        self.assertLessEqual(dataset._segment_cache_bytes, 200)
        self.assertEqual(len(dataset._segment_cache), 1)

    def test_three_axis_rebuild_reuses_path_and_channel_cache(self):
        calls = []
        original = SignalDataSource._convert_csv

        def recording_convert(
            source,
            directory,
            channel,
            *,
            cancel_event,
            progress_callback=None,
        ):
            calls.append(channel)
            return original(
                source,
                directory,
                channel,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
            )

        with patch.object(SignalDataSource, "_convert_csv", recording_convert):
            first = create_three_axis_figure(info=self.info, compact=True, step=1)
            second = create_three_axis_figure(info=self.info, compact=True, step=4)

        self.assertEqual(first.three_axis_plot_step, 1)
        self.assertEqual(second.three_axis_plot_step, 4)
        self.assertEqual(calls, [260])

    def test_three_axis_uses_provided_dataset(self):
        dataset = SignalDataset.from_csv(self.info)
        with patch.object(dataset, "overview", wraps=dataset.overview) as overview:
            figure = create_three_axis_figure(dataset=dataset, compact=True)

        overview.assert_called_once_with(260)
        self.assertEqual(
            figure.three_axis_full_xlim,
            dataset.record_bounds_s(260),
        )


if __name__ == "__main__":
    unittest.main()
