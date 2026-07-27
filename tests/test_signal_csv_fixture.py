import hashlib
import tempfile
import unittest
from pathlib import Path

from benchmarks.signal_csv_fixture import SignalFixtureConfig, generate_signal_csv
from src.signal_data.csv_loader import parse_signal_csv_metadata
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
            self.assertTrue(data.loc[2, "channel_2"] != data.loc[2, "channel_2"])
            self.assertEqual(data.loc[3, "time_us"], data.loc[2, "time_us"])
            self.assertGreater(data.loc[5, "time_us"] - data.loc[4, "time_us"], 1_000_000)
            del data
            path.unlink()  # Fails on Windows if a reader retained its handle.
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
