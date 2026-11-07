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
    _filter_post_exchange_skill_actions,
    _frontline_servants,
    _is_servant_skill_unavailable,
    _matches_hakuno_needs,
    _sync_frontline_alive_positions,
    _wait_for_battle_ready,
    _wait_for_command_cards,
    _wait_for_battle_transition,
    register_battle_jobs,
)
from webapp.automation.program import (
    build_autonomous_skill_commands,
    compile_battle_program,
    resolve_skill_target_point,
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


def test_wait_for_battle_transition_uses_highest_confidence_round_match():
    class Device:
        def snapshot(self):
            return b"frame"

    class Match:
        def __init__(self, template_path, confidence):
            self.template_path = template_path
            self.confidence = confidence
            self.matched = confidence >= 0.85

        def to_dict(self):
            return {
                "template_path": self.template_path,
                "matched": self.matched,
                "confidence": self.confidence,
            }

    class Recognition:
        def match_templates(self, _screenshot, candidates):
            confidences = {
                "battle/CH/attack.png": 0.99,
                "battle/CH/phase_1.png": 0.87,
                "battle/CH/phase_2.png": 0.96,
            }
            return [
                Match(
                    candidate["template_path"],
                    confidences.get(candidate["template_path"], 0.1),
                )
                for candidate in candidates
            ]

    class Context:
        def emit(self, *_args, **_options):
            pass

        def sleep(self, _seconds):
            pass

    result = _wait_for_battle_transition(
        Context(),
        Device(),
        Recognition(),
        "CH",
        0.85,
        1,
        0,
    )

    assert result == {"state": "battle", "round": 2}


@pytest.mark.parametrize("need", [["1B", "2A"], ["1BS0", "2AS0"], ["S0", "1BS0"]],
                         ids=["ordinary", "combined-tag", "tag-alias-overlap"])
def test_hakuno_reroll_casts_skill_until_card_need_matches(need):
    taps = []
    events = []
    tags = [] if need == ["1B", "2A"] else [{"code": "S0", "template_path": "battle/customCommandCard/example.png"}]

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

        def recognize(self, _screenshot, _server, _servants, *, threshold, special_keys=None):
            assert threshold == 0.75
            assert special_keys == (tags or None)
            self.calls += 1
            codes = ["1B", "3Q"] if self.calls == 1 else ["1B", "2A"]
            return {
                "complete": True,
                "cards": [{"code": code, "special_keys": ["S0"] if code != "3Q" else []} for code in codes],
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
            "need_cards": [need],
            "skill_step": {"type": "tap", "role": "servant_skill_1", "x": 70, "y": 590},
            "max_rerolls": 3,
        },
        ["battle/CH/Arts.png", "battle/CH/Buster.png", "battle/CH/Quick.png"],
        "battle/CH/attack.png",
        0.75,
        1.0,
        0.01,
        0,
        special_keys=tags,
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


def test_execute_battle_job_uses_default_extra_turn_on_final_round(tmp_path: Path):
    data = tmp_path / "data"
    (data / "settings").mkdir(parents=True)
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Servant A": {"other_name": []}}),
        encoding="utf-8",
    )
    (data / "settings" / "final-extra.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Servant A",
                "round1_turns": 1,
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
                "setting_name": "final-extra",
                "timeout_seconds": 1,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="fake:final-extra",
        )
        result = manager.wait(job.job_id, timeout=2)

    assert result.status == JobStatus.SUCCEEDED
    assert recognition.transition_calls == 2
    assert taps == [
        (1150, 600),
        (150, 500),
        (375, 500),
        (650, 500),
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


def test_execute_battle_job_skips_stale_turns_after_round_advances(tmp_path: Path):
    data = tmp_path / "data"
    (data / "settings").mkdir(parents=True)
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Servant A": {"other_name": []}}),
        encoding="utf-8",
    )
    (data / "settings" / "round-advance.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Servant A",
                "noSpeedupSkill": 1,
                "round1_turns": 2,
                "round1_turn0_skill": [1],
                "round1_turn1_skill": [2],
                "round2_turns": 1,
                "round2_turn0_skill": [3],
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
                {"battle/CH/attack.png", "battle/CH/phase_2.png"}
                if self.transition_calls == 1
                else {"battle/CH/battleFinish.png"}
            )
            return [Match(path, path in matched_paths) for path in paths]

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
                "setting_name": "round-advance",
                "timeout_seconds": 1,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="fake:round-advance",
        )
        result = manager.wait(job.job_id, timeout=2)

    assert result.status == JobStatus.SUCCEEDED
    assert recognition.transition_calls == 2
    assert taps == [
        (70, 590),
        (1150, 600),
        (150, 500),
        (375, 500),
        (650, 500),
        (256, 590),
        (1150, 600),
        (150, 500),
        (375, 500),
        (650, 500),
    ]


