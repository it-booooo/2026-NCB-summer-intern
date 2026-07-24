from dataclasses import dataclass

from ..markers import MarkerStore
from ..signal_data import LfpAnalysisService


@dataclass
class ApplicationComponents:
    """The constructed application object graph.

    This is a typed registry, not a service locator: only the composition root
    receives the complete object. Feature controllers receive explicit fields.
    """

    marker_store: MarkerStore
    lfp_service: LfpAnalysisService
    video_player: object
    event_table: object
    lfp_panel: object
    sync_panel: object
    led_analysis_panel: object
    ttl_panel: object
    marker_panel: object
    find_peak_panel: object
    workspace: object
    sync_controller: object | None = None
    led_controller: object | None = None
    project_controller: object | None = None
    settings_controller: object | None = None
    import_controller: object | None = None
    export_controller: object | None = None
