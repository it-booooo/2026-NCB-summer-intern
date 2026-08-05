"""Application state grouped by feature ownership.

The dataclasses in this module contain shared data only.  Qt widgets and
controllers receive the specific state objects they need through their
constructors; notification remains the responsibility of the existing Qt
signals and slots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from .markers.models import Marker

if TYPE_CHECKING:
    from .signal_data import LfpDataset, SignalDataset


@dataclass
class VideoMetadata:
    path: str
    filename: str
    file_format: str
    codec: str
    width: int
    height: int
    detected_fps: float
    using_fps: float
    total_frames: int
    detected_duration_sec: float
    duration_sec: float


@dataclass
class VideoState:
    """Metadata and playback values shared outside ``VideoPlayer``."""

    metadata: VideoMetadata | None = None
    current_frame: int = 0
    is_playing: bool = False
    rotation_degrees: int = 0
    rotate_180_enabled: bool = False


@dataclass
class DataState:
    """Imported LFP/3-axis data and cross-component plotting settings."""

    lfp_dataset: LfpDataset | None = None
    three_axis_dataset: SignalDataset | None = None
    lfp_step: int | None = None
    three_axis_step: int | None = None
    line_noise_hz: float = 60.0
    timeline_xlim: tuple[float, float] | None = None
    selected_lfp_channel: int | None = None
    lfp_filter_settings: dict[str, Any] = field(
        default_factory=lambda: {
            "show_filtered": False,
            "bandpass_enabled": False,
            "bandpass_low_hz": 1.0,
            "bandpass_high_hz": 100.0,
            "line_noise_hz": 60.0,
            "notch_quality": 30.0,
        }
    )
    follow_video_playback: bool = True

    @property
    def lfp_info(self) -> dict[str, Any] | None:
        """Compatibility view of metadata owned by the active LFP dataset."""
        dataset = self.lfp_dataset
        return None if dataset is None else dataset.info

    def load_lfp_info(self, info: dict[str, Any]) -> LfpDataset:
        """Prepare and atomically install a dataset from legacy metadata."""
        from .signal_data import LfpDataset

        dataset = LfpDataset.from_csv(info)
        if self.lfp_dataset is not None and self.lfp_dataset is not dataset:
            self.lfp_dataset.close(wait=True)
        self.lfp_dataset = dataset
        return dataset

    @property
    def three_axis_info(self) -> dict[str, Any] | None:
        """Return metadata owned by the active three-axis dataset."""
        dataset = self.three_axis_dataset
        return None if dataset is None else dataset.info

    def load_three_axis_info(self, info: dict[str, Any]) -> SignalDataset:
        """Prepare and atomically install a three-axis dataset from metadata."""
        from .signal_data import SignalDataset

        dataset = SignalDataset.from_csv(info)
        self.three_axis_dataset = dataset
        return dataset


@dataclass
class SyncState:
    """Shared video/record time relationship and derived display data."""

    time_offset_sec: float | None = None
    reference_mode: str = "auto"
    ttl_reference_marker_id: str | None = None
    video_reference_marker_id: str | None = None
    video_time_origin_sec: float | None = None
    record_time_origin_sec: float | None = None
    current_record_time_sec: float | None = None
    event_intervals: list[dict[str, Any]] = field(default_factory=list)
    loading_video: bool = False


@dataclass
class TtlState:
    """Metadata for the currently imported TTL source file."""

    metadata: dict[str, Any] | None = None


@dataclass
class LedState:
    """LED selection, reusable brightness data, and latest analysis result."""

    BRIGHTNESS_CACHE_MAX_ENTRIES: ClassVar[int] = 5

    roi: tuple[int, int, int, int] | None = None
    brightness_cache: dict[tuple[Any, ...], Any] = field(default_factory=dict)
    analysis_points: list[Any] | None = None
    analysis_threshold: float = 0.0
    analysis_stats: dict[str, Any] | None = None
    analysis_status: str | None = None

    def cached_brightness_points(self, key):
        points = self.brightness_cache.pop(key, None)
        if points is not None:
            self.brightness_cache[key] = points
        return points

    def cache_brightness_points(self, key, points):
        self.brightness_cache.pop(key, None)
        self.brightness_cache[key] = points
        while len(self.brightness_cache) > self.BRIGHTNESS_CACHE_MAX_ENTRIES:
            oldest_key = next(iter(self.brightness_cache))
            del self.brightness_cache[oldest_key]


@dataclass
class MarkerState:
    """Canonical markers shared by every marker panel and timeline view."""

    markers: list[Marker] = field(default_factory=list)


@dataclass
class AnalysisSettings:
    """User-adjustable analysis parameters shared by UI and services."""

    lfp_peak_height_sigma: float = 8.0
    lfp_peak_prominence_sigma: float = 6.0
    lfp_peak_min_distance_sec: float = 1.0


@dataclass
class ProjectState:
    """Current project file and unsaved-change state."""

    path: str | None = None
    dirty: bool = False
    loading: bool = False


@dataclass
class AppState:
    """Composition root for all feature states.

    Only the application root should normally receive this complete object.
    Child components are injected with one or more feature-specific states.
    """

    video: VideoState = field(default_factory=VideoState)
    data: DataState = field(default_factory=DataState)
    sync: SyncState = field(default_factory=SyncState)
    ttl: TtlState = field(default_factory=TtlState)
    led: LedState = field(default_factory=LedState)
    markers: MarkerState = field(default_factory=MarkerState)
    analysis: AnalysisSettings = field(default_factory=AnalysisSettings)
    project: ProjectState = field(default_factory=ProjectState)
