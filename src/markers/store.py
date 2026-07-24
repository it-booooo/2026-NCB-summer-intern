from __future__ import annotations

from dataclasses import replace

from .models import Marker, marker_kind, marker_source


class CallbackSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        for callback in tuple(self._callbacks):
            callback(*args)


class MarkerStore:

    def __init__(self, markers=None):
        self.changed = CallbackSignal()
        self.marker_added = CallbackSignal()
        self.marker_updated = CallbackSignal()
        self.marker_removed = CallbackSignal()
        self._markers = markers if isinstance(markers, list) else list(markers or [])

    def all(self) -> tuple[Marker, ...]:
        return tuple(self._markers)

    def get(self, marker_id: str) -> Marker:
        for marker in self._markers:
            if marker.marker_id == marker_id:
                return marker
        raise KeyError(marker_id)

    def add(self, marker: Marker, emit=True) -> Marker:
        if any(item.marker_id == marker.marker_id for item in self._markers):
            raise ValueError(f"Duplicate marker id: {marker.marker_id}")
        self._markers.append(marker)
        if emit:
            self.marker_added.emit(marker.marker_id)
            self.changed.emit()
        return marker

    def update(self, marker_id: str, emit=True, **changes) -> Marker:
        for index, marker in enumerate(self._markers):
            if marker.marker_id != marker_id:
                continue
            if "kind" in changes:
                changes["kind"] = marker_kind(changes["kind"])
            if "source" in changes:
                changes["source"] = marker_source(changes["source"])
            updated = replace(marker, **changes)
            self._markers[index] = updated
            if emit:
                self.marker_updated.emit(marker_id)
                self.changed.emit()
            return updated
        raise KeyError(marker_id)

    def delete(self, marker_id: str, emit=True) -> None:
        for index, marker in enumerate(self._markers):
            if marker.marker_id == marker_id:
                del self._markers[index]
                if emit:
                    self.marker_removed.emit(marker_id)
                    self.changed.emit()
                return
        raise KeyError(marker_id)

    def clear(self, emit=True) -> None:
        if not self._markers:
            return
        self._markers.clear()
        if emit:
            self.changed.emit()

    def replace_all(self, markers, emit=True) -> None:
        self._markers[:] = list(markers)
        if emit:
            self.changed.emit()

    def replace_by_source(self, source, markers, emit=True) -> None:
        source = marker_source(source)
        retained = [item for item in self._markers if item.source != source]
        self._markers[:] = [*retained, *markers]
        if emit:
            self.changed.emit()

    def replace_by_kind(self, kind, markers, emit=True) -> None:
        kind = marker_kind(kind)
        retained = [item for item in self._markers if item.kind != kind]
        self._markers[:] = [*retained, *markers]
        if emit:
            self.changed.emit()

    def by_kind(self, kind) -> tuple[Marker, ...]:
        kind = marker_kind(kind)
        return tuple(marker for marker in self._markers if marker.kind == kind)

    def by_source(self, source) -> tuple[Marker, ...]:
        source = marker_source(source)
        return tuple(marker for marker in self._markers if marker.source == source)
