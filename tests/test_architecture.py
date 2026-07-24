import ast
import unittest
from pathlib import Path

from src.app_state import AppState
from src.project_format import validate_state

ROOT = Path(__file__).resolve().parents[1]


class MainWindowArchitectureTests(unittest.TestCase):
    def test_main_window_remains_a_thin_shell(self):
        tree = ast.parse((ROOT / "src" / "main_window.py").read_text("utf-8"))
        window = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "MainWindow"
        )

        self.assertEqual(
            [base.id for base in window.bases if isinstance(base, ast.Name)],
            ["QMainWindow"],
        )
        methods = {
            node.name for node in window.body if isinstance(node, ast.FunctionDef)
        }
        self.assertEqual(methods, {"__init__", "closeEvent"})

    def test_import_and_export_do_not_retain_main_window(self):
        for relative_path in (
            "src/data_import/import_controller.py",
            "src/data_export/export_controller.py",
        ):
            source = (ROOT / relative_path).read_text("utf-8")
            self.assertNotIn("self.window", source)


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
