import csv
import tempfile
import threading
import unittest
from pathlib import Path

from benchmarks.signal_csv_fixture import SignalFixtureConfig, generate_signal_csv
from src.background_requests import request_matches
from src.data_validation import check
from src.signal_data import (
    LfpAnalysisWorker,
    LfpDataset,
    LfpExportDataWorker,
    LfpFilterSettings,
    PeakDetectionWorker,
    parse_lfp_csv_info,
)
from src.signal_data.source import _SOURCES, CacheBuildCancelled


class ChunkedDataCheckTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.path = self.root / "signal.csv"
        generate_signal_csv(
            self.path,
            SignalFixtureConfig(
                sample_rate_hz=10,
                duration_s=2,
                channels=(2, 5, 260),
                missing_sample_indices=(2,),
                duplicate_timestamp_indices=(5,),
                discontinuity_after_indices=(8,),
                discontinuity_us=2_000_000,
                peak_indices=(),
            ),
        )
        self.info = parse_lfp_csv_info(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def test_chunk_boundaries_preserve_validation_counts(self):
        output = self.root / "report.csv"
        progress = []
        check(
            self.info,
            output,
            chunk_rows=3,
            progress_callback=progress.append,
        )
        with output.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        summary = {
            row["Type"]: row["Value"]
            for row in rows
            if row["Type"]
            in {
                "Missing values",
                "Duplicate timestamps",
                "Discontinuous timestamps",
            }
        }
        self.assertEqual(summary["Missing values"], "3")
        self.assertEqual(summary["Duplicate timestamps"], "1")
        self.assertEqual(summary["Discontinuous timestamps"], "2")
        self.assertGreater(len(progress), 1)
        self.assertEqual(progress[-1], 1.0)

    def test_cancelled_check_leaves_no_output_or_temporary_file(self):
        output = self.root / "report.csv"
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(CacheBuildCancelled):
            check(
                self.info,
                output,
                cancel_event=cancel,
                chunk_rows=1,
            )
        self.assertFalse(output.exists())
        self.assertFalse(any(self.root.glob("*.tmp")))


class PureSignalWorkerTests(unittest.TestCase):
    def setUp(self):
        _SOURCES.clear()
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        path = root / "signal.csv"
        generate_signal_csv(
            path,
            SignalFixtureConfig(
                sample_rate_hz=100,
                duration_s=2,
                channels=(2, 5, 260),
                peak_indices=(50, 150),
                peak_amplitude=20.0,
            ),
        )
        info = parse_lfp_csv_info(path)
        info["_signal_cache_root"] = str(root / "cache")
        self.dataset = LfpDataset.from_csv(info)

    def tearDown(self):
        self.dataset.close(wait=True)
        _SOURCES.clear()
        self.directory.cleanup()

    def test_analysis_worker_returns_arrays_without_figures(self):
        worker = LfpAnalysisWorker(
            "analysis-1",
            self.dataset,
            2,
            0.0,
            1.9,
            LfpFilterSettings(show_filtered=False),
            "power_spectrum",
        )
        completed = []
        worker.completed.connect(
            lambda request_id, identity, result: completed.append(
                (request_id, identity, result)
            )
        )
        worker.run()

        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0][0], "analysis-1")
        self.assertIn("segment", completed[0][2])
        self.assertIn("frequencies", completed[0][2])
        self.assertFalse(
            any(key in completed[0][2] for key in ("figure", "widget", "canvas"))
        )

    def test_peak_worker_returns_pure_records(self):
        worker = PeakDetectionWorker(
            "peaks-1",
            self.dataset,
            2,
            0.0,
            1.9,
            LfpFilterSettings(show_filtered=False),
            height_sigma=2.0,
            prominence_sigma=1.0,
            min_distance_sec=0.1,
        )
        completed = []
        worker.completed.connect(
            lambda _request_id, _identity, result: completed.append(result)
        )
        worker.run()

        self.assertEqual(completed[0]["channel"], 2)
        self.assertTrue(completed[0]["records"])
        self.assertTrue(
            all(
                set(record) == {"record_time_s", "value", "negative"}
                for record in completed[0]["records"]
            )
        )

    def test_export_worker_prepares_all_requested_numeric_data(self):
        worker = LfpExportDataWorker(
            "export-1",
            self.dataset,
            5,
            0.0,
            1.9,
            LfpFilterSettings(show_filtered=False),
            ("waveform", "power_spectrum", "spectrogram"),
        )
        completed = []
        worker.completed.connect(
            lambda _request_id, _identity, result: completed.append(result)
        )
        worker.run()

        self.assertEqual(
            set(completed[0]),
            {"segment", "power_spectrum", "spectrogram"},
        )
        self.assertFalse(
            any(key in completed[0] for key in ("figure", "widget", "canvas"))
        )

    def test_pre_cancelled_worker_emits_only_canceled(self):
        worker = LfpAnalysisWorker(
            "analysis-cancel",
            self.dataset,
            2,
            0.0,
            1.9,
            None,
            "power_spectrum",
        )
        canceled = []
        completed = []
        worker.canceled.connect(
            lambda request_id, _identity: canceled.append(request_id)
        )
        worker.completed.connect(lambda *_args: completed.append(True))
        worker.cancel()
        worker.run()

        self.assertEqual(canceled, ["analysis-cancel"])
        self.assertFalse(completed)


class BackgroundRequestTests(unittest.TestCase):
    def test_old_file_result_cannot_replace_new_file(self):
        identity_a = ("A.csv", 100, 1)
        identity_b = ("B.csv", 200, 2)

        self.assertFalse(
            request_matches("request-a", "request-b", identity_a, identity_b)
        )
        self.assertTrue(
            request_matches("request-b", "request-b", identity_b, identity_b)
        )


if __name__ == "__main__":
    unittest.main()
