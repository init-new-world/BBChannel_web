from types import SimpleNamespace

import pytest

from webapp.automation.assist import create_assist_handler
from webapp.runtime.jobs import JobCancelled


@pytest.mark.parametrize("recommended", [False, True])
@pytest.mark.parametrize("confirm_after", [1, 2, 3, None])
@pytest.mark.parametrize("unconfirmed_class", [1, None, 9, 0])
def test_assist_class_switch_is_confirmed_before_selecting_support(
    recommended, confirm_after, unconfirmed_class,
):
    taps = []
    events = []
    class_taps = 0

    class Device:
        def snapshot(self):
            return b"frame"

        def tap(self, x, y):
            nonlocal class_taps
            taps.append((x, y))
            if y == 128:
                class_taps += 1
            return SimpleNamespace(to_dict=lambda: {"ok": True})

    class Recognizer:
        def match_reconnect(self, *_args):
            return SimpleNamespace(matched=False)

        def match_not_available(self, *_args):
            return SimpleNamespace(matched=False)

        def match_recommended_header(self, *_args):
            return SimpleNamespace(matched=recommended)

        def selected_class_index(self, _screen, **_options):
            if class_taps == 0:
                return 1
            return 5 if confirm_after is not None and class_taps >= confirm_after * 2 else unconfirmed_class

        def recognize(self, *_args, **_options):
            assert confirm_after is not None and class_taps >= confirm_after * 2, "Support selected without class confirmation"
            return {"servant_name": "Support", "candidate_count": 1,
                    "candidates": [{"anchor": [70, 225], "scale": 1, "checks": {}}]}

    script_data = SimpleNamespace(get_setting_plan=lambda _: {
        "server": "CH", "assist": {"mode": "从者礼装", "servant_class": "Caster", "all_not_skip": True},
        "run": {"random_time": 0, "random_touch": False},
    })
    context = SimpleNamespace(checkpoint=lambda *_args, **_options: None, sleep=lambda _: None,
                              emit=lambda *args, **options: events.append((args, options)))
    handler = create_assist_handler(script_data, Device(), Recognizer())
    payload = {"setting_name": "demo", "tap_wait_seconds": 0, "refresh_wait_seconds": 0}

    if confirm_after is None:
        with pytest.raises(RuntimeError, match="Assist class selection was not confirmed"):
            handler(context, payload)
        assert len(taps) == 6
    else:
        result = handler(context, payload)
        assert result["selected"]["tap_point"] == [340, 165]
        assert len(taps) == confirm_after * 2 + 1
        confirmations = [options["data"] for _args, options in events
                         if options.get("data", {}).get("role") == "assist_class_confirmed"]
        assert len(confirmations) == 1
        assert confirmations[0]["attempts"] == confirm_after
    point = (453, 128) if recommended else (430, 128)
    assert taps[:class_taps] == [point] * class_taps


def test_assist_class_retry_recalculates_recommended_tab_layout():
    taps = []

    class Device:
        def snapshot(self):
            return b"frame"

        def tap(self, x, y):
            taps.append((x, y))
            return SimpleNamespace(to_dict=lambda: {"ok": True})

    class Recognizer:
        def match_reconnect(self, *_args):
            return SimpleNamespace(matched=False)

        def match_not_available(self, *_args):
            return SimpleNamespace(matched=False)

        def match_recommended_header(self, *_args):
            return SimpleNamespace(matched=len(taps) < 2)

        def selected_class_index(self, _screen, *, recommended):
            assert recommended == (len(taps) < 2)
            return 5 if len(taps) >= 4 else 1

        def recognize(self, *_args, **_options):
            assert taps == [(453, 128)] * 2 + [(430, 128)] * 2
            return {"servant_name": "Support", "candidate_count": 1,
                    "candidates": [{"anchor": [70, 225], "scale": 1, "checks": {}}]}

    script_data = SimpleNamespace(get_setting_plan=lambda _: {
        "server": "CH", "assist": {"servant_class": "Caster", "all_not_skip": True},
        "run": {"random_time": 0, "random_touch": False},
    })
    context = SimpleNamespace(checkpoint=lambda *_args, **_options: None, sleep=lambda _: None,
                              emit=lambda *_args, **_options: None)

    create_assist_handler(script_data, Device(), Recognizer())(context, {"setting_name": "demo"})

    assert taps == [(453, 128)] * 2 + [(430, 128)] * 2 + [(340, 165)]


def test_assist_class_retry_checks_cancellation_before_more_taps():
    taps = []

    def checkpoint(step, **_options):
        if step == "select_assist_class" and taps:
            raise JobCancelled()

    recognizer = SimpleNamespace(
        match_reconnect=lambda *_args: SimpleNamespace(matched=False),
        match_recommended_header=lambda *_args: SimpleNamespace(matched=False),
        selected_class_index=lambda *_args, **_options: 1,
    )
    device = SimpleNamespace(
        snapshot=lambda: b"frame",
        tap=lambda x, y: (taps.append((x, y)) or SimpleNamespace(to_dict=lambda: {"ok": True})),
    )
    script_data = SimpleNamespace(get_setting_plan=lambda _: {
        "server": "CH", "assist": {"servant_class": "Caster", "all_not_skip": True},
        "run": {"random_time": 0, "random_touch": False},
    })
    context = SimpleNamespace(checkpoint=checkpoint, sleep=lambda _: None,
                              emit=lambda *_args, **_options: None)

    with pytest.raises(JobCancelled):
        create_assist_handler(script_data, device, recognizer)(context, {"setting_name": "demo"})

    assert taps == [(430, 128)] * 2
