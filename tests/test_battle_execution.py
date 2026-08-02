import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.test_client import create_test_client

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from webapp.app import create_app
from webapp.automation.battle import (
    _TapTiming,
    _apply_servant_exchange,
    _apply_servant_replacements,
    _execute_hakuno_reroll,
    _execute_skill_action,
    _execute_strategy_step,
    _evaluate_card_condition,
    _execution_options,
    _execute_steps,
    _frontline_servants,
    _matches_hakuno_needs,
    _wait_for_battle_ready,
    _wait_for_command_cards,
    _wait_for_battle_transition,
    register_battle_jobs,
)
from webapp.devices.coordinates import FrameNormalizer
from webapp.devices.replay import ReplayBackend
from webapp.runtime import JobDatabase, JobManager, JobStatus
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog
from webapp.services.cards import CommandCardRecognizer
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService


def _write_image(path: Path, image) -> None:
    assert cv2.imwrite(str(path), image)


def test_servant_replacements_update_slots_from_same_pre_turn_snapshot():
    servants = [
        {"slot": slot, "name": name, "sn": str(100 + slot)}
        for slot, name in enumerate(("One", "Two", "Three", "Four", "Five", "Six"))
    ]

    _apply_servant_replacements(servants, {"1": 4, "4": None})

    assert [servant["name"] if servant else None for servant in servants] == [
        "Four",
        "Two",
        "Three",
        None,
        "Five",
        "Six",
    ]
    assert [servant["battle_position"] for servant in _frontline_servants(servants)] == [
        1,
        2,
        3,
    ]


def test_servant_exchange_swaps_runtime_positions_immediately():
    servants = [
        {"slot": slot, "name": name}
        for slot, name in enumerate(("One", "Two", "Three", "Four", "Five", "Six"))
    ]

    _apply_servant_exchange(servants, [1, 4])

    assert [servant["name"] for servant in servants] == [
        "Four",
        "Two",
        "Three",
        "One",
        "Five",
        "Six",
    ]


def test_hakuno_card_needs_match_unordered_alternatives_with_duplicate_counts():
    cards = [
        {"code": "1B"},
        {"code": "2A"},
        {"code": "1B"},
        {"code": "3Q"},
        {"code": None},
    ]

    assert _matches_hakuno_needs(cards, [["2B"], ["2A", "1B", "1B"]]) is True
    assert _matches_hakuno_needs(cards, [["1B", "1B", "1B"]]) is False


def test_execute_steps_adds_independent_configured_random_delays(monkeypatch):
    taps = []
    sleeps = []

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def tap(self, x, y):
            taps.append((x, y))
            return Operation()

    class Context:
        def emit(self, *_args, **_kwargs):
            pass

        def sleep(self, seconds):
            sleeps.append(seconds)

    random_values = iter((0.25, 0.75))
    monkeypatch.setattr(
        "webapp.automation.interaction.random.random",
        lambda: next(random_values),
    )
    touch_values = iter((0, 8, 0, 3))
    monkeypatch.setattr(
        "webapp.automation.interaction.random.randint",
        lambda _lower, _upper: next(touch_values),
    )

    _execute_steps(
        Context(),
        Device(),
        [
            {"type": "tap", "role": "first", "x": 1, "y": 2},
            {"type": "tap", "role": "second", "x": 3, "y": 4},
        ],
        0.1,
        random_time=0.4,
        random_touch=True,
    )

    assert taps == [(0, 8), (0, 3)]
    assert sleeps == pytest.approx([0.2, 0.4])


@pytest.mark.parametrize(
    ("speedup_skills", "expected_taps"),
    [
        (True, [(70, 590), (1217, 440), (1217, 440)]),
        (False, [(70, 590)]),
    ],
)
def test_execute_skill_action_honors_animation_speedup_setting(
    speedup_skills: bool,
    expected_taps: list[tuple[int, int]],
):
    taps = []

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def tap(self, x, y):
            taps.append((x, y))
            return Operation()

    class Context:
        def emit(self, *_args, **_options):
            pass

        def sleep(self, _seconds):
            pass

    tap_count = _execute_skill_action(
        Context(),
        Device(),
        {
            "source": {"type": "skill", "command": 1},
            "steps": [{"type": "tap", "role": "servant_skill_1", "x": 70, "y": 590}],
        },
        0,
        speedup_skills=speedup_skills,
    )

    assert tap_count == len(expected_taps)
    assert taps == expected_taps


