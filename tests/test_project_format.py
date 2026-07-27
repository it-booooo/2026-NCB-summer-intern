import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from src.app_state import AppState
from src.project_archive import load_project_archive
from src.project_format import PROJECT_FORMAT, PROJECT_VERSION
from src.project_format import validate_state


class AnalysisSettingsTests(unittest.TestCase):
    def test_peak_settings_live_in_application_state(self):
        state = AppState()

        self.assertEqual(state.analysis.lfp_peak_height_sigma, 8.0)
        self.assertEqual(state.analysis.lfp_peak_prominence_sigma, 6.0)
        self.assertEqual(state.analysis.lfp_peak_min_distance_sec, 1.0)

    def test_project_validation_accepts_valid_analysis_settings(self):
        state = {
            "analysis": {
                "lfp_peak_height_sigma": 7.5,
                "lfp_peak_prominence_sigma": 5.5,
                "lfp_peak_min_distance_sec": 0.02,
            }
        }

        self.assertIs(validate_state(state), state)

    def test_project_validation_rejects_invalid_minimum_distance(self):
        with self.assertRaises(ValueError):
            validate_state(
                {"analysis": {"lfp_peak_min_distance_sec": 0.0}}
            )


class ProjectArchiveTests(unittest.TestCase):
    def test_project_archive_is_read_and_validated_without_qt(self):
        manifest = {
            "format": PROJECT_FORMAT,
            "version": PROJECT_VERSION,
            "sources": {},
        }
        state = {"analysis": {"lfp_peak_min_distance_sec": 0.5}}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "analysis.pigproj"
            with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("state.json", json.dumps(state))

            loaded = load_project_archive(path)

        self.assertEqual(loaded["sources"], {})
        self.assertEqual(loaded["state"], state)

    def test_project_archive_rejects_invalid_state_before_restore(self):
        manifest = {
            "format": PROJECT_FORMAT,
            "version": PROJECT_VERSION,
            "sources": {},
        }
        state = {"analysis": {"lfp_peak_min_distance_sec": 0.0}}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "analysis.pigproj"
            with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("state.json", json.dumps(state))

            with self.assertRaises(ValueError):
                load_project_archive(path)


if __name__ == "__main__":
    unittest.main()
