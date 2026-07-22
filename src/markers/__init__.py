from .models import (
    Marker,
    MarkerKind,
    MarkerSource,
    RecordPosition,
    VideoPosition,
    marker_record_time,
    marker_video_time,
)
from .serialization import (
    marker_from_dict,
    marker_from_legacy_ttl,
    marker_to_dict,
)

__all__ = [
    "Marker",
    "MarkerKind",
    "MarkerSource",
    "MarkerStore",
    "RecordPosition",
    "VideoPosition",
    "marker_from_dict",
    "marker_from_legacy_ttl",
    "marker_record_time",
    "marker_to_dict",
    "marker_video_time",
]


def __getattr__(name):
    if name == "MarkerStore":
        from .store import MarkerStore

        return MarkerStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
