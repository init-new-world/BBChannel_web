import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.automation.completion import BATTLE_COMPLETE_JOB_KIND, register_completion_job
from webapp.devices.coordinates import FrameNormalizer
from webapp.devices.replay import ReplayBackend
from webapp.runtime import JobDatabase, JobManager, JobStatus
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService


def _pattern(size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, size[0] - 3, size[1] - 3), outline=(245, 220, 70), width=2)
    draw.line((3, size[1] - 4, size[0] - 4, 3), fill=(40, 220, 235), width=2)
    return image


def _drop_template() -> Image.Image:
    image = _pattern((176, 193), (165, 105, 45))
    draw = ImageDraw.Draw(image)
    draw.ellipse((52, 58, 76, 86), fill="white", outline="black", width=2)
    draw.rectangle((98, 110, 124, 136), fill=(35, 85, 195), outline="black", width=2)
    return image


def _create_completion_assets(
    assets: Path,
    data: Path,
    *,
    drop_template: Image.Image | None = None,
    config: dict | None = None,
) -> None:
    battle_assets = assets / "battle" / "CH"
    interlude_assets = assets / "battle" / "Interlude" / "CH"
    main_story_assets = assets / "battle" / "MainStory" / "CH"
    drop_assets = assets / "drop"
    settings = data / "settings"
    battle_assets.mkdir(parents=True)
    interlude_assets.mkdir(parents=True)
    main_story_assets.mkdir(parents=True)
    drop_assets.mkdir(parents=True)
    settings.mkdir(parents=True)

    next_button = _pattern((100, 40), (80, 65, 150))
    run_again = _pattern((120, 50), (35, 120, 170))
    friendship_level_10 = _pattern((90, 45), (145, 75, 105))
    friendship_max = _pattern((121, 46), (35, 155, 95))
    friendship_up = _pattern((160, 80), (115, 85, 145))
    friendship_up_legacy = _pattern((110, 54), (175, 125, 45))
    friendship_up_legacy_large = _pattern((172, 188), (195, 165, 65))
    finish_without_friend = _pattern((174, 52), (75, 135, 65))
    apply_for_friend = _pattern((308, 69), (165, 65, 105))
    reconnect = _pattern((114, 53), (125, 45, 165))
    battle_finish = _pattern((150, 60), (55, 105, 165))
    goto_interlude = _pattern((180, 48), (95, 75, 165))
    goto_stage = _pattern((220, 52), (155, 105, 45))
    next_story = _pattern((161, 100), (105, 145, 65))
    ce_detail = _pattern((76, 36), (205, 115, 75))
    bond_ce = _pattern((38, 38), (95, 185, 155))
    not_available = _pattern((100, 38), (185, 85, 95))
    list_update = _pattern((92, 38), (65, 175, 135))
    need_skip = _pattern((48, 48), (145, 115, 205))
    need_skip_1 = _pattern((84, 38), (215, 145, 85))
    menu_btn = _pattern((96, 62), (45, 95, 205))
    ks_btn = _pattern((86, 38), (225, 95, 55))
    rwks_btn = _pattern((136, 38), (55, 195, 95))
    list_update_btn = _pattern((58, 38), (195, 55, 185))
    apple_close = _pattern((60, 38), (125, 185, 55))
    start_task = _pattern((110, 50), (215, 65, 145))
    drop_item = drop_template if drop_template is not None else _pattern((40, 40), (165, 105, 45))
    next_button.save(battle_assets / "next.png")
    run_again.save(battle_assets / "run_again.png")
    friendship_level_10.save(battle_assets / "jblevel10.png")
    friendship_max.save(battle_assets / "jbMax.png")
    friendship_up.save(battle_assets / "relationship_up.png")
    friendship_up_legacy.save(battle_assets / "jbup.png")
    friendship_up_legacy_large.save(battle_assets / "jbup1.png")
    finish_without_friend.save(battle_assets / "friend_apply.png")
    apply_for_friend.save(battle_assets / "friend_apply_1.png")
    reconnect.save(battle_assets / "reconnect.png")
    battle_finish.save(battle_assets / "battleFinish.png")
    ce_detail.save(battle_assets / "nengli.png")
    bond_ce.save(battle_assets / "jblz.png")
    not_available.save(battle_assets / "notAvailable.png")
    list_update.save(battle_assets / "listupdate.png")
    need_skip.save(battle_assets / "needSkip.png")
    need_skip_1.save(battle_assets / "needSkip1.png")
    menu_btn.save(battle_assets / "menu.png")
    ks_btn.save(battle_assets / "ks.png")
    rwks_btn.save(battle_assets / "rwks.png")
    list_update_btn.save(battle_assets / "listupdatebtn.png")
    apple_close.save(battle_assets / "apple_close.png")
    start_task.save(battle_assets / "start_task.png")
    goto_interlude.save(interlude_assets / "gotoInterlude.png")
    goto_stage.save(interlude_assets / "gotoStage.png")
    next_story.save(main_story_assets / "nextOne.png")
    Image.new("L", next_story.size, 255).save(
        main_story_assets / "nextOneMask.png"
    )
    drop_item.save(drop_assets / "item.png")
    (data / "servant_info_CH.json").write_text("{}", encoding="utf-8")
    (settings / "completion.json").write_text(
        json.dumps({"server": "CH", **(config or {})}),
        encoding="utf-8",
    )


