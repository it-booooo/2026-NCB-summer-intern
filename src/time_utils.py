"""Shared conversions between absolute and origin-relative times."""


def relative_time(time_sec, origin_sec=None):
    """Return ``time_sec`` relative to ``origin_sec`` when an origin is set."""
    value = float(time_sec)
    return value if origin_sec is None else value - float(origin_sec)


def absolute_time(relative_time_sec, origin_sec=None):
    """Convert an origin-relative time back to its absolute time."""
    value = float(relative_time_sec)
    return value if origin_sec is None else value + float(origin_sec)


def record_time_parts(record_time_us):
    """Split a microsecond record time into display-friendly components."""
    hours, remainder = divmod(int(record_time_us), 3_600_000_000)
    minutes, remainder = divmod(remainder, 60_000_000)
    seconds, microseconds = divmod(remainder, 1_000_000)
    return {
        "record_hours": hours,
        "record_minutes": minutes,
        "record_seconds": seconds,
        "record_microseconds": microseconds,
    }
