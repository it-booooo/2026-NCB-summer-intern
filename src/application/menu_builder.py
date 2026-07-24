from PySide6.QtGui import QAction


class MenuBuilder:
    """Build the application menu from feature-owned action providers."""

    def __init__(
        self,
        *,
        window,
        import_controller,
        export_controller,
        settings_controller,
    ):
        self.window = window
        self.import_controller = import_controller
        self.export_controller = export_controller
        self.settings_controller = settings_controller

    def build(self):
        menu_bar = self.window.menuBar()
        file_menu = menu_bar.addMenu("File")
        settings_menu = menu_bar.addMenu("Settings")
        self._add_action(
            file_menu,
            "Open Project...",
            self.import_controller.open_project,
            "Restore a complete analysis session from a .pigproj file.",
        )
        self._add_action(
            file_menu,
            "Save Project...",
            self.export_controller.save_project,
            "Save analysis state in one .pigproj file while referencing all imported files by path.",
        )
        file_menu.addSeparator()
        import_menu = file_menu.addMenu("Import")
        export_menu = file_menu.addMenu("Export")
        import_menu.setToolTipsVisible(True)
        export_menu.setToolTipsVisible(True)
        for text, callback, description in self.import_controller.actions():
            self._add_action(import_menu, text, callback, description)
        for text, callback, description in self.export_controller.actions():
            self._add_action(export_menu, text, callback, description)

        self._add_action(
            settings_menu,
            "Set LFP step",
            lambda: self.settings_controller.set_plot_step("lfp"),
        )
        self._add_action(
            settings_menu,
            "Set 3-axis step",
            lambda: self.settings_controller.set_plot_step("axis"),
        )
        self._add_action(
            settings_menu,
            "Set power noise frequency",
            self.settings_controller.set_power_noise_frequency,
        )
        self._add_action(
            settings_menu,
            "Set LFP peak thresholds",
            self.settings_controller.set_lfp_peak_thresholds,
        )
        self._add_action(
            settings_menu,
            "Check OpenCL GPU",
            self.settings_controller.show_opencl_status,
        )

    def _add_action(self, menu, text, callback, description=""):
        action = QAction(text, self.window)
        action.triggered.connect(callback)
        if description:
            action.setToolTip(description)
            action.setStatusTip(description)
        menu.addAction(action)
        return action
