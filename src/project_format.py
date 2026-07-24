"""Validation and file identity rules for path-only ``.pigproj`` files."""

import hashlib
import math
import string
from pathlib import Path


PROJECT_FORMAT = "pig-analysis-project"
PROJECT_VERSION = 3
ALLOWED_SOURCE_TYPES = frozenset({"video", "lfp", "axis", "ttl"})
MAX_MANIFEST_BYTES = 1 * 1024 * 1024
MAX_STATE_BYTES = 256 * 1024 * 1024
MAX_EVENTS = 1_000_000
MAX_TEXT_LENGTH = 100_000
FINGERPRINT_CHUNK_BYTES = 1024 * 1024


def file_fingerprint(path):
    """Return a fast content identity using file size and sampled SHA-256."""
    file_path = Path(path)
    size = file_path.stat().st_size
    digest = hashlib.sha256()
    digest.update(str(size).encode("ascii"))
    with file_path.open("rb") as source:
        offsets = {0}
        if size > FINGERPRINT_CHUNK_BYTES:
            offsets.add(max((size - FINGERPRINT_CHUNK_BYTES) // 2, 0))
            offsets.add(max(size - FINGERPRINT_CHUNK_BYTES, 0))
        for offset in sorted(offsets):
            source.seek(offset)
            digest.update(offset.to_bytes(8, "little"))
            digest.update(source.read(FINGERPRINT_CHUNK_BYTES))
    return {
        "size": size,
        "sample_sha256": digest.hexdigest(),
    }


def validate_manifest(manifest):
    """Validate the current path-only project manifest."""
    if not isinstance(manifest, dict):
        raise ValueError("Project manifest must be a JSON object.")
    if manifest.get("format") != PROJECT_FORMAT:
        raise ValueError("This is not a Pig Analysis Project file.")
    if manifest.get("version") != PROJECT_VERSION:
        raise ValueError(
            f"Unsupported project version: {manifest.get('version')}. "
            f"Only path-only version {PROJECT_VERSION} projects are supported."
        )
    sources = manifest.get("sources", {})
    if not isinstance(sources, dict):
        raise ValueError("Project sources must be a JSON object.")
    unknown = set(sources) - ALLOWED_SOURCE_TYPES
    if unknown:
        raise ValueError(f"Unsupported project source type: {sorted(unknown)[0]}")
    for source_type, source in sources.items():
        if not isinstance(source, dict):
            raise ValueError(f"Project {source_type} source is invalid.")
        unknown_fields = set(source) - {"external_path", "filename", "fingerprint"}
        if unknown_fields:
            raise ValueError(f"Project {source_type} source contains unsupported fields.")
        path = source.get("external_path")
        fingerprint = source.get("fingerprint")
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"Project {source_type} path is invalid.")
        if not isinstance(fingerprint, dict):
            raise ValueError(f"Project {source_type} fingerprint is missing.")
        size = fingerprint.get("size")
        digest = fingerprint.get("sample_sha256")
        if not isinstance(size, int) or size < 0:
            raise ValueError(f"Project {source_type} size is invalid.")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in string.hexdigits for character in digest)
        ):
            raise ValueError(f"Project {source_type} fingerprint is invalid.")
    return sources


