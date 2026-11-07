from io import BytesIO

from pathlib import Path

from PIL import Image

from webapp.automation.lottery import (
    LOTTERY_DRAW_JOB_KIND,
    LOTTERY_GIFTBOX_RECEIVE_JOB_KIND,
    LOTTERY_GIFTBOX_STACKS_INSPECT_JOB_KIND,
    LOTTERY_INSPECT_JOB_KIND,
    LOTTERY_NAVIGATE_JOB_KIND,
    LOTTERY_RUN_JOB_KIND,
    create_lottery_draw_handler,
    create_lottery_giftbox_receive_handler,
    create_lottery_giftbox_stacks_inspect_handler,
    create_lottery_inspect_handler,
    create_lottery_navigate_handler,
    create_lottery_run_handler,
    register_lottery_draw_job,
    register_lottery_giftbox_receive_job,
    register_lottery_giftbox_stacks_inspect_job,
    register_lottery_inspect_job,
    register_lottery_navigate_job,
    register_lottery_run_job,
)
from webapp.core.models import MatchResult, OperationResult
from webapp.runtime import JobDatabase, JobManager
from webapp.services.lottery import LotteryRecognizer, normalize_giftbox_max_counts
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


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


def test_lottery_navigation_recognizer_prioritizes_specific_pages():
    class Resources:
        def template_index(self, *, prefix, limit):
            assert limit == 100
            paths = {
                "unlimitedPool/CH": [
                    "choose_pay.png",
                    "giftbox_loaded.png",
                    "in_box.png",
                    "pay.png",
                ],
                "expball/CH": ["menu.png", "shop.png"],
            }[prefix]
            return {"entries": [{"path": f"{prefix}/{path}"} for path in paths]}

    class Recognition:
        def match_templates(self, _screenshot, candidates):
            return [
                _match(candidate["template_path"], True, 0.95)
                for candidate in candidates
            ]

    report = LotteryRecognizer(Resources(), Recognition()).recognize_navigation(
        b"screen",
        "CH",
    )

    assert report["state"] == "choose_pay"
    assert report["status"] == "actionable"
    assert [match["name"] for match in report["matches"]] == [
        "choose_pay",
        "pay",
        "giftbox_loaded",
        "giftbox",
        "menu_expanded",
        "menu_available",
    ]


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
        self.swipes = []

    def snapshot(self):
        return b"lottery-screen"

    def tap(self, x, y):
        self.taps.append((x, y))
        return OperationResult(ok=True, action="tap", data={"x": x, "y": y})

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.swipes.append((x1, y1, x2, y2, duration_ms))
        return OperationResult(
            ok=True,
            action="swipe",
            data={"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration_ms": duration_ms},
        )


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