def _run_completion(
    tmp_path: Path,
    frames: list[tuple[Image.Image, dict | None]],
    *,
    config: dict | None = None,
    payload: dict | None = None,
    wait_timeout: float = 3,
    story_candidates: list[list[dict[str, object]]] | None = None,
    drop_template: Image.Image | None = None,
):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "completion"
    session.mkdir(parents=True)
    _create_completion_assets(assets, data, drop_template=drop_template, config=config)

    manifest_frames = []
    for index, (frame, expected) in enumerate(frames):
        filename = f"{index}.png"
        frame.save(session / filename)
        entry = {"file": filename}
        if expected is not None:
            entry["expect"] = expected
        manifest_frames.append(entry)
    (session / "manifest.json").write_text(
        json.dumps(
            {"version": 1, "device_id": "completion", "frames": manifest_frames}
        ),
        encoding="utf-8",
    )

    resources = ResourceService(assets, data)
    recognition = RecognitionService(resources)
    if story_candidates is not None:
        match_templates = recognition.match_templates

        def record_story_candidates(screenshot, candidates):
            story_candidates.append([dict(candidate) for candidate in candidates])
            return match_templates(screenshot, candidates)

        recognition.match_templates = record_story_candidates
    devices = DeviceService(
        [ReplayBackend(tmp_path / "replays")],
        EventLog(),
        frame_normalizer=FrameNormalizer(),
    )
    devices.connect("replay", "completion")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_completion_job(
            manager,
            ScriptDataService(data),
            devices,
            recognition,
            resources,
        )
        job = manager.start(
            BATTLE_COMPLETE_JOB_KIND,
            {
                "setting_name": "completion",
                "timeout_seconds": 2,
                "poll_interval": 0,
                "action_wait_seconds": 0,
                **(payload or {}),
            },
            device_key="replay:completion",
        )
        return manager.wait(job.job_id, timeout=wait_timeout)


def test_completion_advances_results_until_repeat_is_available(tmp_path: Path):
    pytest.importorskip("cv2")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    next_frame = base.copy()
    next_frame.paste(_pattern((100, 40), (80, 65, 150)), (600, 500))
    repeat_frame = base.copy()
    repeat_frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))

    result = _run_completion(
        tmp_path,
        [
            (next_frame, {"type": "tap", "x": 650, "y": 520}),
            (repeat_frame, None),
        ],
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is True
    assert result.result["repeated"] is False
    assert result.result["actions"] == ["next"]
    assert result.result["attempts"] == 2


def test_completion_advances_generic_battle_result_screen(tmp_path: Path):
    pytest.importorskip("cv2")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    result_frame = base.copy()
    result_frame.paste(_pattern((150, 60), (55, 105, 165)), (565, 30))
    repeat_frame = base.copy()
    repeat_frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))

    result = _run_completion(
        tmp_path,
        [
            (result_frame, {"type": "tap", "x": 640, "y": 650}),
            (repeat_frame, None),
        ],
        payload={"timeout_seconds": 10},
        wait_timeout=10,
    )

    assert result.status == JobStatus.SUCCEEDED, result.error
    assert result.result["actions"] == ["settlement_continue"]


