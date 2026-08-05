"""Bounded, cancelable preparation of LFP peak display samples."""

from __future__ import annotations

import numpy as np

from .source import CacheBuildCancelled


def merge_peak_display_intervals(
    peak_times,
    *,
    context_sec=1.0,
    maximum_interval_sec=30.0,
):
    """Return overlapping peak neighborhoods as bounded read intervals."""

    radius = max(float(context_sec), 0.0)
    maximum_span = max(float(maximum_interval_sec), 2.0 * radius)
    finite_times = np.asarray(peak_times, dtype=float).reshape(-1)
    finite_times = np.unique(finite_times[np.isfinite(finite_times)])
    if finite_times.size == 0:
        return []

    intervals = []
    current_left = float(finite_times[0] - radius)
    current_right = float(finite_times[0] + radius)
    for peak_time in finite_times[1:]:
        next_left = float(peak_time - radius)
        next_right = float(peak_time + radius)
        merged_right = max(current_right, next_right)
        if next_left <= current_right and merged_right - current_left <= maximum_span:
            current_right = merged_right
            continue
        intervals.append((current_left, current_right))
        current_left, current_right = next_left, next_right
    intervals.append((current_left, current_right))
    return intervals


def allocate_peak_display_points(intervals, point_budget):
    """Distribute a strict point budget in proportion to interval duration."""

    count = len(intervals)
    budget = max(int(point_budget), 0)
    if count == 0:
        return []
    if budget == 0:
        return [0] * count

    durations = np.asarray(
        [max(float(right) - float(left), 0.0) for left, right in intervals],
        dtype=float,
    )
    if not np.any(durations > 0.0):
        durations.fill(1.0)
    exact = durations * (budget / float(np.sum(durations)))
    limits = np.floor(exact).astype(int)
    remaining = budget - int(np.sum(limits))
    if remaining:
        fractions = exact - limits
        order = np.argsort(-fractions, kind="stable")
        limits[order[:remaining]] += 1
    return limits.tolist()


def evenly_sample_signal(times, values, maximum_points):
    """Return matching arrays with no more than ``maximum_points`` samples."""

    sample_times = np.asarray(times, dtype=float).reshape(-1)
    sample_values = np.asarray(values, dtype=float).reshape(-1)
    if sample_times.shape != sample_values.shape:
        raise ValueError("Peak display times and values must match.")
    limit = max(int(maximum_points), 0)
    if limit == 0 or sample_times.size == 0:
        return np.empty(0, dtype=float), np.empty(0, dtype=float)
    if sample_times.size <= limit:
        return sample_times, sample_values
    indices = np.linspace(0, sample_times.size - 1, limit, dtype=np.intp)
    return sample_times[indices], sample_values[indices]


def load_peak_display_samples(
    dataset,
    channel,
    peak_records,
    settings,
    *,
    context_sec=1.0,
    maximum_points=200_000,
    maximum_interval_sec=30.0,
    cancel_event=None,
):
    """Load bounded plot samples while preserving detected peak coordinates."""

    def check_cancel():
        if cancel_event is not None and cancel_event.is_set():
            raise CacheBuildCancelled("LFP peak display was cancelled.")

    check_cancel()
    finite_records = []
    for record_time, value in peak_records:
        try:
            finite_record = float(record_time), float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(finite_record).all():
            finite_records.append(finite_record)
    if not finite_records or maximum_points <= 0:
        return np.empty(0, dtype=float), np.empty(0, dtype=float)

    peak_times = np.asarray([item[0] for item in finite_records], dtype=float)
    peak_values = np.asarray([item[1] for item in finite_records], dtype=float)
    marker_limit = min(peak_times.size, max(int(maximum_points) // 4, 1))
    marker_times, marker_values = evenly_sample_signal(
        peak_times,
        peak_values,
        marker_limit,
    )
    intervals = merge_peak_display_intervals(
        peak_times,
        context_sec=context_sec,
        maximum_interval_sec=maximum_interval_sec,
    )
    waveform_budget = max(int(maximum_points) - marker_times.size, 0)
    interval_limits = allocate_peak_display_points(intervals, waveform_budget)
    time_parts = []
    value_parts = []
    for (left, right), interval_limit in zip(intervals, interval_limits):
        check_cancel()
        if interval_limit <= 0:
            continue
        segment = dataset.segment(
            channel,
            left,
            right,
            settings,
            cancel_event=cancel_event,
        )
        check_cancel()
        sampled_times, sampled_values = evenly_sample_signal(
            segment.record_time_s,
            segment.values,
            interval_limit,
        )
        if sampled_times.size:
            time_parts.append(sampled_times)
            value_parts.append(sampled_values)

    time_parts.append(marker_times)
    value_parts.append(marker_values)
    return np.concatenate(time_parts), np.concatenate(value_parts)
