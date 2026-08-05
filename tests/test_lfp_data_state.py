import unittest
from unittest.mock import Mock

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

class ThreeAxisDataStateTests(unittest.TestCase):
    def test_three_axis_info_is_derived_from_dataset(self):
        info = {"path": "three_axis.csv"}
        dataset = Mock(info=info)
        state = DataState(three_axis_dataset=dataset)

        self.assertIs(state.three_axis_info, info)
        with self.assertRaises(AttributeError):
            state.three_axis_info = {"path": "other.csv"}

if __name__ == "__main__":
    unittest.main()