def test_lottery_navigate_returns_from_giftbox_to_draw_page():
    draw_reports = iter(
        (
            _report("unknown", "unknown"),
            _report("unknown", "unknown"),
            _report("unknown", "unknown"),
            _report("unknown", "unknown"),
            _report("unknown", "unknown"),
            _report(
                "draw_10",
                "actionable",
                action="draw",
                action_point=(413, 435),
            ),
        )
    )
    navigation_reports = iter(
        (
            {"state": "giftbox_loaded", "status": "actionable"},
            {"state": "menu_available", "status": "actionable"},
            {"state": "menu_expanded", "status": "actionable"},
            {"state": "pay", "status": "actionable"},
            {"state": "unknown", "status": "unknown"},
        )
    )

    class Recognizer:
        def recognize(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.8
            return next(draw_reports)

        def recognize_navigation(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.8
            return next(navigation_reports)

    device = _Device()
    result = create_lottery_navigate_handler(
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
    assert result["reason"] == "draw_page"
    assert result["actions"] == [
        "close_giftbox",
        "open_menu",
        "open_terminal",
        "open_rewards",
        "open_event",
    ]
    assert device.taps == [
        (105, 43),
        (1183, 650),
        (137, 597),
        (1183, 40),
        (743, 140),
    ]


def test_lottery_navigate_selects_configured_reward_slot():
    draw_reports = iter(
        (
            _report("unknown", "unknown"),
            _report("unknown", "unknown"),
            _report("draw_10", "actionable", action="draw"),
        )
    )
    navigation_reports = iter(
        (
            {"state": "choose_pay", "status": "actionable"},
            {"state": "unknown", "status": "unknown"},
        )
    )

    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return next(draw_reports)

        def recognize_navigation(self, *_args, **_kwargs):
            return next(navigation_reports)

    device = _Device()
    result = create_lottery_navigate_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "pay_slot": 2,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["actions"] == ["select_reward_slot_2", "open_event"]
    assert device.taps == [(640, 527), (743, 140)]


def test_lottery_run_receives_full_giftbox_and_resumes_drawing():
    draw_reports = iter(
        (
            _report("giftbox_full", "blocked", reason="giftbox_full"),
            _report("unknown", "unknown"),
            _report("unknown", "unknown"),
            _report("draw_10", "actionable", action="draw"),
            _report("pool_empty", "complete", reason="pool_empty"),
        )
    )
    giftbox_reports = iter(
        (
            {"state": "giftbox_full", "status": "actionable", "reason": None},
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
                "servant_exp_enabled": True,
                "star_filters": {3: True, 4: True, 5: True},
            },
            {
                "state": "receive_all_on",
                "status": "actionable",
                "reason": None,
                "receive_all_enabled": True,
            },
            {"state": "receive_confirm", "status": "actionable", "reason": None},
            {
                "state": "receive_all_off",
                "status": "complete",
                "reason": "giftbox_empty",
                "receive_all_enabled": False,
            },
        )
    )
    navigation_reports = iter(
        (
            {"state": "pay", "status": "actionable"},
            {"state": "unknown", "status": "unknown"},
        )
    )

    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return next(draw_reports)

        def recognize_giftbox(self, *_args, **_kwargs):
            return next(giftbox_reports)

        def recognize_navigation(self, *_args, **_kwargs):
            return next(navigation_reports)

    device = _Device()
    result = create_lottery_run_handler(
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
    assert result["giftbox_cycles"] == 1
    assert result["draw_count"] == 0
    assert result["receive_batches"] == 1
    assert [stage["stage"] for stage in result["stages"]] == [
        "draw",
        "receive_giftbox",
        "navigate",
        "draw",
    ]
    assert result["stages"][1]["result"]["completed"] is True
    assert result["stages"][2]["result"]["completed"] is True


def test_lottery_run_stops_when_giftbox_cycle_limit_is_reached():
    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return _report("giftbox_full", "blocked", reason="giftbox_full")

    device = _Device()
    result = create_lottery_run_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {"setting_name": "demo", "max_giftbox_cycles": 0},
    )

    assert result["completed"] is False
    assert result["stopped"] is True
    assert result["reason"] == "giftbox_cycle_limit"
    assert result["giftbox_cycles"] == 0
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


def test_lottery_recognizer_recognizes_giftbox_exp_stacks_and_scrollbar():
    project_root = Path(__file__).resolve().parents[1]
    resources = ResourceService(project_root / "assets", project_root / "data")
    recognition = RecognitionService(resources)
    recognizer = LotteryRecognizer(resources, recognition)

    canvas = Image.new("RGB", (1920, 1080), (245, 245, 245))
    df4 = Image.open(project_root / "assets/unlimitedPool/CH/df1.png").convert("RGB")
    df5 = Image.open(project_root / "assets/unlimitedPool/CH/df2.png").convert("RGB")
    d2 = Image.open(project_root / "assets/unlimitedPool/CH/digits/2.png").convert("RGB")
    d5 = Image.open(project_root / "assets/unlimitedPool/CH/digits/5.png").convert("RGB")
    d8 = Image.open(project_root / "assets/unlimitedPool/CH/digits/8.png").convert("RGB")
    unchosen = Image.open(project_root / "assets/unlimitedPool/CH/unchosen.png").convert("RGB")
    chosen = Image.open(project_root / "assets/unlimitedPool/CH/chosen.png").convert("RGB")
    scrollbar = Image.open(project_root / "assets/unlimitedPool/CH/scrollbar.png").convert("RGB")

    # Row 1: 4-star EXP stack x25, unselected (df4 size 100x100 -> center 231, 399)
    canvas.paste(df4, (181, 349))
    canvas.paste(d2, (533, 329))
    canvas.paste(d5, (557, 329))
    canvas.paste(unchosen, (1231, 399))

    # Row 2: 5-star EXP stack x8, already selected (df5 size 100x100 -> center 231, 599)
    canvas.paste(df5, (181, 549))
    canvas.paste(d8, (533, 529))
    canvas.paste(chosen, (1231, 599))

    # Scrollbar near bottom
    canvas.paste(scrollbar, (1390, 995))

    canvas_720 = canvas.resize((1280, 720), Image.Resampling.BILINEAR)
    buf = BytesIO()
    canvas_720.save(buf, format="PNG")

    report = recognizer.recognize_giftbox_stacks(
        buf.getvalue(),
        "CH",
        stars=[3, 4, 5],
        max_counts={4: 30, 5: 10},
    )

    assert report["stack_count"] == 2
    assert report["selectable_count"] == 1
    assert report["scrollbar"]["matched"] is True
    assert report["scrollbar"]["at_bottom"] is True
    assert report["stacks"][0]["star"] == 4
    assert report["stacks"][0]["count"] == 25
    assert report["stacks"][0]["selected"] is False
    assert report["stacks"][0]["should_select"] is True
    assert report["stacks"][0]["touch_point"] == [851, 266]
    assert report["stacks"][1]["star"] == 5
    assert report["stacks"][1]["count"] == 8
    assert report["stacks"][1]["selected"] is True
    assert report["stacks"][1]["should_select"] is False
    assert report["touch_points"] == [[851, 266]]


def test_normalize_giftbox_max_counts_parses_star_limits():
    assert normalize_giftbox_max_counts(None) == {3: None, 4: None, 5: None}
    assert normalize_giftbox_max_counts({"3": 99, 4: 20, "5": None}) == {
        3: 99,
        4: 20,
        5: None,
    }


def test_lottery_giftbox_stacks_inspect_handler_reports_stacks():
    class Recognizer:
        def recognize_giftbox_stacks(
            self,
            screenshot,
            server,
            *,
            stars,
            max_counts,
            threshold,
        ):
            assert screenshot == b"lottery-screen"
            assert server == "CH"
            assert stars == [3, 4]
            assert max_counts == {3: 50, 4: 20, 5: None}
            assert threshold == 0.75
            return {
                "server": "CH",
                "stars": [3, 4],
                "max_counts": {"3": 50, "4": 20, "5": None},
                "scrollbar": {"matched": True, "center": [930, 200], "at_bottom": False},
                "stack_count": 1,
                "selectable_count": 1,
                "stacks": [{"star": 4, "count": 15, "touch_point": [851, 266]}],
                "touch_points": [[851, 266]],
            }

    context = _Context()
    result = create_lottery_giftbox_stacks_inspect_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
    )(
        context,
        {
            "setting_name": "demo",
            "stars": [3, 4],
            "max_stack_counts": {"3": 50, "4": 20},
            "threshold": 0.75,
        },
    )

    assert result["setting_name"] == "demo"
    assert result["stack_count"] == 1
    assert result["touch_points"] == [[851, 266]]
    assert [event[0] for event in context.events] == [
        "checkpoint",
        "lottery_giftbox_stacks",
        "checkpoint",
    ]


def test_lottery_giftbox_receive_filters_stacks_by_max_stack_counts():
    giftbox_reports = iter(
        (
            {
                "state": "giftbox_loaded",
                "status": "actionable",
                "reason": None,
                "receive_all_enabled": True,
            },
            {
                "state": "filter_dialog",
                "status": "actionable",
                "reason": None,
                "servant_exp_enabled": True,
                "star_filters": {3: False, 4: True, 5: False},
            },
            {
                "state": "filter_dialog",
                "status": "actionable",
                "reason": None,
                "servant_exp_enabled": True,
                "star_filters": {3: False, 4: True, 5: False},
            },
            {
                "state": "receive_all_on",
                "status": "actionable",
                "reason": None,
                "receive_all_enabled": True,
            },
            {
                "state": "receive_all_on",
                "status": "actionable",
                "reason": None,
                "receive_all_enabled": True,
            },
            {
                "state": "receive_all_on",
                "status": "actionable",
                "reason": None,
                "receive_all_enabled": True,
            },
        )
    )
    stack_reports = iter(
        (
            {
                "server": "CH",
                "stars": [4],
                "max_counts": {"3": None, "4": 25, "5": None},
                "scrollbar": {"matched": True, "center": [930, 300], "at_bottom": False},
                "stack_count": 2,
                "selectable_count": 1,
                "stacks": [],
                "touch_points": [[851, 266]],
            },
            {
                "server": "CH",
                "stars": [4],
                "max_counts": {"3": None, "4": 25, "5": None},
                "scrollbar": {"matched": True, "center": [930, 680], "at_bottom": True},
                "stack_count": 1,
                "selectable_count": 1,
                "stacks": [],
                "touch_points": [[851, 400]],
            },
        )
    )

    class Recognizer:
        def recognize_giftbox(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.8
            return next(giftbox_reports)

        def recognize_giftbox_stacks(
            self,
            _screenshot,
            server,
            *,
            stars,
            max_counts,
            threshold,
        ):
            assert server == "CH"
            assert stars == [4]
            assert max_counts == {3: None, 4: 25, 5: None}
            assert threshold == 0.7
            return next(stack_reports)

    device = _Device()
    result = create_lottery_giftbox_receive_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "max_stack_counts": {"4": 25},
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "giftbox_filtered_complete"
    assert result["stars"] == [4]
    assert result["selected_stacks"] == 2
    assert result["receive_batches"] == 1
    assert result["actions"] == [
        "open_filter",
        "clear_filters",
        "apply_filter",
        "select_giftbox_stack",
        "scroll_giftbox",
        "select_giftbox_stack",
        "receive_selected",
    ]
    assert device.swipes == [(467, 667, 467, 267, 500)]
    assert device.taps[-1] == (1149, 372)


def test_lottery_run_handles_inventory_full_via_configured_storage_and_resumes():
    draw_reports = iter(
        (
            _report("giftbox_full", "blocked", reason="giftbox_full"),
            _report("unknown", "unknown"),
            _report(
                "draw_10",
                "actionable",
                action="draw",
                action_point=(413, 435),
            ),
            _report("pool_empty", "complete", reason="pool_empty"),
        )
    )
    giftbox_reports = iter(
        (
            {
                "state": "inventory_full",
                "status": "blocked",
                "reason": "inventory_full",
                "receive_all_enabled": None,
            },
        )
    )
    navigation_reports = iter(
        (
            {"state": "menu_available", "status": "actionable"},
        )
    )
    expball_reports = iter(
        (
            {
                "server": "CH",
                "state": "in_store",
                "flow": "storage",
                "status": "observed",
                "reason": None,
                "recommended_action": None,
                "matches": [
                    {"name": "in_store", "center": [310, 120], "size": [120, 60]},
                ],
            },
            {
                "server": "CH",
                "state": "in_store",
                "flow": "storage",
                "status": "observed",
                "reason": None,
                "recommended_action": None,
                "matches": [
                    {"name": "in_store", "center": [310, 120], "size": [120, 60]},
                    {"name": "jd", "center": [1120, 650], "size": [120, 60]},
                ],
            },
            {
                "server": "CH",
                "state": "zxStore",
                "flow": "storage",
                "status": "actionable",
                "reason": None,
                "recommended_action": "execute_storage",
                "matches": [
                    {"name": "zxStore", "center": [980, 620], "size": [120, 60]},
                ],
            },
            {
                "server": "CH",
                "state": "ljbhclose",
                "flow": "confirmation",
                "status": "actionable",
                "reason": None,
                "recommended_action": "close_result",
                "matches": [
                    {"name": "ljbhclose", "center": [640, 610], "size": [120, 60]},
                ],
            },
            {
                "server": "CH",
                "state": "in_store",
                "flow": "storage",
                "status": "observed",
                "reason": None,
                "recommended_action": None,
                "matches": [
                    {"name": "in_store", "center": [310, 120], "size": [120, 60]},
                ],
            },
        )
    )

    class Recognizer:
        def recognize(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.8
            return next(draw_reports)

        def recognize_giftbox(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.8
            return next(giftbox_reports)

        def recognize_navigation(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.8
            return next(navigation_reports)

    class ExpBallRec:
        def recognize(self, *_args, **_kwargs):
            return next(expball_reports)

        def recognize_storage_grid(self, *_args, **_kwargs):
            return {
                "rows": 3,
                "columns": 7,
                "recognized_count": 1,
                "slots": [{"slot": 0, "star": 5, "center": [136, 248]}],
            }

    device = _Device()
    result = create_lottery_run_handler(
        _ScriptData(),
        device,
        Recognizer(),
        expball_recognizer=ExpBallRec(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "overflow_action": "storage",
            "overflow_stars": [4, 5],
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "pool_empty"
    assert result["giftbox_cycles"] == 1
    assert result["overflow_action"] == "storage"
    assert result["overflow_cycles"] == 1
    assert [stage["stage"] for stage in result["stages"]] == [
        "draw",
        "receive_giftbox",
        "overflow_storage",
        "navigate",
        "draw",
    ]
    assert device.taps[0] == (933, 463)


def test_lottery_run_recovers_from_inventory_full_via_servant_enhancement():
    draw_reports = iter(
        (
            _report("giftbox_full", "blocked", reason="giftbox_full"),
            _report("unknown", "unknown"),
            _report(
                "draw_10",
                "actionable",
                action="draw",
                action_point=(413, 435),
            ),
            _report("pool_empty", "complete", reason="pool_empty"),
        )
    )
    giftbox_reports = iter(
        (
            {
                "state": "inventory_full",
                "status": "blocked",
                "reason": "inventory_full",
                "receive_all_enabled": None,
            },
        )
    )
    navigation_reports = iter(
        (
            {"state": "menu_available", "status": "actionable"},
        )
    )

    class Recognizer:
        def recognize(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.8
            return next(draw_reports)

        def recognize_giftbox(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.8
            return next(giftbox_reports)

        def recognize_navigation(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.8
            return next(navigation_reports)

    class ExpBallRec:
        def recognize(self, *_args, **_kwargs):
            return {
                "server": "CH",
                "state": "slot",
                "flow": "enhancement",
                "status": "actionable",
                "reason": None,
                "recommended_action": None,
                "matches": [
                    {"name": "slot", "center": [823, 283], "size": [120, 60]},
                    {"name": "help", "center": [1180, 110], "size": [120, 60]},
                ],
            }

        def recognize_servant_level(self, *_args, **_kwargs):
            return {
                "valid": True,
                "current_level": 100,
                "max_level": 100,
                "is_max_level": True,
            }

    device = _Device()
    result = create_lottery_run_handler(
        _ScriptData(),
        device,
        Recognizer(),
        expball_recognizer=ExpBallRec(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "overflow_action": "servant_enhancement",
            "target_level": 100,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "pool_empty"
    assert result["overflow_action"] == "servant_enhancement"
    assert result["overflow_cycles"] == 1
    assert [stage["stage"] for stage in result["stages"]] == [
        "draw",
        "receive_giftbox",
        "overflow_servant_enhancement",
        "navigate",
        "draw",
    ]
    assert device.taps[0] == (636, 463)


def test_lottery_run_storage_then_sell_falls_back_when_storage_full():
    draw_reports = iter(
        (
            _report("giftbox_full", "blocked", reason="giftbox_full"),
            _report("unknown", "unknown"),
            _report(
                "draw_10",
                "actionable",
                action="draw",
                action_point=(413, 435),
            ),
            _report("pool_empty", "complete", reason="pool_empty"),
        )
    )
    giftbox_reports = iter(
        (
            {
                "state": "inventory_full",
                "status": "blocked",
                "reason": "inventory_full",
                "receive_all_enabled": None,
            },
        )
    )
    navigation_reports = iter(
        (
            {"state": "menu_available", "status": "actionable"},
        )
    )
    expball_reports = iter(
        (
            {
                "server": "CH",
                "state": "storefull",
                "flow": "storage",
                "status": "blocked",
                "reason": "storage_full",
                "recommended_action": None,
                "matches": [{"name": "storefull", "center": [640, 360]}],
            },
            {
                "server": "CH",
                "state": "autoSell",
                "flow": "sell",
                "status": "actionable",
                "reason": None,
                "recommended_action": "open_auto_sell",
                "matches": [{"name": "autoSell", "center": [320, 610]}],
            },
            {
                "server": "CH",
                "state": "autoSell",
                "flow": "sell",
                "status": "actionable",
                "reason": None,
                "recommended_action": "open_auto_sell",
                "matches": [
                    {"name": "autoSell", "center": [320, 610]},
                    {"name": "jd", "center": [1120, 650]},
                ],
            },
            {
                "server": "CH",
                "state": "destroy",
                "flow": "sell",
                "status": "actionable",
                "reason": None,
                "recommended_action": None,
                "matches": [{"name": "destroy", "center": [980, 620]}],
            },
            {
                "server": "CH",
                "state": "ljbhclose",
                "flow": "confirmation",
                "status": "actionable",
                "reason": None,
                "recommended_action": None,
                "matches": [{"name": "ljbhclose", "center": [640, 610]}],
            },
            {
                "server": "CH",
                "state": "autoSell",
                "flow": "sell",
                "status": "actionable",
                "reason": None,
                "recommended_action": "open_auto_sell",
                "matches": [{"name": "autoSell", "center": [320, 610]}],
            },
        )
    )

    class Recognizer:
        def recognize(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.8
            return next(draw_reports)

        def recognize_giftbox(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.8
            return next(giftbox_reports)

        def recognize_navigation(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.8
            return next(navigation_reports)

    class ExpBallRec:
        def recognize_navigation(self, *_args, **_kwargs):
            return {
                "server": "CH",
                "state": "sell_page",
                "flow": "sell",
                "status": "ready",
                "reason": "sell_page",
                "recommended_action": None,
                "matches": [{"name": "ljbh", "center": [1165, 670]}],
            }

        def recognize(self, *_args, **_kwargs):
            return next(expball_reports)

        def recognize_storage_grid(self, *_args, **_kwargs):
            return {
                "rows": 3,
                "columns": 7,
                "recognized_count": 1,
                "slots": [{"slot": 0, "star": 4, "center": [136, 248]}],
            }

    device = _Device()
    result = create_lottery_run_handler(
        _ScriptData(),
        device,
        Recognizer(),
        expball_recognizer=ExpBallRec(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "overflow_action": "storage_then_sell",
            "overflow_stars": [4],
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "pool_empty"
    assert result["overflow_action"] == "storage_then_sell"
    assert result["storage_full"] is True
    assert result["overflow_cycles"] == 1
    assert [stage["stage"] for stage in result["stages"]] == [
        "draw",
        "receive_giftbox",
        "overflow_storage",
        "navigate_overflow_sell",
        "overflow_sell",
        "navigate",
        "draw",
    ]
    assert device.taps[0] == (933, 463)


def test_lottery_giftbox_receive_first_round_count_ignores_empty_page_limit():
    giftbox_reports = iter(
        (
            {
                "state": "giftbox_loaded",
                "status": "actionable",
                "reason": None,
                "receive_all_enabled": True,
            },
            {
                "state": "filter_dialog",
                "status": "actionable",
                "reason": None,
                "servant_exp_enabled": True,
                "star_filters": {3: False, 4: True, 5: False},
            },
            {
                "state": "filter_dialog",
                "status": "actionable",
                "reason": None,
                "servant_exp_enabled": True,
                "star_filters": {3: False, 4: True, 5: False},
            },
            {
                "state": "receive_all_on",
                "status": "actionable",
                "reason": None,
                "receive_all_enabled": True,
            },
            {
                "state": "receive_all_on",
                "status": "actionable",
                "reason": None,
                "receive_all_enabled": True,
            },
            {
                "state": "receive_all_on",
                "status": "actionable",
                "reason": None,
                "receive_all_enabled": True,
            },
        )
    )
    stack_reports = iter(
        (
            {
                "stack_count": 1,
                "selectable_count": 0,
                "touch_points": [],
                "scrollbar": {"matched": True, "at_bottom": False},
            },
            {
                "stack_count": 1,
                "selectable_count": 0,
                "touch_points": [],
                "scrollbar": {"matched": True, "at_bottom": False},
            },
            {
                "stack_count": 1,
                "selectable_count": 0,
                "touch_points": [],
                "scrollbar": {"matched": True, "at_bottom": True},
            },
        )
    )

    class Recognizer:
        def recognize_giftbox(self, *_args, **_kwargs):
            return next(giftbox_reports)

        def recognize_giftbox_stacks(self, *_args, **_kwargs):
            return next(stack_reports)

    device = _Device()
    result = create_lottery_giftbox_receive_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "stars": [4],
            "max_stack_counts": {4: 50},
            "max_empty_pages": 1,
            "first_round_count": True,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["reason"] == "giftbox_filtered_complete"
    assert len(device.swipes) == 2



def test_lottery_jobs_require_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_lottery_inspect_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )
        register_lottery_giftbox_stacks_inspect_job(
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
        register_lottery_navigate_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )
        register_lottery_run_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )

        assert manager.has_kind(LOTTERY_INSPECT_JOB_KIND)
        assert manager.requires_device(LOTTERY_INSPECT_JOB_KIND) is True
        assert manager.has_kind(LOTTERY_GIFTBOX_STACKS_INSPECT_JOB_KIND)
        assert manager.requires_device(LOTTERY_GIFTBOX_STACKS_INSPECT_JOB_KIND) is True
        assert manager.has_kind(LOTTERY_DRAW_JOB_KIND)
        assert manager.requires_device(LOTTERY_DRAW_JOB_KIND) is True
        assert manager.has_kind(LOTTERY_GIFTBOX_RECEIVE_JOB_KIND)
        assert manager.requires_device(LOTTERY_GIFTBOX_RECEIVE_JOB_KIND) is True
        assert manager.has_kind(LOTTERY_NAVIGATE_JOB_KIND)
        assert manager.requires_device(LOTTERY_NAVIGATE_JOB_KIND) is True
        assert manager.has_kind(LOTTERY_RUN_JOB_KIND)
        assert manager.requires_device(LOTTERY_RUN_JOB_KIND) is True
