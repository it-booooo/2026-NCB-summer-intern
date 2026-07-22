from .lfp_dataset import LfpDataset
from .lfp_processing import LfpFilterSettings


class LfpAnalysisService:
    """Provide LFP data to analysis features without exposing the LFP widget."""

    def __init__(self, data_state):
        self.data_state = data_state

    def selected_channel(self):
        value = self.data_state.selected_lfp_channel
        return None if value is None else int(value)

    def filter_settings(self):
        return LfpFilterSettings(**dict(self.data_state.lfp_filter_settings))

    def dataset(self):
        info = self.data_state.lfp_info
        if not (info and info.get("path")):
            raise ValueError("Please import LFP CSV data first.")
        dataset = self.data_state.lfp_dataset
        if dataset is None or dataset.info.get("path") != info.get("path"):
            dataset = LfpDataset.from_csv(info)
            self.data_state.lfp_dataset = dataset
        return dataset
