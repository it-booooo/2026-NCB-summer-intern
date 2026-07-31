import tempfile
import unittest
from pathlib import Path

from src.signal_data import parse_ttl_marker_csv_info


class TtlMarkerCsvTests(unittest.TestCase):
    def test_parse_ttl_marker_csv_info_preserves_marker_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ttl-markers.csv"
            path.write_text(
                "local_time(us),record_time(us)\n"
                "1722384000000000,2500000\n",
                encoding="utf-8",
            )

            info = parse_ttl_marker_csv_info(path)

        self.assertEqual(info["marker_count"], 1)
        self.assertEqual(info["first_marker_sec"], 2.5)
        self.assertEqual(info["markers"][0]["record_time"], 2_500_000)


if __name__ == "__main__":
    unittest.main()
