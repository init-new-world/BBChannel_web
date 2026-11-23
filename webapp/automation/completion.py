from __future__ import annotations

from io import BytesIO
from time import monotonic
from typing import Any

from PIL import Image, ImageDraw

from webapp.automation.interaction import (
    active_monotonic,
    configured_random_time,
    match_touch_point,
    randomized_touch_point,
    randomized_wait_seconds,
)
from webapp.automation.network import reconnect_if_present
from webapp.core.errors import AppError, ErrorCode
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.drop_templates import DropTemplateService
from webapp.services.drop_recognition import DropRecognizer
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService


BATTLE_COMPLETE_JOB_KIND = "battle.complete"
SETTLEMENT_CONTINUE_POINT = (640, 650)
DROP_CE_ROI = (533, 100, 100, 67)
BOND_CE_ROI = (773, 240, 47, 60)
DROP_CE_CLOSE_POINT = (43, 43)
DROP_CE_CLOSE_SIZE = (47, 61)
FRIEND_FULL_ROI = (553, 533, 180, 60)
REWARD_CLOSE_ROI = (347, 533, 173, 60)
STORY_SKIP_CONFIRM_ROI = (767, 533, 113, 60)
STORY_SKIP_TOP_ROI = (1120, 10, 147, 60)
STORY_SKIP_BOTTOM_ROI = (1193, 573, 67, 80)
STORY_SKIP_POINT = (1197, 40)
STORY_SKIP_SIZE = (100, 46)
MENU_ROI = (1033, 533, 247, 187)
QUEST_REENTER_POINT = (1048, 172)
QUEST_REENTER_SIZE = (5, 17)
QUEST_START_KS_ROI = (780, 533, 120, 60)
QUEST_START_RWKS_ROI = (733, 533, 207, 60)
LIST_UPDATE_BTN_ROI = (820, 100, 147, 60)
APPLE_CLOSE_ROI = (600, 580, 80, 67)
START_QUEST_ROI = (1067, 613, 200, 100)
RUN_AGAIN_720P_ROI = (620, 480, 540, 220)
NEXT_BUTTON_720P_ROI = (560, 460, 720, 260)
FRIEND_APPLY_720P_ROI = (120, 460, 1060, 240)
JB_LEVEL10_720P_ROI = (80, 320, 1120, 220)
JB_MAX_720P_ROI = (80, 320, 1120, 220)
TEAM_RESTRICTION_ROI = (573, 573, 137, 57)
QUEST_UNAVAILABLE_ROI = (573, 533, 137, 60)