def test_completion_prefers_story_navigation_over_generic_result_tap(tmp_path: Path):
    pytest.importorskip("cv2")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    frame.paste(_pattern((150, 60), (55, 105, 165)), (565, 30))
    frame.paste(_pattern((220, 52), (155, 105, 45)), (700, 540))

    result = _run_completion(
        tmp_path,
        [(frame, {"type": "tap", "x": 810, "y": 566})],
        wait_timeout=10,
    )

    assert result.status == JobStatus.SUCCEEDED, result.error
    assert result.result["reason"] == "story_navigation"
    assert result.result["actions"] == ["goto_stage"]


def test_completion_can_start_the_next_run(tmp_path: Path):
    pytest.importorskip("cv2")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))

    result = _run_completion(
        tmp_path,
        [(frame, {"type": "tap", "x": 960, "y": 625})],
        payload={"repeat": True},
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is True
    assert result.result["repeated"] is True
    assert result.result["actions"] == ["run_again"]


def test_completion_stops_when_full_friendship_is_reached(tmp_path: Path):
    pytest.importorskip("cv2")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    frame.paste(_pattern((90, 45), (145, 75, 105)), (500, 350))

    result = _run_completion(
        tmp_path,
        [(frame, None)],
        config={"fullFriendshipStop": 1},
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is False
    assert result.result["stopped"] is True
    assert result.result["reason"] == "full_friendship"
    assert result.result["actions"] == []


def test_completion_does_not_false_trigger_jblevel10_on_loot_screen_with_next_button(tmp_path: Path):
    pytest.importorskip("cv2")
    loot_frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    # Simulate a half-scale false-positive pattern inside the loot grid while Next is visible.
    loot_frame.paste(_pattern((90, 45), (145, 75, 105)).resize((45, 22)), (508, 507))
    loot_frame.paste(_pattern((100, 40), (80, 65, 150)), (1045, 613))
    done_frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    done_frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))

    result = _run_completion(
        tmp_path,
        [
            (loot_frame, {"type": "tap", "x": 1095, "y": 633}),
            (done_frame, None),
        ],
        config={"fullFriendshipStop": 1},
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is True
    assert result.result["actions"] == ["next"]


def test_completion_stops_when_friendship_maximum_marker_is_reached(tmp_path: Path):
    pytest.importorskip("cv2")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    frame.paste(_pattern((121, 46), (35, 155, 95)), (500, 350))

    result = _run_completion(
        tmp_path,
        [(frame, None)],
        config={"fullFriendshipStop": 1},
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is False
    assert result.result["stopped"] is True
    assert result.result["reason"] == "full_friendship"
    assert result.result["actions"] == []


@pytest.mark.parametrize("slot", range(1, 6))
def test_completion_ignores_only_configured_full_friendship_reward_positions(tmp_path: Path, slot: int):
    pytest.importorskip("cv2")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    marker = _pattern((121, 46), (35, 155, 95)).resize((81, 31))
    x = round((177 + 334 * (slot - 1)) * 2 / 3) + 20
    frame.paste(marker, (x, 490))
    frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))
    result = _run_completion(
        tmp_path,
        [(frame, None)],
        config={"fullFriendshipStop": True, "ignoreFriendship": f"x{slot}06"},
    )
    assert result.status == JobStatus.SUCCEEDED, result.error
    assert result.result["complete"] is True
    assert result.result["actions"] == []


def test_completion_still_stops_for_another_full_friendship_position(tmp_path: Path):
    pytest.importorskip("cv2")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    marker = _pattern((121, 46), (35, 155, 95)).resize((81, 31))
    frame.paste(marker, (140, 490))
    frame.paste(marker, (585, 490))
    result = _run_completion(
        tmp_path,
        [(frame, None)],
        config={"fullFriendshipStop": True, "ignoreFriendship": "1"},
    )
    assert result.status == JobStatus.SUCCEEDED, result.error
    assert result.result["reason"] == "full_friendship"


