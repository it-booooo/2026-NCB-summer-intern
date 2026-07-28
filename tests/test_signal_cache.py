import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np

from benchmarks.signal_csv_fixture import SignalFixtureConfig, generate_signal_csv
from src.signal_data import parse_lfp_csv_info
from src.signal_data.readers import read_signal_csv
from src.signal_data.source import (
    CacheBuildCancelled,
    SignalDataSource,
    cleanup_signal_cache,
)


class SignalCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.path = root / "signal.csv"
        self.cache_root = root / "cache"
        self.config = SignalFixtureConfig(
            sample_rate_hz=100,
            duration_s=2,
            channels=(2, 5, 260),
            peak_indices=(73,),
            peak_amplitude=50,
        )
        generate_signal_csv(self.path, self.config)
        self.info = parse_lfp_csv_info(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def source(self, max_points=20):
        return SignalDataSource(
            str(self.path),
            self.info["metadata"],
            overview_max_points=max_points,
            chunk_rows=17,
            cache_root=self.cache_root,
        )

    def test_overview_matches_original_step_sampling(self):
        overview = self.source().overview(260)
        raw = read_signal_csv(self.path, [260], metadata=self.info["metadata"])
        step = max(len(raw) // 20, 1)

        np.testing.assert_array_equal(
            overview.time_us,
            raw["time_us"].to_numpy()[::step],
        )
        np.testing.assert_allclose(
            overview.values,
            raw["channel_260"].to_numpy()[::step],
        )
        self.assertLess(len(overview.values), len(raw))

    def test_segment_searchsorted_matches_legacy_inclusive_mask(self):
        source = self.source()
        start_us = 310_000
        end_us = 870_000
        segment = source.segment(5, start_us, end_us)
        legacy = read_signal_csv(
            self.path, [5], metadata=self.info["metadata"]
        )
        expected = legacy[
            (legacy["time_us"] >= start_us) & (legacy["time_us"] <= end_us)
        ]

        np.testing.assert_array_equal(segment.time_us, expected["time_us"].to_numpy())
        np.testing.assert_allclose(segment.values, expected["channel_5"].to_numpy())
        self.assertEqual(segment.time_us[0], expected["time_us"].iloc[0])
        self.assertEqual(segment.time_us[-1], expected["time_us"].iloc[-1])

    def test_truncated_or_version_mismatched_cache_is_rebuilt(self):
        source = self.source()
        cache = source.ensure_cache(2)
        metadata = json.loads((cache / "metadata.json").read_text("utf-8"))
        expected_size = metadata["sample_count"] * 4

        with (cache / "values.bin").open("r+b") as stream:
            stream.truncate(8)
        rebuilt = self.source().ensure_cache(2)
        self.assertEqual((rebuilt / "values.bin").stat().st_size, expected_size)

        metadata_path = rebuilt / "metadata.json"
        metadata = json.loads(metadata_path.read_text("utf-8"))
        metadata["identity"]["cache_format_version"] = -1
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        rebuilt_again = self.source().ensure_cache(2)
        restored = json.loads((rebuilt_again / "metadata.json").read_text("utf-8"))
        self.assertGreater(restored["identity"]["cache_format_version"], 0)

    def test_source_size_or_timestamp_change_uses_a_new_cache(self):
        source = self.source()
        original = source.ensure_cache(2)
        original_metadata = json.loads(
            (original / "metadata.json").read_text("utf-8")
        )
        with self.path.open("a", encoding="utf-8", newline="") as stream:
            stream.write("2000000,0,0,0\n")

        updated = self.source().ensure_cache(2)
        updated_metadata = json.loads(
            (updated / "metadata.json").read_text("utf-8")
        )
        self.assertNotEqual(original, updated)
        self.assertEqual(
            updated_metadata["sample_count"],
            original_metadata["sample_count"] + 1,
        )

    def test_cancelled_build_leaves_no_valid_or_temporary_cache(self):
        cancel = threading.Event()
        cancel.set()
        source = self.source()
        with self.assertRaises(CacheBuildCancelled):
            source.ensure_cache(260, cancel)

        self.assertFalse(any(self.cache_root.glob("signal-*")))
        self.assertFalse(any(self.cache_root.glob("*.tmp")))

    def test_backwards_timestamp_is_detected_before_indexed_access(self):
        backwards = Path(self.directory.name) / "backwards.csv"
        generate_signal_csv(
            backwards,
            SignalFixtureConfig(
                sample_rate_hz=10,
                duration_s=1,
                channels=(2, 5, 260),
                discontinuity_after_indices=(3,),
                discontinuity_us=-1_000_000,
            ),
        )
        info = parse_lfp_csv_info(backwards)
        source = SignalDataSource(
            str(backwards),
            info["metadata"],
            cache_root=Path(self.directory.name) / "backwards-cache",
            chunk_rows=2,
        )
        with self.assertRaisesRegex(ValueError, "backwards"):
            source.ensure_cache(2)

    def test_cleanup_removes_abandoned_and_oldest_excess_caches(self):
        now = 2_000_000_000.0
        self.cache_root.mkdir()
        recent_temporary = self.cache_root / ".recent.tmp"
        old_temporary = self.cache_root / ".old.tmp"
        recent_temporary.mkdir()
        old_temporary.mkdir()
        os.utime(recent_temporary, (now, now))
        os.utime(old_temporary, (now - 2 * 24 * 60 * 60,) * 2)

        oldest = self._fake_cache("signal-oldest", 40, now - 300)
        newer = self._fake_cache("signal-newer", 40, now - 200)
        protected = self._fake_cache("signal-protected", 40, now - 400)
        expired = self._fake_cache(
            "signal-expired",
            10,
            now - 31 * 24 * 60 * 60,
        )

        cleanup_signal_cache(
            self.cache_root,
            max_bytes=40,
            max_age_days=30,
            protected_paths=(protected,),
            now=now,
        )

        self.assertTrue(recent_temporary.exists())
        self.assertFalse(old_temporary.exists())
        self.assertFalse(oldest.exists())
        self.assertFalse(newer.exists())
        self.assertTrue(protected.exists())
        self.assertFalse(expired.exists())

    def test_expired_cache_rebuild_preserves_source_and_segment(self):
        source = self.source()
        before = source.segment(2, 200_000, 600_000)
        cache = source.ensure_cache(2)
        old_time = 1_000_000_000.0
        os.utime(cache / "COMPLETE", (old_time, old_time))

        cleanup_signal_cache(
            self.cache_root,
            max_age_days=30,
            now=old_time + 31 * 24 * 60 * 60,
        )

        self.assertTrue(self.path.exists())
        self.assertFalse(cache.exists())
        after = source.segment(2, 200_000, 600_000)
        np.testing.assert_array_equal(after.time_us, before.time_us)
        np.testing.assert_array_equal(after.values, before.values)

    def _fake_cache(self, name, size, access_time):
        path = self.cache_root / name
        path.mkdir()
        (path / "values.bin").write_bytes(b"x" * size)
        complete = path / "COMPLETE"
        complete.write_text("complete\n", encoding="ascii")
        os.utime(complete, (access_time, access_time))
        return path


if __name__ == "__main__":
    unittest.main()
