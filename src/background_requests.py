"""Helpers for rejecting stale background results."""

from pathlib import Path

from shiboken6 import isValid


def widget_is_valid(widget) -> bool:
    try:
        return widget is not None and isValid(widget)
    except RuntimeError:
        return False


def source_identity_for_info(info: dict) -> tuple[str, int, int]:
    path = Path(info["path"]).resolve()
    stat = path.stat()
    return str(path), int(stat.st_size), int(stat.st_mtime_ns)


def request_matches(
    result_request_id,
    latest_request_id,
    result_identity,
    current_identity,
) -> bool:
    """Return whether a worker result still belongs to the active request."""

    return (
        result_request_id == latest_request_id
        and result_identity == current_identity
    )
