from __future__ import annotations

from datetime import datetime

from .models import (
    Marker,
    MarkerKind,
    MarkerSource,
    RecordPosition,
    VideoPosition,
    marker_kind,
    marker_source,
)


def _json_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def marker_to_dict(marker: Marker) -> dict:
    if isinstance(marker.position, VideoPosition):
        position = {
            "domain": "video",
            "time_sec": marker.position.time_sec,
            "frame_index": marker.position.frame_index,
        }
    else:
        position = {
            "domain": "record",
            "time_sec": marker.position.time_sec,
        }
    return {
        "marker_id": marker.marker_id,
        "kind": marker.kind.value,
        "source": marker.source.value,
        "position": position,
        "note": marker.note,
        "payload": {key: _json_value(value) for key, value in marker.payload.items()},
    }


def marker_from_dict(data: dict) -> Marker:
    position_data = data.get("position") or {}
    if position_data.get("domain") == "record":
        position = RecordPosition(float(position_data.get("time_sec", 0.0)))
    else:
        position = VideoPosition(
            float(position_data.get("time_sec", 0.0)),
            int(position_data.get("frame_index", 0)),
        )
    marker_args = {
        "kind": marker_kind(data.get("kind", "")),
        "source": marker_source(data.get("source", MarkerSource.MANUAL.value)),
        "position": position,
        "note": str(data.get("note", "")),
        "payload": dict(data.get("payload") or {}),
    }
    if data.get("marker_id"):
        marker_args["marker_id"] = str(data["marker_id"])
    return Marker(**marker_args)


def marker_from_legacy_ttl(data: dict, source=MarkerSource.TTL_IMPORT) -> Marker:
    record_time_us = int(data.get("record_time", 0))
    payload = {
        key: _json_value(value)
        for key, value in data.items()
        if key not in {"record_time", "source"}
    }
    payload["record_time_us"] = record_time_us
    return Marker(
        kind=MarkerKind.TTL,
        source=source,
        position=RecordPosition(record_time_us / 1_000_000.0),
        payload=payload,
    )
