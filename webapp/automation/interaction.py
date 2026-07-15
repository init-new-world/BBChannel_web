from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from typing import Any


RandInt = Callable[[int, int], int]
BASE_WIDTH = 1280
BASE_HEIGHT = 720


def randomized_touch_point(
    center: Sequence[int | float],
    *,
    enabled: bool,
    size: Sequence[int | float] | None = None,
    radius: int = 8,
    randint: RandInt | None = None,
) -> tuple[int, int]:
    x = round(float(center[0]))
    y = round(float(center[1]))
    if not enabled:
        return x, y

    choose = randint or random.randint
    if size is None:
        x_bounds = (x - radius, x + radius)
        y_bounds = (y - radius, y + radius)
    else:
        width = max(round(float(size[0])), 1)
        height = max(round(float(size[1])), 1)
        x_inset = max(width // 10, 1)
        y_inset = max(height // 10, 1)
        x_bounds = (x - width // 2 + x_inset, x + width // 2 - x_inset)
        y_bounds = (y - height // 2 + y_inset, y + height // 2 - y_inset)

    lower_x, upper_x = _screen_bounds(*x_bounds, maximum=BASE_WIDTH - 1)
    lower_y, upper_y = _screen_bounds(*y_bounds, maximum=BASE_HEIGHT - 1)
    return choose(lower_x, upper_x), choose(lower_y, upper_y)


def match_touch_point(
    match: Any,
    *,
    enabled: bool,
    randint: RandInt | None = None,
) -> tuple[int, int]:
    return randomized_touch_point(
        match.center,
        enabled=enabled,
        size=getattr(match, "size", None),
        randint=randint,
    )


def _screen_bounds(lower: int, upper: int, *, maximum: int) -> tuple[int, int]:
    bounded_lower = min(max(lower, 0), maximum)
    bounded_upper = min(max(upper, bounded_lower), maximum)
    return bounded_lower, bounded_upper