def test_execute_battle_job_uses_default_extra_turn_until_round_advances(
    tmp_path: Path,
):
    data = tmp_path / "data"
    (data / "settings").mkdir(parents=True)
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Servant A": {"other_name": []}}),
        encoding="utf-8",
    )
    (data / "settings" / "default-extra.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Servant A",
                "noSpeedupSkill": 1,
                "round1_turns": 1,
                "round2_turns": 1,
                "round2_turn0_skill": [3],
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
            if self.transition_calls < 3:
                matched_paths = {
                    "battle/CH/attack.png",
                    f"battle/CH/phase_{self.transition_calls}.png",
                }
            else:
                matched_paths = {"battle/CH/battleFinish.png"}
            return [Match(path, path in matched_paths) for path in paths]

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
                "setting_name": "default-extra",
                "timeout_seconds": 1,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="fake:default-extra",
        )
        result = manager.wait(job.job_id, timeout=2)

    assert result.status == JobStatus.SUCCEEDED
    assert recognition.transition_calls == 3
    assert taps == [
        (1150, 600),
        (150, 500),
        (375, 500),
        (650, 500),
        (1150, 600),
        (150, 500),
        (375, 500),
        (650, 500),
        (256, 590),
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
    monkeypatch.setattr(
        "webapp.automation.battle._wait_for_battle_transition",
        lambda *_args, **_kwargs: {"state": "finished", "round": None},
    )
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


def test_hakuno_needs_exclude_unavailable_cards():
    cards = [{"code": "1A", "available": False}, {"code": "2B", "available": True}]
    assert not _matches_hakuno_needs(cards, [["1A", "2B"]])
    assert _matches_hakuno_needs(cards, [["2B"]])


@pytest.mark.parametrize("blocked", [False, True])
def test_execute_battle_job_recognizes_and_selects_strategy_cards(
    tmp_path: Path,
    monkeypatch,
    blocked,
):
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
    blocker = pattern(20, 30, (20, 220, 240), 6)
    _write_image(assets / "battle" / "CH" / "freeze.png", blocker)
    _write_image(assets / "battle" / "CH" / "bjfy.png", pattern(22, 28, (210, 40, 150), 9))
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
    if blocked:
        command_frame[479:509, 1212:1232] = blocker[:, :, :3]

    expectations = [
        (battle_frame, {"type": "tap", "x": 1150, "y": 600}),
        (command_frame, {"type": "tap", "x": 500, "y": 110}),
        (command_frame, {"type": "tap", "x": 650, "y": 500}),
        (command_frame, {"type": "tap", "x": 150 if blocked else 1175, "y": 500}),
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
        "card3": {"type": 1, "cards": ["2B", "1B"], "criticalStar": 0, "more_or_less": True},
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
    monkeypatch.setattr(
        "webapp.automation.battle._wait_for_battle_transition",
        lambda *_args, **_kwargs: {"state": "finished", "round": None},
    )
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
        "face_card_1" if blocked else "face_card_5",
    ]


def test_resolve_skill_target_point_adjusts_for_frontline_losses():
    assert resolve_skill_target_point(1, [0, 1, 2]) == (350, 440)
    assert resolve_skill_target_point(2, [0, 1, 2]) == (640, 440)
    assert resolve_skill_target_point(3, [0, 1, 2]) == (970, 440)

    assert resolve_skill_target_point(1, [0, None, 2]) == (476, 440)
    assert resolve_skill_target_point(3, [0, None, 2]) == (805, 440)
    assert resolve_skill_target_point(2, [None, 1, 2]) == (476, 440)
    assert resolve_skill_target_point(3, [None, 1, 2]) == (805, 440)

    assert resolve_skill_target_point(3, [0, None, None]) == (640, 440)


def test_execute_skill_action_uses_dynamic_target_points_when_frontline_shrinks():
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

    _execute_skill_action(
        Context(),
        Device(),
        {
            "source": {"type": "skill", "command": [1, 3]},
            "steps": [
                {"type": "tap", "role": "servant_skill_1", "x": 70, "y": 590},
                {"type": "tap", "role": "skill_target_3", "x": 970, "y": 440},
            ],
        },
        0,
        speedup_skills=False,
        occupied_positions=[0, None, 2, None, None, None],
    )

    assert taps == [(70, 590), (805, 440)]


def test_compile_battle_program_supports_crawl_tower_script_and_autonomous_modes():
    plan = {
        "name": "tower",
        "server": "CH",
        "servants": [
            {"slot": 0, "name": "库库尔坎"},
            {"slot": 1, "name": "太空伊什塔尔"},
            {"slot": 2, "name": "岸波白野(女性)"},
        ],
        "rounds": [
            {
                "round": 1,
                "turns": [
                    {
                        "turn": 0,
                        "actions": [
                            {"type": "skill", "command": 1},
                            {"type": "skill", "command": 10},
                        ],
                        "nps": [],
                        "strategy": None,
                        "condition": None,
                    }
                ],
                "extra_skill": [2],
                "extra_strategy": None,
            }
        ],
        "validation": {"ok": True, "errors": [], "warnings": []},
    }

    script_program = compile_battle_program(plan, crawl_tower_mode="script")
    first_turn_actions = script_program["rounds"][0]["turns"][0]["actions"]
    assert first_turn_actions[0]["source"]["command"] == [1, 1]
    assert [step["role"] for step in first_turn_actions[0]["steps"]] == [
        "servant_skill_1",
        "skill_target_1",
    ]
    assert first_turn_actions[1]["source"]["command"] == 10
    assert (
        script_program["rounds"][0]["extra_turn"]["actions"][0]["source"]["command"]
        == [2, 1]
    )

    autonomous_commands = build_autonomous_skill_commands(
        ["库库尔坎", "太空伊什塔尔", "岸波白野(女性)"],
        default_target=1,
    )
    assert autonomous_commands == [
        ["Kukulkan", 1, 1],
        ["Kukulkan", 2, 1, 1],
        ["Kukulkan", 3, 1],
        [4, 1],
        [-5, 3],
        [6, 1],
        ["Hakuno", 7, []],
        [8, 1],
        ["Hakuno", 9, "R"],
    ]

    autonomous_program = compile_battle_program(
        {**plan, "rounds": []},
        crawl_tower_mode="autonomous",
    )
    assert autonomous_program["execution"]["battle"]["ready"] is True
    assert len(autonomous_program["rounds"]) == 3
    assert [
        step["role"]
        for step in autonomous_program["rounds"][0]["turns"][0]["command_phase"]["steps"]
    ] == ["attack", "np_1", "np_2", "np_3"]
    assert [
        step["role"]
        for step in autonomous_program["rounds"][0]["extra_turn"]["command_phase"]["steps"]
    ] == ["attack", "np_1", "np_2", "np_3"]


def test_sync_frontline_alive_positions_updates_empty_frontline_slots():
    events = []
    occupied = [0, 1, 2, 3, 4, 5]
    servants = [
        {"slot": index, "name": f"Servant {index + 1}"}
        for index in range(6)
    ]

    class Recognition:
        def match_template(self, _screenshot, template_path, **options):
            assert template_path == "battle/public/alive.png"
            roi = options["roi"]
            return SimpleNamespace(matched=roi[0] != 604)

    class Context:
        def emit(self, event_type, message, *, data):
            events.append((event_type, message, data))

    alive = _sync_frontline_alive_positions(
        Context(),
        Recognition(),
        b"frame",
        occupied,
        servants,
    )

    assert alive == [True, False, True]
    assert occupied[:3] == [0, None, 2]
    assert [s["name"] if s else None for s in servants[:3]] == [
        "Servant 1",
        None,
        "Servant 3",
    ]
    assert len(events) == 1
    assert events[0][0] == "frontline_alive"
    assert events[0][2]["occupied_positions"] == [0, None, 2]


@pytest.mark.parametrize(
    ("popup_template", "expected_popup", "expected_tap"),
    [
        ("battle/CH/notAvailable.png", "skill_not_available", (642, 563)),
        ("battle/CH/x.png", "servant_detail", (1090, 60)),
    ],
)
def test_wait_for_battle_ready_dismisses_skill_and_servant_detail_popups(
    popup_template: str,
    expected_popup: str,
    expected_tap: tuple[int, int],
):
    state = {"frame": "popup"}
    taps = []
    events = []

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

    class Recognition:
        def match_template(self, screenshot, template_path, *_args, **_options):
            frame = screenshot.decode()
            if template_path == "battle/CH/attack.png":
                return SimpleNamespace(matched=frame == "battle", confidence=1.0)
            if template_path == popup_template:
                return SimpleNamespace(
                    matched=frame == "popup",
                    confidence=0.95,
                    center=(1090, 60),
                    size=(62, 64),
                )
            return SimpleNamespace(matched=False, confidence=0.0)

    class Context:
        def emit(self, event_type, message, *, data):
            events.append((event_type, message, data))

        def sleep(self, _seconds):
            pass

    _wait_for_battle_ready(
        Context(),
        Device(),
        Recognition(),
        "battle/CH/attack.png",
        0.85,
        1.0,
        0.01,
        reconnect_timing=_TapTiming(0),
    )

    assert taps == [expected_tap]
    popup_events = [event for event in events if event[0] == "battle_popup_closed"]
    assert len(popup_events) == 1
    assert popup_events[0][2]["popup"] == expected_popup


def test_execute_battle_job_skips_skills_on_cooldown_or_empty_frontline_slot(
    tmp_path: Path,
):
    data = tmp_path / "data"
    (data / "settings").mkdir(parents=True)
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Servant A": {"other_name": []}}),
        encoding="utf-8",
    )
    (data / "settings" / "cooldown.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Servant A",
                "noSpeedupSkill": 1,
                "round1_turns": 1,
                "round1_turn0_skill": [1, 2, [3, 3], 4],
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

    class Recognition:
        def match_template(self, _screenshot, template_path, _threshold=None, **options):
            if template_path == "battle/CH/attack.png":
                return SimpleNamespace(matched=True, confidence=1.0)
            if template_path == "battle/public/alive.png":
                roi = options["roi"]
                return SimpleNamespace(matched=roi[0] != 604, confidence=0.95)
            if template_path == "battle/CH/incd1.png":
                roi = options["roi"]
                return SimpleNamespace(matched=roi[0] == 51, confidence=0.95, roi=roi)
            if template_path == "battle/CH/freeze1.png":
                roi = options["roi"]
                return SimpleNamespace(matched=roi[0] == 155, confidence=0.95, roi=roi)
            return SimpleNamespace(matched=False, confidence=0.0)

        def match_templates(self, _screenshot, candidates):
            paths = [candidate["template_path"] for candidate in candidates]
            if any("phase_" in path or "battleFinish" in path for path in paths):
                return [
                    SimpleNamespace(
                        template_path=path,
                        matched=path.endswith("/battleFinish.png"),
                        confidence=1.0,
                        to_dict=lambda p=path: {
                            "template_path": p,
                            "matched": p.endswith("/battleFinish.png"),
                        },
                    )
                    for path in paths
                ]
            return [
                SimpleNamespace(
                    template_path=path,
                    matched=True,
                    confidence=1.0,
                    to_dict=lambda p=path: {"template_path": p, "matched": True},
                )
                for path in paths
            ]

    assert (
        _is_servant_skill_unavailable(
            Recognition(),
            b"frame",
            "CH",
            1,
            [0, 1, 2],
        )
        is True
    )
    assert (
        _is_servant_skill_unavailable(
            Recognition(),
            b"frame",
            "CH",
            2,
            [0, 1, 2],
        )
        is True
    )
    assert (
        _is_servant_skill_unavailable(
            Recognition(),
            b"frame",
            "CH",
            3,
            [0, 1, 2],
        )
        is False
    )

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
                "setting_name": "cooldown",
                "timeout_seconds": 1,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="fake:cooldown",
        )
        result = manager.wait(job.job_id, timeout=5)
        events = manager.database.list_events(job.job_id)

    assert result.status == JobStatus.SUCCEEDED
    skipped = [
        event.data["skill_number"]
        for event in events
        if event.event_type == "skill_skipped"
        and event.data.get("reason") == "skill_unavailable"
    ]
    assert skipped == [1, 2, 4]
    assert taps == [
        (256, 590),
        (805, 440),
        (1150, 600),
        (150, 500),
        (375, 500),
        (650, 500),
    ]


