from types import SimpleNamespace

from webapp.automation.interaction import match_touch_point, randomized_touch_point


def test_randomized_touch_point_returns_center_when_disabled():
    assert randomized_touch_point((640, 360), enabled=False) == (640, 360)


def test_randomized_touch_point_uses_safe_jitter_without_a_hitbox():
    values = iter((634, 366))

    assert randomized_touch_point(
        (640, 360),
        enabled=True,
        randint=lambda _lower, _upper: next(values),
    ) == (634, 366)


def test_match_touch_point_randomizes_inside_the_matched_rectangle():
    match = SimpleNamespace(center=[100, 200], size=[80, 40])
    bounds = []

    def choose_lower(lower, upper):
        bounds.append((lower, upper))
        return lower

    point = match_touch_point(match, enabled=True, randint=choose_lower)

    assert point == (68, 184)
    assert bounds == [(68, 132), (184, 216)]
