import threading
import time
import unittest
from types import SimpleNamespace

import numpy as np

from src.signal_data.peak_display import (
    allocate_peak_display_points,
    load_peak_display_samples,
    merge_peak_display_intervals,
)
from src.signal_data import CacheBuildCancelled, LfpPeakDisplayWorker


class FakeDataset:
    def __init__(self, sample_rate_hz=1_000.0):
        self.sample_rate_hz = float(sample_rate_hz)
        self.calls = []
        self.source = SimpleNamespace(identity_token=lambda: "fake-source")

    def segment(self, channel, left, right, settings, cancel_event=None):
        self.calls.append((channel, left, right, settings))
        count = max(round((right - left) * self.sample_rate_hz), 2)
        times = np.linspace(left, right, count, endpoint=False)
        return SimpleNamespace(record_time_s=times, values=np.sin(times))


class BlockingDataset(FakeDataset):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def segment(self, channel, left, right, settings, cancel_event=None):
        self.started.set()
        self.release.wait(2.0)
        return super().segment(channel, left, right, settings, cancel_event)


class PeakDisplayTests(unittest.TestCase):
    def test_overlapping_neighborhoods_share_one_bounded_read(self):
        intervals = merge_peak_display_intervals(
            [1.0, 1.5, 12.0],
            context_sec=1.0,
            maximum_interval_sec=30.0,
        )

        self.assertEqual(intervals, [(0.0, 2.5), (11.0, 13.0)])

    def test_long_overlap_chain_is_split_into_bounded_intervals(self):
        intervals = merge_peak_display_intervals(
            np.arange(0.0, 20.0, 1.0),
            context_sec=1.0,
            maximum_interval_sec=5.0,
        )

        self.assertGreater(len(intervals), 1)
        self.assertTrue(all(right - left <= 5.0 for left, right in intervals))

    def test_interval_allocation_never_exceeds_budget(self):
        limits = allocate_peak_display_points([(0.0, 1.0), (2.0, 5.0)], 101)

        self.assertEqual(sum(limits), 101)
        self.assertGreater(limits[1], limits[0])

    def test_loaded_samples_merge_reads_and_obey_plot_cap(self):
        dataset = FakeDataset()
        records = [
            (1.0, 4.0),
            (1.5, -3.0),
            (12.0, 5.0),
            (20.0, None),
        ]

        times, values = load_peak_display_samples(
            dataset,
            1,
            records,
            settings=None,
            context_sec=1.0,
            maximum_points=200,
            maximum_interval_sec=30.0,
        )

        self.assertEqual(len(dataset.calls), 2)
        self.assertEqual(times.shape, values.shape)
        self.assertLessEqual(times.size, 200)
        for peak_time in (1.0, 1.5, 12.0):
            self.assertTrue(np.any(times == peak_time))

    def test_pre_cancelled_display_load_does_not_read_segments(self):
        dataset = FakeDataset()
        cancel_event = threading.Event()
        cancel_event.set()

        with self.assertRaises(CacheBuildCancelled):
            load_peak_display_samples(
                dataset,
                1,
                [(1.0, 4.0)],
                settings=None,
                cancel_event=cancel_event,
            )

        self.assertEqual(dataset.calls, [])

    def test_display_worker_returns_bounded_pure_arrays(self):
        dataset = FakeDataset()
        settings = SimpleNamespace(show_filtered=False)
        worker = LfpPeakDisplayWorker(
            "display-1",
            dataset,
            1,
            [(1.0, 4.0), (1.5, -3.0)],
            settings,
            context_sec=1.0,
            maximum_points=100,
            maximum_interval_sec=30.0,
        )
        completed = []
        worker.completed.connect(
            lambda _request_id, _identity, result: completed.append(result)
        )

        worker.run()

        self.assertEqual(completed[0]["channel"], 1)
        self.assertFalse(completed[0]["filtered"])
        self.assertLessEqual(completed[0]["times"].size, 100)
        self.assertEqual(completed[0]["times"].shape, completed[0]["values"].shape)

    def test_started_display_worker_does_not_block_calling_thread(self):
        dataset = BlockingDataset()
        settings = SimpleNamespace(show_filtered=True)
        worker = LfpPeakDisplayWorker(
            "display-background",
            dataset,
            1,
            [(1.0, 4.0)],
            settings,
            context_sec=1.0,
            maximum_points=100,
            maximum_interval_sec=30.0,
        )

        started = time.perf_counter()
        worker.start()
        launch_elapsed = time.perf_counter() - started
        try:
            self.assertTrue(dataset.started.wait(1.0))
            self.assertTrue(worker.isRunning())
            self.assertLess(launch_elapsed, 0.25)
        finally:
            dataset.release.set()
            worker.wait(5_000)


if __name__ == "__main__":
    unittest.main()