def test_completion_does_not_ignore_friendship_level_ten_dialog(tmp_path: Path):
    pytest.importorskip("cv2")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    frame.paste(_pattern((90, 45), (145, 75, 105)), (140, 485))
    result = _run_completion(
        tmp_path,
        [(frame, None)],
        config={"fullFriendshipStop": True, "ignoreFriendship": "12345"},
    )
    assert result.status == JobStatus.SUCCEEDED, result.error
    assert result.result["reason"] == "full_friendship"


def test_completion_advances_friendship_level_dialog(tmp_path: Path):
    pytest.importorskip("cv2")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    friendship_frame = base.copy()
    friendship_frame.paste(_pattern((160, 80), (115, 85, 145)), (400, 250))
    repeat_frame = base.copy()
    repeat_frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))

    result = _run_completion(
        tmp_path,
        [
            (friendship_frame, {"type": "tap", "x": 480, "y": 290}),
            (repeat_frame, None),
        ],
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["actions"] == ["relationship_up"]


def test_completion_advances_legacy_friendship_level_dialogs(tmp_path: Path):
    pytest.importorskip("cv2")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    friendship_frame = base.copy()
    friendship_frame.paste(_pattern((110, 54), (175, 125, 45)), (400, 250))
    friendship_large_frame = base.copy()
    friendship_large_frame.paste(
        _pattern((172, 188), (195, 165, 65)),
        (500, 200),
    )
    repeat_frame = base.copy()
    repeat_frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))

    result = _run_completion(
        tmp_path,
        [
            (friendship_frame, {"type": "tap", "x": 455, "y": 277}),
            (friendship_large_frame, {"type": "tap", "x": 586, "y": 294}),
            (repeat_frame, None),
        ],
        payload={"timeout_seconds": 10},
        wait_timeout=10,
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["actions"] == ["relationship_up", "relationship_up"]


@pytest.mark.parametrize(
    (
        "add_friend",
        "template_size",
        "template_color",
        "expected_point",
        "expected_action",
    ),
    [
        (False, (174, 52), (75, 135, 65), (287, 526), "finish_without_friend"),
        (True, (308, 69), (165, 65, 105), (854, 534), "apply_for_friend"),
    ],
)
def test_completion_handles_friend_request_page(
    tmp_path: Path,
    add_friend: bool,
    template_size: tuple[int, int],
    template_color: tuple[int, int, int],
    expected_point: tuple[int, int],
    expected_action: str,
):
    pytest.importorskip("cv2")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    friend_frame = base.copy()
    left, top = (200, 500) if not add_friend else (700, 500)
    friend_frame.paste(_pattern(template_size, template_color), (left, top))
    repeat_frame = base.copy()
    repeat_frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))

    result = _run_completion(
        tmp_path,
        [
            (
                friend_frame,
                {"type": "tap", "x": expected_point[0], "y": expected_point[1]},
            ),
            (repeat_frame, None),
        ],
        config={"addFriend": int(add_friend)},
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["actions"] == [expected_action]


def test_completion_recovers_from_network_reconnect_prompt(tmp_path: Path):
    pytest.importorskip("cv2")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    reconnect_frame = base.copy()
    reconnect_frame.paste(_pattern((114, 53), (125, 45, 165)), (580, 380))
    repeat_frame = base.copy()
    repeat_frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))

    result = _run_completion(
        tmp_path,
        [
            (reconnect_frame, {"type": "tap", "x": 637, "y": 406}),
            (repeat_frame, None),
        ],
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["actions"] == ["reconnect"]


def test_completion_counts_configured_drops_from_previous_runs(tmp_path: Path):
    pytest.importorskip("cv2")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    drop_template = _drop_template()
    drop_item = drop_template.resize((117, 129), Image.Resampling.BILINEAR)
    frame.paste(drop_item, (300, 250))
    frame.paste(drop_item, (700, 450))

    result = _run_completion(
        tmp_path,
        [(frame, None)],
        config={
            "dropStopNum": 3,
            "dropImage": "E:/old/BBchannel/assets/drop/item.png",
        },
        payload={"initial_drop_count": 1},
        drop_template=drop_template,
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is False
    assert result.result["stopped"] is True
    assert result.result["reason"] == "drop_limit"
    assert result.result["drop_count"] == 3


def test_completion_counts_animated_drop_screen_only_once(tmp_path: Path):
    pytest.importorskip("cv2")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    drop_template = _drop_template()
    drop_item = drop_template.resize((117, 129), Image.Resampling.BILINEAR)
    first_drop_frame = base.copy()
    first_drop_frame.paste(drop_item, (300, 250))
    first_drop_frame.paste(drop_item, (700, 450))
    first_drop_frame.paste(_pattern((100, 40), (80, 65, 150)), (600, 500))
    animated_drop_frame = first_drop_frame.copy()
    animated_drop_frame.putpixel((50, 50), (19, 24, 32))
    animated_drop_frame.paste(
        _pattern((120, 50), (35, 120, 170)),
        (900, 600),
    )

    result = _run_completion(
        tmp_path,
        [
            (first_drop_frame, {"type": "tap", "x": 650, "y": 520}),
            (animated_drop_frame, None),
        ],
        config={"dropStopNum": 3, "dropImage": "assets/drop/item.png"},
        drop_template=drop_template,
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is True
    assert result.result["drop_count"] == 2


@pytest.mark.parametrize(
    ("template_size", "template_color", "reason", "action"),
    [
        pytest.param(
            (180, 48),
            (95, 75, 165),
            "interlude_navigation",
            "goto_interlude",
            id="goto-interlude",
        ),
        pytest.param(
            (220, 52),
            (155, 105, 45),
            "story_navigation",
            "goto_stage",
            id="goto-stage",
        ),
        pytest.param(
            (161, 100),
            (105, 145, 65),
            "main_story_navigation",
            "next_story",
            id="next-story",
        ),
    ],
)
def test_completion_handles_post_battle_story_navigation(
    tmp_path: Path,
    template_size: tuple[int, int],
    template_color: tuple[int, int, int],
    reason: str,
    action: str,
):
    pytest.importorskip("cv2")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    frame.paste(_pattern(template_size, template_color), (700, 540))

    result = _run_completion(
        tmp_path,
        [
            (
                frame,
                {
                    "type": "tap",
                    "x": 700 + template_size[0] // 2,
                    "y": 540 + template_size[1] // 2,
                },
            )
        ],
        wait_timeout=10,
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is True
    assert result.result["stopped"] is True
    assert result.result["reason"] == reason
    assert result.result["actions"] == [action]


def test_completion_uses_mask_for_main_story_navigation(tmp_path: Path):
    pytest.importorskip("cv2")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    frame.paste(_pattern((161, 100), (105, 145, 65)), (700, 540))
    story_candidates: list[list[dict[str, object]]] = []

    result = _run_completion(
        tmp_path,
        [(frame, {"type": "tap", "x": 780, "y": 590})],
        story_candidates=story_candidates,
        wait_timeout=10,
    )

    assert result.status == JobStatus.SUCCEEDED
    assert story_candidates[0][2]["mask_path"] == (
        "battle/MainStory/CH/nextOneMask.png"
    )
    assert "mask_path" not in story_candidates[0][0]
    assert "mask_path" not in story_candidates[0][1]


def test_completion_ignore_full_friendship_bypasses_bond_stop(tmp_path: Path):
    pytest.importorskip("cv2")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    repeat_frame = base.copy()
    repeat_frame.paste(_pattern((90, 36), (185, 50, 50)), (250, 300))
    repeat_frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))

    result = _run_completion(
        tmp_path,
        [(repeat_frame, None)],
        config={"jbstop": 1},
        payload={"ignore_full_friendship": True},
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is True
    assert result.result.get("stopped") is not True


def test_completion_closes_non_bond_craft_essence_detail_screen(tmp_path: Path):
    pytest.importorskip("cv2")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    ce_frame = base.copy()
    ce_frame.paste(_pattern((76, 36), (205, 115, 75)), (550, 120))
    repeat_frame = base.copy()
    repeat_frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))

    result = _run_completion(
        tmp_path,
        [
            (ce_frame, {"type": "tap", "x": 43, "y": 43}),
            (repeat_frame, None),
        ],
        config={"fullFriendshipStop": 1},
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is True
    assert result.result["actions"] == ["close_drop_ce"]


def test_completion_stops_on_bond_craft_essence_detail_screen_when_configured(
    tmp_path: Path,
):
    pytest.importorskip("cv2")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    frame.paste(_pattern((76, 36), (205, 115, 75)), (550, 120))
    frame.paste(_pattern((38, 38), (95, 185, 155)), (780, 250))

    result = _run_completion(
        tmp_path,
        [(frame, None)],
        config={"fullFriendshipStop": 1},
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is False
    assert result.result["stopped"] is True
    assert result.result["reason"] == "full_friendship"
    assert result.result["actions"] == []


def test_completion_dismisses_friend_full_dialog_and_falls_back_to_finish_without_friend(
    tmp_path: Path,
):
    pytest.importorskip("cv2")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    friend_apply_frame = base.copy()
    friend_apply_frame.paste(_pattern((174, 52), (75, 135, 65)), (200, 500))
    friend_apply_frame.paste(_pattern((308, 69), (165, 65, 105)), (700, 500))
    friend_full_frame = base.copy()
    friend_full_frame.paste(_pattern((100, 38), (185, 85, 95)), (590, 545))
    repeat_frame = base.copy()
    repeat_frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))

    result = _run_completion(
        tmp_path,
        [
            (friend_apply_frame, {"type": "tap", "x": 854, "y": 534}),
            (friend_full_frame, {"type": "tap", "x": 640, "y": 564}),
            (friend_apply_frame, {"type": "tap", "x": 287, "y": 526}),
            (repeat_frame, None),
        ],
        config={"addFriend": 1},
        payload={"timeout_seconds": 10},
        wait_timeout=10,
    )

    assert result.status == JobStatus.SUCCEEDED, result.error
    assert result.result["actions"] == [
        "apply_for_friend",
        "dismiss_friend_full",
        "finish_without_friend",
    ]


def test_completion_closes_reward_dialog_and_skips_post_battle_cutscene(
    tmp_path: Path,
):
    pytest.importorskip("cv2")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    reward_dialog_frame = base.copy()
    reward_dialog_frame.paste(_pattern((100, 38), (185, 85, 95)), (380, 545))
    skip_prompt_frame = base.copy()
    skip_prompt_frame.paste(_pattern((84, 38), (215, 145, 85)), (1140, 20))
    skip_confirm_frame = base.copy()
    skip_confirm_frame.paste(_pattern((92, 38), (65, 175, 135)), (780, 545))
    repeat_frame = base.copy()
    repeat_frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))

    result = _run_completion(
        tmp_path,
        [
            (reward_dialog_frame, {"type": "tap", "x": 430, "y": 564}),
            (skip_prompt_frame, {"type": "tap", "x": 1197, "y": 40}),
            (skip_confirm_frame, {"type": "tap", "x": 826, "y": 564}),
            (repeat_frame, None),
        ],
        payload={"timeout_seconds": 10},
        wait_timeout=10,
    )

    assert result.status == JobStatus.SUCCEEDED, result.error
    assert result.result["actions"] == [
        "close_reward_dialog",
        "story_skip",
        "story_skip_confirm",
    ]


