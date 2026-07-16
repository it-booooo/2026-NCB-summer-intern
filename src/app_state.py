"""Application state grouped by feature ownership.

The dataclasses in this module contain shared data only.  Qt widgets and
controllers receive the specific state objects they need through their
constructors; notification remains the responsibility of the existing Qt
signals and slots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .signal_data import LfpDataset
    from .video_player.video_helpers import VideoMetadata


@dataclass
class VideoState:
    """Metadata and playback values shared outside ``VideoPlayer``."""

    metadata: VideoMetadata | None = None
    current_frame: int = 0
    is_playing: bool = False
    rotate_180_enabled: bool = False


@dataclass
class DataState:
    """Imported LFP/3-axis data and cross-component plotting settings."""

    lfp_info: dict[str, Any] | None = None
    lfp_dataset: LfpDataset | None = None
    axis_info: dict[str, Any] | None = None
    lfp_step: int | None = None
    axis_step: int | None = None
    line_noise_hz: float = 60.0
    timeline_xlim: tuple[float, float] | None = None


@dataclass
class SyncState:
    """Shared video/record time relationship and derived display data."""

    time_marker_info: dict[str, Any] | None = None
    time_offset_sec: float | None = None
    video_time_origin_sec: float | None = None
    record_time_origin_sec: float | None = None
    current_record_time_sec: float | None = None
    event_intervals: list[dict[str, Any]] = field(default_factory=list)
    loading_video: bool = False


@dataclass
class LedState:
    """LED selection, reusable brightness data, and latest analysis result."""

    roi: tuple[int, int, int, int] | None = None
    brightness_cache: dict[tuple[Any, ...], Any] = field(default_factory=dict)
    analysis_points: list[Any] | None = None
    analysis_threshold: float = 0.0
    analysis_events: list[Any] | None = None
    analysis_stats: dict[str, Any] | None = None
    analysis_status: str | None = None


@dataclass
class EventState:
    """Canonical event marker records displayed by ``EventTable``."""

    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AppState:
    """Composition root for all feature states.

    Only the application root should normally receive this complete object.
    Child components are injected with one or more feature-specific states.
    """

    video: VideoState = field(default_factory=VideoState)
    data: DataState = field(default_factory=DataState)
    sync: SyncState = field(default_factory=SyncState)
    led: LedState = field(default_factory=LedState)
    events: EventState = field(default_factory=EventState)
