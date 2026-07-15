from types import SimpleNamespace

from webapp.automation.network import reconnect_if_present


def test_reconnect_if_present_taps_the_recognized_button():
    taps = []
    events = []
    sleeps = []

    class Recognition:
        def match_template(self, screenshot, template_path, **options):
            assert screenshot == b"frame"
            assert template_path == "battle/CH/reconnect.png"
            assert options["threshold"] == 0.85
            return SimpleNamespace(matched=True, center=(640, 420), size=(120, 60))

    class Device:
        def tap(self, x, y):
            taps.append((x, y))
            return SimpleNamespace(to_dict=lambda: {"ok": True})

    class Context:
        def emit(self, event_type, message, *, data):
            events.append((event_type, message, data))

        def sleep(self, seconds):
            sleeps.append(seconds)

    reconnected = reconnect_if_present(
        Context(),
        Device(),
        Recognition(),
        b"frame",
        "CH",
        action_wait_seconds=0.5,
        random_time=0,
        random_touch=False,
    )

    assert reconnected is True
    assert taps == [(640, 420)]
    assert sleeps == [0.5]
    assert events[0][2]["role"] == "reconnect"


def test_reconnect_if_present_leaves_unmatched_screen_untouched():
    class Recognition:
        def match_template(self, *_args, **_options):
            return SimpleNamespace(matched=False)

    class Device:
        def tap(self, _x, _y):
            raise AssertionError("unexpected tap")

    class Context:
        def emit(self, *_args, **_options):
            raise AssertionError("unexpected event")

        def sleep(self, _seconds):
            raise AssertionError("unexpected sleep")

    assert reconnect_if_present(
        Context(),
        Device(),
        Recognition(),
        b"frame",
        "JP",
        action_wait_seconds=0.5,
        random_time=0,
        random_touch=False,
    ) is False
