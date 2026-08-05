import unittest
from unittest.mock import Mock, patch

from src.app_state import DataState
from src.signal_data import LfpAnalysisService


class LfpDataStateTests(unittest.TestCase):
    def test_lfp_info_is_derived_from_dataset(self):
        info = {"path": "current.csv", "channels": [2, 5]}
        dataset = Mock(info=info, channels=[2, 5])
        state = DataState(lfp_dataset=dataset)

        self.assertIs(state.lfp_info, info)
        with self.assertRaises(AttributeError):
            state.lfp_info = {"path": "other.csv"}

    def test_analysis_service_reuses_the_shared_dataset(self):
        dataset = Mock(info={"path": "current.csv"}, channels=[2, 5])
        state = DataState(lfp_dataset=dataset)
        service = LfpAnalysisService(state)

        self.assertIs(service.dataset(), dataset)
        self.assertEqual(service.available_channels(), [2, 5])

    def test_failed_compatibility_import_keeps_current_dataset(self):
        current = Mock(info={"path": "current.csv"})
        state = DataState(lfp_dataset=current)

        with patch(
            "src.signal_data.LfpDataset.from_csv",
            side_effect=ValueError("invalid LFP"),
        ), self.assertRaisesRegex(ValueError, "invalid LFP"):
            state.load_lfp_info({"path": "broken.csv"})

        self.assertIs(state.lfp_dataset, current)


class ThreeAxisDataStateTests(unittest.TestCase):
    def test_three_axis_info_is_derived_from_dataset(self):
        info = {"path": "three_axis.csv"}
        dataset = Mock(info=info)
        state = DataState(three_axis_dataset=dataset)

        self.assertIs(state.three_axis_info, info)
        with self.assertRaises(AttributeError):
            state.three_axis_info = {"path": "other.csv"}

    def test_failed_compatibility_import_keeps_current_dataset(self):
        current = Mock(info={"path": "current.csv"})
        state = DataState(three_axis_dataset=current)

        with patch(
            "src.signal_data.SignalDataset.from_csv",
            side_effect=ValueError("invalid three-axis data"),
        ), self.assertRaisesRegex(ValueError, "invalid three-axis data"):
            state.load_three_axis_info({"path": "broken.csv"})

        self.assertIs(state.three_axis_dataset, current)


if __name__ == "__main__":
    unittest.main()
