from io import BytesIO

from PIL import Image

from webapp.automation.lottery import (
    LOTTERY_DRAW_JOB_KIND,
    LOTTERY_GIFTBOX_RECEIVE_JOB_KIND,
    LOTTERY_INSPECT_JOB_KIND,
    create_lottery_draw_handler,
    create_lottery_giftbox_receive_handler,
    create_lottery_inspect_handler,
    register_lottery_draw_job,
    register_lottery_giftbox_receive_job,
    register_lottery_inspect_job,
)
from webapp.core.models import MatchResult, OperationResult
from webapp.runtime import JobDatabase, JobManager
from webapp.services.lottery import LotteryRecognizer


def _match(template_path: str, matched: bool, confidence: float) -> MatchResult:
    return MatchResult(
        template_path=template_path,
        matched=matched,
        confidence=confidence,
        threshold=0.8,
        top_left=[100, 200],
        size=[80, 40],
        center=[140, 220],
    )


class _Resources:
    def template_index(self, *, prefix, limit):
        assert prefix == "unlimitedPool/CH"
        assert limit == 100
        return {
            "entries": [
                {"path": "unlimitedPool/CH/ge.png"},
                {"path": "unlimitedPool/CH/giftbox_full.png"},
                {"path": "unlimitedPool/CH/pool_empty.png"},
            ]
        }


def test_lottery_recognizer_prioritizes_giftbox_full_over_draw_state():
    class Recognition:
        def __init__(self):
            self.candidates = None

        def match_templates(self, _screenshot, candidates):
            self.candidates = candidates
            return [
                _match(candidate["template_path"], True, 0.9)
                for candidate in candidates
            ]

    recognition = Recognition()
    report = LotteryRecognizer(_Resources(), recognition).recognize(
        b"screen",
        "ch",
    )

    assert report["state"] == "giftbox_full"
    assert report["status"] == "blocked"
    assert report["reason"] == "giftbox_full"
    assert report["recommended_action"] is None
    assert any(
        candidate.get("roi") == (407, 413, 100, 67)
        for candidate in recognition.candidates
        if candidate["template_path"] == "unlimitedPool/CH/ge.png"
    )


def test_lottery_giftbox_recognizer_reports_filter_toggle_states():
    class Resources:
        def template_index(self, *, prefix, limit):
            assert prefix == "unlimitedPool/CH"
            assert limit == 100
            return {
                "entries": [
                    {"path": f"{prefix}/decide.png"},
                    {"path": f"{prefix}/servant_off.png"},
                    {"path": f"{prefix}/servant_on.png"},
                ]
            }

    class Recognition:
        def match_templates(self, _screenshot, candidates):
            matched = {
                "unlimitedPool/CH/decide.png",
                "unlimitedPool/CH/servant_on.png",
            }
            return [
                _match(
                    candidate["template_path"],
                    candidate["template_path"] in matched,
                    0.95 if candidate["template_path"] in matched else 0.2,
                )
                for candidate in candidates
            ]

    class Recognizer(LotteryRecognizer):
        def _star_filter_states(self, _screenshot):
            return {3: True, 4: False, 5: True}

    report = Recognizer(Resources(), Recognition()).recognize_giftbox(
        b"screen",
        "CH",
    )

    assert report["state"] == "filter_dialog"
    assert report["status"] == "actionable"
    assert report["servant_exp_enabled"] is True
    assert report["star_filters"] == {3: True, 4: False, 5: True}
    assert report["receive_all_enabled"] is None


def test_lottery_giftbox_recognizer_reads_star_filter_colors():
    screenshot = Image.new("RGB", (1280, 720), (18, 24, 32))
    states = {3: True, 4: False, 5: True}
    rois = {
        3: (580, 467, 613, 500),
        4: (393, 467, 426, 500),
        5: (205, 467, 239, 500),
    }
    for star, roi in rois.items():
        color = (61, 112, 196) if states[star] else (215, 215, 215)
        screenshot.paste(color, roi)
    encoded = BytesIO()
    screenshot.save(encoded, format="PNG")

    recognizer = LotteryRecognizer(object(), object())

    assert recognizer._star_filter_states(encoded.getvalue()) == states


class _ScriptData:
    def get_setting_plan(self, name):
        assert name == "demo"
        return {
            "server": "CH",
            "run": {"random_touch": False, "random_time": 0},
        }


class _Device:
    def __init__(self):
        self.taps = []

    def snapshot(self):
        return b"lottery-screen"

    def tap(self, x, y):
        self.taps.append((x, y))
        return OperationResult(ok=True, action="tap", data={"x": x, "y": y})


class _Context:
    def __init__(self):
        self.events = []
        self.sleeps = []

    def checkpoint(self, step, **options):
        self.events.append(("checkpoint", step, options))

    def emit(self, event_type, message, **options):
        self.events.append((event_type, message, options))

    def sleep(self, seconds):
        self.sleeps.append(seconds)


