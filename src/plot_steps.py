"""Pure plot-stride calculations shared by charts and datasets."""

import math

LFP_POINTS_PER_PIXEL = 2.0


def resolve_visible_plot_step(
    visible_sample_count: int,
    configured_step: int | None,
    plot_width_px: float,
    points_per_pixel: float = LFP_POINTS_PER_PIXEL,
) -> int:
    """Resolve a stride from a sample count and one canvas width."""
    sample_count = max(int(visible_sample_count), 0)
    if configured_step is None:
        target_points = max(int(float(plot_width_px) * points_per_pixel), 1)
        return max(math.ceil(sample_count / target_points), 1)

    configured_step = int(configured_step)
    if configured_step == 0:
        return 1
    if configured_step > 0:
        return configured_step
    raise ValueError("Plot step must be None, 0, or a positive integer.")
