import json
from zipfile import ZipFile

from .project_format import (
    MAX_MANIFEST_BYTES,
    MAX_STATE_BYTES,
    validate_manifest,
    validate_state,
)


def read_project_json(archive, name, max_bytes):
    """Read one bounded JSON member from a project archive."""
    info = archive.getinfo(name)
    if info.file_size > max_bytes:
        raise ValueError(f"Project {name} is too large.")
    return json.loads(archive.read(name))


def load_project_archive(path):
    """Read and validate project JSON without touching Qt or application state."""
    with ZipFile(path, "r") as archive:
        manifest = read_project_json(
            archive,
            "manifest.json",
            MAX_MANIFEST_BYTES,
        )
        state = read_project_json(archive, "state.json", MAX_STATE_BYTES)

    return {
        "sources": validate_manifest(manifest),
        "state": validate_state(state),
    }
