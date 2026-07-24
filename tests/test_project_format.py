import unittest

from src.app_state import AppState
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


if __name__ == "__main__":
    unittest.main()
