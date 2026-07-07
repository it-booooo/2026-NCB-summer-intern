import draw_function as draw
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class LfpPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(300)

        self.lfp_path = None
        self.axis_path = None
        self.lfp_canvas = None
        self.axis_canvas = None

        self.lfp_file_label = QLabel("LFP CSV: Not imported")
        self.axis_file_label = QLabel("3-axis CSV: Not imported")

        self.lfp_channel_selector = QComboBox()
        self.lfp_channel_selector.addItem("No LFP channel")
        self.lfp_channel_selector.setEnabled(False)
        self.lfp_channel_selector.currentIndexChanged.connect(self.plot_lfp)

        waveform_grid = QGridLayout()
        waveform_grid.setVerticalSpacing(4)
        waveform_grid.setColumnStretch(1, 1)
        waveform_grid.setRowStretch(0, 1)
        waveform_grid.setRowStretch(1, 1)

        self.lfp_waveform_area = self.create_waveform_area("Import LFP CSV to show waveform")
        self.axis_waveform_area = self.create_waveform_area("Import 3-axis CSV to show waveform")

        waveform_grid.addWidget(QLabel("LFP"), 0, 0)
        waveform_grid.addWidget(self.lfp_waveform_area, 0, 1)

        waveform_grid.addWidget(QLabel("3-axis"), 1, 0)
        waveform_grid.addWidget(self.axis_waveform_area, 1, 1)

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 4, 8, 6)
        layout.setSpacing(4)

        layout.addWidget(self.lfp_file_label)
        layout.addWidget(self.lfp_channel_selector)

        layout.addWidget(self.axis_file_label)
        layout.addLayout(waveform_grid, stretch=1)

        self.setLayout(layout)

    def create_waveform_area(self, text):
        frame = QFrame()
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        frame.setStyleSheet(
            """
            QFrame {
                background-color: #fbfbfb;
                border: 1px solid #d0d0d0;
            }
            """
        )

        frame.setToolTip(text)
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        placeholder = QLabel(text)
        placeholder.setAlignment(Qt.AlignCenter) # type: ignore
        placeholder.setStyleSheet("color: #777; border: none;")
        layout.addWidget(placeholder)
        frame.setLayout(layout)
        return frame

    def set_figure(self, frame, canvas_attr, fig):
        old_canvas = getattr(self, canvas_attr)
        if old_canvas is not None:
            old_canvas.setParent(None)
            old_canvas.deleteLater()

        layout = frame.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        canvas = FigureCanvas(fig)
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(canvas)
        setattr(self, canvas_attr, canvas)
        canvas.draw_idle()

    def selected_channel(self, selector):
        channel = selector.currentData()
        if channel is None:
            return None

        try:
            return int(channel)
        except (TypeError, ValueError):
            return None

    def plot_lfp(self):
        if not self.lfp_path:
            return

        channel = self.selected_channel(self.lfp_channel_selector)
        try:
            fig = draw.LFP(file_path=self.lfp_path, channels=channel, compact=True)
        except Exception as error:
            QMessageBox.warning(self, "LFP plot failed", str(error))
            return

        self.set_figure(self.lfp_waveform_area, "lfp_canvas", fig)

    def plot_axis(self):
        if not self.axis_path:
            return

        try:
            fig = draw.accelerator(file_path=self.axis_path, compact=True)
        except Exception as error:
            QMessageBox.warning(self, "3-axis plot failed", str(error))
            return

        self.set_figure(self.axis_waveform_area, "axis_canvas", fig)

    def set_lfp_info(self, info):
        self.lfp_path = info["path"]
        self.lfp_file_label.setText(f"LFP CSV: {info['filename']}")

        self.lfp_channel_selector.blockSignals(True)
        self.lfp_channel_selector.clear()

        channels = info.get("channels", [])

        if channels:
            for channel in channels:
                self.lfp_channel_selector.addItem(f"Channel {channel}", channel)

            self.lfp_channel_selector.setEnabled(True)
        else:
            self.lfp_channel_selector.addItem("No LFP channel")
            self.lfp_channel_selector.setEnabled(False)

        self.lfp_channel_selector.blockSignals(False)
        self.plot_lfp()

    def set_axis_info(self, info):
        self.axis_path = info["path"]
        self.axis_file_label.setText(f"3-axis CSV: {info['filename']} (channel 260)")
        self.plot_axis()
