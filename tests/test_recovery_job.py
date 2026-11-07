from io import BytesIO

from PIL import Image, ImageDraw

from webapp.automation.recovery import create_recovery_handler


class _ScriptData:
    def __init__(self, enabled=True):
        self.enabled = enabled

    def get_setting_plan(self, _name):
        return {
            "server": "CH",
            "run": {
                "game_crash_restart": self.enabled,
                "random_time": 0,
                "random_touch": False,
            },
        }


class _Operation:
    def to_dict(self):
        return {"ok": True, "action": "restart_game"}


class _Device:
    def __init__(self, frames=None):
        self.packages = []
        self.frames = iter(frames or [])
        self.taps = []

    def restart_game(self, package_name=None):
        self.packages.append(package_name)
        return _Operation()

    def snapshot(self):
        return next(self.frames)

    def tap(self, x, y):
        self.taps.append((x, y))
        return _Operation()


class _Match:
    def __init__(self, matched=False, center=(0, 0), top_left=(0, 0), size=(0, 0)):
        self.matched = matched
        self.center = list(center)
        self.top_left = list(top_left)
        self.size = list(size)


class _Recognition:
    def match_template(self, screenshot, template_path, **_options):
        matches = {
            (b"title", "crushRestart/CH/menu.png"): _Match(
                True,
                center=(1100, 650),
            ),
            (b"terms", "crushRestart/CH/yhxy.png"): _Match(
                True,
                center=(300, 250),
                top_left=(100, 200),
                size=(400, 100),
            ),
            (b"announcement", "crushRestart/CH/yxgg.png"): _Match(True),
            (b"announcement", "battle/CH/x.png"): _Match(
                True,
                center=(1180, 80),
            ),
            (b"network", "battle/CH/reconnect.png"): _Match(
                True,
                center=(640, 430),
            ),
            (b"resume", "crushRestart/CH/enterBattle.png"): _Match(
                True,
                center=(650, 450),
            ),
        }
        return matches.get((screenshot, template_path), _Match())


class _Context:
    def __init__(self):
        self.events = []

    def checkpoint(self, step, **_options):
        self.events.append(("checkpoint", step))

    def emit(self, event_type, message, **options):
        self.events.append((event_type, message, options))

    def sleep(self, _seconds):
        return None


def test_recovery_restarts_game_and_waits_for_recognized_stage():
    device = _Device()
    stages = iter(("unknown", "prepare"))

    def detect(_context, _payload):
        return {"stage": next(stages)}

    handler = create_recovery_handler(_ScriptData(), device, detect)

    result = handler(
        _Context(),
        {
            "setting_name": "demo",
            "package_name": "com.example.fgo",
            "launch_wait_seconds": 0,
            "poll_interval": 0,
            "timeout_seconds": 1,
        },
    )

    assert result["recovered"] is True
    assert result["stage"] == "prepare"
    assert result["attempts"] == 2
    assert device.packages == ["com.example.fgo"]


def test_recovery_does_not_restart_when_setting_is_disabled():
    device = _Device()
    handler = create_recovery_handler(
        _ScriptData(enabled=False),
        device,
        lambda _context, _payload: {"stage": "assist"},
    )

    result = handler(_Context(), {"setting_name": "demo"})

    assert result == {
        "setting_name": "demo",
        "recovered": False,
        "reason": "game_crash_restart_disabled",
        "stage": "unknown",
    }
    assert device.packages == []


def test_recovery_navigates_startup_pages_before_resuming_battle():
    device = _Device(
        [b"title", b"terms", b"announcement", b"network", b"resume"]
    )
    stages = iter(
        ("unknown", "unknown", "unknown", "unknown", "unknown", "battle")
    )

    handler = create_recovery_handler(
        _ScriptData(),
        device,
        lambda _context, _payload: {"stage": next(stages)},
        _Recognition(),
    )

    result = handler(
        _Context(),
        {
            "setting_name": "demo",
            "launch_wait_seconds": 0,
            "action_wait_seconds": 0,
            "poll_interval": 0,
            "timeout_seconds": 1,
        },
    )

    assert result["recovered"] is True
    assert result["stage"] == "battle"
    assert result["actions"] == [
        "title_start",
        "accept_terms",
        "close_announcement",
        "reconnect",
        "enter_battle",
    ]
    assert device.taps == [
        (640, 360),
        (400, 250),
        (1180, 80),
        (640, 430),
        (650, 450),
    ]


def test_recovery_supports_contour_terms_dialog_tx_fallback_and_wait_menu():
    terms_img = Image.new("RGB", (1280, 720), (20, 20, 30))
    draw = ImageDraw.Draw(terms_img)
    draw.rectangle((150, 50, 1129, 669), fill=(250, 250, 250))
    buf = BytesIO()
    terms_img.save(buf, format="PNG")
    terms_bytes = buf.getvalue()
    seen_rois = []

    class ContourRecognition:
        def match_template(self, screenshot, template_path, **options):
            if screenshot == terms_bytes and template_path == "crushRestart/CH/yhxy.png":
                seen_rois.append((options.get("threshold"), options.get("roi")))
                return _Match(True, center=(400, 300), top_left=(300, 250), size=(200, 100))
            if screenshot == b"announcement-no-x" and template_path == "crushRestart/CH/yxgg.png":
                return _Match(True)
            return _Match()

    device = _Device([terms_bytes, b"announcement-no-x", b"splash"])
    stages = iter(("unknown", "unknown", "unknown", "assist"))
    handler = create_recovery_handler(
        _ScriptData(),
        device,
        lambda _context, _payload: {"stage": next(stages)},
        ContourRecognition(),
    )

    result = handler(
        _Context(),
        {
            "setting_name": "demo",
            "launch_wait_seconds": 0,
            "action_wait_seconds": 0,
            "poll_interval": 0,
            "timeout_seconds": 1,
            "tap_wait_menu": True,
        },
    )

    assert result["recovered"] is True
    assert result["stage"] == "assist"
    assert seen_rois == [(0.7, (150, 50, 980, 620))]
    assert result["actions"] == [
        "accept_terms",
        "close_announcement",
        "wait_menu",
    ]
    assert device.taps == [
        (750, 580),
        (1243, 33),
        (1183, 707),
    ]