def test_completion_finishes_on_menu_screen_without_repeat(tmp_path: Path):
    pytest.importorskip("cv2")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    frame.paste(_pattern((96, 62), (45, 95, 205)), (1100, 620))

    result = _run_completion(
        tmp_path,
        [(frame, None)],
        payload={"repeat": False, "timeout_seconds": 10},
        wait_timeout=10,
    )

    assert result.status == JobStatus.SUCCEEDED, result.error
    assert result.result["complete"] is True
    assert result.result["repeated"] is False
    assert result.result["actions"] == []


def test_completion_reenters_quest_from_menu_screen_when_repeat_enabled(
    tmp_path: Path,
):
    pytest.importorskip("cv2")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    menu_frame = base.copy()
    menu_frame.paste(_pattern((96, 62), (45, 95, 205)), (1100, 620))
    ks_frame = base.copy()
    ks_frame.paste(_pattern((86, 38), (225, 95, 55)), (795, 545))
    assist_frame = base.copy()
    assist_frame.paste(_pattern((58, 38), (195, 55, 185)), (900, 110))

    result = _run_completion(
        tmp_path,
        [
            (menu_frame, {"type": "tap", "x": 1048, "y": 172}),
            (ks_frame, {"type": "tap", "x": 838, "y": 564}),
            (assist_frame, None),
        ],
        payload={"repeat": True, "timeout_seconds": 10},
        wait_timeout=10,
    )

    assert result.status == JobStatus.SUCCEEDED, result.error
    assert result.result["complete"] is True
    assert result.result["repeated"] is True
    assert result.result["actions"] == ["reenter_quest", "confirm_quest_start"]


