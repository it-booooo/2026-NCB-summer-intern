from importlib import import_module

from .app_state import (
    AppState,
    DataState,
    LedState,
    MarkerState,
    SyncState,
    TtlState,
    VideoState,
)

_LAZY_EXPORTS = {
    "EventTable": (".ui", "EventTable"),
    "export_events_csv": (".data_export", "export_events_csv"),
    "export_events_excel": (".data_export", "export_events_excel"),
    "LfpPanel": (".ui", "LfpPanel"),
    "MarkerPanel": (".ui", "MarkerPanel"),
    "SyncPanel": (".ui", "SyncPanel"),
    "VideoPlayer": (".video_player", "VideoPlayer"),
}


def __getattr__(name):
    module_name, attribute = _LAZY_EXPORTS.get(name, (None, None))
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value

__all__ = [
    "EventTable",
    "MarkerState",
    "export_events_csv",
    "export_events_excel",
    "LfpPanel",
    "LedState",
    "MarkerPanel",
    "DataState",
    "SyncPanel",
    "SyncState",
    "TtlState",
    "AppState",
    "VideoPlayer",
    "VideoState",
]