def test_wait_for_battle_ready_recovers_network_prompt():
    state = {"frame": "network"}
    taps = []

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def snapshot(self):
            return state["frame"].encode()

        def tap(self, x, y):
            taps.append((x, y))
            state["frame"] = "battle"
            return Operation()

    class Match:
        confidence = 1.0
        center = (640, 420)
        size = (120, 60)

        def __init__(self, matched):
            self.matched = matched

    class Recognition:
        def match_template(self, screenshot, template_path, *_args, **_options):
            frame = screenshot.decode()
            if template_path.endswith("/reconnect.png"):
                return Match(frame == "network")
            return Match(frame == "battle")

    class Context:
        def emit(self, *_args, **_options):
            pass

        def sleep(self, _seconds):
            pass

    _wait_for_battle_ready(
        Context(),
        Device(),
        Recognition(),
        "battle/CH/attack.png",
        0.85,
        1,
        0,
        reconnect_timing=_TapTiming(0),
    )

    assert taps == [(640, 420)]


def test_wait_for_battle_ready_matches_scaled_attack_button():
    class Device:
        def snapshot(self):
            return b"battle"

    class Match:
        matched = True
        confidence = 0.99

    class Recognition:
        def match_template(self, _screenshot, _template_path, _threshold, **options):
            assert options["scales"] == (1.0, 0.75, 2 / 3, 0.5)
            return Match()

    class Context:
        def emit(self, *_args, **_options):
            pass

        def sleep(self, _seconds):
            pass

    _wait_for_battle_ready(
        Context(),
        Device(),
        Recognition(),
        "battle/CH/attack.png",
        0.85,
        1,
        0,
    )


def test_execution_options_allow_long_np_transitions_by_default():
    _threshold, timeout_seconds, _poll_interval, tap_interval = _execution_options({})

    assert timeout_seconds == 120.0
    assert tap_interval == 0.1


def test_wait_for_command_cards_settles_and_returns_fresh_screenshot():
    frames = iter((b"first", b"fresh"))
    snapshots = []
    sleeps = []

    class Device:
        def snapshot(self):
            screenshot = next(frames)
            snapshots.append(screenshot)
            return screenshot

    class Match:
        matched = True
        confidence = 1.0

        def to_dict(self):
            return {"matched": True, "confidence": 1.0}

    class Recognition:
        def match_templates(self, _screenshot, candidates):
            return [Match() for _ in candidates]

    class Context:
        def emit(self, *_args, **_options):
            pass

        def sleep(self, seconds):
            sleeps.append(seconds)

    screenshot = _wait_for_command_cards(
        Context(),
        Device(),
        Recognition(),
        ["battle/CH/Arts.png"],
        0.75,
        1.0,
        0.01,
        settle_seconds=0.6,
    )

    assert screenshot == b"fresh"
    assert snapshots == [b"first", b"fresh"]
    assert sleeps == [0.6]


def test_wait_for_command_cards_rejects_low_confidence_transition_frame():
    frames = iter((b"transition", b"ready"))
    sleeps = []

    class Device:
        def snapshot(self):
            return next(frames)

    class Match:
        def __init__(self, confidence):
            self.confidence = confidence
            self.matched = confidence >= 0.75

        def to_dict(self):
            return {"matched": self.matched, "confidence": self.confidence}

    class Recognition:
        def match_templates(self, screenshot, candidates):
            assert all(
                candidate["scales"] == (1.0, 0.75, 2 / 3, 0.5)
                for candidate in candidates
            )
            confidence = 0.80 if screenshot == b"transition" else 0.99
            return [Match(confidence)]

    class Context:
        def emit(self, *_args, **_options):
            pass

        def sleep(self, seconds):
            sleeps.append(seconds)

    screenshot = _wait_for_command_cards(
        Context(),
        Device(),
        Recognition(),
        ["battle/CH/Arts.png"],
        0.75,
        1.0,
        0.01,
    )

    assert screenshot == b"ready"
    assert sleeps == [0.01]