def _report(
    state,
    status,
    *,
    action=None,
    reason=None,
    action_point=None,
):
    return {
        "server": "CH",
        "state": state,
        "status": status,
        "reason": reason,
        "recommended_action": action,
        "action_point": list(action_point) if action_point else None,
        "matches": [],
    }


def test_lottery_inspect_handler_reports_current_state():
    class Recognizer:
        def recognize(self, screenshot, server, *, threshold):
            assert screenshot == b"lottery-screen"
            assert server == "CH"
            assert threshold == 0.9
            return _report(
                "draw_10",
                "actionable",
                action="draw",
                action_point=(413, 435),
            )

    context = _Context()
    result = create_lottery_inspect_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
    )(context, {"setting_name": "demo", "threshold": 0.9})

    assert result["state"] == "draw_10"
    assert result["recommended_action"] == "draw"
    assert [event[0] for event in context.events] == [
        "checkpoint",
        "lottery_state",
        "checkpoint",
    ]


def test_lottery_draw_runs_until_pool_is_empty():
    reports = iter(
        (
            _report(
                "draw_10",
                "actionable",
                action="draw",
                action_point=(413, 435),
            ),
            _report(
                "result_close",
                "actionable",
                action="close_result",
                action_point=(1180, 40),
            ),
            _report("pool_empty", "complete", reason="pool_empty"),
        )
    )

    class Recognizer:
        def recognize(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.8
            return next(reports)

    device = _Device()
    result = create_lottery_draw_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "pool_empty"
    assert result["draw_count"] == 1
    assert result["actions"] == ["draw", "close_result"]
    assert device.taps == [(413, 435), (1180, 40)]


def test_lottery_draw_stops_when_giftbox_is_full():
    class Recognizer:
        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.8
            return _report("giftbox_full", "blocked", reason="giftbox_full")

    device = _Device()
    result = create_lottery_draw_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(_Context(), {"setting_name": "demo"})

    assert result["completed"] is False
    assert result["stopped"] is True
    assert result["reason"] == "giftbox_full"
    assert result["actions"] == []
    assert device.taps == []


def test_lottery_giftbox_receive_configures_filters_and_receives_batches():
    reports = iter(
        (
            {
                "state": "giftbox_full",
                "status": "actionable",
                "reason": None,
            },
            {
                "state": "giftbox_loaded",
                "status": "actionable",
                "reason": None,
                "receive_all_enabled": None,
            },
            {
                "state": "filter_dialog",
                "status": "actionable",
                "reason": None,
                "servant_exp_enabled": True,
                "star_filters": {3: True, 4: True, 5: True},
            },
            {
                "state": "filter_dialog",
                "status": "actionable",
                "reason": None,
                "servant_exp_enabled": False,
                "star_filters": {3: False, 4: False, 5: False},
            },
            {
                "state": "filter_dialog",
                "status": "actionable",
                "reason": None,
                "servant_exp_enabled": True,
                "star_filters": {3: False, 4: False, 5: False},
            },
            {
                "state": "filter_dialog",
                "status": "actionable",
                "reason": None,
                "servant_exp_enabled": True,
                "star_filters": {3: True, 4: False, 5: False},
            },
            {
                "state": "filter_dialog",
                "status": "actionable",
                "reason": None,
                "servant_exp_enabled": True,
                "star_filters": {3: True, 4: True, 5: False},
            },
            {
                "state": "receive_all_on",
                "status": "actionable",
                "reason": None,
                "receive_all_enabled": True,
            },
            {
                "state": "receive_confirm",
                "status": "actionable",
                "reason": None,
            },
            {
                "state": "receive_all_off",
                "status": "complete",
                "reason": "giftbox_empty",
                "receive_all_enabled": False,
            },
        )
    )

    class Recognizer:
        def recognize_giftbox(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.8
            return next(reports)

    device = _Device()
    result = create_lottery_giftbox_receive_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "stars": [3, 4],
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "giftbox_empty"
    assert result["receive_batches"] == 1
    assert result["stars"] == [3, 4]
    assert result["actions"] == [
        "open_giftbox",
        "open_filter",
        "clear_filters",
        "enable_servant_exp",
        "toggle_star_3",
        "toggle_star_4",
        "apply_filter",
        "receive_all",
        "confirm_receive",
    ]
    assert device.taps == [
        (860, 565),
        (1157, 128),
        (225, 637),
        (535, 250),
        (640, 483),
        (453, 483),
        (1060, 635),
        (1150, 222),
        (837, 563),
    ]


def test_lottery_jobs_require_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_lottery_inspect_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )
        register_lottery_draw_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )
        register_lottery_giftbox_receive_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )

        assert manager.has_kind(LOTTERY_INSPECT_JOB_KIND)
        assert manager.requires_device(LOTTERY_INSPECT_JOB_KIND) is True
        assert manager.has_kind(LOTTERY_DRAW_JOB_KIND)
        assert manager.requires_device(LOTTERY_DRAW_JOB_KIND) is True
        assert manager.has_kind(LOTTERY_GIFTBOX_RECEIVE_JOB_KIND)
        assert manager.requires_device(LOTTERY_GIFTBOX_RECEIVE_JOB_KIND) is True