def create_completion_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognition: RecognitionService,
    resources: ResourceService,
):

    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        repeat = payload.get("repeat", False)
        if not isinstance(repeat, bool):
            raise ValueError("repeat must be a boolean.")
        ignore_full_friendship = payload.get("ignore_full_friendship", False)
        if not isinstance(ignore_full_friendship, bool):
            raise ValueError("ignore_full_friendship must be a boolean.")
        timeout_seconds = _number(payload, "timeout_seconds", 180, 0.1, 600)
        poll_interval = _number(payload, "poll_interval", 0.5, 0, 10)
        action_wait_seconds = _number(payload, "action_wait_seconds", 0.5, 0, 10)
        initial_drop_count = payload.get("initial_drop_count", 0)
        if (
            isinstance(initial_drop_count, bool)
            or not isinstance(initial_drop_count, int)
            or initial_drop_count < 0
        ):
            raise ValueError("initial_drop_count must be a non-negative integer.")
        plan = script_data.get_setting_plan(setting_name.strip())
        random_touch = bool(plan["run"].get("random_touch"))
        random_time = configured_random_time(plan["run"].get("random_time", 0))
        server = str(plan["server"]).upper()
        drop_limit = int(plan["run"]["drop_stop_num"])
        drop_template = _resolve_drop_template(
            resources,
            plan["run"]["drop_image"],
        )
        drop_recognizer = DropRecognizer(resources, recognition, drop_template) if drop_limit > 0 and drop_template else None
        started = active_monotonic(context, clock=monotonic)
        attempts = 0
        actions: list[str] = []
        drop_count = initial_drop_count
        observed_drop_bounds: list[tuple[int, int, int, int]] = []
        cant_add_friend = False
        reentering_quest = False

        real_recognition = isinstance(recognition, RecognitionService)
        while active_monotonic(context, clock=monotonic) - started <= timeout_seconds:
            elapsed = active_monotonic(context, clock=monotonic) - started
            context.checkpoint(
                "complete_battle",
                progress=min(elapsed / timeout_seconds, 0.95),
            )
            screenshot = device_service.snapshot()
            attempts += 1
            if reconnect_if_present(
                context,
                device_service,
                recognition,
                screenshot,
                server,
                action_wait_seconds=action_wait_seconds,
                random_time=random_time,
                random_touch=random_touch,
            ):
                actions.append("reconnect")
                continue
            frame_is_720p = False
            if real_recognition:
                try:
                    frame_is_720p = recognition.image_size(screenshot) == (1280, 720)
                except Exception:
                    frame_is_720p = False
            if drop_recognizer is not None:
                drop_report = drop_recognizer.recognize(screenshot, check_cancelled=context.raise_if_cancelled)
                drop_matches = drop_report["matches"]
                new_drop_matches = _unseen_drop_matches(
                    drop_matches,
                    observed_drop_bounds,
                )
                drop_count += len(new_drop_matches)
                context.emit(
                    "recognition",
                    "Configured battle drops counted.",
                    data={
                        "frame_drop_count": len(new_drop_matches),
                        "drop_count": drop_count,
                        "drop_limit": drop_limit,
                        "candidate_drop_count": drop_report["candidate_count"],
                        "verified_drop_count": len(drop_matches),
                        "center_rejected_count": drop_report["center_rejected_count"],
                        "offset_rejected_count": drop_report["offset_rejected_count"],
                    },
                )
                if drop_count >= drop_limit:
                    context.checkpoint(
                        "complete",
                        progress=1.0,
                        message="Stopped after reaching the configured drop limit.",
                    )
                    return {
                        "setting_name": setting_name.strip(),
                        "complete": False,
                        "stopped": True,
                        "reason": "drop_limit",
                        "drop_count": drop_count,
                        "actions": actions,
                        "attempts": attempts,
                    }
            drop_ce_screen = _match_optional(
                recognition,
                screenshot,
                f"battle/{server}/nengli.png",
                threshold=0.8,
                roi=DROP_CE_ROI,
            )
            if drop_ce_screen is not None and drop_ce_screen.matched:
                if plan["run"]["full_friendship_stop"] and not ignore_full_friendship:
                    bond_ce_marker = _match_optional(
                        recognition,
                        screenshot,
                        f"battle/{server}/jblz.png",
                        threshold=0.8,
                        roi=BOND_CE_ROI,
                    )
                    if bond_ce_marker is not None and bond_ce_marker.matched:
                        context.checkpoint(
                            "complete",
                            progress=1.0,
                            message="Stopped after reaching full friendship.",
                        )
                        return {
                            "setting_name": setting_name.strip(),
                            "complete": False,
                            "stopped": True,
                            "reason": "full_friendship",
                            "drop_count": drop_count,
                            "actions": actions,
                            "attempts": attempts,
                        }
                operation = device_service.tap(
                    *randomized_touch_point(
                        DROP_CE_CLOSE_POINT,
                        enabled=random_touch,
                        size=DROP_CE_CLOSE_SIZE,
                    )
                )
                actions.append("close_drop_ce")
                context.emit(
                    "device_action",
                    "Closed the dropped Craft Essence detail screen.",
                    data={"role": "close_drop_ce", "operation": operation.to_dict()},
                )
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue

            run_again = _match_optional(
                recognition,
                screenshot,
                f"battle/{server}/run_again.png",
                roi=RUN_AGAIN_720P_ROI if frame_is_720p else None,
            )
            if run_again is not None and run_again.matched:
                if repeat:
                    operation = device_service.tap(
                        *match_touch_point(run_again, enabled=random_touch)
                    )
                    actions.append("run_again")
                    context.emit(
                        "device_action",
                        "Started the next run.",
                        data={"role": "run_again", "operation": operation.to_dict()},
                    )
                    context.sleep(
                        randomized_wait_seconds(action_wait_seconds, random_time)
                    )
                context.checkpoint(
                    "complete",
                    progress=1.0,
                    message="Battle settlement completed.",
                )
                return {
                    "setting_name": setting_name.strip(),
                    "complete": True,
                    "repeated": repeat,
                    "drop_count": drop_count,
                    "actions": actions,
                    "attempts": attempts,
                }

            next_button = _match_optional(
                recognition,
                screenshot,
                f"battle/{server}/next.png",
                roi=NEXT_BUTTON_720P_ROI if frame_is_720p else None,
            )
            if next_button is not None and next_button.matched:
                operation = device_service.tap(
                    *match_touch_point(next_button, enabled=random_touch)
                )
                actions.append("next")
                context.emit(
                    "device_action",
                    "Advanced battle settlement.",
                    data={"role": "next", "operation": operation.to_dict()},
                )
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue

            if plan["run"]["full_friendship_stop"] and not ignore_full_friendship:
                friendship_marker = _match_optional(
                    recognition,
                    screenshot,
                    f"battle/{server}/jblevel10.png",
                    roi=JB_LEVEL10_720P_ROI if frame_is_720p else None,
                    scales=(1.0, 2 / 3),
                )
                if friendship_marker is None or not friendship_marker.matched:
                    friendship_marker = _match_optional(
                        recognition,
                        screenshot,
                        f"battle/{server}/jbMax.png",
                        roi=JB_MAX_720P_ROI if frame_is_720p else None,
                        scales=(1.0, 2 / 3),
                    )
                    ignored_positions = plan["run"].get("ignored_friendship_slots", [])
                    if friendship_marker is not None and friendship_marker.matched and ignored_positions:
                        friendship_marker = _match_optional(
                            recognition,
                            _mask_ignored_friendship(screenshot, ignored_positions),
                            f"battle/{server}/jbMax.png",
                            roi=JB_MAX_720P_ROI if frame_is_720p else None,
                            scales=(1.0, 2 / 3),
                        )
                if friendship_marker is not None and friendship_marker.matched:
                    context.checkpoint(
                        "complete",
                        progress=1.0,
                        message="Stopped after reaching full friendship.",
                    )
                    return {
                        "setting_name": setting_name.strip(),
                        "complete": False,
                        "stopped": True,
                        "reason": "full_friendship",
                        "drop_count": drop_count,
                        "actions": actions,
                        "attempts": attempts,
                    }

            friend_full = (
                None
                if reentering_quest
                else _match_optional(
                    recognition,
                    screenshot,
                    f"battle/{server}/notAvailable.png",
                    roi=FRIEND_FULL_ROI,
                )
            )
            if friend_full is not None and friend_full.matched:
                cant_add_friend = True
                operation = device_service.tap(
                    *match_touch_point(friend_full, enabled=random_touch)
                )
                actions.append("dismiss_friend_full")
                context.emit(
                    "device_action",
                    "Dismissed the friend list full dialog.",
                    data={
                        "role": "dismiss_friend_full",
                        "operation": operation.to_dict(),
                    },
                )
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue

            reward_close = _match_optional(
                recognition,
                screenshot,
                f"battle/{server}/notAvailable.png",
                roi=REWARD_CLOSE_ROI,
            )
            if reward_close is not None and reward_close.matched:
                operation = device_service.tap(
                    *match_touch_point(reward_close, enabled=random_touch)
                )
                actions.append("close_reward_dialog")
                context.emit(
                    "device_action",
                    "Closed the post-battle reward dialog.",
                    data={
                        "role": "close_reward_dialog",
                        "operation": operation.to_dict(),
                    },
                )
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue

            add_friend = bool(plan["run"].get("add_friend")) and not cant_add_friend
            friend_action = (
                "apply_for_friend" if add_friend else "finish_without_friend"
            )
            friend_template = "friend_apply_1.png" if add_friend else "friend_apply.png"
            friend_button = _match_optional(
                recognition,
                screenshot,
                f"battle/{server}/{friend_template}",
                roi=FRIEND_APPLY_720P_ROI if frame_is_720p else None,
            )
            if friend_button is not None and friend_button.matched:
                operation = device_service.tap(
                    *match_touch_point(friend_button, enabled=random_touch)
                )
                actions.append(friend_action)
                context.emit(
                    "device_action",
                    "Handled the post-battle friend request.",
                    data={"role": friend_action, "operation": operation.to_dict()},
                )
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue

            story_skip_confirm = _match_optional(
                recognition,
                screenshot,
                f"battle/{server}/listupdate.png",
                roi=STORY_SKIP_CONFIRM_ROI,
            )
            if story_skip_confirm is not None and story_skip_confirm.matched:
                operation = device_service.tap(
                    *match_touch_point(story_skip_confirm, enabled=random_touch)
                )
                actions.append("story_skip_confirm")
                context.emit(
                    "device_action",
                    "Confirmed post-battle story cutscene skip.",
                    data={
                        "role": "story_skip_confirm",
                        "operation": operation.to_dict(),
                    },
                )
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue

            story_skip_prompt = None
            for template_name, skip_roi in (
                ("needSkip1", STORY_SKIP_TOP_ROI),
                ("needSkip", STORY_SKIP_BOTTOM_ROI),
            ):
                candidate = _match_optional(
                    recognition,
                    screenshot,
                    f"battle/{server}/{template_name}.png",
                    roi=skip_roi,
                )
                if candidate is not None and candidate.matched:
                    story_skip_prompt = candidate
                    break
            if story_skip_prompt is not None:
                operation = device_service.tap(
                    *randomized_touch_point(
                        STORY_SKIP_POINT,
                        enabled=random_touch,
                        size=STORY_SKIP_SIZE,
                    )
                )
                actions.append("story_skip")
                context.emit(
                    "device_action",
                    "Triggered post-battle story cutscene skip.",
                    data={"role": "story_skip", "operation": operation.to_dict()},
                )
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue

            relationship_up = None
            for template_name in ("relationship_up", "jbup", "jbup1"):
                candidate = _match_optional(
                    recognition,
                    screenshot,
                    f"battle/{server}/{template_name}.png",
                )
                if candidate is not None and candidate.matched:
                    relationship_up = candidate
                    break
            if relationship_up is not None:
                operation = device_service.tap(
                    *match_touch_point(relationship_up, enabled=random_touch)
                )
                actions.append("relationship_up")
                context.emit(
                    "device_action",
                    "Advanced friendship level dialog.",
                    data={"role": "relationship_up", "operation": operation.to_dict()},
                )
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue

            story_specs = (
                (
                    f"battle/Interlude/{server}/gotoInterlude.png",
                    "goto_interlude",
                    "interlude_navigation",
                    None,
                ),
                (
                    f"battle/Interlude/{server}/gotoStage.png",
                    "goto_stage",
                    "story_navigation",
                    None,
                ),
                (
                    f"battle/MainStory/{server}/nextOne.png",
                    "next_story",
                    "main_story_navigation",
                    f"battle/MainStory/{server}/nextOneMask.png",
                ),
            )
            story_matches = recognition.match_templates(
                screenshot,
                [
                    {
                        "template_path": template_path,
                        "threshold": 0.85,
                        "roi": (0, 360, 1280, 360),
                        "scales": (1.0, 2 / 3) if frame_is_720p else (1.0, 0.75, 2 / 3, 0.5),
                        **({"mask_path": mask_path} if mask_path else {}),
                    }
                    for template_path, _action, _reason, mask_path in story_specs
                ],
            )
            story_navigation = next(
                (
                    (match, action, reason)
                    for match, (_template_path, action, reason, _mask_path) in zip(
                        story_matches,
                        story_specs,
                        strict=True,
                    )
                    if match.matched
                ),
                None,
            )
            if story_navigation is not None:
                candidate, action, reason = story_navigation
                operation = device_service.tap(
                    *match_touch_point(candidate, enabled=random_touch)
                )
                actions.append(action)
                context.emit(
                    "device_action",
                    "Opened post-battle story content.",
                    data={"role": action, "operation": operation.to_dict()},
                )
                context.sleep(
                    randomized_wait_seconds(action_wait_seconds, random_time)
                )
                context.checkpoint(
                    "complete",
                    progress=1.0,
                    message="Battle settlement opened story content.",
                )
                return {
                    "setting_name": setting_name.strip(),
                    "complete": True,
                    "repeated": False,
                    "stopped": True,
                    "reason": reason,
                    "drop_count": drop_count,
                    "actions": actions,
                    "attempts": attempts,
                }

            if reentering_quest:
                team_restriction = _match_optional(
                    recognition,
                    screenshot,
                    f"battle/{server}/notAvailable.png",
                    threshold=0.8,
                    roi=TEAM_RESTRICTION_ROI,
                )
                if team_restriction is not None and team_restriction.matched:
                    context.checkpoint(
                        "complete",
                        progress=1.0,
                        message="Stopped because quest has party formation restrictions.",
                    )
                    return {
                        "setting_name": setting_name.strip(),
                        "complete": False,
                        "stopped": True,
                        "reason": "team_restriction",
                        "drop_count": drop_count,
                        "actions": actions,
                        "attempts": attempts,
                    }

                quest_unavailable = _match_optional(
                    recognition,
                    screenshot,
                    f"battle/{server}/notAvailable.png",
                    threshold=0.8,
                    roi=QUEST_UNAVAILABLE_ROI,
                )
                if quest_unavailable is not None and quest_unavailable.matched:
                    context.checkpoint(
                        "complete",
                        progress=1.0,
                        message="Stopped because quest entry is unavailable.",
                    )
                    return {
                        "setting_name": setting_name.strip(),
                        "complete": False,
                        "stopped": True,
                        "reason": "quest_unavailable",
                        "drop_count": drop_count,
                        "actions": actions,
                        "attempts": attempts,
                    }

                quest_start = None
                for template_name, start_roi in (
                    ("ks", QUEST_START_KS_ROI),
                    ("rwks", QUEST_START_RWKS_ROI),
                ):
                    candidate = _match_optional(
                        recognition,
                        screenshot,
                        f"battle/{server}/{template_name}.png",
                        threshold=0.8,
                        roi=start_roi,
                    )
                    if candidate is not None and candidate.matched:
                        quest_start = candidate
                        break
                if quest_start is not None:
                    operation = device_service.tap(
                        *match_touch_point(quest_start, enabled=random_touch)
                    )
                    actions.append("confirm_quest_start")
                    context.emit(
                        "device_action",
                        "Confirmed quest entry for the next run.",
                        data={
                            "role": "confirm_quest_start",
                            "operation": operation.to_dict(),
                        },
                    )
                    context.sleep(
                        randomized_wait_seconds(action_wait_seconds, random_time)
                    )
                    continue

                assist_screen = _match_optional(
                    recognition,
                    screenshot,
                    f"battle/{server}/listupdatebtn.png",
                    threshold=0.7,
                    roi=LIST_UPDATE_BTN_ROI,
                )
                apple_prompt = _match_optional(
                    recognition,
                    screenshot,
                    f"battle/{server}/apple_close.png",
                    threshold=0.8,
                    roi=APPLE_CLOSE_ROI,
                )
                if (assist_screen is not None and assist_screen.matched) or (
                    apple_prompt is not None and apple_prompt.matched
                ):
                    context.checkpoint(
                        "complete",
                        progress=1.0,
                        message="Battle settlement completed and re-entered quest.",
                    )
                    return {
                        "setting_name": setting_name.strip(),
                        "complete": True,
                        "repeated": True,
                        "drop_count": drop_count,
                        "actions": actions,
                        "attempts": attempts,
                    }

                prepare_screen = None
                for template_name in ("start_task", "start_battle"):
                    candidate = _match_optional(
                        recognition,
                        screenshot,
                        f"battle/{server}/{template_name}.png",
                        threshold=0.8,
                        roi=START_QUEST_ROI,
                    )
                    if candidate is not None and candidate.matched:
                        prepare_screen = candidate
                        break
                if prepare_screen is not None:
                    context.checkpoint(
                        "complete",
                        progress=1.0,
                        message="Battle settlement completed and reached party preparation.",
                    )
                    return {
                        "setting_name": setting_name.strip(),
                        "complete": True,
                        "repeated": True,
                        "next_stage": "prepare",
                        "drop_count": drop_count,
                        "actions": actions,
                        "attempts": attempts,
                    }

            menu_button = _match_optional(
                recognition,
                screenshot,
                f"battle/{server}/menu.png",
                threshold=0.8,
                roi=MENU_ROI,
            )
            if menu_button is not None and menu_button.matched:
                if not repeat:
                    context.checkpoint(
                        "complete",
                        progress=1.0,
                        message="Battle settlement returned to the terminal screen.",
                    )
                    return {
                        "setting_name": setting_name.strip(),
                        "complete": True,
                        "repeated": False,
                        "drop_count": drop_count,
                        "actions": actions,
                        "attempts": attempts,
                    }
                reentering_quest = True
                operation = device_service.tap(
                    *randomized_touch_point(
                        QUEST_REENTER_POINT,
                        enabled=random_touch,
                        size=QUEST_REENTER_SIZE,
                    )
                )
                actions.append("reenter_quest")
                context.emit(
                    "device_action",
                    "Selected the quest node to start the next run.",
                    data={
                        "role": "reenter_quest",
                        "operation": operation.to_dict(),
                    },
                )
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue

            battle_finish = None
            for template_name in ("battleFinish", "battleFinish1", "fight_end"):
                candidate = _match_optional(
                    recognition,
                    screenshot,
                    f"battle/{server}/{template_name}.png",
                )
                if candidate is not None and candidate.matched:
                    battle_finish = candidate
                    break
            if battle_finish is not None:
                operation = device_service.tap(
                    *randomized_touch_point(
                        SETTLEMENT_CONTINUE_POINT,
                        enabled=random_touch,
                    )
                )
                actions.append("settlement_continue")
                context.emit(
                    "device_action",
                    "Advanced the generic battle result screen.",
                    data={
                        "role": "settlement_continue",
                        "operation": operation.to_dict(),
                    },
                )
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue

            context.emit(
                "recognition",
                "Battle settlement state checked.",
                data={"attempt": attempts, "state": None},
            )
            context.sleep(poll_interval)

        raise TimeoutError(
            f"Battle settlement did not complete within {timeout_seconds:.2f} seconds."
        )

    return handler


