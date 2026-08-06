import unittest
import sys
from types import ModuleType

import matplotlib

matplotlib.use("Agg")

from matplotlib.figure import Figure

sys.modules.setdefault("cv2", ModuleType("cv2"))

from src.ui.lfp_controls import SharedTimelineSlider  # noqa: E402


class LfpFilterStatusTests(unittest.TestCase):
    def test_status_is_hidden_for_raw_and_red_green_for_filtered(self):
        figure = Figure()
        slider = SharedTimelineSlider(
            figure.add_subplot(111), (0.0, 10.0), (2.0, 4.0)
        )

        slider.set_filter_status(False)
        self.assertFalse(slider.filter_status_track.get_visible())

        slider.set_filter_status(True, [(3.0, 5.0), (7.0, 9.0)])
        self.assertTrue(slider.filter_status_track.get_visible())
        self.assertEqual(
            slider.filter_status_track.get_facecolor()[:3],
            (217 / 255, 83 / 255, 79 / 255),
        )
        self.assertEqual(len(slider.filter_status_patches), 2)
        self.assertEqual(
            slider.filter_status_patches[0].get_facecolor()[:3],
            (60 / 255, 166 / 255, 92 / 255),
        )


if __name__ == "__main__":
    unittest.main()
