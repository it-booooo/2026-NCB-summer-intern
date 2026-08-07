import csv
import struct
import tempfile
import threading
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmarks.signal_csv_fixture import SignalFixtureConfig, generate_signal_csv
from src.background_requests import request_matches
from src.data_validation import check
from src.markers import (
    RecordPosition,
    marker_video_time,
    peak_records_to_markers,
)
from src.signal_data import (
    LfpAnalysisWorker,
    LfpDataset,
    LfpDisplaySegmentWorker,
    LfpExportDataWorker,
    LfpFilterSettings,
    PeakDetectionWorker,
    parse_signal_csv_info,
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
        self.info = parse_signal_csv_info(self.path)

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

    def test_chunk_size_does_not_change_report_or_boundary_anomalies(self):
        reports = []
        for chunk_rows in (1, 3, 5, 9, 100):
            output = self.root / f"report-{chunk_rows}.csv"
            check(self.info, output, chunk_rows=chunk_rows)
            with output.open("r", encoding="utf-8-sig", newline="") as stream:
                reports.append(list(csv.DictReader(stream)))

        for report in reports[1:]:
            self.assertEqual(report, reports[0])
        details = reports[0][7:]
        self.assertIn(
            ("Duplicate timestamp", "line 10"),
            {(row["Type"], row["File"]) for row in details},
        )
        self.assertIn(
            ("Time discontinuity", "line 14"),
            {(row["Type"], row["File"]) for row in details},
        )

    def test_many_missing_details_are_streamed_with_bounded_memory(self):
        path = self.root / "many-missing.csv"
        sample_count = 2_000
        generate_signal_csv(
            path,
            SignalFixtureConfig(
                sample_rate_hz=100,
                duration_s=sample_count / 100,
                channels=(2, 5, 260),
                missing_sample_indices=tuple(range(sample_count)),
                peak_indices=(),
            ),
        )
        output = self.root / "many-missing-report.csv"
        tracemalloc.start()
        check(
            parse_signal_csv_info(path),
            output,
            chunk_rows=17,
        )
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        missing_details = 0
        summary = {}
        with output.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                summary[row["Type"]] = row["Value"]
                if row["Type"] == "Missing value":
                    missing_details += 1
        self.assertEqual(summary["Rows"], str(sample_count))
        self.assertEqual(summary["Missing values"], str(sample_count * 3))
        self.assertEqual(missing_details, sample_count * 3)
        self.assertLess(peak_bytes, 25 * 1024 * 1024)


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
        info = parse_signal_csv_info(path)
        info["_signal_cache_root"] = str(root / "cache")
        self.dataset = LfpDataset.from_csv(info)

    def tearDown(self):
        self.dataset.close(wait=True)
        _SOURCES.clear()
        self.directory.cleanup()

    def test_analysis_worker_returns_metadata_without_segment(self):
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
        result = completed[0][2]
        self.assertNotIn("segment", result)
        self.assertFalse(
            any(
                key in result
                for key in ("values", "time_us", "record_time_s")
            )
        )
        self.assertEqual(result["sample_count"], 191)
        self.assertEqual(result["sample_rate_hz"], 100.0)
        self.assertEqual(result["start_time_s"], 0.0)
        self.assertEqual(result["end_time_s"], 1.9)
        self.assertTrue(result["image_png"].startswith(b"\x89PNG"))
        width, height = struct.unpack(">II", result["image_png"][16:24])
        self.assertEqual((width, height), (2280, 1320))
        self.assertNotIn("frequencies", result)
        self.assertNotIn("power", result)
        self.assertFalse(
            any(key in result for key in ("figure", "widget", "canvas"))
        )

    def test_display_segment_worker_returns_only_requested_downsampled_interval(self):
        worker = LfpDisplaySegmentWorker(
            "display-1",
            self.dataset,
            2,
            0.5,
            1.0,
            5,
            LfpFilterSettings(
                show_filtered=True,
                bandpass_enabled=True,
                bandpass_low_hz=2.0,
                bandpass_high_hz=30.0,
            ),
        )
        completed = []
        worker.completed.connect(
            lambda _request_id, _identity, result: completed.append(result)
        )

        with patch.object(
            self.dataset,
            "segment",
            wraps=self.dataset.segment,
        ) as segment:
            worker.run()

        self.assertEqual(len(completed), 1)
        self.assertEqual(
            segment.call_args.kwargs["dispatch_sample_count"],
            self.dataset.source.sample_count(2),
        )
        result = completed[0]
        self.assertGreater(len(result["values"]), 1)
        self.assertLessEqual(len(result["values"]), 11)
        self.assertEqual(result["time_us"].shape, result["values"].shape)
        self.assertGreaterEqual(result["time_us"][0], 500_000)
        self.assertLessEqual(result["time_us"][-1], 1_000_000)

    def test_spectrogram_worker_returns_static_image_and_metadata(self):
        worker = LfpAnalysisWorker(
            "analysis-spectrogram",
            self.dataset,
            2,
            0.0,
            1.9,
            LfpFilterSettings(show_filtered=False),
            "spectrogram",
            spectrogram_color_limits_db=(-80.0, -20.0),
        )
        completed = []
        worker.completed.connect(
            lambda _request_id, _identity, result: completed.append(result)
        )
        worker.run()

        result = completed[0]
        self.assertNotIn("segment", result)
        self.assertEqual(result["sample_count"], 191)
        self.assertEqual(result["sample_rate_hz"], 100.0)
        self.assertTrue(result["image_png"].startswith(b"\x89PNG"))
        self.assertEqual(
            result["spectrogram_color_limits_db"],
            (-80.0, -20.0),
        )
        self.assertNotIn("frequencies", result)
        self.assertNotIn("times", result)
        self.assertNotIn("power", result)

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

    def test_peak_chunks_are_size_independent_and_boundary_safe(self):
        results = []
        for chunk_samples in (17, 50, 73, 500):
            worker = PeakDetectionWorker(
                f"peaks-{chunk_samples}",
                self.dataset,
                2,
                0.0,
                1.9,
                LfpFilterSettings(show_filtered=False),
                height_sigma=2.0,
                prominence_sigma=1.0,
                min_distance_sec=0.1,
                chunk_samples=chunk_samples,
            )
            completed = []
            worker.completed.connect(
                lambda _request_id, _identity, result: completed.append(result)
            )
            worker.run()
            results.append(completed[0]["records"])

        for records in results[1:]:
            self.assertEqual(records, results[0])
        record_times = [record["record_time_s"] for record in results[0]]
        self.assertEqual(len(record_times), len(set(record_times)))
        self.assertTrue(any(abs(time_s - 0.5) < 1e-9 for time_s in record_times))
        self.assertTrue(any(abs(time_s - 1.5) < 1e-9 for time_s in record_times))

    def test_peak_marker_record_video_time_and_payload(self):
        records = [
            {
                "record_time_s": 1.25,
                "value": 8.5,
                "negative": False,
            }
        ]
        marker = peak_records_to_markers(260, records)[0]

        self.assertIsInstance(marker.position, RecordPosition)
        self.assertEqual(marker.position.time_sec, 1.25)
        self.assertEqual(marker_video_time(marker, 0.75), 2.0)
        self.assertEqual(marker.payload, {"channel": 260, "value": 8.5})

    def test_export_worker_returns_waveform_and_static_spectral_images(self):
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
            {
                "sample_count",
                "sample_rate_hz",
                "start_time_s",
                "end_time_s",
                "waveform",
                "rendered_images",
            },
        )
        self.assertNotIn("segment", completed[0])
        self.assertLessEqual(
            completed[0]["waveform"].sample_count,
            completed[0]["sample_count"],
        )
        self.assertEqual(
            set(completed[0]["rendered_images"]),
            {"power_spectrum", "spectrogram"},
        )
        self.assertTrue(
            all(
                image.startswith(b"\x89PNG")
                for image in completed[0]["rendered_images"].values()
            )
        )
        self.assertFalse(
            any(key in completed[0] for key in ("figure", "widget", "canvas"))
        )

    def test_export_worker_forwards_custom_spectrogram_color_scale(self):
        worker = LfpExportDataWorker(
            "export-spectrogram-scale",
            self.dataset,
            5,
            0.0,
            1.9,
            LfpFilterSettings(show_filtered=False),
            ("spectrogram",),
            spectrogram_color_limits_db=(-80.0, -20.0),
        )

        with patch(
            "src.signal_data.background_workers._render_analysis_file",
            return_value=b"png",
        ) as render:
            result = worker.execute()

        self.assertEqual(result["rendered_images"]["spectrogram"], b"png")
        self.assertEqual(
            render.call_args.kwargs["spectrogram_color_limits_db"],
            (-80.0, -20.0),
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
