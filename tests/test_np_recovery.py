import json
from pathlib import Path
from types import SimpleNamespace

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from webapp.automation import battle
from webapp.automation.program import ATTACK_POINT, COMMAND_CARD_BACK_POINT, FACE_CARD_POINTS, NP_POINTS
from webapp.devices.coordinates import FrameNormalizer
from webapp.devices.replay import ReplayBackend
from webapp.services.cards import recognize_card_blocks
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


class ClockContext:
    now = 0.0

    def __init__(self):
        self.events = []
        self.action_times = []

    def sleep(self, seconds):
        self.now += seconds

    def emit(self, kind, _message, **options):
        self.events.append((kind, options.get("data")))
        if kind == "device_action":
            self.action_times.append((options["data"]["role"], self.now))


@pytest.fixture
def replay_factory(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    directory = assets / "battle" / "CH"
    directory.mkdir(parents=True)
    rng = np.random.default_rng(1824)
    templates = {}
    for filename in ("attack", "back", "Arts", "Buster", "Quick", "freeze", "bjfy", "reconnect"):
        templates[filename] = rng.integers(0, 256, (20, 24, 3), dtype=np.uint8)
        assert cv2.imwrite(str(directory / f"{filename}.png"), templates[filename])

    def frame(*, command=True, blocked_nps=(), blocked_faces=()):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        def paste(name, x, y):
            image[y:y + 20, x:x + 24] = templates[name]
        if command:
            paste("back", 1200, 670)
            paste("Arts", 50, 600)
            for position in blocked_nps:
                paste("bjfy", round((693 + 347 * (position - 1)) / 1.5) + 4, 181)
            for slot in blocked_faces:
                x = round(((60, 444, 826, 1212, 1601)[slot - 1] + 210) / 1.5) + 4
                paste("freeze", x, 477)
        else:
            paste("attack", 1100, 560)
        return image

    resources = ResourceService(assets, tmp_path / "data")
    recognition = RecognitionService(resources)
    context = ClockContext()
    monkeypatch.setattr(battle, "monotonic", lambda: context.now)

    def create(expectations):
        session = tmp_path / "replays" / "np"
        session.mkdir(parents=True)
        frames = []
        for index, (image, point) in enumerate(expectations):
            filename = f"{index}.png"
            assert cv2.imwrite(str(session / filename), image)
            entry = {"file": filename}
            if point is not None:
                entry["expect"] = {"type": "tap", "x": point[0], "y": point[1]}
            frames.append(entry)
        (session / "manifest.json").write_text(json.dumps({
            "version": 1, "device_id": "np", "frames": frames,
        }), encoding="utf-8")
        devices = DeviceService([ReplayBackend(tmp_path / "replays")], EventLog(), frame_normalizer=FrameNormalizer())
        devices.connect("replay", "np")
        return devices

    def recognize(screenshot, *_args, **_kwargs):
        blocks = recognize_card_blocks(recognition, screenshot, "CH")
        cards = [
            {"slot": slot, "code": code, "servant_position": int(code[0]), "color": code[1],
             "stars": 0, "available": slot not in blocks["faces"]}
            for slot, code in enumerate(("1B", "2A", "3Q", "1A", "2B"), start=1)
        ]
        return {"complete": True, "recognized_count": 5, "cards": cards}

    return SimpleNamespace(frame=frame, create=create, recognition=recognition, context=context,
                           cards=SimpleNamespace(recognize=recognize))


def tap_step(role, point):
    return {"type": "tap", "role": role, "x": point[0], "y": point[1]}


@pytest.mark.parametrize("mode", ["direct", "strategy", "no_chain", "extra"])
def test_failed_np_selection_returns_and_uses_available_face_cards(replay_factory, mode):
    env = replay_factory
    command = env.frame(blocked_nps=[1], blocked_faces=[4])
    ready = env.frame(command=False)
    expectations = [(ready, ATTACK_POINT)]
    expectations += [(command, point) for point in (NP_POINTS[0], FACE_CARD_POINTS[0], FACE_CARD_POINTS[1], COMMAND_CARD_BACK_POINT)]
    expectations += [(ready, ATTACK_POINT)]
    expectations += [(command, point) for point in FACE_CARD_POINTS[:3]]
    expectations += [(ready, None)]
    devices = env.create(expectations)
    steps = [tap_step("attack", ATTACK_POINT)]
    if mode in {"direct", "extra"}:
        steps += [tap_step("np_1", NP_POINTS[0]), tap_step("face_card_1", FACE_CARD_POINTS[0]), tap_step("face_card_2", FACE_CARD_POINTS[1])]
    else:
        strategy = {"card1": {"type": 1, "cards": ["1B"]},
                    "card2": {"type": 1, "cards": ["2A"]}, "card3": {"type": 2}}
        steps.append({"type": "strategy", "strategies": [strategy], "preselected_nps": [1], "avoid_chain": mode == "no_chain"})

    if mode == "extra":
        count = battle._execute_extra_turn(
            env.context, devices, env.recognition, None, "CH", [],
            {"actions": [], "command_phase": {"steps": steps}},
            ["battle/CH/Arts.png"], "battle/CH/attack.png", 0.9, 3, 0.1, 0,
        )
    else:
        count = battle._execute_command_phase(
            env.context, devices, env.recognition, env.cards if mode != "direct" else None,
            "CH", [], steps, 0.9, 3, 0.1, 0,
        )
    assert count == 9
    assert np.array_equal(cv2.imdecode(np.frombuffer(devices.snapshot(), dtype=np.uint8), cv2.IMREAD_COLOR), ready)
    recovery = [data for kind, data in env.context.events if kind == "np_selection_recovery"]
    assert len(recovery) == 1
    assert recovery[0]["unavailable_nps"] == [1]


@pytest.mark.parametrize("blocked,still_command", [([], True), ([2], True), ([1], False)])
def test_np_recovery_does_not_retry_without_confirmed_selected_np_block(replay_factory, blocked, still_command):
    env = replay_factory
    ready = env.frame(command=False)
    command = env.frame(blocked_nps=blocked)
    devices = env.create([
        (ready, ATTACK_POINT), (command, NP_POINTS[0]),
        (command, FACE_CARD_POINTS[0]), (command, FACE_CARD_POINTS[1]),
        (command if still_command else ready, None),
    ])
    steps = [tap_step(role, point) for role, point in (
        ("attack", ATTACK_POINT), ("np_1", NP_POINTS[0]),
        ("face_card_1", FACE_CARD_POINTS[0]), ("face_card_2", FACE_CARD_POINTS[1]),
    )]
    count = battle._execute_command_phase(
        env.context, devices, env.recognition, None, "CH", [], steps, 0.9, 3, 0.1, 0,
    )
    assert count == 4
    assert not any(kind == "np_selection_recovery" for kind, _data in env.context.events)


def test_direct_np_recovery_preserves_working_np_and_skips_blocked_face(replay_factory):
    env = replay_factory
    ready = env.frame(command=False)
    command = env.frame(blocked_nps=[1], blocked_faces=[2])
    first = [NP_POINTS[0], NP_POINTS[1], FACE_CARD_POINTS[0]]
    retry = [NP_POINTS[1], FACE_CARD_POINTS[0], FACE_CARD_POINTS[2]]
    devices = env.create([
        (ready, ATTACK_POINT), *[(command, point) for point in first],
        (command, COMMAND_CARD_BACK_POINT), (ready, ATTACK_POINT),
        *[(command, point) for point in retry], (ready, None),
    ])
    steps = [tap_step(role, point) for role, point in (
        ("attack", ATTACK_POINT), ("np_1", NP_POINTS[0]),
        ("np_2", NP_POINTS[1]), ("face_card_1", FACE_CARD_POINTS[0]),
    )]
    count = battle._execute_command_phase(
        env.context, devices, env.recognition, None, "CH", [], steps, 0.9, 3, 0.1, 0,
    )
    assert count == 9


def test_np_recovery_is_bounded_by_three_distinct_np_positions(replay_factory):
    env = replay_factory
    ready = env.frame(command=False)
    expectations = [(ready, ATTACK_POINT)]
    for position in (1, 2, 3):
        command = env.frame(blocked_nps=[position])
        expectations += [(command, point) for point in (
            NP_POINTS[position - 1], FACE_CARD_POINTS[0], FACE_CARD_POINTS[1], COMMAND_CARD_BACK_POINT,
        )]
        expectations.append((ready, ATTACK_POINT))
    command = env.frame()
    expectations += [(command, point) for point in FACE_CARD_POINTS[:3]]
    expectations.append((ready, None))
    devices = env.create(expectations)
    strategy = {"card1": {"type": 0, "cards": [1, 2, 3]},
                "card2": {"type": 1, "cards": ["1B"]}, "card3": {"type": 1, "cards": ["2A"]}}
    steps = [tap_step("attack", ATTACK_POINT), {"type": "strategy", "strategies": [strategy]}]
    count = battle._execute_command_phase(
        env.context, devices, env.recognition, env.cards, "CH", [], steps, 0.9, 3, 0.1, 0,
    )
    assert count == 19
    recovery = [data for kind, data in env.context.events if kind == "np_selection_recovery"]
    assert [data["unavailable_nps"] for data in recovery] == [[1], [1, 2], [1, 2, 3]]


def test_np_recovery_stops_when_back_does_not_restore_battle(replay_factory):
    env = replay_factory
    ready = env.frame(command=False)
    command = env.frame(blocked_nps=[1])
    devices = env.create([
        (ready, ATTACK_POINT), (command, NP_POINTS[0]),
        (command, FACE_CARD_POINTS[0]), (command, FACE_CARD_POINTS[1]),
        (command, COMMAND_CARD_BACK_POINT), (command, None),
    ])
    steps = [tap_step(role, point) for role, point in (
        ("attack", ATTACK_POINT), ("np_1", NP_POINTS[0]),
        ("face_card_1", FACE_CARD_POINTS[0]), ("face_card_2", FACE_CARD_POINTS[1]),
    )]
    with pytest.raises(TimeoutError, match="Battle controls did not become ready"):
        battle._execute_command_phase(
            env.context, devices, env.recognition, None, "CH", [], steps, 0.9, 1, 0.1, 0,
        )
    roles = [data["role"] for kind, data in env.context.events if kind == "device_action"]
    assert roles == ["attack", "np_1", "face_card_1", "face_card_2", "np_recovery_back"]


def test_np_recovery_keeps_two_second_grace_with_short_recognition_timeout(replay_factory):
    env = replay_factory
    ready = env.frame(command=False)
    command = env.frame(blocked_nps=[1])
    devices = env.create([
        (ready, ATTACK_POINT), (command, NP_POINTS[0]),
        (command, FACE_CARD_POINTS[0]), (command, FACE_CARD_POINTS[1]),
        (command, COMMAND_CARD_BACK_POINT), (ready, ATTACK_POINT),
        *[(command, point) for point in FACE_CARD_POINTS[:3]], (ready, None),
    ])
    steps = [tap_step(role, point) for role, point in (
        ("attack", ATTACK_POINT), ("np_1", NP_POINTS[0]),
        ("face_card_1", FACE_CARD_POINTS[0]), ("face_card_2", FACE_CARD_POINTS[1]),
    )]
    battle._execute_command_phase(
        env.context, devices, env.recognition, None, "CH", [], steps, 0.9, 0.25, 0.05, 0,
    )
    assert next(time for role, time in env.context.action_times if role == "np_recovery_back") >= 2.0


def test_np_recovery_keeps_other_confirmed_np_blocks_for_strategy_retry(replay_factory):
    env = replay_factory
    ready = env.frame(command=False)
    command = env.frame(blocked_nps=[1, 2])
    devices = env.create([
        (ready, ATTACK_POINT), (command, NP_POINTS[0]),
        (command, FACE_CARD_POINTS[0]), (command, FACE_CARD_POINTS[1]),
        (command, COMMAND_CARD_BACK_POINT), (ready, ATTACK_POINT),
        (command, NP_POINTS[2]), (command, FACE_CARD_POINTS[0]),
        (command, FACE_CARD_POINTS[1]), (ready, None),
    ])
    strategy = {"card1": {"type": 0, "cards": [1, 2, 3]},
                "card2": {"type": 1, "cards": ["1B"]}, "card3": {"type": 1, "cards": ["2A"]}}
    count = battle._execute_command_phase(
        env.context, devices, env.recognition, env.cards, "CH", [],
        [tap_step("attack", ATTACK_POINT), {"type": "strategy", "strategies": [strategy]}],
        0.9, 3, 0.1, 0,
    )
    assert count == 9
    recovery = [data for kind, data in env.context.events if kind == "np_selection_recovery"]
    assert recovery[0]["unavailable_nps"] == [1, 2]