def register_completion_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognition: RecognitionService,
    resources: ResourceService,
) -> None:
    if job_manager.has_kind(BATTLE_COMPLETE_JOB_KIND):
        return
    job_manager.register(
        BATTLE_COMPLETE_JOB_KIND,
        create_completion_handler(
            script_data,
            device_service,
            recognition,
            resources,
        ),
        requires_device=True,
    )


def _mask_ignored_friendship(screenshot: bytes, positions: list[int]) -> bytes:
    with Image.open(BytesIO(screenshot)) as source:
        frame = source.convert("RGB")
    scale = min(frame.width / 1920, frame.height / 1080)
    dx = (frame.width - 1920 * scale) / 2
    dy = (frame.height - 1080 * scale) / 2
    draw = ImageDraw.Draw(frame)
    # Original FGObattle.checkBattleEnd masks these five reward-panel regions.
    for position in positions:
        left = 177 + 334 * (position - 1)
        right = 420 + 334 * (position - 1)
        draw.rectangle(
            (round(left * scale + dx), round(730 * scale + dy),
             round(right * scale + dx), round(785 * scale + dy)),
            fill=(0, 0, 0),
        )
    output = BytesIO()
    frame.save(output, format="PNG")
    return output.getvalue()


def _match_optional(
    recognition: RecognitionService,
    screenshot: bytes,
    template_path: str,
    *,
    threshold: float = 0.85,
    roi: tuple[int, int, int, int] | None = None,
    scales: tuple[float, ...] = (1.0, 0.75, 2 / 3, 0.5),
):
    try:
        return recognition.match_template(
            screenshot,
            template_path,
            threshold=threshold,
            roi=roi,
            scales=scales,
        )
    except AppError as exc:
        if exc.code == ErrorCode.TEMPLATE_NOT_FOUND:
            return None
        raise


def _number(
    payload: dict[str, Any],
    key: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number.")
    result = float(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}.")
    return result


def _resolve_drop_template(
    resources: ResourceService,
    configured_path: object,
) -> str | None:
    return DropTemplateService(resources).resolve(configured_path)


def _unseen_drop_matches(
    matches: list[Any],
    observed_bounds: list[tuple[int, int, int, int]],
) -> list[Any]:
    unseen = []
    for match in matches:
        left, top = match.top_left
        width, height = match.size
        bounds = (left, top, width, height)
        center_x = left + width / 2
        center_y = top + height / 2
        if any(
            abs(center_x - (seen_left + seen_width / 2)) <= max(width, seen_width) / 2
            and abs(center_y - (seen_top + seen_height / 2)) <= max(height, seen_height) / 2
            for seen_left, seen_top, seen_width, seen_height in observed_bounds
        ):
            continue
        observed_bounds.append(bounds)
        unseen.append(match)
    return unseen