def test_filter_post_exchange_skill_actions_slices_pre_exchange_and_orphaned_end():
    actions = [
        {"source": {"type": "skill", "command": ["Start", True, []]}, "control": {"type": "condition_start"}},
        {"source": {"type": "skill", "command": 1}, "steps": []},
        {
            "source": {"type": "skill", "command": [12, 1, 4]},
            "state_change": {"type": "servant_exchange", "positions": [1, 4]},
            "steps": [],
        },
        {"source": {"type": "skill", "command": ["End"]}, "control": {"type": "condition_end"}},
        {"source": {"type": "skill", "command": 2}, "steps": []},
    ]

    remaining, skipped = _filter_post_exchange_skill_actions(actions, has_exchanged=True)

    assert [item["source"]["command"] for item in skipped] == [1, [12, 1, 4]]
    assert [item["source"]["command"] for item in remaining] == [2]


def test_execute_battle_job_skips_repeat_order_change_in_extra_turns_and_continues_unconfigured_round(
    tmp_path: Path,
):
    data = tmp_path / "data"
    (data / "settings").mkdir(parents=True)
    (data / "servant_info_CH.json").write_text(
        json.dumps(
            {
                "Servant A": {"other_name": []},
                "Servant B": {"other_name": []},
            }
        ),
        encoding="utf-8",
    )
    (data / "settings" / "exchange-extra.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Servant A",
                "servant_3_name": "Servant B",
                "noSpeedupSkill": 1,
                "round1_turns": 1,
                "round1_turn0_skill": [1, [12, 1, 4]],
                "round1_extraSkill": [1, [12, 1, 4], ["Start", True, [], ["np", [1, "≥", 100], [0, "≥", 0], [0, "≥", 0]]], 2, ["End"]],
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

        def match_template(self, _screenshot, template_path, _threshold=None, **_options):
            if template_path == "battle/CH/attack.png":
                return Match(template_path, True)
            if template_path == "battle/public/alive.png":
                return Match(template_path, True)
            return Match(template_path, False)

        def match_templates(self, _screenshot, candidates):
            paths = [candidate["template_path"] for candidate in candidates]
            if not any("phase_" in path or "battleFinish" in path for path in paths):
                return [Match(path) for path in paths]
            self.transition_calls += 1
            if self.transition_calls == 1:
                matched_paths = {"battle/CH/attack.png", "battle/CH/phase_1.png"}
            elif self.transition_calls == 2:
                matched_paths = {"battle/CH/attack.png", "battle/CH/phase_2.png"}
            else:
                matched_paths = {"battle/CH/battleFinish.png"}
            return [Match(path, path in matched_paths) for path in paths]

    class NpRecognizer:
        def recognize(self, _screenshot, _server, *, present):
            assert present == [True, False, False]
            return {"complete": True, "values": [100, None, None]}

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_battle_jobs(
            manager,
            ScriptDataService(data),
            Device(),
            Recognition(),
            np_recognizer=NpRecognizer(),
        )
        job = manager.start(
            "battle.execute-plan",
            {
                "setting_name": "exchange-extra",
                "timeout_seconds": 1,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="fake:exchange-extra",
        )
        result = manager.wait(job.job_id, timeout=5)
        events = manager.database.list_events(job.job_id)

    assert result.status == JobStatus.SUCCEEDED
    exchanges = [event for event in events if event.event_type == "servant_exchange"]
    # Round 1 turn 0 exchanges once; Round 1 extra turn 1 skips duplicate exchange and runs skill 2;
    # Round 2 (unconfigured wave) resets has_exchanged and falls back to round1_extraSkill.
    assert len(exchanges) == 2
    already_exchanged = [
        event.data["action"]["command"]
        for event in events
        if event.event_type == "skill_skipped"
        and event.data.get("reason") == "already_exchanged"
    ]
    assert already_exchanged == [1, [12, 1, 4]]


def test_wait_for_battle_ready_closes_command_card_back_screen(tmp_path: Path):
    data = tmp_path / "data"
    (data / "settings").mkdir(parents=True)
    (data / "servant_info_CH.json").write_text("{}", encoding="utf-8")
    (data / "settings" / "resume-from-cards.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "noSpeedupSkill": 1,
                "round1_turns": 1,
                "round1_turn0_skill": [1],
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
        card_screen_open = True

        def match_template(self, _screenshot, template_path, _threshold=None, **options):
            if template_path == "battle/CH/attack.png":
                return Match(template_path, not self.card_screen_open)
            if template_path == "battle/CH/back.png":
                assert options.get("roi") == (1100, 610, 180, 110)
                if self.card_screen_open:
                    self.card_screen_open = False
                    return Match(template_path, True)
                return Match(template_path, False)
            return Match(template_path, False)

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_battle_jobs(
            manager,
            ScriptDataService(data),
            Device(),
            Recognition(),
        )
        job = manager.start(
            "battle.execute-skills",
            {
                "setting_name": "resume-from-cards",
                "round": 1,
                "turn": 0,
                "timeout_seconds": 1,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="fake:resume-from-cards",
        )
        result = manager.wait(job.job_id, timeout=2)
        events = manager.database.list_events(job.job_id)

    assert result.status == JobStatus.SUCCEEDED
    assert taps == [(1250, 683), (70, 590)]
    popups = [
        event.data["popup"]
        for event in events
        if event.event_type == "battle_popup_closed"
    ]
    assert popups == ["command_card_back"]

