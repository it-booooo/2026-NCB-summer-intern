def format_led_detection_status(points, threshold, events, stats):
    stats = stats or {}
    interval_count = stats.get("event_count", len(events or []) // 2)
    mode_label = stats.get("mode_label", "Frame delta (ROI mean brightness)")
    status_prefix = (
        "LED scan completed: no events found"
        if stats.get("scan_outcome") == "no_events"
        else "LED detection"
    )
    event_status = (
        f"event pairs={interval_count}"
        if interval_count
        else "no LED event selected"
    )

    status = (
        f"{status_prefix}: {mode_label} | {interval_count} intervals | "
        f"scan frames={stats.get('scan_start_frame', 0)}-{stats.get('scan_end_frame', 0)} | "
        f"coarse step={stats.get('coarse_step', 20)} frames | "
        f"refine window={stats.get('refine_window_sec', 1.0):.1f}s | "
        f"points={stats.get('points_count', len(points or []))} | "
        f"{'multiple' if stats.get('detect_multiple') else 'single'} | "
        f"requested={stats.get('requested_event_count', interval_count)} | "
        f"threshold={stats.get('threshold', threshold):.6f} | "
        f"duration={stats.get('min_duration_sec', 0.6):.1f}-{stats.get('max_duration_sec', 1.5):.1f}s "
        f"target={stats.get('expected_duration_sec', 1.0):.1f}s | "
        f"{event_status}"
    )
    status += format_timing_status(stats)
    status += format_acceleration_status(stats)
    return status


def format_timing_status(stats):
    return (
        f" | scan={stats.get('scan_elapsed_sec', 0.0):.1f}s"
        f" detect={stats.get('detect_elapsed_sec', 0.0):.1f}s"
    )


def format_acceleration_status(stats):
    backend = stats.get("brightness_backend")
    status = ""
    if backend == "opencl":
        status += (
            f" | brightness=OpenCL"
            f" device={stats.get('opencl_device', 'GPU')}"
            f" selected={stats.get('opencl_selected_reason', 'auto')}"
            f" batch={stats.get('opencl_batch_mode', 'fixed')}"
            f" capacity={stats.get('opencl_batch_capacity', 0)}"
            f" batches={stats.get('opencl_batches', 0)}"
            f" max_batch={stats.get('opencl_max_batch_frames', 0)}"
        )
    elif backend == "cpu":
        status += " | brightness=CPU"
        if stats.get("opencl_fallback_reason"):
            status += f" (OpenCL fallback: {stats.get('opencl_fallback_reason')})"
    elif backend == "cache":
        status += " | brightness=cached"

    if stats.get("video_decode_backend"):
        status += f" | decode={stats.get('video_decode_backend')}"
        if (
            stats.get("video_decode_backend") == "opencv_cpu"
            and stats.get("video_decode_fallback_reason")
        ):
            status += " (hw fallback)"

    return status
