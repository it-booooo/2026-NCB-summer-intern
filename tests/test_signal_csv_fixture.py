import hashlib
import tempfile
import unittest
from pathlib import Path

import numpy as np

from benchmarks.signal_csv_fixture import SignalFixtureConfig, generate_signal_csv
from src.signal_data.csv_loader import parse_signal_csv_info, parse_signal_csv_metadata
from src.signal_data.lfp_dataset import LfpDataset
from src.signal_data.lfp_processing import prepare_lfp_signal
from src.signal_data.readers import read_signal_csv


class SignalCsvFixtureTests(unittest.TestCase):
    def test_generation_is_deterministic_and_has_non_contiguous_channels(self):
        config = SignalFixtureConfig(sample_rate_hz=20, duration_s=1)
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.csv"
            second = Path(directory) / "second.csv"
            generate_signal_csv(first, config)
            generate_signal_csv(second, config)
            first_hash = hashlib.sha256(first.read_bytes()).digest()
            second_hash = hashlib.sha256(second.read_bytes()).digest()
            metadata = parse_signal_csv_metadata(first)

        self.assertEqual(first_hash, second_hash)
        self.assertEqual(metadata["channels"], [2, 5, 260])

    def test_anomalies_and_file_handles_are_released(self):
        config = SignalFixtureConfig(
            sample_rate_hz=10,
            duration_s=1,
            missing_sample_indices=(2,),
            duplicate_timestamp_indices=(3,),
            discontinuity_after_indices=(4,),
            discontinuity_us=2_000_000,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "anomalies.csv"
            generate_signal_csv(path, config)
            metadata = parse_signal_csv_metadata(path)
            data = read_signal_csv(path, metadata=metadata)
            self.assertEqual(data["time_us"].dtype, np.dtype("float64"))
            self.assertEqual(data["channel_2"].dtype, np.dtype("float32"))
            self.assertTrue(data.loc[2, "channel_2"] != data.loc[2, "channel_2"])
            self.assertEqual(data.loc[3, "time_us"], data.loc[2, "time_us"])
            self.assertGreater(data.loc[5, "time_us"] - data.loc[4, "time_us"], 1_000_000)
            del data
            path.unlink()  # Fails on Windows if a reader retained its handle.
            self.assertFalse(path.exists())

    def test_long_recording_timestamps_keep_microsecond_precision(self):
        start_us = 72_000_000_000
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "long-timestamp.csv"
            path.write_text(
                "Channels,2\n"
                "Sample Rate[Hz],1000\n"
                "Unit,uV\n"
                "Time[us],Channel 2\n"
                f"{start_us},1.25\n"
                f"{start_us + 1000},2.5\n",
                encoding="utf-8",
            )
            metadata = parse_signal_csv_metadata(path)
            data = read_signal_csv(path, metadata=metadata)

        self.assertEqual(data["time_us"].dtype, np.dtype("float64"))
        self.assertEqual(data["channel_2"].dtype, np.dtype("float32"))
        self.assertEqual(float(data.loc[1, "time_us"] - data.loc[0, "time_us"]), 1000.0)

    def test_lazy_dataset_keeps_time_float64_and_raw_signal_float32(self):
        config = SignalFixtureConfig(
            sample_rate_hz=10,
            duration_s=1,
            missing_sample_indices=(2,),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.csv"
            generate_signal_csv(path, config)
            info = parse_signal_csv_info(path)
            info["_signal_cache_root"] = str(Path(directory) / "signal-cache")
            dataset = LfpDataset.from_csv(info)
            segment = dataset.segment(2, 0.0, 0.5, None)

        self.assertEqual(segment.record_time_s.dtype, np.dtype("float64"))
        self.assertEqual(segment.values.dtype, np.dtype("float32"))
        self.assertTrue(np.isfinite(segment.values).all())

    def test_missing_float32_signal_is_interpolated_without_upcasting(self):
        values = np.array([1.0, np.nan, 3.0], dtype=np.float32)

        prepared = prepare_lfp_signal(values, 1000.0, None)

        self.assertEqual(prepared.dtype, np.dtype("float32"))
        np.testing.assert_array_equal(
            prepared,
            np.array([1.0, 2.0, 3.0], dtype=np.float32),
        )

    def test_all_missing_float32_signal_is_replaced_with_zeros(self):
        values = np.array([np.nan, np.nan], dtype=np.float32)

        prepared = prepare_lfp_signal(values, 1000.0, None)

        self.assertEqual(prepared.dtype, np.dtype("float32"))
        np.testing.assert_array_equal(
            prepared,
            np.zeros(2, dtype=np.float32),
        )

if __name__ == "__main__":
    unittest.main()