def test_completion_stops_on_team_restriction_during_quest_reentry(
    tmp_path: Path,
):
    pytest.importorskip("cv2")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    menu_frame = base.copy()
    menu_frame.paste(_pattern((96, 62), (45, 95, 205)), (1100, 620))
    restriction_frame = base.copy()
    restriction_frame.paste(_pattern((100, 38), (185, 85, 95)), (590, 580))

    result = _run_completion(
        tmp_path,
        [
            (menu_frame, {"type": "tap", "x": 1048, "y": 172}),
            (restriction_frame, None),
        ],
        payload={"repeat": True, "timeout_seconds": 10},
        wait_timeout=10,
    )

    assert result.status == JobStatus.SUCCEEDED, result.error
    assert result.result["complete"] is False
    assert result.result["stopped"] is True
    assert result.result["reason"] == "team_restriction"
    assert result.result["actions"] == ["reenter_quest"]


def test_completion_timeout_excludes_paused_duration(tmp_path: Path):
    pytest.importorskip("cv2")
    import threading
    import time
    from webapp.automation.completion import create_completion_handler

    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    next_frame = base.copy()
    next_frame.paste(_pattern((100, 40), (80, 65, 150)), (600, 630))
    done_frame = base.copy()
    done_frame.paste(_pattern((120, 50), (35, 120, 170)), (910, 590))

    assets = tmp_path / "assets"
    data = tmp_path / "data"
    _create_completion_assets(assets, data)

    pause_entered = threading.Event()
    resume_allowed = threading.Event()
    snapshot_calls = {"count": 0}

    def _to_bytes(image: Image.Image) -> bytes:
        from io import BytesIO
        buf = BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    frame_bytes = [
        _to_bytes(next_frame),
        _to_bytes(done_frame),
    ]

    class _FakeDevices:
        def snapshot(self) -> bytes:
            idx = snapshot_calls["count"]
            snapshot_calls["count"] += 1
            return frame_bytes[min(idx, len(frame_bytes) - 1)]

        def tap(self, x: int, y: int):
            pause_entered.set()
            resume_allowed.wait(timeout=3)
            from webapp.core.models import OperationResult
            return OperationResult(ok=True, action="tap", message=f"{x},{y}")

    resources = ResourceService(assets, data)
    recognition = RecognitionService(resources)
    script_data = ScriptDataService(data)
    handler = create_completion_handler(script_data, _FakeDevices(), recognition, resources)

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        manager.register(BATTLE_COMPLETE_JOB_KIND, handler)
        record = manager.start(
            BATTLE_COMPLETE_JOB_KIND,
            {
                "setting_name": "completion",
                "repeat": False,
                "timeout_seconds": 1.2,
                "poll_interval": 0.01,
                "action_wait_seconds": 0.0,
            },
        )
        assert pause_entered.wait(timeout=5)
        manager.pause(record.job_id)
        resume_allowed.set()
        time.sleep(1.35)
        manager.resume(record.job_id)
        finished = manager.wait(record.job_id, timeout=5)

    assert finished.status == JobStatus.SUCCEEDED, finished.error
    assert finished.result["complete"] is True
    assert finished.result["actions"] == ["next"]



