from .lfp_processing import LfpFilterSettings, parse_line_noise_frequencies


class LfpAnalysisService:
    """Provide LFP data to analysis features without exposing the LFP widget."""

    def __init__(self, data_state):
        self.data_state = data_state

    def selected_channel(self):
        value = self.data_state.selected_lfp_channel
        return None if value is None else int(value)

    def available_channels(self):
        dataset = self.data_state.lfp_dataset
        return [] if dataset is None else dataset.channels

    def filter_settings(self):
        settings = dict(self.data_state.lfp_filter_settings)
        settings["line_noise_frequencies_hz"] = parse_line_noise_frequencies(
            settings.get(
                "line_noise_frequencies_hz",
                settings.get("line_noise_hz"),
            )
        )
        settings.setdefault(
            "regression_all_harmonics",
            int(settings.get("regression_harmonics", 1)) > 1,
        )
        return LfpFilterSettings(**settings)

    def dataset(self):
        dataset = self.data_state.lfp_dataset
        if dataset is None:
            raise ValueError("Please import LFP CSV data first.")
        return dataset
