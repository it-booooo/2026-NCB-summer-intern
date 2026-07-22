from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class MarkerKind(str, Enum):
    TTL = "TTL"
    LED_ON = "LED_on"
    LED_OFF = "LED_off"
    BEHAVIOR_START = "behavior_start"
    BEHAVIOR_END = "behavior_end"
    SEIZURE_LIKE = "seizure_like_event"
    LFP_PEAK = "LFP_peak"


class MarkerSource(str, Enum):
    MANUAL = "manual"
    TTL_IMPORT = "ttl_import"
    LED_DETECTION = "led_detection"
    LFP_DETECTION = "lfp_peak"
    PROJECT_IMPORT = "project_import"


@dataclass(frozen=True, slots=True)
class VideoPosition:
    time_sec: float
    frame_index: int


@dataclass(frozen=True, slots=True)
class RecordPosition:
    time_sec: float


@dataclass(frozen=True, slots=True)
class Marker:
    kind: MarkerKind
    source: MarkerSource
    position: VideoPosition | RecordPosition
    note: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    marker_id: str = field(default_factory=lambda: str(uuid4()))


def marker_kind(value: MarkerKind | str) -> MarkerKind:
    if isinstance(value, MarkerKind):
        return value
    return MarkerKind(str(value))


def marker_source(value: MarkerSource | str) -> MarkerSource:
    if isinstance(value, MarkerSource):
        return value
    aliases = {
        "lfp_detection": MarkerSource.LFP_DETECTION,
        "timeline": MarkerSource.TTL_IMPORT,
    }
    alias = aliases.get(str(value))
    return alias if alias is not None else MarkerSource(str(value))


def marker_video_time(marker: Marker, offset_sec: float | None) -> float | None:
    if isinstance(marker.position, VideoPosition):
        return marker.position.time_sec
    if offset_sec is None:
        return None
    return marker.position.time_sec + offset_sec


def marker_record_time(marker: Marker, offset_sec: float | None) -> float | None:
    if isinstance(marker.position, RecordPosition):
        return marker.position.time_sec
    if offset_sec is None:
        return None
    return marker.position.time_sec - offset_sec