def validate_state(state):
    """Validate persisted values before they are applied to AppState or widgets."""
    if not isinstance(state, dict):
        raise ValueError("Project state must be a JSON object.")
    for section in ("video", "data", "analysis", "sync", "led"):
        if not isinstance(state.get(section, {}), dict):
            raise ValueError(f"Project {section} state is invalid.")

    video = state.get("video", {})
    frame = video.get("current_frame", 0)
    rotation = video.get("rotation_degrees", 0)
    if not isinstance(frame, int) or isinstance(frame, bool) or frame < 0:
        raise ValueError("Project current frame is invalid.")
    if rotation not in {0, 90, 180, 270}:
        raise ValueError("Project video rotation must be 0, 90, 180, or 270 degrees.")

    data = state.get("data", {})
    for name in ("lfp_step", "axis_step", "selected_lfp_channel"):
        value = data.get(name)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise ValueError(f"Project {name} is invalid.")
    line_noise = data.get("line_noise_hz", 60.0)
    if not _finite_number(line_noise) or float(line_noise) <= 0:
        raise ValueError("Project line noise frequency is invalid.")
    timeline = data.get("timeline_xlim")
    if timeline is not None and (
        not isinstance(timeline, (list, tuple))
        or len(timeline) != 2
        or not all(_finite_number(value) for value in timeline)
        or float(timeline[0]) >= float(timeline[1])
    ):
        raise ValueError("Project timeline range is invalid.")
    if not isinstance(data.get("lfp_filter_settings", {}), dict):
        raise ValueError("Project LFP filter settings are invalid.")

    analysis = state.get("analysis", {})
    for name in ("lfp_peak_height_sigma", "lfp_peak_prominence_sigma"):
        value = analysis.get(name)
        if value is not None and (
            not _finite_number(value) or float(value) < 0
        ):
            raise ValueError(f"Project analysis setting {name} is invalid.")
    min_distance = analysis.get("lfp_peak_min_distance_sec")
    if min_distance is not None and (
        not _finite_number(min_distance) or float(min_distance) <= 0
    ):
        raise ValueError(
            "Project analysis setting lfp_peak_min_distance_sec is invalid."
        )

    markers = state.get("markers", [])
    if not isinstance(markers, list) or len(markers) > MAX_EVENTS:
        raise ValueError("Project marker list is invalid or too large.")
    for marker in markers:
        _validate_marker(marker)

    led = state.get("led", {})
    roi = led.get("roi")
    if roi is not None and (
        not isinstance(roi, (list, tuple))
        or len(roi) != 4
        or any(not isinstance(value, int) or isinstance(value, bool) for value in roi)
        or roi[0] < 0
        or roi[1] < 0
        or roi[2] <= 0
        or roi[3] <= 0
    ):
        raise ValueError("Project LED ROI is invalid.")
    for name in ("analysis_points", "brightness_cache"):
        value = led.get(name)
        if value is not None and (
            not isinstance(value, list) or len(value) > MAX_EVENTS
        ):
            raise ValueError(f"Project LED {name} is invalid or too large.")
    return state


def validate_video_bounds(state, metadata):
    """Validate frame and ROI values against the prepared video metadata."""
    if metadata is None:
        return
    frame = state.get("video", {}).get("current_frame", 0)
    if metadata.total_frames <= 0 or frame >= metadata.total_frames:
        raise ValueError("Project current frame is outside the source video.")
    for marker in state.get("markers", []):
        position = marker.get("position")
        if position and position.get("domain") == "video":
            if position.get("frame_index", 0) >= metadata.total_frames:
                raise ValueError("A project video marker frame is outside the source video.")
            if float(position.get("time_sec", 0.0)) > metadata.duration_sec:
                raise ValueError("A project video marker time is outside the source video.")
    roi = state.get("led", {}).get("roi")
    if roi is None:
        return
    x, y, width, height = roi
    rotation = state.get("video", {}).get("rotation_degrees", 0)
    frame_width, frame_height = metadata.width, metadata.height
    if rotation in {90, 270}:
        frame_width, frame_height = frame_height, frame_width
    if x + width > frame_width or y + height > frame_height:
        raise ValueError("Project LED ROI is outside the source video.")


def _finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _validate_marker(marker):
    if not isinstance(marker, dict):
        raise ValueError("Project marker is invalid.")
    position = marker.get("position")
    if not isinstance(position, dict) or position.get("domain") not in {"video", "record"}:
        raise ValueError("Project marker position is invalid.")
    if not _finite_number(position.get("time_sec")) or position["time_sec"] < 0:
        raise ValueError("Project marker time is invalid.")
    if position["domain"] == "video":
        frame = position.get("frame_index")
        if not isinstance(frame, int) or isinstance(frame, bool) or frame < 0:
            raise ValueError("Project marker frame is invalid.")
    for name in ("marker_id", "kind", "source", "note"):
        value = marker.get(name, "")
        if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH:
            raise ValueError(f"Project marker {name} is invalid.")
    if not isinstance(marker.get("payload", {}), dict):
        raise ValueError("Project marker payload is invalid.")
