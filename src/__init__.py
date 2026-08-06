from importlib import import_module

_LAZY_EXPORTS = {
    "AppState": (".app_state", "AppState"),
    "DataState": (".app_state", "DataState"),
    "LedState": (".app_state", "LedState"),
    "MarkerState": (".app_state", "MarkerState"),
    "SyncState": (".app_state", "SyncState"),
    "TtlState": (".app_state", "TtlState"),
    "VideoState": (".app_state", "VideoState"),
    "MarkerTable": (".ui", "MarkerTable"),
    "export_markers_csv": (".data_export", "export_markers_csv"),
    "export_markers_excel": (".data_export", "export_markers_excel"),
    "WavePanel": (".ui", "WavePanel"),
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
    "AppState",
    "DataState",
    "MarkerTable",
    "LedState",
    "WavePanel",
    "MarkerPanel",
    "MarkerState",
    "SyncPanel",
    "SyncState",
    "TtlState",
    "VideoPlayer",
    "VideoState",
    "export_markers_csv",
    "export_markers_excel",
]