@pytest.mark.parametrize(
    ("matched_paths", "expected"),
    [
        (
            {"battle/CH/attack.png", "battle/CH/phase_2.png"},
            {"state": "battle", "round": 2},
        ),
        (
            {"battle/CH/attack.png", "battle/CH/phase_2.png", "battle/CH/battleFinish.png"},
            {"state": "finished", "round": None},
        ),
    ],
)
def test_wait_for_battle_transition_recognizes_round_or_finish(
    matched_paths: set[str],
    expected: dict,
):
    events = []

    class Device:
        def snapshot(self):
            return b"frame"

    class Match:
        confidence = 1.0

        def __init__(self, template_path, matched):
            self.template_path = template_path
            self.matched = matched

        def to_dict(self):
            return {"template_path": self.template_path, "matched": self.matched}

    class Recognition:
        def match_templates(self, _screenshot, candidates):
            return [
                Match(candidate["template_path"], candidate["template_path"] in matched_paths)
                for candidate in candidates
            ]

    class Context:
        def emit(self, event_type, message, *, data):
            events.append((event_type, message, data))

        def sleep(self, _seconds):
            pass

    result = _wait_for_battle_transition(
        Context(),
        Device(),
        Recognition(),
        "CH",
        0.75,
        1.0,
        0.01,
    )

    assert result == expected
    assert events[-1][0] == "battle_transition"


def test_hakuno_reroll_casts_skill_until_card_need_matches():
    taps = []
    events = []

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def snapshot(self):
            return b"frame"

        def tap(self, x, y):
            taps.append((x, y))
            return Operation()

    class Match:
        matched = True
        confidence = 1.0

        def to_dict(self):
            return {"matched": True, "confidence": 1.0}

    class Recognition:
        def match_template(self, _screenshot, template_path, *_args, **_options):
            if template_path.endswith("/reconnect.png"):
                return SimpleNamespace(matched=False)
            return Match()

        def match_templates(self, _screenshot, candidates):
            return [Match() for _ in candidates]

    class Cards:
        calls = 0

        def recognize(self, _screenshot, _server, _servants, *, threshold):
            assert threshold == 0.75
            self.calls += 1
            codes = ["1B", "3Q"] if self.calls == 1 else ["1B", "2A"]
            return {
                "complete": True,
                "cards": [{"code": code} for code in codes],
            }

    class Context:
        def emit(self, event_type, message, *, data):
            events.append((event_type, message, data))

        def sleep(self, _seconds):
            pass

    card_recognizer = Cards()
    tap_count = _execute_hakuno_reroll(
        Context(),
        Device(),
        Recognition(),
        card_recognizer,
        "CH",
        [{"slot": 0, "name": "Hakuno", "active": True, "sn": "1"}],
        {
            "type": "hakuno_card_reroll",
            "need_cards": [["1B", "2A"]],
            "skill_step": {"type": "tap", "role": "servant_skill_1", "x": 70, "y": 590},
            "max_rerolls": 3,
        },
        ["battle/CH/Arts.png", "battle/CH/Buster.png", "battle/CH/Quick.png"],
        "battle/CH/attack.png",
        0.75,
        1.0,
        0.01,
        0,
    )

    assert tap_count == 5
    assert card_recognizer.calls == 2
    assert taps == [
        (1150, 600),
        (1250, 683),
        (70, 590),
        (1150, 600),
        (1250, 683),
    ]
    checks = [event for event in events if event[0] == "hakuno_card_check"]
    assert [event[2]["matched"] for event in checks] == [False, True]


