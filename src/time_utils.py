"""Shared conversions between absolute and origin-relative times."""


def relative_time(time_sec, origin_sec=None):
    """Return ``time_sec`` relative to ``origin_sec`` when an origin is set."""
    value = float(time_sec)
    return value if origin_sec is None else value - float(origin_sec)


def absolute_time(relative_time_sec, origin_sec=None):
    """Convert an origin-relative time back to its absolute time."""
    value = float(relative_time_sec)
    return value if origin_sec is None else value + float(origin_sec)
