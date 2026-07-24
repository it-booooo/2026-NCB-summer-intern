from ..data_export import ExportContext, ExportController
from ..data_import import ImportContext, ImportController
from ..led_detection import LedController
from ..markers import MarkerStore
from ..signal_data import LfpAnalysisService
from ..synchronization import SyncController
from ..ui import (
    FindPeakPanel,
    LedAnalysisPanel,
    LfpPanel,
    MarkerPanel,
    MarkerTable,
    SyncPanel,
    TtlPanel,
)
from ..ui.workspace_view import WorkspaceView
from ..video_player import VideoPlayer
from .components import ApplicationComponents
from .menu_builder import MenuBuilder
from .project_controller import ProjectController
from .settings_controller import AnalysisSettingsController


class ApplicationComposer:
    """Construct and wire the application object graph."""

    def __init__(self, window, app_state):
        self.window = window
        self.app_state = app_state

    def compose(self):
        state = self.app_state
        marker_store = MarkerStore(state.markers.markers)
        lfp_service = LfpAnalysisService(state.data)

        video_player = VideoPlayer(state.video, state.sync, state.led)
        event_table = MarkerTable(marker_store, state.video, state.sync)
        lfp_panel = LfpPanel(state.data, state.sync, marker_store)
        sync_panel = SyncPanel()
        led_analysis_panel = LedAnalysisPanel(
            state.led, video_player, marker_store
        )
        ttl_panel = TtlPanel(
            marker_store,
            state.ttl,
            video_player,
            state.video,
        )
        marker_panel = MarkerPanel(
            marker_store,
            event_table,
            video_player,
            state.video,
        )
        find_peak_panel = FindPeakPanel(
            marker_store,
            lfp_service,
            state.sync,
            state.video,
            video_player,
            state.analysis,
        )
        sync_panel.set_marker_panels(
            ttl_panel,
            marker_panel,
            find_peak_panel,
            led_analysis_panel,
        )
        workspace = WorkspaceView(lfp_panel, sync_panel, video_player)

        components = ApplicationComponents(
            marker_store=marker_store,
            lfp_service=lfp_service,
            video_player=video_player,
            event_table=event_table,
            lfp_panel=lfp_panel,
            sync_panel=sync_panel,
            led_analysis_panel=led_analysis_panel,
            ttl_panel=ttl_panel,
            marker_panel=marker_panel,
            find_peak_panel=find_peak_panel,
            workspace=workspace,
        )

        project_controller = ProjectController(self.window, state.project)
        sync_controller = SyncController(
            sync_state=state.sync,
            ttl_state=state.ttl,
            led_state=state.led,
            video_state=state.video,
            marker_store=marker_store,
            video_player=video_player,
            event_table=event_table,
            lfp_panel=lfp_panel,
            ttl_panel=ttl_panel,
            find_peak_panel=find_peak_panel,
            led_analysis_panel=led_analysis_panel,
        )
        led_controller = LedController(
            dialog_parent=self.window,
            video_player=video_player,
            video_state=state.video,
            led_state=state.led,
            led_analysis_panel=led_analysis_panel,
            marker_store=marker_store,
            add_led_events=sync_controller.add_led_events,
        )
        import_context = ImportContext(
            parent=self.window,
            marker_store=marker_store,
            video_player=video_player,
            event_table=event_table,
            lfp_panel=lfp_panel,
            ttl_panel=ttl_panel,
            sync_panel=sync_panel,
            led_analysis_panel=led_analysis_panel,
            project_controller=project_controller,
            sync_controller=sync_controller,
            led_controller=led_controller,
        )
        export_context = ExportContext(
            parent=self.window,
            marker_store=marker_store,
            lfp_panel=lfp_panel,
            led_analysis_panel=led_analysis_panel,
            led_controller=led_controller,
            project_controller=project_controller,
            find_peak_panel=find_peak_panel,
        )
        import_controller = ImportController(import_context, state)
        export_controller = ExportController(export_context, state)
        settings_controller = AnalysisSettingsController(
            parent=self.window,
            data_state=state.data,
            analysis_settings=state.analysis,
            lfp_panel=lfp_panel,
            show_opencl_status=led_controller.show_opencl_status,
        )

        components.sync_controller = sync_controller
        components.led_controller = led_controller
        components.project_controller = project_controller
        components.settings_controller = settings_controller
        components.import_controller = import_controller
        components.export_controller = export_controller

        project_controller.set_save_callback(export_controller.save_project)
        project_controller.connect_dirty_sources(
            video_player.roi_selected,
            video_player.project_changed,
            marker_store.changed,
            lfp_panel.project_changed,
        )
        sync_controller.connect_signals()
        led_controller.connect_signals()
        event_table.events_changed.connect(lfp_panel.update_lfp_peak_artist)

        MenuBuilder(
            window=self.window,
            import_controller=import_controller,
            export_controller=export_controller,
            settings_controller=settings_controller,
        ).build()
        return components