@pytest.mark.parametrize(
    ("job_kind", "expected_result"),
    [
        (
            "battle.execute-plan",
            {
                "setting_name": "hakuno",
                "turn_count": 1,
                "action_count": 1,
                "tap_count": 11,
            },
        ),
        (
            "battle.execute-skills",
            {
                "setting_name": "hakuno",
                "action_count": 1,
                "tap_count": 7,
            },
        ),
    ],
)
def test_battle_jobs_run_dynamic_hakuno_reroll(
    tmp_path: Path,
    job_kind: str,
    expected_result: dict,
):
    data = tmp_path / "data"
    (data / "settings").mkdir(parents=True)
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Hakuno": {"other_name": [], "id": "1"}}),
        encoding="utf-8",
    )
    (data / "settings" / "hakuno.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Hakuno",
                "intervalBFchooseCard": 0,
                "round1_turns": 1,
                "round1_turn0_skill": [["Hakuno", 1, [["1B", "2A"]]]],
            }
        ),
        encoding="utf-8",
    )
    taps = []

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def snapshot(self):
            return b"frame"

        def tap(self, x, y):
            taps.append((x, y))
            return Operation()

    class Match:
        matched = True
        confidence = 1.0

        def to_dict(self):
            return {"matched": True, "confidence": 1.0}

    class Recognition:
        def match_template(self, _screenshot, template_path, *_args, **_options):
            if template_path.endswith("/reconnect.png"):
                return SimpleNamespace(matched=False)
            return Match()

        def match_templates(self, _screenshot, candidates):
            return [Match() for _ in candidates]

    class Cards:
        calls = 0

        def recognize(self, _screenshot, _server, _servants, *, threshold):
            self.calls += 1
            codes = ["1B", "3Q"] if self.calls == 1 else ["1B", "2A"]
            return {"complete": True, "cards": [{"code": code} for code in codes]}

    cards = Cards()
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_battle_jobs(
            manager,
            ScriptDataService(data),
            Device(),
            Recognition(),
            cards,
        )
        job = manager.start(
            job_kind,
            {
                "setting_name": "hakuno",
                "timeout_seconds": 1,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="fake:hakuno",
        )
        result = manager.wait(job.job_id, timeout=2)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result == expected_result
    assert cards.calls == 2
    assert taps[:7] == [
        (1150, 600),
        (1250, 683),
        (70, 590),
        (1217, 440),
        (1217, 440),
        (1150, 600),
        (1250, 683),
    ]


def test_execute_battle_job_runs_extra_turn_while_round_is_unchanged(tmp_path: Path):
    data = tmp_path / "data"
    (data / "settings").mkdir(parents=True)
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Servant A": {"other_name": []}}),
        encoding="utf-8",
    )
    (data / "settings" / "extra.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Servant A",
                "round1_turns": 1,
                "round1_extraSkill": [1],
            }
        ),
        encoding="utf-8",
    )
    taps = []

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def snapshot(self):
            return b"frame"

        def tap(self, x, y):
            taps.append((x, y))
            return Operation()

    class Match:
        confidence = 1.0

        def __init__(self, template_path, matched=True):
            self.template_path = template_path
            self.matched = matched

        def to_dict(self):
            return {"template_path": self.template_path, "matched": self.matched}

    class Recognition:
        transition_calls = 0

        def match_template(
            self,
            _screenshot,
            template_path,
            _threshold=None,
            **_options,
        ):
            return Match(template_path, not template_path.endswith("/reconnect.png"))

        def match_templates(self, _screenshot, candidates):
            paths = [candidate["template_path"] for candidate in candidates]
            if not any("phase_" in path or "battleFinish" in path for path in paths):
                return [Match(path) for path in paths]
            self.transition_calls += 1
            matched_paths = (
                {"battle/CH/attack.png", "battle/CH/phase_1.png"}
                if self.transition_calls == 1
                else {"battle/CH/battleFinish.png"}
            )
            return [Match(path, path in matched_paths) for path in paths]

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_battle_jobs(
            manager,
            ScriptDataService(data),
            Device(),
            Recognition(),
        )
        job = manager.start(
            "battle.execute-plan",
            {
                "setting_name": "extra",
                "timeout_seconds": 1,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="fake:extra",
        )
        result = manager.wait(job.job_id, timeout=2)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["tap_count"] == 11
    assert taps == [
        (1150, 600),
        (150, 500),
        (375, 500),
        (650, 500),
        (70, 590),
        (1217, 440),
        (1217, 440),
        (1150, 600),
        (150, 500),
        (375, 500),
        (650, 500),
    ]


def test_execute_battle_job_stops_when_battle_finishes_before_configured_turns(
    tmp_path: Path,
):
    data = tmp_path / "data"
    (data / "settings").mkdir(parents=True)
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Servant A": {"other_name": []}}),
        encoding="utf-8",
    )
    (data / "settings" / "early-finish.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Servant A",
                "round1_turns": 1,
                "round2_turns": 1,
            }
        ),
        encoding="utf-8",
    )
    taps = []

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def snapshot(self):
            return b"frame"

        def tap(self, x, y):
            taps.append((x, y))
            return Operation()

    class Match:
        confidence = 1.0

        def __init__(self, template_path, matched=True):
            self.template_path = template_path
            self.matched = matched

        def to_dict(self):
            return {"template_path": self.template_path, "matched": self.matched}

    class Recognition:
        transition_calls = 0

        def match_template(
            self,
            _screenshot,
            template_path,
            _threshold=None,
            **_options,
        ):
            return Match(template_path, not template_path.endswith("/reconnect.png"))

        def match_templates(self, _screenshot, candidates):
            paths = [candidate["template_path"] for candidate in candidates]
            if not any("phase_" in path or "battleFinish" in path for path in paths):
                return [Match(path) for path in paths]
            self.transition_calls += 1
            return [
                Match(path, path.endswith("/battleFinish.png"))
                for path in paths
            ]

    recognition = Recognition()
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_battle_jobs(
            manager,
            ScriptDataService(data),
            Device(),
            recognition,
        )
        job = manager.start(
            "battle.execute-plan",
            {
                "setting_name": "early-finish",
                "timeout_seconds": 1,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="fake:early-finish",
        )
        result = manager.wait(job.job_id, timeout=2)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["tap_count"] == 4
    assert recognition.transition_calls == 1
    assert taps == [
        (1150, 600),
        (150, 500),
        (375, 500),
        (650, 500),
    ]


def test_card_condition_opens_command_cards_and_returns_to_battle():
    taps = []
    events = []

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def snapshot(self):
            return b"frame"

        def tap(self, x, y):
            taps.append((x, y))
            return Operation()

    class Recognition:
        def match_template(self, _screenshot, _template_path, **_options):
            return SimpleNamespace(matched=False)

        def match_templates(self, _screenshot, candidates):
            return [
                SimpleNamespace(
                    matched=True,
                    confidence=1.0,
                    to_dict=lambda: {"matched": True, "confidence": 1.0},
                )
                for _ in candidates
            ]

    class Cards:
        def recognize(self, _screenshot, _server, _servants, *, threshold):
            assert threshold == 0.75
            return {
                "complete": True,
                "recognized_count": 5,
                "cards": [
                    {"slot": 1, "code": "1B", "servant_position": 1, "stars": 0},
                    {"slot": 2, "code": "2A", "servant_position": 2, "stars": 0},
                    {"slot": 3, "code": "3Q", "servant_position": 3, "stars": 0},
                    {"slot": 4, "code": "1A", "servant_position": 1, "stars": 0},
                    {"slot": 5, "code": "2B", "servant_position": 2, "stars": 0},
                ],
            }

    class Context:
        def emit(self, event_type, message, *, data):
            events.append((event_type, message, data))

        def sleep(self, _seconds):
            pass

    condition = [{
        "card1": {"type": 1, "cards": ["1B"], "criticalStar": 0, "more_or_less": True},
        "card2": {"type": 2, "cards": [], "criticalStar": 0, "more_or_less": True},
        "card3": {"type": 2, "cards": [], "criticalStar": 0, "more_or_less": True},
        "colorFirst": True,
    }]

    matched, tap_count = _evaluate_card_condition(
        Context(),
        Device(),
        Recognition(),
        Cards(),
        "CH",
        [{"slot": 0, "name": "One", "active": True, "sn": "100"}],
        condition,
        ["battle/CH/Arts.png", "battle/CH/Buster.png", "battle/CH/Quick.png"],
        0.75,
        1.0,
        0.01,
        0,
    )

    assert matched is True
    assert tap_count == 2
    assert taps == [(1150, 600), (1250, 683)]
    assert events[-1][0] == "skill_condition"


def test_strategy_execution_passes_special_keys_to_card_recognition():
    received_special_keys = []
    taps = []

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def tap(self, x, y):
            taps.append((x, y))
            return Operation()

    class Cards:
        def recognize(
            self,
            _screenshot,
            _server,
            _servants,
            *,
            threshold,
            special_keys,
        ):
            assert threshold == 0.75
            received_special_keys.extend(special_keys)
            return {
                "complete": True,
                "recognized_count": 5,
                "cards": [
                    {
                        "slot": slot,
                        "code": f"{slot}B",
                        "servant_position": ((slot - 1) % 3) + 1,
                        "stars": 0,
                        "special_keys": ["S0"] if slot == 2 else [],
                    }
                    for slot in range(1, 6)
                ],
            }

    class Context:
        def emit(self, _event_type, _message, *, data):
            assert data

        def sleep(self, _seconds):
            pass

    special_keys = [
        {
            "code": "S0",
            "template_path": "special_keys/custom.png",
            "threshold": 0.85,
        }
    ]
    strategy = {
        "card1": {
            "type": 1,
            "cards": ["S0"],
            "criticalStar": 0,
            "more_or_less": True,
        },
        "card2": {
            "type": 2,
            "cards": [],
            "criticalStar": 0,
            "more_or_less": True,
        },
        "card3": {
            "type": 2,
            "cards": [],
            "criticalStar": 0,
            "more_or_less": True,
        },
        "colorFirst": True,
    }

    tap_count = _execute_strategy_step(
        Context(),
        Device(),
        Cards(),
        b"frame",
        "CH",
        [],
        {"strategies": [strategy]},
        0.75,
        0,
        special_keys=special_keys,
    )

    assert tap_count == 3
    assert received_special_keys == special_keys
    assert taps[0] == (375, 500)


def test_strategy_execution_avoids_chain_for_single_np():
    taps = []

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def tap(self, x, y):
            taps.append((x, y))
            return Operation()

    class Cards:
        def recognize(self, *_args, **_options):
            return {
                "complete": True,
                "recognized_count": 5,
                "cards": [
                    {
                        "slot": slot,
                        "code": code,
                        "servant_position": int(code[0]),
                        "color": code[1],
                        "stars": 0,
                    }
                    for slot, code in enumerate(
                        ("1B", "1A", "2B", "2A", "3B"),
                        start=1,
                    )
                ],
            }

    class Context:
        def emit(self, *_args, **_options):
            pass

        def sleep(self, _seconds):
            pass

    tap_count = _execute_strategy_step(
        Context(),
        Device(),
        Cards(),
        b"frame",
        "CH",
        [],
        {
            "strategies": [],
            "preselected_nps": [1],
            "avoid_chain": True,
        },
        0.75,
        0,
    )

    assert tap_count == 3
    assert taps == [(500, 110), (150, 500), (900, 500)]


def test_execute_skills_job_recognizes_battle_and_taps_skill_target(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "skills"
    (assets / "battle" / "CH").mkdir(parents=True)
    (data / "settings").mkdir(parents=True)
    session.mkdir(parents=True)

    attack = np.zeros((28, 34, 3), dtype=np.uint8)
    attack[2:26, 2:32] = (30, 180, 240)
    attack[8:20, 12:22] = (255, 255, 255)
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame[560:588, 1100:1134] = attack
    _write_image(assets / "battle" / "CH" / "attack.png", attack)
    for index in range(5):
        _write_image(session / f"{index}.png", frame)

    (session / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "device_id": "skills",
                "frames": [
                    {"file": "0.png", "expect": {"type": "tap", "x": 474, "y": 590}},
                    {"file": "1.png", "expect": {"type": "tap", "x": 640, "y": 440}},
                    {"file": "2.png", "expect": {"type": "tap", "x": 1217, "y": 440}},
                    {"file": "3.png", "expect": {"type": "tap", "x": 1217, "y": 440}},
                    {"file": "4.png"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Servant A": {"other_name": []}}),
        encoding="utf-8",
    )
    (data / "settings" / "demo.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Servant A",
                "round1_turns": 1,
                "round1_turn0_skill": [[5, 2]],
            }
        ),
        encoding="utf-8",
    )

    event_log = EventLog()
    devices = DeviceService(
        [ReplayBackend(tmp_path / "replays")],
        event_log,
        frame_normalizer=FrameNormalizer(),
    )
    devices.connect("replay", "skills")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        app = create_app(
            assets,
            data,
            device_service=devices,
            event_log=event_log,
            job_manager=manager,
        )
        with create_test_client(app) as client:
            response = client.post(
                "/api/jobs",
                json={
                    "kind": "battle.execute-skills",
                    "payload": {
                        "setting_name": "demo",
                        "timeout_seconds": 1,
                        "poll_interval": 0.01,
                        "tap_interval_seconds": 0,
                    },
                },
            )
            assert response.status_code == 202
            job_id = response.json()["job"]["job_id"]
            result = manager.wait(job_id, timeout=2)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result == {
        "setting_name": "demo",
        "action_count": 1,
        "tap_count": 4,
    }
    events = manager.database.list_events(job_id)
    assert [event.data["role"] for event in events if event.event_type == "device_action"] == [
        "servant_skill_5",
        "skill_target_2",
        "skill_animation_skip_1",
        "skill_animation_skip_2",
    ]


def test_execute_skills_rejects_np_before_snapshot_or_tap(tmp_path: Path):
    data = tmp_path / "data"
    (data / "settings").mkdir(parents=True)
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Servant A": {"other_name": []}}),
        encoding="utf-8",
    )
    (data / "settings" / "np.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Servant A",
                "round1_turns": 1,
                "round1_turn0_np": [1],
            }
        ),
        encoding="utf-8",
    )
    device_calls = []

    class NoActionDevice:
        def snapshot(self):
            device_calls.append("snapshot")
            raise AssertionError("snapshot must not be called")

        def tap(self, _x, _y):
            device_calls.append("tap")
            raise AssertionError("tap must not be called")

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_battle_jobs(
            manager,
            ScriptDataService(data),
            NoActionDevice(),
            object(),
        )
        job = manager.start(
            "battle.execute-skills",
            {"setting_name": "np"},
            device_key="replay:unused",
        )
        result = manager.wait(job.job_id, timeout=2)

    assert result.status == JobStatus.FAILED
    assert result.error["message"] == "Program contains non-skill actions."
    assert device_calls == []


