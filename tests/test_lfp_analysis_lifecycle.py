import gc
import io
import os
import sys
import types
import unittest
import weakref
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QWidget

# Loading this focused module must not import every optional UI feature (notably
# OpenCV) through src.ui.__init__.
ui_package = types.ModuleType("src.ui")
ui_package.__path__ = [str(Path(__file__).parents[1] / "src" / "ui")]
sys.modules.setdefault("src.ui", ui_package)

from src.ui.lfp_analysis import LfpAnalysisMixin


class _AnalysisHost(QWidget, LfpAnalysisMixin):
    def __init__(self):
        super().__init__()
        self.spectrum_dialogs = []
        self.sync_state = SimpleNamespace(record_time_origin_sec=None)


class LfpAnalysisLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = _AnalysisHost()

    def tearDown(self):
        self.host.close()
        self.app.processEvents()

    def test_static_render_does_not_retain_figure_or_canvas(self):
        figure = Figure(figsize=(2, 1))
        figure.add_subplot(111).plot([0, 1], [0, 1])
        canvas_ref = weakref.ref(figure.canvas)
        figure_ref = weakref.ref(figure)

        pixmap = self.host._figure_to_pixmap(figure)
        self.host._dispose_figure(figure)
        del figure
        gc.collect()

        self.assertFalse(pixmap.isNull())
        self.assertIsNone(figure_ref())
        self.assertIsNone(canvas_ref())

    def test_repeated_dialog_close_releases_pixmaps_and_registry_entries(self):
        label_refs = []
        for index in range(5):
            figure = Figure(figsize=(2, 1))
            figure.add_subplot(111).plot([0, 1], [index, index + 1])
            pixmap = self.host._figure_to_pixmap(figure)
            self.host._dispose_figure(figure)
            del figure
            self.host.open_lfp_analysis_dialog(
                f"Analysis {index}",
                2,
                0.0,
                1.0,
                101,
                100.0,
                None,
                pixmap,
                (820, 560),
            )
            dialog = self.host.spectrum_dialogs[-1]
            label = dialog._lfp_image_label
            scroll_area = dialog._lfp_scroll_area
            self.app.processEvents()
            scroll_area.fit_pixmap_height()
            label_refs.append(weakref.ref(label))
            self.assertFalse(label.pixmap().isNull())
            # The window now sizes toward the image aspect ratio, clamped to the
            # screen, instead of staying pinned to the default width.
            available = dialog.screen().availableGeometry()
            self.assertLessEqual(dialog.width(), available.width())
            self.assertLessEqual(dialog.height(), 560)
            self.assertEqual(
                scroll_area.verticalScrollBarPolicy(),
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
            )
            self.assertEqual(label.height(), scroll_area.viewport().height())
            self.assertEqual(scroll_area.verticalScrollBar().maximum(), 0)
            dialog.close()
            self.app.processEvents()
            QCoreApplication.sendPostedEvents(
                None,
                QEvent.Type.DeferredDelete,
            )
            del dialog, label, pixmap, scroll_area

        self.assertEqual(self.host.spectrum_dialogs, [])
        self.assertTrue(all(reference() is None for reference in label_refs))

    def test_dialog_width_grows_with_image_aspect_ratio(self):
        def open_dialog(figure_width):
            figure = Figure(figsize=(figure_width, 1))
            figure.add_subplot(111).plot([0, 1], [0, 1])
            pixmap = self.host._figure_to_pixmap(figure)
            self.host._dispose_figure(figure)
            del figure
            self.host.open_lfp_analysis_dialog(
                "Analysis",
                2,
                0.0,
                1.0,
                101,
                100.0,
                None,
                pixmap,
                (820, 560),
            )
            dialog = self.host.spectrum_dialogs[-1]
            self.app.processEvents()
            return dialog

        narrow = open_dialog(2)
        wide = open_dialog(8)
        available = wide.screen().availableGeometry()
        # A longer recording renders a wider image, so its window opens wider
        # (until both hit the screen clamp, where they stay equal).
        self.assertGreaterEqual(wide.width(), narrow.width())
        self.assertLessEqual(wide.width(), available.width())
        narrow.close()
        wide.close()
        self.app.processEvents()

    def test_finished_analysis_clears_static_image_payload(self):
        figure = Figure(figsize=(2, 1))
        figure.add_subplot(111).plot([0, 1], [0, 1])
        canvas = FigureCanvasAgg(figure)
        image_output = io.BytesIO()
        canvas.print_png(image_output)
        result = {
            "sample_count": 1000,
            "sample_rate_hz": 100.0,
            "start_time_s": 0.0,
            "end_time_s": 10.0,
            "image_png": image_output.getvalue(),
        }
        self.host._dispose_figure(figure)
        self.host._analysis_result_is_current = Mock(return_value=True)
        self.host._complete_lfp_analysis_request = Mock()
        self.host.open_lfp_analysis_dialog = Mock()

        self.host._finish_lfp_analysis(
            "request",
            ("source",),
            result,
            analysis_type="power_spectrum",
            failure_title="failed",
            dialog_title="Power",
            dialog_size=(320, 240),
            channel=2,
            left=0.0,
            right=10.0,
            settings=None,
        )

        self.assertEqual(result, {})
        self.host.open_lfp_analysis_dialog.assert_called_once()

    def test_spectrogram_dialog_supports_auto_and_custom_color_scale(self):
        figure = Figure(figsize=(2, 1))
        figure.add_subplot(111).plot([0, 1], [0, 1])
        pixmap = self.host._figure_to_pixmap(figure)
        self.host._dispose_figure(figure)
        self.host.open_lfp_analysis_dialog(
            "Spectrogram",
            2,
            0.0,
            1.0,
            101,
            100.0,
            None,
            pixmap,
            (820, 560),
            analysis_type="spectrogram",
            spectrogram_auto_scale=True,
            spectrogram_color_limits_db=(-75.0, -15.0),
        )
        dialog = self.host.spectrum_dialogs[-1]

        self.assertTrue(dialog._spectrogram_auto_scale.isChecked())
        self.assertFalse(dialog._spectrogram_color_min.isEnabled())
        self.assertFalse(dialog._spectrogram_color_max.isEnabled())
        self.assertEqual(dialog._spectrogram_color_min.value(), -75.0)
        self.assertEqual(dialog._spectrogram_color_max.value(), -15.0)

        dialog._spectrogram_auto_scale.setChecked(False)
        dialog._spectrogram_color_min.setValue(-80.0)
        dialog._spectrogram_color_max.setValue(-20.0)
        self.host.show_lfp_analysis = Mock(return_value=True)
        applied = self.host._apply_spectrogram_scale(
            dialog,
            dialog._spectrogram_auto_scale,
            dialog._spectrogram_color_min,
            dialog._spectrogram_color_max,
        )

        self.assertTrue(applied)
        self.host.show_lfp_analysis.assert_called_once_with(
            "spectrogram",
            spectrogram_color_limits_db=(-80.0, -20.0),
        )
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
