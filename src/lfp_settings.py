"""Shared, dependency-free LFP filter configuration."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LfpFilterSettings:
    """Complete LFP display and analysis filter configuration."""

    show_filtered: bool = False
    bandpass_enabled: bool = False
    bandpass_low_hz: float = 1.0
    bandpass_high_hz: float = 100.0
    line_noise_hz: float | None = None
    notch_quality: float = 30.0
    line_noise_method: str = "notch"
    regression_window_seconds: float = 4.0
    regression_overlap: float = 0.5
    regression_harmonics: int = 1
    regression_all_harmonics: bool = False
    line_noise_frequencies_hz: tuple[float, ...] = ()