def test_execute_battle_job_runs_skill_and_command_phase(
    tmp_path: Path,
    monkeypatch,
):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "battle"
    (assets / "battle" / "CH").mkdir(parents=True)
    (data / "settings").mkdir(parents=True)
    session.mkdir(parents=True)

    attack = np.zeros((28, 34, 3), dtype=np.uint8)
    attack[2:26, 2:32] = (30, 180, 240)
    attack[8:20, 12:22] = (255, 255, 255)
    arts = np.zeros((30, 46, 3), dtype=np.uint8)
    arts[2:28, 2:44] = (200, 80, 30)
    arts[9:21, 10:36] = (255, 255, 255)
    battle_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    battle_frame[560:588, 1100:1134] = attack
    command_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    command_frame[470:500, 130:176] = arts
    _write_image(assets / "battle" / "CH" / "attack.png", attack)
    for card_type in ("Arts", "Buster", "Quick"):
        _write_image(assets / "battle" / "CH" / f"{card_type}.png", arts)
    expectations = [
        (battle_frame, {"type": "tap", "x": 70, "y": 590}),
        (battle_frame, {"type": "tap", "x": 1217, "y": 440}),
        (battle_frame, {"type": "tap", "x": 1217, "y": 440}),
        (battle_frame, {"type": "tap", "x": 1150, "y": 600}),
        (command_frame, {"type": "tap", "x": 500, "y": 110}),
        (command_frame, {"type": "tap", "x": 150, "y": 500}),
        (command_frame, {"type": "tap", "x": 375, "y": 500}),
        (command_frame, None),
    ]
    frames = []
    for index, (image, expect) in enumerate(expectations):
        filename = f"{index}.png"
        _write_image(session / filename, image)
        frame = {"file": filename}
        if expect is not None:
            frame["expect"] = expect
        frames.append(frame)
    (session / "manifest.json").write_text(
        json.dumps({"version": 1, "device_id": "battle", "frames": frames}),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Servant A": {"other_name": []}}),
        encoding="utf-8",
    )
    (data / "settings" / "battle.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Servant A",
                "round1_turns": 1,
                "round1_turn0_skill": [1],
                "round1_turn0_np": [1],
                "firstBattleSet": 1,
            }
        ),
        encoding="utf-8",
    )

    event_log = EventLog()
    devices = DeviceService(
        [ReplayBackend(tmp_path / "replays")],
        event_log,
        frame_normalizer=FrameNormalizer(),
    )
    devices.connect("replay", "battle")
    initialized = []

    def initialize(*_args, **_kwargs):
        initialized.append(True)
        return {"changed": False, "states": [True, True, False], "actions": []}

    monkeypatch.setattr("webapp.automation.battle.initialize_battle_settings", initialize)
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_battle_jobs(
            manager,
            ScriptDataService(data),
            devices,
            RecognitionService(ResourceService(assets, data)),
        )
        job = manager.start(
            "battle.execute-plan",
            {
                "setting_name": "battle",
                "timeout_seconds": 1,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="replay:battle",
        )
        result = manager.wait(job.job_id, timeout=10)

    assert result.status == JobStatus.SUCCEEDED
    assert initialized == [True]
    assert result.result == {
        "setting_name": "battle",
        "turn_count": 1,
        "action_count": 2,
        "tap_count": 7,
    }
    events = manager.database.list_events(job.job_id)
    assert [event.data["role"] for event in events if event.event_type == "device_action"] == [
        "servant_skill_1",
        "skill_animation_skip_1",
        "skill_animation_skip_2",
        "attack",
        "np_1",
        "face_card_1",
        "face_card_2",
    ]


def test_execute_battle_job_recognizes_and_selects_strategy_cards(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "strategy"
    (assets / "battle" / "CH").mkdir(parents=True)
    (data / "settings").mkdir(parents=True)
    session.mkdir(parents=True)

    def pattern(width, height, color, marker):
        image = np.zeros((height, width, 4), dtype=np.uint8)
        image[2:-2, 2:-2, :3] = color
        image[2:-2, 2:-2, 3] = 255
        image[marker : marker + 2, 3:-3, :3] = 255
        image[marker : marker + 2, 3:-3, 3] = 255
        return image

    attack = pattern(34, 28, (30, 180, 240), 8)
    colors = {
        "Buster": pattern(34, 20, (40, 40, 210), 4),
        "Arts": pattern(34, 20, (220, 80, 40), 8),
        "Quick": pattern(34, 20, (80, 190, 40), 12),
    }
    portraits = {
        1: pattern(48, 48, (130, 40, 50), 5),
        2: pattern(48, 48, (100, 40, 100), 10),
        3: pattern(48, 48, (70, 40, 150), 15),
    }
    _write_image(assets / "battle" / "CH" / "attack.png", attack)
    for name, image in colors.items():
        _write_image(assets / "battle" / "CH" / f"{name}.png", image)
    for position, image in portraits.items():
        directory = assets / "commands_CH" / str(100 + position)
        directory.mkdir(parents=True)
        _write_image(directory / "card_servant_1.png", image)
    star_directory = assets / "battle" / "public" / "starNum"
    star_directory.mkdir(parents=True)
    star_templates = {}
    for number in range(10):
        image = np.zeros((39, 40), dtype=np.uint8)
        image[5:34, 5:35] = 20 + number * 15
        image[6:33, 6 + number * 2 : 8 + number * 2] = 240
        mask = np.zeros_like(image)
        mask[5:34, 5:35] = 255
        _write_image(star_directory / f"n{number}.png", image)
        _write_image(star_directory / f"n{number}mask.png", mask)
        star_templates[number] = image

    battle_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    battle_frame[560:588, 1100:1134] = attack[:, :, :3]
    command_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    expected_cards = [(1, "Buster"), (2, "Arts"), (1, "Arts"), (3, "Quick"), (2, "Buster")]
    for slot, (position, color_name) in enumerate(expected_cards):
        x = slot * 256
        color = colors[color_name]
        portrait = portraits[position]
        command_frame[420:440, x + 20 : x + 54] = color[:, :, :3]
        command_frame[500:548, x + 100 : x + 148] = portrait[:, :, :3]
    command_frame[353:392, 584:624] = np.repeat(
        star_templates[6][:, :, np.newaxis],
        3,
        axis=2,
    )

    expectations = [
        (battle_frame, {"type": "tap", "x": 1150, "y": 600}),
        (command_frame, {"type": "tap", "x": 500, "y": 110}),
        (command_frame, {"type": "tap", "x": 650, "y": 500}),
        (command_frame, {"type": "tap", "x": 1175, "y": 500}),
        (command_frame, None),
    ]
    frames = []
    for index, (image, expect) in enumerate(expectations):
        filename = f"{index}.png"
        _write_image(session / filename, image)
        frame = {"file": filename}
        if expect is not None:
            frame["expect"] = expect
        frames.append(frame)
    (session / "manifest.json").write_text(
        json.dumps({"version": 1, "device_id": "strategy", "frames": frames}),
        encoding="utf-8",
    )
    servants = {
        "One": {"other_name": [], "SN": "101"},
        "Two": {"other_name": [], "SN": "102"},
        "Three": {"other_name": [], "SN": "103"},
    }
    (data / "servant_info_CH.json").write_text(json.dumps(servants), encoding="utf-8")
    strategy = {
        "card1": {"type": 0, "cards": [1], "criticalStar": 0, "more_or_less": True},
        "card2": {"type": 1, "cards": ["1A"], "criticalStar": 5, "more_or_less": True},
        "card3": {"type": 1, "cards": ["2B"], "criticalStar": 0, "more_or_less": True},
        "breakpoint": [False, False],
        "colorFirst": True,
    }
    (data / "settings" / "strategy.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "One",
                "servant_1_name": "Two",
                "servant_2_name": "Three",
                "usedServant": [0, 1, 2],
                "round1_turns": 1,
                "round1_turn0_strategy": [strategy],
            }
        ),
        encoding="utf-8",
    )

    resources = ResourceService(assets, data)
    recognition = RecognitionService(resources)
    cards = CommandCardRecognizer(resources, recognition)
    devices = DeviceService(
        [ReplayBackend(tmp_path / "replays")],
        EventLog(),
        frame_normalizer=FrameNormalizer(),
    )
    devices.connect("replay", "strategy")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_battle_jobs(
            manager,
            ScriptDataService(data),
            devices,
            recognition,
            cards,
        )
        job = manager.start(
            "battle.execute-plan",
            {
                "setting_name": "strategy",
                "timeout_seconds": 1,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="replay:strategy",
        )
        result = manager.wait(job.job_id, timeout=10)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result == {
        "setting_name": "strategy",
        "turn_count": 1,
        "action_count": 1,
        "tap_count": 4,
    }
    events = manager.database.list_events(job.job_id)
    assert [event.data["role"] for event in events if event.event_type == "device_action"] == [
        "attack",
        "np_1",
        "face_card_3",
        "face_card_5",
    ]
