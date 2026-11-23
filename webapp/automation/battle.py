from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from time import monotonic
from typing import Any

from webapp.automation.interaction import (
    active_monotonic,
    configured_random_time,
    match_touch_point,
    randomized_touch_point,
    randomized_wait_seconds,
)
from webapp.automation.network import reconnect_if_present
from webapp.automation.program import (
    ATTACK_POINT,
    COMMAND_CARD_BACK_POINT,
    CRAWL_TOWER_MODES,
    FACE_CARD_POINTS,
    NP_POINTS,
    build_autonomous_skill_commands,
    build_complex_skill_commands,
    compile_battle_program,
    compile_skill_command,
    resolve_skill_target_point,
)
from webapp.automation.strategy import (
    StrategySelectionError,
    matches_card_preference,
    select_command_cards,
    select_command_cards_default,
    select_command_cards_without_chain,
)
from webapp.core.errors import AppError, ErrorCode
from webapp.runtime import JobManager, RunContext
from webapp.services.battle_servants import FrontlineServantRecognizer
from webapp.services.cards import CommandCardRecognizer, recognize_card_blocks
from webapp.services.devices import DeviceService
from webapp.services.np_charge import NpChargeRecognizer
from webapp.services.recognition import RecognitionService
from webapp.services.script_data import ScriptDataService


BATTLE_DRY_RUN_JOB_KIND = "battle.dry-run"
BATTLE_EXECUTE_PLAN_JOB_KIND = "battle.execute-plan"
BATTLE_EXECUTE_SKILLS_JOB_KIND = "battle.execute-skills"
SKILL_ANIMATION_SKIP_POINT = (1217, 440)
BATTLE_MENU_TRANSITION_SECONDS = 0.5
BATTLE_MENU_CLOSE_POINT = (1178, 108)
COMMAND_CARD_READY_CONFIDENCE = 0.9
FRONTLINE_ALIVE_ROIS: tuple[tuple[int, int, int, int], ...] = (
    (287, 627, 33, 73),
    (604, 627, 33, 73),
    (921, 627, 33, 73),
)
SKILL_NOT_AVAILABLE_ROI = (550, 530, 180, 70)
SKILL_NOT_AVAILABLE_CLOSE_POINT = (642, 563)
SKILL_NOT_AVAILABLE_CLOSE_SIZE = (197, 53)
SERVANT_DETAIL_CLOSE_ROI = (1047, 20, 87, 80)
COMMAND_CARD_BACK_ROI = (1100, 610, 180, 110)
COMMAND_CARD_BACK_SIZE = (73, 53)
ATTACK_BUTTON_ROI_720P = (960, 480, 320, 240)
COMMAND_CARDS_ROI_720P = (0, 380, 1280, 290)
BATTLE_TEMPLATE_SCALES = (1.0, 0.75, 2 / 3, 0.5)
NAMED_SKILL_COMMANDS = {
    "Kukulkan",
    "Barghest",
    "Soujyuro",
    "BBDubai",
    "Hakuno",
    "VanGoghMiner",
    "Dante",
    "Gyokuto",
    "Charlotte",
    "Flora",
}


@dataclass(frozen=True)
class _TapTiming:
    interval: float
    random_time: float = 0.0
    random_touch: bool = False


def initialize_battle_settings(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    server: str,
    *,
    action_wait_seconds: float = 0.5,
    random_time: float = 0.0,
    random_touch: bool = False,
) -> dict[str, Any]:
    server = server.upper()
    actions: list[str] = []
    toggles: list[tuple[bool, Any]] = []
    screenshot = b""
    max_open_attempts = 8
    for attempt in range(max_open_attempts):
        screenshot = device_service.snapshot()
        menu_button = recognition.match_template(
            screenshot,
            f"battle/{server}/fight_menu_button.png",
            threshold=0.85,
            scales=(1.0, 0.75, 2 / 3, 0.5),
        )
        if not menu_button.matched:
            if attempt + 1 >= max_open_attempts:
                raise RuntimeError("Battle menu button was not recognized.")
            context.sleep(
                randomized_wait_seconds(
                    max(action_wait_seconds, BATTLE_MENU_TRANSITION_SECONDS),
                    random_time,
                )
            )
            continue
        device_service.tap(*match_touch_point(menu_button, enabled=random_touch))
        if not actions:
            actions.append("open_menu")
        context.sleep(
            randomized_wait_seconds(
                max(action_wait_seconds, BATTLE_MENU_TRANSITION_SECONDS),
                random_time,
            )
        )

        screenshot = device_service.snapshot()
        candidates = []
        for enabled, template_path in (
            (True, f"battle/{server}/on.png"),
            (False, f"battle/{server}/off.png"),
        ):
            for match in recognition.match_template_all(
                screenshot,
                template_path,
                threshold=0.85,
                scales=(1.0, 0.75, 2 / 3, 0.5),
                max_results=10,
            ):
                candidates.append((enabled, match))
        toggles = _distinct_toggle_matches(candidates)
        if len(toggles) == 3:
            break
    if len(toggles) != 3:
        raise RuntimeError(
            f"Expected three battle settings toggles but recognized {len(toggles)}."
        )

    speed_off = _match_optional_battle_template(
        recognition,
        screenshot,
        f"battle/{server}/speed_off.png",
    )
    speed_on = _match_optional_battle_template(
        recognition,
        screenshot,
        f"battle/{server}/speed_on.png",
    )
    speed_enabled = _optional_toggle_state(speed_on, speed_off)
    np_auto = _match_optional_battle_template(
        recognition,
        screenshot,
        f"battle/{server}/needSkip.png",
    )
    np_skip = _match_optional_battle_template(
        recognition,
        screenshot,
        f"battle/{server}/needSkip1.png",
    )
    np_skip_enabled = _optional_toggle_state(np_skip, np_auto)

    initial_states = [enabled for enabled, _match in toggles]
    for index, ((enabled, match), desired) in enumerate(
        zip(toggles, (False, True, False), strict=True),
        start=1,
    ):
        if enabled == desired:
            continue
        device_service.tap(*match_touch_point(match, enabled=random_touch))
        actions.append(f"toggle_{index}")
        context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))

    if speed_enabled is False and speed_off is not None:
        device_service.tap(*match_touch_point(speed_off, enabled=random_touch))
        actions.append("enable_speed")
        context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
    if np_skip_enabled is False and np_auto is not None:
        device_service.tap(*match_touch_point(np_auto, enabled=random_touch))
        actions.append("enable_np_skip")
        context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))

    screenshot = device_service.snapshot()
    back_button = _match_optional_battle_template(
        recognition,
        screenshot,
        f"battle/{server}/back.png",
    )
    close_point = (
        match_touch_point(back_button, enabled=random_touch)
        if back_button is not None and back_button.matched
        else randomized_touch_point(BATTLE_MENU_CLOSE_POINT, enabled=random_touch)
    )
    device_service.tap(*close_point)
    actions.append("close_menu")
    context.emit(
        "battle_settings",
        "Initial battle settings were normalized.",
        data={
            "states": initial_states,
            "speed_enabled": speed_enabled,
            "np_skip_enabled": np_skip_enabled,
            "actions": actions,
        },
    )
    context.sleep(
        randomized_wait_seconds(
            max(action_wait_seconds, BATTLE_MENU_TRANSITION_SECONDS),
            random_time,
        )
    )
    return {
        "changed": (
            any(
                state != desired
                for state, desired in zip(
                    initial_states,
                    (False, True, False),
                    strict=True,
                )
            )
            or speed_enabled is False
            or np_skip_enabled is False
        ),
        "states": initial_states,
        "speed_enabled": speed_enabled,
        "np_skip_enabled": np_skip_enabled,
        "actions": actions,
    }


def _match_optional_battle_template(
    recognition: RecognitionService,
    screenshot: bytes,
    template_path: str,
    *,
    roi: tuple[int, int, int, int] | None = None,
    threshold: float = 0.85,
    mask_path: str | None = None,
):
    options: dict[str, Any] = {
        "threshold": threshold,
        "scales": (1.0, 0.75, 2 / 3, 0.5),
        "roi": roi,
    }
    if mask_path is not None:
        options["mask_path"] = mask_path
    try:
        return recognition.match_template(
            screenshot,
            template_path,
            **options,
        )
    except AppError as exc:
        if exc.code == ErrorCode.TEMPLATE_NOT_FOUND and mask_path is not None:
            options.pop("mask_path", None)
            try:
                return recognition.match_template(
                    screenshot,
                    template_path,
                    **options,
                )
            except AppError as retry_exc:
                if retry_exc.code == ErrorCode.TEMPLATE_NOT_FOUND:
                    return None
                raise
        if exc.code == ErrorCode.TEMPLATE_NOT_FOUND:
            return None
        raise


def _skill_cooldown_roi(skill_number: int, server: str) -> tuple[int, int, int, int]:
    index = skill_number - 1
    base_x = (50 if server.upper() == "JP" else 76) + index * 132 + (index // 3) * 80
    return (round(base_x * 2 / 3), 592, 30, 30)


def _skill_seal_roi(skill_number: int) -> tuple[int, int, int, int]:
    index = skill_number - 1
    base_x = 100 + index * 132 + (index // 3) * 80
    return (round(base_x * 2 / 3), 553, 33, 33)


def _servant_skill_number(action: dict[str, Any]) -> int | None:
    source = action.get("source")
    if not isinstance(source, dict) or source.get("type") != "skill":
        return None
    command = source.get("command")
    if isinstance(command, int) and not isinstance(command, bool):
        return command if 1 <= command <= 9 else None
    if not isinstance(command, list) or not command:
        return None
    head = command[0]
    if isinstance(head, int) and not isinstance(head, bool):
        if len(command) == 3:
            return None
        skill_num = abs(head)
        return skill_num if 1 <= skill_num <= 9 else None
    if (
        isinstance(head, str)
        and head in NAMED_SKILL_COMMANDS
        and len(command) >= 2
        and isinstance(command[1], int)
        and not isinstance(command[1], bool)
    ):
        skill_num = command[1]
        return skill_num if 1 <= skill_num <= 9 else None
    return None


def _sync_frontline_alive_positions(
    context: RunContext,
    recognition: RecognitionService,
    screenshot: bytes,
    occupied_positions: list[int | None] | None,
    servant_positions: list[dict[str, Any] | None] | None = None,
) -> list[bool] | None:
    if occupied_positions is None or len(occupied_positions) < 3:
        return None
    alive_slots: list[bool] = []
    for roi in FRONTLINE_ALIVE_ROIS:
        match = _match_optional_battle_template(
            recognition,
            screenshot,
            "battle/public/alive.png",
            roi=roi,
            threshold=0.6,
            mask_path="battle/public/aliveMask.png",
        )
        if match is None:
            return None
        alive_slots.append(bool(match.matched))
    if not (0 < sum(alive_slots) <= 3):
        return None
    changed = False
    for index, is_alive in enumerate(alive_slots):
        if not is_alive:
            if occupied_positions[index] is not None:
                occupied_positions[index] = None
                changed = True
            if servant_positions is not None and index < len(servant_positions):
                servant_positions[index] = None
        elif occupied_positions[index] is None:
            occupied_positions[index] = -1
            changed = True
    if changed:
        context.emit(
            "frontline_alive",
            "Frontline servant survival positions were updated.",
            data={
                "alive": alive_slots,
                "occupied_positions": list(occupied_positions[:3]),
            },
        )
    return alive_slots


def _sync_frontline_servant_names(
    context: RunContext,
    device_service: DeviceService,
    frontline_recognizer: FrontlineServantRecognizer | None,
    screenshot: bytes,
    server: str,
    servant_positions: list[dict[str, Any] | None],
    occupied_positions: list[int | None] | None = None,
    party_servants: list[dict[str, Any]] | None = None,
    *,
    max_attempts: int = 4,
    retry_wait_seconds: float = 0.5,
) -> dict[str, Any] | None:
    if frontline_recognizer is None or not frontline_recognizer.has_assets():
        return None
    present = (
        [occupied_positions[index] is not None for index in range(3)]
        if occupied_positions is not None and len(occupied_positions) >= 3
        else [servant_positions[index] is not None for index in range(3)]
    )
    if not any(present):
        return None
    try:
        classes = frontline_recognizer.recognize_classes(screenshot, present=present)
    except (AppError, ValueError):
        return None
    if not any(classes):
        return None
    current_screenshot = screenshot
    recognized: dict[str, Any] | None = None
    attempts = max(int(max_attempts), 1)
    for remaining in range(attempts, 0, -1):
        name_threshold = 0.5 if remaining == 1 and attempts > 1 else 0.7
        recognized = frontline_recognizer.recognize_names(
            current_screenshot,
            classes=classes,
            present=present,
            threshold=name_threshold,
            final_attempt=remaining == 1,
        )
        if recognized["complete"] or remaining == 1:
            break
        if retry_wait_seconds > 0:
            context.sleep(retry_wait_seconds)
        current_screenshot = device_service.snapshot()
    assert recognized is not None
    changed = frontline_recognizer.apply_recognized_names(
        recognized["names"],
        servant_positions,
        occupied_positions=occupied_positions,
        party_servants=party_servants,
        server=server,
    )
    recognized["changed"] = changed
    context.emit(
        "frontline_servants",
        "Frontline servant classes and portraits were checked.",
        data={
            "classes": recognized["classes"],
            "names": recognized["names"],
            "complete": recognized["complete"],
            "changed": changed,
            "frontline": _frontline_servants(servant_positions),
        },
    )
    return recognized


def _party_slot_at_frontline(
    frontline_index: int,
    occupied_positions: list[int | None] | None,
    servant_positions: list[dict[str, Any] | None] | None = None,
) -> int | None:
    if occupied_positions is not None and 0 <= frontline_index < len(occupied_positions):
        slot = occupied_positions[frontline_index]
        if isinstance(slot, int) and not isinstance(slot, bool) and slot >= 0:
            return slot
    if servant_positions is not None and 0 <= frontline_index < len(servant_positions):
        entry = servant_positions[frontline_index]
        if isinstance(entry, dict):
            slot = entry.get("slot")
            if isinstance(slot, int) and not isinstance(slot, bool) and slot >= 0:
                return slot
    return None


def _ensure_party_slot_capacity(
    slot: int | None,
    buff_counts: list[int] | None,
    unopened_skills: list[set[int]] | None,
) -> None:
    if slot is None or slot < 0:
        return
    if buff_counts is not None:
        while len(buff_counts) <= slot:
            buff_counts.append(0)
    if unopened_skills is not None:
        while len(unopened_skills) <= slot:
            unopened_skills.append(set())


def _record_skill_buff(
    action: dict[str, Any],
    buff_counts: list[int] | None,
    occupied_positions: list[int | None] | None,
    servant_positions: list[dict[str, Any] | None] | None = None,
) -> None:
    if buff_counts is None:
        return
    source = action.get("source")
    if not isinstance(source, dict) or source.get("type") != "skill":
        return
    command = source.get("command")
    target: int | None = None
    if (
        isinstance(command, list)
        and len(command) == 2
        and isinstance(command[0], int)
        and not isinstance(command[0], bool)
        and 1 <= command[0] <= 12
        and isinstance(command[1], int)
        and not isinstance(command[1], bool)
        and 1 <= command[1] <= 3
    ):
        target = command[1]
    elif (
        isinstance(command, list)
        and len(command) == 4
        and command[0] == "Kukulkan"
        and isinstance(command[3], int)
        and not isinstance(command[3], bool)
        and 1 <= command[3] <= 3
    ):
        target = command[3]
    if target is None:
        return
    slot = _party_slot_at_frontline(
        target - 1,
        occupied_positions,
        servant_positions,
    )
    if slot is None:
        return
    _ensure_party_slot_capacity(slot, buff_counts, None)
    buff_counts[slot] += 1


def _record_np_servants(
    selected_nps: set[int],
    np_servants: set[int] | None,
    occupied_positions: list[int | None] | None,
    servant_positions: list[dict[str, Any] | None] | None = None,
) -> None:
    if np_servants is None:
        return
    for servant in selected_nps:
        if not (1 <= servant <= 3):
            continue
        slot = _party_slot_at_frontline(
            servant - 1,
            occupied_positions,
            servant_positions,
        )
        if slot is not None:
            np_servants.add(slot)


def _record_unopened_skill(
    skill_number: int | None,
    unopened_skills: list[set[int]] | None,
    occupied_positions: list[int | None] | None,
    servant_positions: list[dict[str, Any] | None] | None = None,
) -> None:
    if (
        skill_number is None
        or unopened_skills is None
        or not (1 <= skill_number <= 9)
    ):
        return
    slot = _party_slot_at_frontline(
        (skill_number - 1) // 3,
        occupied_positions,
        servant_positions,
    )
    if slot is None:
        return
    _ensure_party_slot_capacity(slot, None, unopened_skills)
    unopened_skills[slot].add((skill_number - 1) % 3)


def _has_skill_availability_assets(
    recognition: RecognitionService,
    server: str,
) -> bool:
    if not isinstance(recognition, RecognitionService):
        return False
    normalized_server = server.upper()
    cooldown_template = (
        f"battle/{normalized_server}/incd.png"
        if normalized_server == "JP"
        else f"battle/{normalized_server}/incd1.png"
    )
    try:
        return recognition._resources.resolve_template(cooldown_template).is_file()
    except (AppError, AttributeError):
        return False


def _update_servant_diff_state(
    context: RunContext,
    servant_positions: list[dict[str, Any] | None],
    servant_diff_state: dict[str, Any] | None,
    *,
    names_changed: bool = False,
) -> bool:
    if servant_diff_state is None:
        return False
    if servant_diff_state.get("has_diff"):
        return True
    current_signature = [
        (
            servant.get("sn")
            or servant.get("canonical_name")
            or servant.get("name")
            or ("assist" if servant.get("is_assist") else None)
        )
        if isinstance(servant, dict)
        else None
        for servant in servant_positions[:3]
    ]
    recorded = servant_diff_state.get("recorded")
    if recorded is None:
        servant_diff_state["recorded"] = list(current_signature)
        if not names_changed:
            return False
    if names_changed or servant_diff_state.get("recorded") != current_signature:
        servant_diff_state["has_diff"] = True
        context.emit(
            "servant_diff",
            "Frontline servant lineup changed during extra battle turns.",
            data={
                "recorded": servant_diff_state.get("recorded"),
                "current": current_signature,
            },
        )
        return True
    return False


def _is_servant_skill_unavailable(
    recognition: RecognitionService,
    screenshot: bytes,
    server: str,
    skill_number: int,
    occupied_positions: list[int | None] | None = None,
    *,
    unopened_skills: list[set[int]] | None = None,
    servant_positions: list[dict[str, Any] | None] | None = None,
) -> bool:
    if not (1 <= skill_number <= 9):
        return False
    slot_index = (skill_number - 1) // 3
    if (
        occupied_positions is not None
        and slot_index < len(occupied_positions)
        and occupied_positions[slot_index] is None
    ):
        return True
    if unopened_skills is not None:
        slot = _party_slot_at_frontline(
            slot_index,
            occupied_positions,
            servant_positions,
        )
        if (
            slot is not None
            and 0 <= slot < len(unopened_skills)
            and ((skill_number - 1) % 3) in unopened_skills[slot]
        ):
            return True
    server = server.upper()
    cooldown_template = (
        f"battle/{server}/incd.png"
        if server == "JP"
        else f"battle/{server}/incd1.png"
    )
    cooldown_match = _match_optional_battle_template(
        recognition,
        screenshot,
        cooldown_template,
        roi=_skill_cooldown_roi(skill_number, server),
        threshold=0.6,
    )
    seal_match = _match_optional_battle_template(
        recognition,
        screenshot,
        f"battle/{server}/freeze1.png",
        roi=_skill_seal_roi(skill_number),
        threshold=0.6,
        mask_path=f"battle/{server}/freeze1mask.png",
    )
    cooldown_matched = bool(cooldown_match is not None and cooldown_match.matched)
    seal_matched = bool(seal_match is not None and seal_match.matched)
    if (
        not isinstance(recognition, RecognitionService)
        and cooldown_matched
        and seal_matched
        and getattr(cooldown_match, "roi", None) is None
        and getattr(seal_match, "roi", None) is None
    ):
        return False
    return cooldown_matched or seal_matched


def _optional_toggle_state(enabled_match, disabled_match) -> bool | None:
    if enabled_match is not None and enabled_match.matched:
        return True
    if disabled_match is not None and disabled_match.matched:
        return False
    return None


def _distinct_toggle_matches(candidates):
    selected = []
    for candidate in sorted(candidates, key=lambda item: item[1].confidence, reverse=True):
        if any(_match_iou(candidate[1], existing[1]) > 0.3 for existing in selected):
            continue
        selected.append(candidate)
    if not selected:
        return []
    min_x = min(item[1].center[0] for item in selected)
    col_width = max(max(item[1].size[0] for item in selected) * 2, 1)
    return sorted(
        selected,
        key=lambda item: (
            (item[1].center[0] - min_x) // col_width,
            item[1].center[1],
            item[1].center[0],
        ),
    )


def _match_iou(first, second) -> float:
    first_x, first_y = first.top_left
    first_width, first_height = first.size
    second_x, second_y = second.top_left
    second_width, second_height = second.size
    left = max(first_x, second_x)
    top = max(first_y, second_y)
    right = min(first_x + first_width, second_x + second_width)
    bottom = min(first_y + first_height, second_y + second_height)
    intersection = max(right - left, 0) * max(bottom - top, 0)
    if not intersection:
        return 0.0
    union = first_width * first_height + second_width * second_height - intersection
    return intersection / union


def _matches_hakuno_needs(
    cards: list[dict[str, Any]],
    need_cards: list[list[str]],
) -> bool:
    available = [
        card
        for card in cards
        if isinstance(card.get("code"), str)
        and card.get("available") is not False
    ]
    for need in need_cards:
        if len(need) > len(available):
            continue
        # A card may match several aliases, but each hand slot can be used only once.
        if any(
            all(matches_card_preference(card, code) for card, code in zip(selection, need, strict=True))
            for selection in permutations(available, len(need))
        ):
            return True
    return False


def _recognize_command_cards(
    card_recognizer: CommandCardRecognizer,
    screenshot: bytes,
    server: str,
    servants: list[dict[str, Any]],
    threshold: float,
    special_keys: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    options: dict[str, Any] = {"threshold": threshold}
    if special_keys:
        options["special_keys"] = special_keys
    return card_recognizer.recognize(
        screenshot,
        server,
        servants,
        **options,
    )


def _recognize_command_cards_with_recovery(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    card_recognizer: CommandCardRecognizer,
    screenshot: bytes,
    server: str,
    servants: list[dict[str, Any]],
    threshold: float,
    special_keys: list[dict[str, Any]] | None,
    *,
    frontline_recognizer: FrontlineServantRecognizer | None = None,
    servant_positions: list[dict[str, Any] | None] | None = None,
    occupied_positions: list[int | None] | None = None,
    party_servants: list[dict[str, Any]] | None = None,
    card_templates: list[str] | None = None,
    attack_template: str | None = None,
    timeout_seconds: float = 15.0,
    poll_interval: float = 0.25,
    tap_interval: float | _TapTiming = 0.0,
    card_wait_seconds: float = 0.0,
) -> tuple[dict[str, Any], bytes, int]:
    recognized = _recognize_command_cards(
        card_recognizer,
        screenshot,
        server,
        servants,
        threshold,
        special_keys,
    )
    if (
        recognized["complete"]
        or frontline_recognizer is None
        or not frontline_recognizer.has_assets()
        or servant_positions is None
    ):
        return recognized, screenshot, 0
    recovery_taps = _execute_steps(
        context,
        device_service,
        [
            {
                "type": "tap",
                "role": "card_recognition_back",
                "x": COMMAND_CARD_BACK_POINT[0],
                "y": COMMAND_CARD_BACK_POINT[1],
            }
        ],
        tap_interval,
    )
    battle_screenshot = _wait_for_battle_ready(
        context,
        device_service,
        recognition,
        attack_template or f"battle/{server}/attack.png",
        threshold,
        timeout_seconds,
        poll_interval,
        reconnect_timing=tap_interval,
    )
    _sync_frontline_alive_positions(
        context,
        recognition,
        battle_screenshot,
        occupied_positions,
        servant_positions,
    )
    name_sync = _sync_frontline_servant_names(
        context,
        device_service,
        frontline_recognizer,
        battle_screenshot,
        server,
        servant_positions,
        occupied_positions,
        party_servants,
        retry_wait_seconds=poll_interval,
    )
    servants[:] = _frontline_servants(servant_positions)
    recovery_taps += _execute_steps(
        context,
        device_service,
        [
            {
                "type": "tap",
                "role": "card_recognition_attack",
                "x": ATTACK_POINT[0],
                "y": ATTACK_POINT[1],
            }
        ],
        tap_interval,
    )
    effective_card_templates = card_templates or [
        f"battle/{server}/{color}.png" for color in ("Arts", "Buster", "Quick")
    ]
    screenshot = _wait_for_command_cards(
        context,
        device_service,
        recognition,
        effective_card_templates,
        threshold,
        timeout_seconds,
        poll_interval,
        reconnect_timing=tap_interval,
        settle_seconds=card_wait_seconds,
    )
    recognized = _recognize_command_cards(
        card_recognizer,
        screenshot,
        server,
        servants,
        threshold,
        special_keys,
    )
    context.emit(
        "card_recognition_recovery",
        "Re-checked frontline servant names after unrecognized command cards.",
        data={
            "names": name_sync["names"] if name_sync is not None else None,
            "complete": recognized["complete"],
            "recognized_count": recognized["recognized_count"],
        },
    )
    return recognized, screenshot, recovery_taps


def _execute_hakuno_reroll(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    card_recognizer: CommandCardRecognizer,
    server: str,
    servants: list[dict[str, Any]],
    runtime: dict[str, Any],
    card_templates: list[str],
    attack_template: str,
    threshold: float,
    timeout_seconds: float,
    poll_interval: float,
    tap_interval: float | _TapTiming,
    special_keys: list[dict[str, Any]] | None = None,
    card_wait_seconds: float = 0.0,
    speedup_skills: bool = False,
    *,
    frontline_recognizer: FrontlineServantRecognizer | None = None,
    servant_positions: list[dict[str, Any] | None] | None = None,
    occupied_positions: list[int | None] | None = None,
    party_servants: list[dict[str, Any]] | None = None,
) -> int:
    tap_count = 0
    need_cards = runtime["need_cards"]
    max_rerolls = int(runtime["max_rerolls"])
    for check_number in range(1, max_rerolls + 2):
        _wait_for_battle_ready(
            context,
            device_service,
            recognition,
            attack_template,
            threshold,
            timeout_seconds,
            poll_interval,
            reconnect_timing=tap_interval,
        )
        tap_count += _execute_steps(
            context,
            device_service,
            [
                {
                    "type": "tap",
                    "role": "hakuno_check_attack",
                    "x": ATTACK_POINT[0],
                    "y": ATTACK_POINT[1],
                }
            ],
            tap_interval,
        )
        screenshot = _wait_for_command_cards(
            context,
            device_service,
            recognition,
            card_templates,
            threshold,
            timeout_seconds,
            poll_interval,
            reconnect_timing=tap_interval,
            settle_seconds=card_wait_seconds,
        )
        recognized, screenshot, recovery_taps = _recognize_command_cards_with_recovery(
            context,
            device_service,
            recognition,
            card_recognizer,
            screenshot,
            server,
            servants,
            threshold,
            special_keys,
            frontline_recognizer=frontline_recognizer,
            servant_positions=servant_positions,
            occupied_positions=occupied_positions,
            party_servants=party_servants,
            card_templates=card_templates,
            attack_template=attack_template,
            timeout_seconds=timeout_seconds,
            poll_interval=poll_interval,
            tap_interval=tap_interval,
            card_wait_seconds=card_wait_seconds,
        )
        tap_count += recovery_taps
        matched = _matches_hakuno_needs(recognized["cards"], need_cards)
        tap_count += _execute_steps(
            context,
            device_service,
            [
                {
                    "type": "tap",
                    "role": "hakuno_check_back",
                    "x": COMMAND_CARD_BACK_POINT[0],
                    "y": COMMAND_CARD_BACK_POINT[1],
                }
            ],
            tap_interval,
        )
        context.emit(
            "hakuno_card_check",
            "Hakuno card requirement check completed.",
            data={
                "check": check_number,
                "matched": matched,
                "need_cards": need_cards,
                "recognition": recognized,
            },
        )
        if matched:
            return tap_count
        if check_number > max_rerolls:
            raise RuntimeError(
                f"Hakuno card requirements were not met after {max_rerolls} rerolls."
            )
        _wait_for_battle_ready(
            context,
            device_service,
            recognition,
            attack_template,
            threshold,
            timeout_seconds,
            poll_interval,
            reconnect_timing=tap_interval,
        )
        tap_count += _execute_steps(
            context,
            device_service,
            [runtime["skill_step"]],
            tap_interval,
        )
        if speedup_skills:
            tap_count += _execute_skill_animation_speedup(
                context,
                device_service,
                tap_interval,
            )
    raise AssertionError("Hakuno reroll loop exited unexpectedly.")


def _wait_for_battle_transition(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    server: str,
    threshold: float,
    timeout_seconds: float,
    poll_interval: float,
    reconnect_timing: float | _TapTiming | None = None,
) -> dict[str, Any]:
    server = server.upper()
    attack_path = f"battle/{server}/attack.png"
    phase_paths = [f"battle/{server}/phase_{round_number}.png" for round_number in range(1, 4)]
    phase_path_set = set(phase_paths)
    finish_paths = [
        f"battle/{server}/battleFinish.png",
        f"battle/{server}/battleFinish1.png",
        f"battle/{server}/fight_end.png",
    ]
    use_720p_rois = isinstance(recognition, RecognitionService)
    candidates = [
        {
            "template_path": path,
            "threshold": threshold,
            "scales": BATTLE_TEMPLATE_SCALES,
            **({"roi": (867, 0, 44, 48)} if path in phase_path_set else {}),
        }
        for path in [attack_path, *phase_paths, *finish_paths]
    ]
    started = active_monotonic(context, clock=monotonic)
    attempts = 0
    while True:
        screenshot = device_service.snapshot()
        if _battle_reconnect_if_present(
            context,
            device_service,
            recognition,
            screenshot,
            server,
            reconnect_timing,
        ) and active_monotonic(context, clock=monotonic) - started < timeout_seconds:
            continue
        effective_candidates = candidates
        if use_720p_rois:
            try:
                if recognition.image_size(screenshot) == (1280, 720):
                    effective_candidates = [
                        {**candidate, "roi": ATTACK_BUTTON_ROI_720P}
                        if candidate["template_path"] == attack_path
                        else candidate
                        for candidate in candidates
                    ]
            except AppError:
                pass
        matches = recognition.match_templates(screenshot, effective_candidates)
        attempts += 1
        by_path = {
            candidate["template_path"]: match
            for candidate, match in zip(candidates, matches, strict=True)
        }
        if any(by_path[path].matched for path in finish_paths):
            result = {"state": "finished", "round": None}
        else:
            matched_rounds = [
                (round_number, by_path[path])
                for round_number, path in enumerate(phase_paths, start=1)
                if by_path[path].matched
            ]
            result = (
                {
                    "state": "battle",
                    "round": max(
                        matched_rounds,
                        key=lambda item: item[1].confidence,
                    )[0],
                }
                if by_path[attack_path].matched and matched_rounds
                else None
            )
        context.emit(
            "battle_transition",
            "Battle transition recognition completed.",
            data={
                "attempt": attempts,
                "result": result,
                "matches": [match.to_dict() for match in matches],
            },
        )
        if result is not None:
            return result
        if active_monotonic(context, clock=monotonic) - started >= timeout_seconds:
            raise TimeoutError(
                f"Battle transition was not recognized within {timeout_seconds:.2f} seconds."
            )
        context.sleep(poll_interval)


def register_battle_jobs(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService | None = None,
    recognition: RecognitionService | None = None,
    card_recognizer: CommandCardRecognizer | None = None,
    np_recognizer: NpChargeRecognizer | None = None,
    frontline_recognizer: FrontlineServantRecognizer | None = None,
) -> None:
    def dry_run(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = _required_setting_name(payload)
        action_delay = _action_delay(payload)
        plan = script_data.get_setting_plan(setting_name)
        validation = plan["validation"]
        if not validation["ok"]:
            raise ValueError(
                f"Setting {setting_name} has {len(validation['errors'])} validation errors."
            )

        rounds = plan["rounds"]
        total_actions = plan["summary"]["action_count"]
        turn_count = sum(len(round_plan["turns"]) for round_plan in rounds)
        action_number = 0
        context.emit(
            "battle_plan",
            "Battle dry run started.",
            data={
                "setting_name": setting_name,
                "round_count": len(rounds),
                "turn_count": turn_count,
                "action_count": total_actions,
            },
        )

        for round_plan in rounds:
            round_number = round_plan["round"]
            context.emit(
                "battle_round",
                f"Entered round {round_number}.",
                data={"round": round_number},
            )
            for turn in round_plan["turns"]:
                turn_number = turn["turn"]
                context.emit(
                    "battle_turn",
                    f"Entered round {round_number}, turn {turn_number}.",
                    data={"round": round_number, "turn": turn_number},
                )
                for action in turn["actions"]:
                    action_number += 1
                    action_type = str(action.get("type", "action"))
                    context.checkpoint(
                        f"round_{round_number}.turn_{turn_number}.{action_type}_{action_number}",
                        progress=action_number / max(total_actions, 1),
                    )
                    context.emit(
                        "battle_action",
                        f"Dry-ran {action_type} action {action_number} of {total_actions}.",
                        data={
                            "round": round_number,
                            "turn": turn_number,
                            "action_number": action_number,
                            "action": action,
                        },
                    )
                    if action_delay:
                        context.sleep(action_delay)

        context.checkpoint(
            "complete",
            progress=1.0,
            message="Battle dry run completed.",
        )
        return {
            "setting_name": setting_name,
            "round_count": len(rounds),
            "turn_count": turn_count,
            "action_count": action_number,
        }

    if not job_manager.has_kind(BATTLE_DRY_RUN_JOB_KIND):
        job_manager.register(BATTLE_DRY_RUN_JOB_KIND, dry_run)
    if (
        device_service is not None
        and recognition is not None
        and not job_manager.has_kind(BATTLE_EXECUTE_SKILLS_JOB_KIND)
    ):
        job_manager.register(
            BATTLE_EXECUTE_SKILLS_JOB_KIND,
            _execute_skills_handler(
                script_data,
                device_service,
                recognition,
                card_recognizer,
                frontline_recognizer,
            ),
            requires_device=True,
        )
    if (
        device_service is not None
        and recognition is not None
        and not job_manager.has_kind(BATTLE_EXECUTE_PLAN_JOB_KIND)
    ):
        job_manager.register(
            BATTLE_EXECUTE_PLAN_JOB_KIND,
            create_battle_execute_plan_handler(
                script_data,
                device_service,
                recognition,
                card_recognizer,
                np_recognizer,
                frontline_recognizer,
            ),
            requires_device=True,
        )


def create_battle_execute_plan_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognition: RecognitionService,
    card_recognizer: CommandCardRecognizer | None,
    np_recognizer: NpChargeRecognizer | None = None,
    frontline_recognizer: FrontlineServantRecognizer | None = None,
):
    def execute(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = _required_setting_name(payload)
        threshold, timeout_seconds, poll_interval, tap_interval = _execution_options(
            payload
        )
        plan = script_data.get_setting_plan(setting_name)
        party_servants = plan["servants"]
        special_keys = plan.get("special_keys", [])
        card_wait_seconds = _configured_card_wait(
            plan["run"].get("interval_before_choose_card", 0.5)
        )
        speedup_skills = not bool(plan["run"].get("no_speedup_skill"))
        tap_interval = _TapTiming(
            tap_interval,
            configured_random_time(plan["run"].get("random_time", 0)),
            bool(plan["run"].get("random_touch")),
        )
        initialize_settings = payload.get(
            "initialize_settings",
            bool(plan["run"]["first_battle_set"]),
        )
        if not isinstance(initialize_settings, bool):
            raise ValueError("initialize_settings must be a boolean.")
        crawl_tower_mode = payload.get("crawl_tower_mode", "off")
        if crawl_tower_mode not in CRAWL_TOWER_MODES:
            raise ValueError(
                "crawl_tower_mode must be off, script, or autonomous."
            )
        program = compile_battle_program(plan, crawl_tower_mode=crawl_tower_mode)
        execution_status = program["execution"]["battle"]
        if not execution_status["ready"]:
            raise ValueError(execution_status["reason"])
        needs_card_recognition = any(
            step.get("type") == "strategy"
            for round_plan in program["rounds"]
            for turn in round_plan["turns"]
            for step in turn["command_phase"]["steps"]
        ) or any(
            action.get("control", {}).get("check_cards")
            for round_plan in program["rounds"]
            for turn in round_plan["turns"]
            for action in turn["actions"]
        ) or any(
            action.get("runtime", {}).get("type") == "hakuno_card_reroll"
            for round_plan in program["rounds"]
            for turn in round_plan["turns"]
            for action in turn["actions"]
        ) or any(
            step.get("type") == "strategy"
            for round_plan in program["rounds"]
            for step in round_plan["extra_turn"]["command_phase"]["steps"]
        ) or any(
            action.get("control", {}).get("check_cards")
            for round_plan in program["rounds"]
            for action in round_plan["extra_turn"]["actions"]
        ) or any(
            action.get("runtime", {}).get("type") == "hakuno_card_reroll"
            for round_plan in program["rounds"]
            for action in round_plan["extra_turn"]["actions"]
        )
        if needs_card_recognition and card_recognizer is None:
            raise ValueError("Command card recognition is not configured.")
        needs_np_recognition = any(
            action.get("control", {}).get("check_np")
            for round_plan in program["rounds"]
            for turn in round_plan["turns"]
            for action in turn["actions"]
        ) or any(
            action.get("control", {}).get("check_np")
            for round_plan in program["rounds"]
            for action in round_plan["extra_turn"]["actions"]
        )
        effective_np_recognizer = np_recognizer or (
            NpChargeRecognizer(recognition)
            if isinstance(recognition, RecognitionService)
            else None
        )
        if needs_np_recognition and effective_np_recognizer is None:
            raise ValueError("NP charge recognition is not configured.")
        effective_frontline_recognizer = frontline_recognizer or (
            FrontlineServantRecognizer(recognition._resources)
            if isinstance(recognition, RecognitionService)
            else None
        )
        if initialize_settings:
            initialize_battle_settings(
                context,
                device_service,
                recognition,
                program["server"],
                action_wait_seconds=tap_interval.interval,
                random_time=tap_interval.random_time,
                random_touch=tap_interval.random_touch,
            )

        turns = [
            (round_plan["round"], turn)
            for round_plan in program["rounds"]
            for turn in round_plan["turns"]
        ]
        attack_template = f"battle/{program['server']}/attack.png"
        card_templates = [
            f"battle/{program['server']}/{card_type}.png"
            for card_type in ("Arts", "Buster", "Quick")
        ]
        action_count = 0
        tap_count = 0
        servant_positions = _servant_positions(
            party_servants,
            assist_slot=(plan.get("assist") or {}).get("slot"),
        )
        occupied_positions: list[int | None] = list(range(6))
        servant_diff_state: dict[str, Any] = {"recorded": None, "has_diff": False}
        buff_counts: list[int] = [0] * 6
        np_servants: set[int] = set()
        unopened_skills: list[set[int]] = [set() for _ in range(6)]
        last_skill_number: int | None = None
        compiled_rounds = {
            round_plan["round"]: round_plan for round_plan in program["rounds"]
        }
        last_turns = {
            round_plan["round"]: max(
                (turn["turn"] for turn in round_plan["turns"]),
                default=-1,
            )
            for round_plan in program["rounds"]
        }
        battle_finished = False
        detected_round: int | None = None
        current_round: int | None = None
        has_exchanged = False

        for turn_number, (round_number, turn) in enumerate(turns, start=1):
            if detected_round is not None and round_number < detected_round:
                context.emit(
                    "battle_turn_skipped",
                    "Skipped a configured turn after the battle advanced.",
                    data={
                        "configured_round": round_number,
                        "configured_turn": turn["turn"],
                        "detected_round": detected_round,
                    },
                )
                continue
            if round_number != current_round:
                current_round = round_number
                has_exchanged = False
            raw_skill_actions = [
                action
                for action in turn["actions"]
                if action["source"].get("type") == "skill"
            ]
            skill_actions, skipped_exchange_actions = _filter_post_exchange_skill_actions(
                raw_skill_actions,
                has_exchanged,
            )
            for skipped_action in skipped_exchange_actions:
                context.emit(
                    "skill_skipped",
                    "Skill was skipped because order change already occurred in this round.",
                    data={
                        "action": skipped_action["source"],
                        "reason": "already_exchanged",
                    },
                )
            execute_conditional_skills = True
            for skill_number, action in enumerate(skill_actions, start=1):
                control = action.get("control")
                if control and control["type"] == "condition_start":
                    check_np = bool(control.get("check_np"))
                    check_cards = bool(control["check_cards"])
                    if check_cards:
                        condition = turn.get("condition")
                        if not isinstance(condition, list) or not condition:
                            raise ValueError("Conditional skill block has no card condition.")
                    battle_screenshot: bytes | None = None
                    if check_np or check_cards:
                        battle_screenshot = _wait_for_battle_ready(
                            context,
                            device_service,
                            recognition,
                            attack_template,
                            threshold,
                            timeout_seconds,
                            poll_interval,
                            reconnect_timing=tap_interval,
                            unopened_skills=unopened_skills,
                            occupied_positions=occupied_positions,
                            servant_positions=servant_positions,
                            last_skill_number=last_skill_number,
                        )
                        last_skill_number = None
                        _sync_frontline_alive_positions(
                            context,
                            recognition,
                            battle_screenshot,
                            occupied_positions,
                            servant_positions,
                        )
                    np_matched = True
                    if check_np:
                        assert battle_screenshot is not None
                        assert effective_np_recognizer is not None
                        np_matched = _evaluate_np_condition(
                            context,
                            effective_np_recognizer,
                            battle_screenshot,
                            program["server"],
                            servant_positions,
                            control["np_checks"],
                        )
                    card_matched = True
                    if check_cards:
                        card_matched, condition_taps = _evaluate_card_condition(
                            context,
                            device_service,
                            recognition,
                            card_recognizer,
                            program["server"],
                            _frontline_servants(servant_positions),
                            condition,
                            card_templates,
                            threshold,
                            timeout_seconds,
                            poll_interval,
                            tap_interval,
                            special_keys=special_keys,
                            card_wait_seconds=card_wait_seconds,
                            checks=control["checks"],
                            frontline_recognizer=effective_frontline_recognizer,
                            servant_positions=servant_positions,
                            occupied_positions=occupied_positions,
                            party_servants=party_servants,
                            attack_template=attack_template,
                        )
                        tap_count += condition_taps
                    matched = np_matched and card_matched
                    execute_conditional_skills = matched == control["execute_when_matched"]
                    continue
                if control and control["type"] == "condition_end":
                    execute_conditional_skills = True
                    continue
                if not execute_conditional_skills:
                    context.emit(
                        "skill_skipped",
                        "Skill was skipped because its condition did not match.",
                        data={"action": action["source"]},
                    )
                    continue
                action_count += 1
                context.checkpoint(
                    f"round_{round_number}.turn_{turn['turn']}.skill_{skill_number}",
                    progress=(turn_number - 1) / max(len(turns), 1),
                )
                runtime = action.get("runtime")
                if runtime and runtime["type"] == "hakuno_card_reroll":
                    tap_count += _execute_hakuno_reroll(
                        context,
                        device_service,
                        recognition,
                        card_recognizer,
                        program["server"],
                        _frontline_servants(servant_positions),
                        runtime,
                        card_templates,
                        attack_template,
                        threshold,
                        timeout_seconds,
                        poll_interval,
                        tap_interval,
                        special_keys=special_keys,
                        card_wait_seconds=card_wait_seconds,
                        speedup_skills=speedup_skills,
                        frontline_recognizer=effective_frontline_recognizer,
                        servant_positions=servant_positions,
                        occupied_positions=occupied_positions,
                        party_servants=party_servants,
                    )
                    last_skill_number = None
                    continue
                battle_screenshot = _wait_for_battle_ready(
                    context,
                    device_service,
                    recognition,
                    attack_template,
                    threshold,
                    timeout_seconds,
                    poll_interval,
                    reconnect_timing=tap_interval,
                    unopened_skills=unopened_skills,
                    occupied_positions=occupied_positions,
                    servant_positions=servant_positions,
                    last_skill_number=last_skill_number,
                )
                last_skill_number = None
                _sync_frontline_alive_positions(
                    context,
                    recognition,
                    battle_screenshot,
                    occupied_positions,
                    servant_positions,
                )
                target_skill_number = _servant_skill_number(action)
                if target_skill_number is not None and _is_servant_skill_unavailable(
                    recognition,
                    battle_screenshot,
                    program["server"],
                    target_skill_number,
                    occupied_positions,
                    unopened_skills=unopened_skills,
                    servant_positions=servant_positions,
                ):
                    context.emit(
                        "skill_skipped",
                        "Skill was skipped because it is unavailable.",
                        data={
                            "action": action["source"],
                            "skill_number": target_skill_number,
                            "reason": "skill_unavailable",
                        },
                    )
                    continue
                tap_count += _execute_skill_action(
                    context,
                    device_service,
                    action,
                    tap_interval,
                    speedup_skills=speedup_skills,
                    occupied_positions=occupied_positions,
                )
                last_skill_number = target_skill_number
                _record_skill_buff(
                    action,
                    buff_counts,
                    occupied_positions,
                    servant_positions,
                )
                state_change = action.get("state_change")
                if state_change and state_change["type"] == "servant_exchange":
                    has_exchanged = True
                    _apply_servant_exchange(
                        servant_positions,
                        state_change["positions"],
                    )
                    _apply_servant_exchange(
                        occupied_positions,
                        state_change["positions"],
                    )
                    context.emit(
                        "servant_exchange",
                        "Runtime servant positions were exchanged.",
                        data={
                            "positions": state_change["positions"],
                            "frontline": _frontline_servants(servant_positions),
                        },
                    )

            context.checkpoint(
                f"round_{round_number}.turn_{turn['turn']}.command_phase",
                progress=(turn_number - 0.5) / max(len(turns), 1),
            )
            tap_count += _execute_command_phase(
                context, device_service, recognition, card_recognizer,
                program["server"], _frontline_servants(servant_positions),
                turn["command_phase"]["steps"], threshold, timeout_seconds,
                poll_interval, tap_interval, special_keys=special_keys,
                card_wait_seconds=card_wait_seconds,
                frontline_recognizer=effective_frontline_recognizer,
                servant_positions=servant_positions,
                occupied_positions=occupied_positions,
                party_servants=party_servants,
                buff_counts=buff_counts,
                np_servants=np_servants,
                unopened_skills=unopened_skills,
                last_skill_number=last_skill_number,
                np_recognizer=effective_np_recognizer,
            )
            last_skill_number = None
            action_count += sum(
                1 for action in turn["actions"] if action["source"].get("type") == "np"
            )
            for action in turn["actions"]:
                if action["source"].get("type") != "replace":
                    continue
                _apply_servant_replacements(
                    servant_positions,
                    action["source"]["replacements"],
                )
                _apply_servant_replacements(
                    occupied_positions,
                    action["source"]["replacements"],
                )
                context.emit(
                    "servant_replacement",
                    "Post-turn servant positions were updated.",
                    data={
                        "replacements": action["source"]["replacements"],
                        "frontline": _frontline_servants(servant_positions),
                    },
                )

            extra_turn = _resolve_fallback_extra_turn(program, round_number)
            transition = _wait_for_battle_transition(
                context,
                device_service,
                recognition,
                program["server"],
                threshold,
                timeout_seconds,
                poll_interval,
                reconnect_timing=tap_interval,
            )
            if transition["state"] == "finished":
                battle_finished = True
            else:
                detected_round = int(transition["round"])
            if (
                not battle_finished
                and turn["turn"] == last_turns[round_number]
                and transition["round"] == round_number
            ):
                exchange_state = {"has_exchanged": has_exchanged}
                for extra_number in range(1, 11):
                    context.emit(
                        "battle_extra_turn",
                        "Executing configured extra battle turn.",
                        data={"round": round_number, "extra_turn": extra_number},
                    )
                    tap_count += _execute_extra_turn(
                        context,
                        device_service,
                        recognition,
                        card_recognizer,
                        program["server"],
                        servant_positions,
                        extra_turn,
                        card_templates,
                        attack_template,
                        threshold,
                        timeout_seconds,
                        poll_interval,
                        tap_interval,
                        special_keys=special_keys,
                        card_wait_seconds=card_wait_seconds,
                        speedup_skills=speedup_skills,
                        occupied_positions=occupied_positions,
                        np_recognizer=effective_np_recognizer,
                        exchange_state=exchange_state,
                        frontline_recognizer=effective_frontline_recognizer,
                        party_servants=party_servants,
                        servant_diff_state=servant_diff_state,
                        buff_counts=buff_counts,
                        np_servants=np_servants,
                        unopened_skills=unopened_skills,
                    )
                    has_exchanged = exchange_state["has_exchanged"]
                    transition = _wait_for_battle_transition(
                        context,
                        device_service,
                        recognition,
                        program["server"],
                        threshold,
                        timeout_seconds,
                        poll_interval,
                        reconnect_timing=tap_interval,
                    )
                    if transition["state"] == "finished":
                        battle_finished = True
                        break
                    detected_round = int(transition["round"])
                    if detected_round != round_number:
                        break
                else:
                    raise RuntimeError(
                        f"Round {round_number} exceeded the 10 configured extra-turn limit."
                    )
            if battle_finished:
                break

        while not battle_finished and detected_round is not None:
            active_round = detected_round
            if active_round != current_round:
                current_round = active_round
                has_exchanged = False
            extra_turn = _resolve_fallback_extra_turn(program, active_round)
            exchange_state = {"has_exchanged": has_exchanged}
            for extra_number in range(1, 11):
                context.emit(
                    "battle_extra_turn",
                    "Executing configured extra battle turn.",
                    data={"round": active_round, "extra_turn": extra_number},
                )
                tap_count += _execute_extra_turn(
                    context,
                    device_service,
                    recognition,
                    card_recognizer,
                    program["server"],
                    servant_positions,
                    extra_turn,
                    card_templates,
                    attack_template,
                    threshold,
                    timeout_seconds,
                    poll_interval,
                    tap_interval,
                    special_keys=special_keys,
                    card_wait_seconds=card_wait_seconds,
                    speedup_skills=speedup_skills,
                    occupied_positions=occupied_positions,
                    np_recognizer=effective_np_recognizer,
                    exchange_state=exchange_state,
                    frontline_recognizer=effective_frontline_recognizer,
                    party_servants=party_servants,
                    servant_diff_state=servant_diff_state,
                    buff_counts=buff_counts,
                    np_servants=np_servants,
                    unopened_skills=unopened_skills,
                )
                has_exchanged = exchange_state["has_exchanged"]
                transition = _wait_for_battle_transition(
                    context,
                    device_service,
                    recognition,
                    program["server"],
                    threshold,
                    timeout_seconds,
                    poll_interval,
                    reconnect_timing=tap_interval,
                )
                if transition["state"] == "finished":
                    battle_finished = True
                    break
                detected_round = int(transition["round"])
                if detected_round != active_round:
                    break
            else:
                raise RuntimeError(
                    f"Round {active_round} exceeded the 10 configured extra-turn limit."
                )

        context.checkpoint("complete", progress=1.0, message="Battle execution completed.")
        return {
            "setting_name": setting_name,
            "turn_count": len(turns),
            "action_count": program["summary"]["action_count"],
            "tap_count": tap_count,
        }

    return execute


def _filter_post_exchange_skill_actions(
    skill_actions: list[dict[str, Any]],
    has_exchanged: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not has_exchanged:
        return skill_actions, []
    exchange_idx: int | None = None
    has_start = False
    for index, action in enumerate(skill_actions):
        control = action.get("control")
        if control and control.get("type") == "condition_start":
            has_start = True
            continue
        if control and control.get("type") == "condition_end":
            has_start = False
            continue
        state_change = action.get("state_change")
        if state_change and state_change.get("type") == "servant_exchange":
            exchange_idx = index
            break
    if exchange_idx is None:
        return skill_actions, []
    skipped_actions = [
        action
        for action in skill_actions[: exchange_idx + 1]
        if not action.get("control")
    ]
    remaining = list(skill_actions[exchange_idx + 1 :])
    if has_start:
        for index, action in enumerate(remaining):
            control = action.get("control")
            if control and control.get("type") == "condition_end":
                remaining.pop(index)
                break
    return remaining, skipped_actions


def _is_configured_extra_turn(extra_turn: dict[str, Any]) -> bool:
    if extra_turn.get("actions"):
        return True
    return any(
        step.get("type") == "strategy"
        for step in extra_turn.get("command_phase", {}).get("steps", [])
    )


def _round_has_configured_turn_content(round_plan: dict[str, Any]) -> bool:
    for turn in round_plan.get("turns", []):
        if turn.get("actions") or turn.get("condition"):
            return True
        if any(
            step.get("type") == "strategy"
            or str(step.get("role", "")).startswith("np_")
            for step in turn.get("command_phase", {}).get("steps", [])
        ):
            return True
    return False


def _resolve_fallback_extra_turn(
    program: dict[str, Any],
    round_number: int,
) -> dict[str, Any]:
    compiled_rounds = {
        round_plan["round"]: round_plan for round_plan in program["rounds"]
    }
    if round_number in compiled_rounds:
        candidate = compiled_rounds[round_number]["extra_turn"]
        if _is_configured_extra_turn(candidate):
            return candidate
    max_configured_round = max(compiled_rounds, default=1)
    if round_number >= max_configured_round:
        for round_plan in reversed(program["rounds"]):
            candidate = round_plan["extra_turn"]
            if _is_configured_extra_turn(candidate):
                return candidate
            if (
                round_plan["round"] < round_number
                and _round_has_configured_turn_content(round_plan)
            ):
                break
    if round_number in compiled_rounds:
        return compiled_rounds[round_number]["extra_turn"]
    return program["rounds"][-1]["extra_turn"]


def _party_servant_names(
    party_servants: list[dict[str, Any]] | None,
    servant_positions: list[dict[str, Any] | None],
) -> list[str]:
    names = [""] * 6
    for source in (party_servants or [], servant_positions):
        for entry in source:
            if not isinstance(entry, dict):
                continue
            slot = entry.get("slot")
            name = entry.get("canonical_name") or entry.get("name")
            if (
                isinstance(slot, int)
                and not isinstance(slot, bool)
                and slot >= 0
                and isinstance(name, str)
                and name
            ):
                while len(names) <= slot:
                    names.append("")
                names[slot] = name
    return names


def _resolve_free_skill_target(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    card_recognizer: CommandCardRecognizer | None,
    server: str,
    servant_positions: list[dict[str, Any] | None],
    occupied_positions: list[int | None] | None,
    buff_counts: list[int] | None,
    np_servants: set[int] | None,
    card_templates: list[str],
    attack_template: str,
    threshold: float,
    timeout_seconds: float,
    poll_interval: float,
    tap_interval: float | _TapTiming,
    *,
    special_keys: list[dict[str, Any]] | None = None,
    card_wait_seconds: float = 0.0,
    frontline_recognizer: FrontlineServantRecognizer | None = None,
    party_servants: list[dict[str, Any]] | None = None,
) -> tuple[int, int]:
    max_idx = 0
    max_score = 0
    for frontline_idx in range(3):
        slot = _party_slot_at_frontline(
            frontline_idx,
            occupied_positions,
            servant_positions,
        )
        if slot is not None and buff_counts is not None and 0 <= slot < len(buff_counts):
            score = min(9, max(0, buff_counts[slot])) + (
                2 if np_servants is not None and slot in np_servants else 0
            )
            if score > max_score:
                max_idx = frontline_idx + 1
                max_score = score
    tap_count = 0
    if max_score == 0 and card_recognizer is not None:
        attack_x, attack_y = ATTACK_POINT
        tap_count += _execute_steps(
            context,
            device_service,
            [{"type": "tap", "role": "free_skill_probe_attack", "x": attack_x, "y": attack_y}],
            tap_interval,
        )
        screenshot = _wait_for_command_cards(
            context,
            device_service,
            recognition,
            card_templates,
            threshold,
            timeout_seconds,
            poll_interval,
            reconnect_timing=tap_interval,
            settle_seconds=card_wait_seconds,
        )
        recognized, screenshot, recovery_taps = _recognize_command_cards_with_recovery(
            context,
            device_service,
            recognition,
            card_recognizer,
            screenshot,
            server,
            _frontline_servants(servant_positions),
            threshold,
            special_keys,
            frontline_recognizer=frontline_recognizer,
            servant_positions=servant_positions,
            occupied_positions=occupied_positions,
            party_servants=party_servants,
            card_templates=card_templates,
            attack_template=attack_template,
            timeout_seconds=timeout_seconds,
            poll_interval=poll_interval,
            tap_interval=tap_interval,
            card_wait_seconds=card_wait_seconds,
        )
        tap_count += recovery_taps
        weak_servants = [
            int(card["servant"])
            for card in recognized.get("cards", [])
            if card.get("affinity_score") == 1 and card.get("servant") in (1, 2, 3)
        ]
        if weak_servants:
            max_idx = min(weak_servants)
        back_x, back_y = COMMAND_CARD_BACK_POINT
        tap_count += _execute_steps(
            context,
            device_service,
            [{"type": "tap", "role": "free_skill_probe_back", "x": back_x, "y": back_y}],
            tap_interval,
        )
    if max_idx == 0:
        max_idx = 1
    return max_idx, tap_count


def _execute_extra_turn(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    card_recognizer: CommandCardRecognizer | None,
    server: str,
    servant_positions: list[dict[str, Any] | None],
    turn: dict[str, Any],
    card_templates: list[str],
    attack_template: str,
    threshold: float,
    timeout_seconds: float,
    poll_interval: float,
    tap_interval: float | _TapTiming,
    special_keys: list[dict[str, Any]] | None = None,
    card_wait_seconds: float = 0.0,
    speedup_skills: bool = False,
    occupied_positions: list[int | None] | None = None,
    np_recognizer: NpChargeRecognizer | None = None,
    exchange_state: dict[str, bool] | None = None,
    *,
    frontline_recognizer: FrontlineServantRecognizer | None = None,
    party_servants: list[dict[str, Any]] | None = None,
    servant_diff_state: dict[str, Any] | None = None,
    buff_counts: list[int] | None = None,
    np_servants: set[int] | None = None,
    unopened_skills: list[set[int]] | None = None,
) -> int:
    tap_count = 0
    checked_frontline_names = False
    cached_battle_screenshot: bytes | None = None
    last_skill_number: int | None = None

    def sync_extra_turn_frontline(battle_screenshot: bytes) -> None:
        nonlocal checked_frontline_names
        _sync_frontline_alive_positions(
            context,
            recognition,
            battle_screenshot,
            occupied_positions,
            servant_positions,
        )
        if checked_frontline_names:
            return
        _update_servant_diff_state(
            context,
            servant_positions,
            servant_diff_state,
        )
        name_sync = _sync_frontline_servant_names(
            context,
            device_service,
            frontline_recognizer,
            battle_screenshot,
            server,
            servant_positions,
            occupied_positions,
            party_servants,
            retry_wait_seconds=poll_interval,
        )
        for index in range(3):
            slot = _party_slot_at_frontline(
                index,
                occupied_positions,
                servant_positions,
            )
            _ensure_party_slot_capacity(slot, buff_counts, unopened_skills)
        _update_servant_diff_state(
            context,
            servant_positions,
            servant_diff_state,
            names_changed=bool(name_sync and name_sync.get("changed")),
        )
        checked_frontline_names = True

    def get_or_wait_battle_ready() -> bytes:
        nonlocal cached_battle_screenshot, last_skill_number
        if cached_battle_screenshot is not None:
            shot = cached_battle_screenshot
            cached_battle_screenshot = None
            return shot
        shot = _wait_for_battle_ready(
            context,
            device_service,
            recognition,
            attack_template,
            threshold,
            timeout_seconds,
            poll_interval,
            reconnect_timing=tap_interval,
            unopened_skills=unopened_skills,
            occupied_positions=occupied_positions,
            servant_positions=servant_positions,
            last_skill_number=last_skill_number,
        )
        last_skill_number = None
        return shot

    raw_skill_actions = [
        action
        for action in turn["actions"]
        if action["source"].get("type") == "skill"
    ]
    can_synthesize_diff_skills = (
        servant_diff_state is not None
        and (
            _has_skill_availability_assets(recognition, server)
            or bool(servant_diff_state.get("enable_free_skills"))
        )
        and (
            (frontline_recognizer is not None and frontline_recognizer.has_assets())
            or bool(servant_diff_state.get("has_diff"))
        )
    )
    if can_synthesize_diff_skills:
        cached_battle_screenshot = get_or_wait_battle_ready()
        sync_extra_turn_frontline(cached_battle_screenshot)
        if servant_diff_state is not None and servant_diff_state.get("has_diff"):
            available_skills = [
                not _is_servant_skill_unavailable(
                    recognition,
                    cached_battle_screenshot,
                    server,
                    skill_num,
                    occupied_positions,
                    unopened_skills=unopened_skills,
                    servant_positions=servant_positions,
                )
                for skill_num in range(1, 10)
            ]
            party_names = _party_servant_names(party_servants, servant_positions)
            frontline_names = [
                (servant.get("canonical_name") or servant.get("name"))
                if isinstance(servant, dict)
                else None
                for servant in servant_positions[:3]
            ]
            preview_free = build_autonomous_skill_commands(
                party_names,
                occupied_positions,
                default_target=1,
                available_skills=available_skills,
                unopened_skills=unopened_skills,
                frontline_servant_names=frontline_names,
            )
            if preview_free:
                max_idx, probe_taps = _resolve_free_skill_target(
                    context,
                    device_service,
                    recognition,
                    card_recognizer,
                    server,
                    servant_positions,
                    occupied_positions,
                    buff_counts,
                    np_servants,
                    card_templates,
                    attack_template,
                    threshold,
                    timeout_seconds,
                    poll_interval,
                    tap_interval,
                    special_keys=special_keys,
                    card_wait_seconds=card_wait_seconds,
                    frontline_recognizer=frontline_recognizer,
                    party_servants=party_servants,
                )
                tap_count += probe_taps
                if probe_taps > 0:
                    cached_battle_screenshot = None
                free_commands = build_autonomous_skill_commands(
                    party_names,
                    occupied_positions,
                    default_target=max_idx,
                    available_skills=available_skills,
                    unopened_skills=unopened_skills,
                    frontline_servant_names=frontline_names,
                )
                extra_commands = [
                    action["source"]["command"]
                    for action in raw_skill_actions
                    if "command" in action.get("source", {})
                ]
                if extra_commands:
                    commands = build_complex_skill_commands(
                        extra_commands,
                        free_commands,
                        default_target=max_idx,
                    )
                    mode = "complex"
                else:
                    commands = free_commands
                    mode = "free"
                raw_skill_actions = [
                    compiled
                    for command in commands
                    if (compiled := compile_skill_command(command))["supported"]
                ]
                context.emit(
                    "servant_diff_skills",
                    "Synthesized extra-turn skills after frontline servant diff.",
                    data={
                        "mode": mode,
                        "target": max_idx,
                        "commands": commands,
                    },
                )

    has_exchanged = bool(exchange_state and exchange_state.get("has_exchanged"))
    skill_actions, skipped_exchange_actions = _filter_post_exchange_skill_actions(
        raw_skill_actions,
        has_exchanged,
    )
    for skipped_action in skipped_exchange_actions:
        context.emit(
            "skill_skipped",
            "Skill was skipped because order change already occurred in this round.",
            data={
                "action": skipped_action["source"],
                "reason": "already_exchanged",
            },
        )
    execute_conditional_skills = True
    for action in skill_actions:
        control = action.get("control")
        if control and control["type"] == "condition_start":
            check_np = bool(control.get("check_np"))
            check_cards = bool(control["check_cards"])
            if check_cards:
                condition = turn.get("condition")
                if not isinstance(condition, list) or not condition:
                    raise ValueError("Conditional skill block has no card condition.")
            battle_screenshot: bytes | None = None
            if check_np or check_cards:
                battle_screenshot = get_or_wait_battle_ready()
                sync_extra_turn_frontline(battle_screenshot)
            np_matched = True
            if check_np:
                if np_recognizer is None:
                    raise ValueError("NP charge recognition is not configured.")
                assert battle_screenshot is not None
                np_matched = _evaluate_np_condition(
                    context,
                    np_recognizer,
                    battle_screenshot,
                    server,
                    servant_positions,
                    control["np_checks"],
                )
            card_matched = True
            if check_cards:
                card_matched, condition_taps = _evaluate_card_condition(
                    context,
                    device_service,
                    recognition,
                    card_recognizer,
                    server,
                    _frontline_servants(servant_positions),
                    condition,
                    card_templates,
                    threshold,
                    timeout_seconds,
                    poll_interval,
                    tap_interval,
                    special_keys=special_keys,
                    card_wait_seconds=card_wait_seconds,
                    checks=control["checks"],
                    frontline_recognizer=frontline_recognizer,
                    servant_positions=servant_positions,
                    occupied_positions=occupied_positions,
                    party_servants=party_servants,
                    attack_template=attack_template,
                )
                tap_count += condition_taps
            matched = np_matched and card_matched
            execute_conditional_skills = matched == control["execute_when_matched"]
            continue
        if control and control["type"] == "condition_end":
            execute_conditional_skills = True
            continue
        if not execute_conditional_skills:
            context.emit(
                "skill_skipped",
                "Skill was skipped because its condition did not match.",
                data={"action": action["source"]},
            )
            continue
        runtime = action.get("runtime")
        if runtime and runtime["type"] == "hakuno_card_reroll":
            if card_recognizer is None:
                raise ValueError("Command card recognition is not configured.")
            tap_count += _execute_hakuno_reroll(
                context,
                device_service,
                recognition,
                card_recognizer,
                server,
                _frontline_servants(servant_positions),
                runtime,
                card_templates,
                attack_template,
                threshold,
                timeout_seconds,
                poll_interval,
                tap_interval,
                special_keys=special_keys,
                card_wait_seconds=card_wait_seconds,
                speedup_skills=speedup_skills,
                frontline_recognizer=frontline_recognizer,
                servant_positions=servant_positions,
                occupied_positions=occupied_positions,
                party_servants=party_servants,
            )
            cached_battle_screenshot = None
            last_skill_number = None
            continue
        battle_screenshot = get_or_wait_battle_ready()
        sync_extra_turn_frontline(battle_screenshot)
        target_skill_number = _servant_skill_number(action)
        if target_skill_number is not None and _is_servant_skill_unavailable(
            recognition,
            battle_screenshot,
            server,
            target_skill_number,
            occupied_positions,
            unopened_skills=unopened_skills,
            servant_positions=servant_positions,
        ):
            context.emit(
                "skill_skipped",
                "Skill was skipped because it is unavailable.",
                data={
                    "action": action["source"],
                    "skill_number": target_skill_number,
                    "reason": "skill_unavailable",
                },
            )
            continue
        tap_count += _execute_skill_action(
            context,
            device_service,
            action,
            tap_interval,
            speedup_skills=speedup_skills,
            occupied_positions=occupied_positions,
        )
        last_skill_number = target_skill_number
        _record_skill_buff(
            action,
            buff_counts,
            occupied_positions,
            servant_positions,
        )
        state_change = action.get("state_change")
        if state_change and state_change["type"] == "servant_exchange":
            if exchange_state is not None:
                exchange_state["has_exchanged"] = True
            _apply_servant_exchange(servant_positions, state_change["positions"])
            if occupied_positions is not None:
                _apply_servant_exchange(
                    occupied_positions,
                    state_change["positions"],
                )
            context.emit(
                "servant_exchange",
                "Runtime servant positions were exchanged.",
                data={
                    "positions": state_change["positions"],
                    "frontline": _frontline_servants(servant_positions),
                },
            )

    tap_count += _execute_command_phase(
        context, device_service, recognition, card_recognizer, server,
        _frontline_servants(servant_positions), turn["command_phase"]["steps"],
        threshold, timeout_seconds, poll_interval, tap_interval,
        special_keys=special_keys, card_wait_seconds=card_wait_seconds,
        frontline_recognizer=frontline_recognizer,
        servant_positions=servant_positions,
        occupied_positions=occupied_positions,
        party_servants=party_servants,
        check_servant_names=not checked_frontline_names,
        servant_diff_state=servant_diff_state,
        is_extra_turn=True,
        buff_counts=buff_counts,
        np_servants=np_servants,
        unopened_skills=unopened_skills,
        last_skill_number=last_skill_number,
        initial_battle_screenshot=cached_battle_screenshot,
        np_recognizer=np_recognizer,
    )
    return tap_count


def _execute_command_phase(
    context: RunContext, device_service: DeviceService, recognition: RecognitionService,
    card_recognizer: CommandCardRecognizer | None, server: str,
    servants: list[dict[str, Any]], command_steps: list[dict[str, Any]],
    threshold: float, timeout_seconds: float, poll_interval: float,
    tap_interval: float | _TapTiming, *,
    special_keys: list[dict[str, Any]] | None = None, card_wait_seconds: float = 0.0,
    frontline_recognizer: FrontlineServantRecognizer | None = None,
    servant_positions: list[dict[str, Any] | None] | None = None,
    occupied_positions: list[int | None] | None = None,
    party_servants: list[dict[str, Any]] | None = None,
    check_servant_names: bool = False,
    servant_diff_state: dict[str, Any] | None = None,
    is_extra_turn: bool = False,
    buff_counts: list[int] | None = None,
    np_servants: set[int] | None = None,
    unopened_skills: list[set[int]] | None = None,
    last_skill_number: int | None = None,
    initial_battle_screenshot: bytes | None = None,
    np_recognizer: NpChargeRecognizer | None = None,
) -> int:
    unavailable_nps: set[int] = set()
    tap_count = 0
    attack_template = f"battle/{server}/attack.png"
    card_templates = [f"battle/{server}/{color}.png" for color in ("Arts", "Buster", "Quick")]
    pending_skill_number = last_skill_number
    for attempt in range(4):
        if attempt == 0 and initial_battle_screenshot is not None:
            battle_screenshot = initial_battle_screenshot
        else:
            battle_screenshot = _wait_for_battle_ready(
                context, device_service, recognition, attack_template,
                threshold, timeout_seconds, poll_interval, reconnect_timing=tap_interval,
                dismiss_command_cards=attempt == 0,
                unopened_skills=unopened_skills,
                occupied_positions=occupied_positions,
                servant_positions=servant_positions,
                last_skill_number=pending_skill_number,
            )
            pending_skill_number = None
        if attempt == 0 and check_servant_names and servant_positions is not None:
            _sync_frontline_alive_positions(
                context,
                recognition,
                battle_screenshot,
                occupied_positions,
                servant_positions,
            )
            _update_servant_diff_state(
                context,
                servant_positions,
                servant_diff_state,
            )
            name_sync = _sync_frontline_servant_names(
                context,
                device_service,
                frontline_recognizer,
                battle_screenshot,
                server,
                servant_positions,
                occupied_positions,
                party_servants,
                retry_wait_seconds=poll_interval,
            )
            for index in range(3):
                slot = _party_slot_at_frontline(
                    index,
                    occupied_positions,
                    servant_positions,
                )
                _ensure_party_slot_capacity(slot, buff_counts, unopened_skills)
            _update_servant_diff_state(
                context,
                servant_positions,
                servant_diff_state,
                names_changed=bool(name_sync and name_sync.get("changed")),
            )
            servants[:] = _frontline_servants(servant_positions)
        tap_count += _execute_steps(context, device_service, command_steps[:1], tap_interval)
        screenshot = _wait_for_command_cards(
            context, device_service, recognition, card_templates,
            threshold, timeout_seconds, poll_interval, reconnect_timing=tap_interval,
            settle_seconds=card_wait_seconds,
        )
        tap_steps = []
        for step in command_steps[1:]:
            if step.get("type") == "strategy":
                effective_step = (
                    {
                        **step,
                        "strategies": [
                            {f"card{index}": {"type": 2} for index in (1, 2, 3)}
                        ],
                        "avoid_chain": False,
                        "use_default_scoring": True,
                    }
                    if is_extra_turn
                    and servant_diff_state is not None
                    and servant_diff_state.get("has_diff")
                    else dict(step)
                )
                if "buff_counts" not in effective_step and buff_counts is not None:
                    effective_step["buff_counts"] = buff_counts
                if "np_servants" not in effective_step and np_servants is not None:
                    effective_step["np_servants"] = np_servants
                strategy_steps, recovery_taps, screenshot = _strategy_tap_steps_with_recovery(
                    context,
                    device_service,
                    recognition,
                    card_recognizer,
                    screenshot,
                    server,
                    servants,
                    effective_step,
                    threshold,
                    special_keys=special_keys,
                    unavailable_nps=sorted(unavailable_nps),
                    frontline_recognizer=frontline_recognizer if attempt == 0 else None,
                    servant_positions=servant_positions,
                    occupied_positions=occupied_positions,
                    party_servants=party_servants,
                    card_templates=card_templates,
                    attack_template=attack_template,
                    timeout_seconds=timeout_seconds,
                    poll_interval=poll_interval,
                    tap_interval=tap_interval,
                    card_wait_seconds=card_wait_seconds,
                )
                tap_count += recovery_taps
                tap_steps.extend(strategy_steps)
            elif step.get("type") == "tap":
                tap_steps.append(step)
        if unavailable_nps and not any(step.get("type") == "strategy" for step in command_steps):
            blocks = recognize_card_blocks(recognition, screenshot, server, threshold=threshold)
            unavailable_nps.update(blocks["nps"])
            tap_steps = _replace_blocked_direct_cards(tap_steps, unavailable_nps, set(blocks["faces"]))
        tap_count += _execute_steps(context, device_service, tap_steps, tap_interval)
        selected_nps = {int(step["role"][3:]) for step in tap_steps if step.get("role", "").startswith("np_")}
        if not selected_nps:
            return tap_count
        present_frontline = (
            [position is not None for position in occupied_positions[:3]]
            if isinstance(occupied_positions, list) and len(occupied_positions) >= 3
            else [True, True, True]
        )
        blocked = _failed_np_selection(
            context, device_service, recognition, server, selected_nps,
            threshold, 2.0, poll_interval,
            battle_screenshot=battle_screenshot,
            np_recognizer=np_recognizer,
            present=present_frontline,
        )
        newly_blocked = blocked - unavailable_nps
        if not newly_blocked:
            if not is_extra_turn:
                _record_np_servants(
                    selected_nps - unavailable_nps,
                    np_servants,
                    occupied_positions,
                    servant_positions,
                )
            return tap_count
        unavailable_nps.update(newly_blocked)
        context.emit(
            "np_selection_recovery", "Unavailable Noble Phantasms will be replaced.",
            data={"attempt": attempt + 1, "unavailable_nps": sorted(unavailable_nps)},
        )
        tap_count += _execute_steps(context, device_service, [{
            "type": "tap", "role": "np_recovery_back",
            "x": COMMAND_CARD_BACK_POINT[0], "y": COMMAND_CARD_BACK_POINT[1],
        }], tap_interval)
    raise StrategySelectionError("Noble Phantasm selection recovery exhausted all three positions.")


def _replace_blocked_direct_cards(
    tap_steps: list[dict[str, Any]], unavailable_nps: set[int], blocked_faces: set[int],
) -> list[dict[str, Any]]:
    result = [
        step for step in tap_steps
        if not (step.get("role", "").startswith("np_") and int(step["role"][3:]) in unavailable_nps)
        and not (step.get("role", "").startswith("face_card_") and int(step["role"][10:]) in blocked_faces)
    ]
    selected_slots = {int(step["role"][10:]) for step in result if step.get("role", "").startswith("face_card_")}
    for slot, (x, y) in enumerate(FACE_CARD_POINTS, start=1):
        if len(result) >= 3:
            break
        if slot not in selected_slots and slot not in blocked_faces:
            result.append({"type": "tap", "role": f"face_card_{slot}", "x": x, "y": y})
    if len(result) != 3:
        raise StrategySelectionError("Not enough available command cards to replace blocked Noble Phantasms.")
    return result


def _failed_np_selection(
    context: RunContext, device_service: DeviceService, recognition: RecognitionService,
    server: str, selected_nps: set[int], threshold: float,
    wait_seconds: float, poll_interval: float,
    *,
    battle_screenshot: bytes | None = None,
    np_recognizer: NpChargeRecognizer | None = None,
    present: list[bool] | None = None,
) -> set[int]:
    started = active_monotonic(context, clock=monotonic)
    while True:
        screenshot = device_service.snapshot()
        back = _match_optional_battle_template(
            recognition, screenshot, f"battle/{server}/back.png", roi=(1100, 610, 180, 110),
        )
        if back is None or not back.matched:
            return set()
        if active_monotonic(context, clock=monotonic) - started >= wait_seconds:
            blocks = recognize_card_blocks(recognition, screenshot, server, threshold=threshold)
            if selected_nps.intersection(blocks["nps"]):
                return set(blocks["nps"])
            if battle_screenshot is not None:
                checker = np_recognizer or NpChargeRecognizer(recognition)
                flags = (
                    present
                    if isinstance(present, list) and len(present) == 3
                    else [True, True, True]
                )
                try:
                    charges = checker.recognize(battle_screenshot, server, present=flags)
                except (AppError, ValueError):
                    charges = None
                if isinstance(charges, dict):
                    values = charges.get("values")
                    if isinstance(values, list) and len(values) == 3:
                        return {
                            position
                            for position in selected_nps
                            if isinstance(values[position - 1], int)
                            and not isinstance(values[position - 1], bool)
                            and values[position - 1] < 100
                        }
            return set()
        context.sleep(max(poll_interval, 0.01))


def _servant_positions(
    servants: list[dict[str, Any]],
    *,
    assist_slot: int | None = None,
) -> list[dict[str, Any] | None]:
    positions: list[dict[str, Any] | None] = [None] * 6
    valid_assist_slot = (
        assist_slot
        if isinstance(assist_slot, int)
        and not isinstance(assist_slot, bool)
        and 0 <= assist_slot < len(positions)
        else None
    )
    for servant in servants:
        slot = servant.get("slot")
        if (
            isinstance(slot, int)
            and not isinstance(slot, bool)
            and 0 <= slot < len(positions)
        ):
            is_assist = bool(
                servant.get("is_assist")
                or servant.get("assist")
                or (valid_assist_slot is not None and slot == valid_assist_slot)
            )
            if servant.get("name") or is_assist:
                entry = dict(servant)
                if is_assist:
                    entry["is_assist"] = True
                positions[slot] = entry
    return positions


def _frontline_servants(
    servant_positions: list[dict[str, Any] | None],
) -> list[dict[str, Any]]:
    frontline = []
    for battle_position, servant in enumerate(servant_positions[:3], start=1):
        if servant is None:
            continue
        frontline.append(
            {
                **servant,
                "active": True,
                "battle_position": battle_position,
            }
        )
    return frontline


def _apply_servant_replacements(
    servant_positions: list[dict[str, Any] | None],
    replacements: dict[str, int | None],
) -> None:
    previous = list(servant_positions)
    for destination, source in replacements.items():
        destination_index = int(destination) - 1
        servant_positions[destination_index] = (
            previous[source - 1] if source is not None else None
        )


def _apply_servant_exchange(
    servant_positions: list[dict[str, Any] | None],
    positions: list[int],
) -> None:
    left, right = positions
    servant_positions[left - 1], servant_positions[right - 1] = (
        servant_positions[right - 1],
        servant_positions[left - 1],
    )


def _execute_strategy_step(
    context: RunContext,
    device_service: DeviceService,
    card_recognizer: CommandCardRecognizer | None,
    screenshot: bytes,
    server: str,
    servants: list[dict[str, Any]],
    step: dict[str, Any],
    threshold: float,
    tap_interval: float | _TapTiming,
    special_keys: list[dict[str, Any]] | None = None,
) -> int:
    return _execute_steps(context, device_service, _strategy_tap_steps(
        context, card_recognizer, screenshot, server, servants, step, threshold,
        special_keys=special_keys,
    ), tap_interval)


def _strategy_tap_steps_with_recovery(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    card_recognizer: CommandCardRecognizer | None,
    screenshot: bytes,
    server: str,
    servants: list[dict[str, Any]],
    step: dict[str, Any],
    threshold: float,
    *,
    special_keys: list[dict[str, Any]] | None = None,
    unavailable_nps: list[int] | None = None,
    frontline_recognizer: FrontlineServantRecognizer | None = None,
    servant_positions: list[dict[str, Any] | None] | None = None,
    occupied_positions: list[int | None] | None = None,
    party_servants: list[dict[str, Any]] | None = None,
    card_templates: list[str] | None = None,
    attack_template: str | None = None,
    timeout_seconds: float = 15.0,
    poll_interval: float = 0.25,
    tap_interval: float | _TapTiming = 0.0,
    card_wait_seconds: float = 0.0,
) -> tuple[list[dict[str, Any]], int, bytes]:
    if card_recognizer is None:
        raise ValueError("Command card recognition is not configured.")
    recognized, screenshot, recovery_taps = _recognize_command_cards_with_recovery(
        context,
        device_service,
        recognition,
        card_recognizer,
        screenshot,
        server,
        servants,
        threshold,
        special_keys,
        frontline_recognizer=frontline_recognizer,
        servant_positions=servant_positions,
        occupied_positions=occupied_positions,
        party_servants=party_servants,
        card_templates=card_templates,
        attack_template=attack_template,
        timeout_seconds=timeout_seconds,
        poll_interval=poll_interval,
        tap_interval=tap_interval,
        card_wait_seconds=card_wait_seconds,
    )
    return (
        _resolve_strategy_tap_steps_from_recognized(
            context,
            recognized,
            step,
            unavailable_nps=unavailable_nps,
            servants=servants,
            server=server,
        ),
        recovery_taps,
        screenshot,
    )


def _strategy_tap_steps(
    context: RunContext, card_recognizer: CommandCardRecognizer | None,
    screenshot: bytes, server: str, servants: list[dict[str, Any]],
    step: dict[str, Any], threshold: float, *,
    special_keys: list[dict[str, Any]] | None = None,
    unavailable_nps: list[int] | None = None,
) -> list[dict[str, Any]]:
    if card_recognizer is None:
        raise ValueError("Command card recognition is not configured.")
    recognized = _recognize_command_cards(
        card_recognizer,
        screenshot,
        server,
        servants,
        threshold,
        special_keys,
    )
    return _resolve_strategy_tap_steps_from_recognized(
        context,
        recognized,
        step,
        unavailable_nps=unavailable_nps,
        servants=servants,
        server=server,
    )


def _resolve_strategy_tap_steps_from_recognized(
    context: RunContext,
    recognized: dict[str, Any],
    step: dict[str, Any],
    *,
    unavailable_nps: list[int] | None = None,
    servants: list[dict[str, Any]] | None = None,
    server: str = "CH",
) -> list[dict[str, Any]]:
    context.emit(
        "card_recognition",
        "Command cards were classified.",
        data=recognized,
    )
    if not recognized["complete"]:
        raise ValueError(
            f"Recognized {recognized['recognized_count']} of 5 command cards."
        )
    if step.get("use_default_scoring"):
        selected = select_command_cards_default(
            recognized["cards"],
            preselected_nps=step.get("preselected_nps", []),
            unavailable_nps=unavailable_nps,
            frontline_servants=servants,
            buff_counts=step.get("buff_counts"),
            np_servants=step.get("np_servants"),
            server=server,
        )
    elif step.get("avoid_chain"):
        preselected_nps = step.get("preselected_nps")
        if not isinstance(preselected_nps, list) or len(preselected_nps) != 1:
            raise StrategySelectionError(
                "No-chain selection requires exactly one Noble Phantasm."
            )
        if preselected_nps[0] in (unavailable_nps or []):
            selected = select_command_cards(
                [{f"card{index}": {"type": 2} for index in (1, 2, 3)}], recognized["cards"],
            )
        else:
            selected = select_command_cards_without_chain(
                recognized["cards"], preselected_np=preselected_nps[0],
            )
    else:
        selected = select_command_cards(
            step["strategies"],
            recognized["cards"],
            preselected_nps=step.get("preselected_nps", []),
            unavailable_nps=unavailable_nps,
            allow_star_relaxation=bool(step.get("allow_star_relaxation", True)),
            fallback_to_default=bool(step.get("fallback_to_default", True)),
            frontline_servants=servants,
            buff_counts=step.get("buff_counts"),
            np_servants=step.get("np_servants"),
            server=server,
        )
    context.emit(
        "strategy_selection",
        "Command card strategy was resolved.",
        data={"selected": selected},
    )
    tap_steps = []
    for selection in selected:
        if selection["type"] == "np":
            servant = int(selection["servant"])
            x, y = NP_POINTS[servant - 1]
            tap_steps.append(
                {"type": "tap", "role": f"np_{servant}", "x": x, "y": y}
            )
        else:
            slot = int(selection["slot"])
            x, y = FACE_CARD_POINTS[slot - 1]
            tap_steps.append(
                {"type": "tap", "role": f"face_card_{slot}", "x": x, "y": y}
            )
    return tap_steps


def _evaluate_card_condition(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    card_recognizer: CommandCardRecognizer | None,
    server: str,
    servants: list[dict[str, Any]],
    condition: list[dict[str, Any]],
    card_templates: list[str],
    threshold: float,
    timeout_seconds: float,
    poll_interval: float,
    tap_interval: float | _TapTiming,
    special_keys: list[dict[str, Any]] | None = None,
    card_wait_seconds: float = 0.0,
    checks: list[Any] | tuple[Any, ...] | None = None,
    *,
    frontline_recognizer: FrontlineServantRecognizer | None = None,
    servant_positions: list[dict[str, Any] | None] | None = None,
    occupied_positions: list[int | None] | None = None,
    party_servants: list[dict[str, Any]] | None = None,
    attack_template: str | None = None,
) -> tuple[bool, int]:
    if card_recognizer is None:
        raise ValueError("Command card recognition is not configured.")
    attack_x, attack_y = ATTACK_POINT
    tap_count = _execute_steps(
        context,
        device_service,
        [{"type": "tap", "role": "condition_attack", "x": attack_x, "y": attack_y}],
        tap_interval,
    )
    screenshot = _wait_for_command_cards(
        context,
        device_service,
        recognition,
        card_templates,
        threshold,
        timeout_seconds,
        poll_interval,
        reconnect_timing=tap_interval,
        settle_seconds=card_wait_seconds,
    )
    recognized, screenshot, recovery_taps = _recognize_command_cards_with_recovery(
        context,
        device_service,
        recognition,
        card_recognizer,
        screenshot,
        server,
        servants,
        threshold,
        special_keys,
        frontline_recognizer=frontline_recognizer,
        servant_positions=servant_positions,
        occupied_positions=occupied_positions,
        party_servants=party_servants,
        card_templates=card_templates,
        attack_template=attack_template,
        timeout_seconds=timeout_seconds,
        poll_interval=poll_interval,
        tap_interval=tap_interval,
        card_wait_seconds=card_wait_seconds,
    )
    tap_count += recovery_taps
    if not recognized["complete"]:
        raise ValueError(
            f"Recognized {recognized['recognized_count']} of 5 command cards."
        )
    matched = False
    reason = "No selected command card strategies matched."
    for index, strategy in enumerate(condition):
        # Keep mask lookup lazy: an earlier match may precede a missing position.
        if checks and not checks[index]:
            continue
        try:
            select_command_cards([strategy], recognized["cards"])
        except StrategySelectionError as exc:
            reason = str(exc)
        else:
            matched = True
            reason = None
            break
    back_x, back_y = COMMAND_CARD_BACK_POINT
    tap_count += _execute_steps(
        context,
        device_service,
        [{"type": "tap", "role": "condition_back", "x": back_x, "y": back_y}],
        tap_interval,
    )
    context.emit(
        "skill_condition",
        "Conditional skill card check completed.",
        data={"matched": matched, "reason": reason, "recognition": recognized},
    )
    return matched, tap_count


def _evaluate_np_condition(
    context: RunContext,
    np_recognizer: NpChargeRecognizer,
    screenshot: bytes,
    server: str,
    servant_positions: list[str | None],
    np_checks: list[dict[str, Any]],
) -> bool:
    present = [servant is not None for servant in servant_positions[:3]]
    recognized = np_recognizer.recognize(screenshot, server, present=present)
    if not recognized["complete"]:
        recognized_count = sum(1 for value in recognized["values"] if value is not None)
        raise ValueError(f"Recognized {recognized_count} of 3 NP charge values.")
    matched = True
    reason: str | None = None
    for item in np_checks:
        if not item["enabled"]:
            continue
        servant = int(item["servant"])
        value = recognized["values"][servant - 1]
        if value is None:
            raise ValueError(f"Missing NP charge value for servant slot {servant}.")
        target = int(item["value"])
        operator = item["operator"]
        if operator == "≥":
            slot_matched = value >= target
        elif operator == "≤":
            slot_matched = value <= target
        else:
            raise ValueError(f"Unsupported NP condition operator: {operator!r}.")
        if not slot_matched:
            matched = False
            reason = f"Servant {servant} NP {value}% did not satisfy {operator} {target}%."
            break
    context.emit(
        "skill_np_condition",
        "Conditional skill NP check completed.",
        data={
            "matched": matched,
            "reason": reason,
            "checks": np_checks,
            "recognition": recognized,
        },
    )
    return matched


def _execute_skills_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognition: RecognitionService,
    card_recognizer: CommandCardRecognizer | None,
    frontline_recognizer: FrontlineServantRecognizer | None = None,
):
    def execute(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = _required_setting_name(payload)
        threshold, timeout_seconds, poll_interval, tap_interval = _execution_options(
            payload
        )
        plan = script_data.get_setting_plan(setting_name)
        party_servants = plan["servants"]
        special_keys = plan.get("special_keys", [])
        card_wait_seconds = _configured_card_wait(
            plan["run"].get("interval_before_choose_card", 0.5)
        )
        speedup_skills = not bool(plan["run"].get("no_speedup_skill"))
        tap_interval = _TapTiming(
            tap_interval,
            configured_random_time(plan["run"].get("random_time", 0)),
            bool(plan["run"].get("random_touch")),
        )
        program = compile_battle_program(plan)
        execution_status = program["execution"]["skills"]
        if not execution_status["ready"]:
            raise ValueError(execution_status["reason"])

        actions = [
            action
            for round_plan in program["rounds"]
            for turn in round_plan["turns"]
            for action in turn["actions"]
        ]
        has_hakuno_reroll = any(
            action.get("runtime", {}).get("type") == "hakuno_card_reroll"
            for action in actions
        )
        if has_hakuno_reroll and card_recognizer is None:
            raise ValueError("Command card recognition is not configured.")
        effective_frontline_recognizer = frontline_recognizer or (
            FrontlineServantRecognizer(recognition._resources)
            if isinstance(recognition, RecognitionService)
            else None
        )
        attack_template = f"battle/{program['server']}/attack.png"
        card_templates = [
            f"battle/{program['server']}/{card_type}.png"
            for card_type in ("Arts", "Buster", "Quick")
        ]
        servant_positions = _servant_positions(
            party_servants,
            assist_slot=(plan.get("assist") or {}).get("slot"),
        )
        occupied_positions: list[int | None] = list(range(6))
        tap_count = 0
        for action_number, action in enumerate(actions, start=1):
            context.checkpoint(
                f"skill_{action_number}.wait_for_battle",
                progress=(action_number - 1) / max(len(actions), 1),
            )
            runtime = action.get("runtime")
            if runtime and runtime["type"] == "hakuno_card_reroll":
                tap_count += _execute_hakuno_reroll(
                    context,
                    device_service,
                    recognition,
                    card_recognizer,
                    program["server"],
                    _frontline_servants(servant_positions),
                    runtime,
                    card_templates,
                    attack_template,
                    threshold,
                    timeout_seconds,
                    poll_interval,
                    tap_interval,
                    special_keys=special_keys,
                    card_wait_seconds=card_wait_seconds,
                    speedup_skills=speedup_skills,
                    frontline_recognizer=effective_frontline_recognizer,
                    servant_positions=servant_positions,
                    occupied_positions=occupied_positions,
                    party_servants=party_servants,
                )
                continue
            _wait_for_battle_ready(
                context,
                device_service,
                recognition,
                attack_template,
                threshold,
                timeout_seconds,
                poll_interval,
                reconnect_timing=tap_interval,
            )
            tap_count += _execute_skill_action(
                context,
                device_service,
                action,
                tap_interval,
                speedup_skills=speedup_skills,
            )

        context.checkpoint(
            "complete",
            progress=1.0,
            message="Skill execution completed.",
        )
        return {
            "setting_name": setting_name,
            "action_count": len(actions),
            "tap_count": tap_count,
        }

    return execute


def _execution_options(payload: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        _number(payload, "threshold", 0.75, minimum=0.0, maximum=1.0),
        _number(payload, "timeout_seconds", 120.0, minimum=0.1, maximum=300.0),
        _number(payload, "poll_interval", 0.25, minimum=0.01, maximum=10.0),
        _number(payload, "tap_interval_seconds", 0.1, minimum=0.0, maximum=10.0),
    )


def _execute_steps(
    context: RunContext,
    device_service: DeviceService,
    steps: list[dict[str, Any]],
    tap_interval: float | _TapTiming,
    *,
    random_time: float = 0.0,
    random_touch: bool = False,
) -> int:
    timing = (
        tap_interval
        if isinstance(tap_interval, _TapTiming)
        else _TapTiming(
            float(tap_interval),
            configured_random_time(random_time),
            random_touch,
        )
    )
    for step in steps:
        touch_point = randomized_touch_point(
            (step["x"], step["y"]),
            enabled=timing.random_touch,
        )
        operation = device_service.tap(*touch_point)
        context.emit(
            "device_action",
            f"Tapped {step['role']}.",
            data={"role": step["role"], "operation": operation.to_dict()},
        )
        wait_after = max(
            randomized_wait_seconds(timing.interval, timing.random_time),
            float(step.get("wait_after_seconds", 0.0)),
        )
        if getattr(device_service, "operation_timing_active", lambda: False)():
            wait_after = max(0.0, wait_after - 0.1)
        if wait_after:
            context.sleep(wait_after)
    return len(steps)


def _resolve_action_target_steps(
    steps: list[dict[str, Any]],
    occupied_positions: list[int | None] | None,
) -> list[dict[str, Any]]:
    if occupied_positions is None or len(occupied_positions) < 3:
        return steps
    if occupied_positions[:3].count(None) == 0:
        return steps
    resolved: list[dict[str, Any]] = []
    for step in steps:
        role = str(step.get("role", ""))
        target: int | None = None
        if role.startswith("skill_target_"):
            target = int(role[len("skill_target_") :])
        elif role.startswith("command_spell_target_"):
            target = int(role[len("command_spell_target_") :])
        if target is not None and 1 <= target <= 3:
            target_x, target_y = resolve_skill_target_point(
                target,
                occupied_positions,
            )
            resolved.append({**step, "x": target_x, "y": target_y})
        else:
            resolved.append(step)
    return resolved


def _execute_skill_action(
    context: RunContext,
    device_service: DeviceService,
    action: dict[str, Any],
    tap_interval: float | _TapTiming,
    *,
    speedup_skills: bool,
    occupied_positions: list[int | None] | None = None,
) -> int:
    steps = _resolve_action_target_steps(action["steps"], occupied_positions)
    tap_count = _execute_steps(
        context,
        device_service,
        steps,
        tap_interval,
    )
    if not speedup_skills or not _skill_animation_can_be_sped_up(action):
        return tap_count
    return tap_count + _execute_skill_animation_speedup(
        context,
        device_service,
        tap_interval,
    )


def _execute_skill_animation_speedup(
    context: RunContext,
    device_service: DeviceService,
    tap_interval: float | _TapTiming,
) -> int:
    skip_x, skip_y = SKILL_ANIMATION_SKIP_POINT
    return _execute_steps(
        context,
        device_service,
        [
            {
                "type": "tap",
                "role": f"skill_animation_skip_{attempt}",
                "x": skip_x,
                "y": skip_y,
            }
            for attempt in range(1, 3)
        ],
        tap_interval,
    )


def _skill_animation_can_be_sped_up(action: dict[str, Any]) -> bool:
    source = action.get("source")
    if not isinstance(source, dict) or source.get("type") != "skill":
        return False
    command = source.get("command")
    if isinstance(command, int) and not isinstance(command, bool):
        return 1 <= command <= 12
    if not isinstance(command, list) or not command:
        return False
    head = command[0]
    if isinstance(head, int) and not isinstance(head, bool):
        if head < 0:
            return -9 <= head <= -1
        return 1 <= head <= 12 and len(command) != 3
    return isinstance(head, str) and head in NAMED_SKILL_COMMANDS


def _wait_for_battle_ready(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    template_path: str,
    threshold: float,
    timeout_seconds: float,
    poll_interval: float,
    reconnect_timing: float | _TapTiming | None = None,
    *,
    dismiss_command_cards: bool = True,
    unopened_skills: list[set[int]] | None = None,
    occupied_positions: list[int | None] | None = None,
    servant_positions: list[dict[str, Any] | None] | None = None,
    last_skill_number: int | None = None,
) -> bytes:
    started = active_monotonic(context, clock=monotonic)
    attempts = 0
    while True:
        screenshot = device_service.snapshot()
        server = _server_from_battle_template(template_path)
        if server is not None and _battle_reconnect_if_present(
            context,
            device_service,
            recognition,
            screenshot,
            server,
            reconnect_timing,
        ) and active_monotonic(context, clock=monotonic) - started < timeout_seconds:
            continue
        attack_options: dict[str, Any] = {
            "scales": BATTLE_TEMPLATE_SCALES,
        }
        if isinstance(recognition, RecognitionService):
            try:
                if recognition.image_size(screenshot) == (1280, 720):
                    attack_options["roi"] = ATTACK_BUTTON_ROI_720P
            except AppError:
                pass
        match = recognition.match_template(
            screenshot,
            template_path,
            threshold,
            **attack_options,
        )
        attempts += 1
        context.emit(
            "recognition",
            "Battle readiness recognition completed.",
            data={
                "template_path": template_path,
                "matched": match.matched,
                "confidence": match.confidence,
                "attempt": attempts,
            },
        )
        if match.matched:
            return screenshot
        if (
            server is not None
            and _battle_popup_dismiss_if_present(
                context,
                device_service,
                recognition,
                screenshot,
                server,
                reconnect_timing,
                dismiss_command_cards=dismiss_command_cards,
                unopened_skills=unopened_skills,
                occupied_positions=occupied_positions,
                servant_positions=servant_positions,
                last_skill_number=last_skill_number,
            )
            and active_monotonic(context, clock=monotonic) - started < timeout_seconds
        ):
            continue
        if active_monotonic(context, clock=monotonic) - started >= timeout_seconds:
            raise TimeoutError(
                f"Battle controls did not become ready within {timeout_seconds:.2f} seconds."
            )
        context.sleep(poll_interval)


def _battle_popup_dismiss_if_present(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    screenshot: bytes,
    server: str,
    timing: float | _TapTiming | None,
    *,
    dismiss_command_cards: bool = True,
    unopened_skills: list[set[int]] | None = None,
    occupied_positions: list[int | None] | None = None,
    servant_positions: list[dict[str, Any] | None] | None = None,
    last_skill_number: int | None = None,
) -> bool:
    normalized = (
        timing
        if isinstance(timing, _TapTiming)
        else _TapTiming(float(timing) if timing is not None else 0.0)
    )
    not_available = _match_optional_battle_template(
        recognition,
        screenshot,
        f"battle/{server}/notAvailable.png",
        roi=SKILL_NOT_AVAILABLE_ROI,
        threshold=0.8,
    )
    if not_available is not None and not_available.matched:
        _record_unopened_skill(
            last_skill_number,
            unopened_skills,
            occupied_positions,
            servant_positions,
        )
        touch_point = randomized_touch_point(
            SKILL_NOT_AVAILABLE_CLOSE_POINT,
            size=SKILL_NOT_AVAILABLE_CLOSE_SIZE,
            enabled=normalized.random_touch,
        )
        operation = device_service.tap(*touch_point)
        context.emit(
            "battle_popup_closed",
            "Dismissed skill-not-available prompt.",
            data={
                "popup": "skill_not_available",
                "skill_number": last_skill_number,
                "operation": operation.to_dict(),
            },
        )
        wait_after = randomized_wait_seconds(
            normalized.interval,
            normalized.random_time,
        )
        if wait_after:
            context.sleep(wait_after)
        return True
    servant_close = _match_optional_battle_template(
        recognition,
        screenshot,
        f"battle/{server}/x.png",
        roi=SERVANT_DETAIL_CLOSE_ROI,
        threshold=0.8,
    )
    if servant_close is not None and servant_close.matched:
        touch_point = match_touch_point(
            servant_close,
            enabled=normalized.random_touch,
        )
        operation = device_service.tap(*touch_point)
        context.emit(
            "battle_popup_closed",
            "Dismissed servant detail modal.",
            data={
                "popup": "servant_detail",
                "operation": operation.to_dict(),
            },
        )
        wait_after = randomized_wait_seconds(
            normalized.interval,
            normalized.random_time,
        )
        if wait_after:
            context.sleep(wait_after)
        return True
    if not dismiss_command_cards:
        return False
    command_card_back = _match_optional_battle_template(
        recognition,
        screenshot,
        f"battle/{server}/back.png",
        roi=COMMAND_CARD_BACK_ROI,
        threshold=0.8,
    )
    if command_card_back is not None and command_card_back.matched:
        touch_point = randomized_touch_point(
            COMMAND_CARD_BACK_POINT,
            size=COMMAND_CARD_BACK_SIZE,
            enabled=normalized.random_touch,
        )
        operation = device_service.tap(*touch_point)
        context.emit(
            "battle_popup_closed",
            "Closed command card screen to return to battle controls.",
            data={
                "popup": "command_card_back",
                "operation": operation.to_dict(),
            },
        )
        wait_after = randomized_wait_seconds(
            normalized.interval,
            normalized.random_time,
        )
        if wait_after:
            context.sleep(wait_after)
        return True
    return False


def _wait_for_command_cards(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    template_paths: list[str],
    threshold: float,
    timeout_seconds: float,
    poll_interval: float,
    reconnect_timing: float | _TapTiming | None = None,
    settle_seconds: float = 0.0,
) -> bytes:
    started = active_monotonic(context, clock=monotonic)
    attempts = 0
    settled = settle_seconds <= 0
    use_720p_rois = isinstance(recognition, RecognitionService)
    candidates = [
        {
            "template_path": template_path,
            "threshold": threshold,
            "scales": BATTLE_TEMPLATE_SCALES,
        }
        for template_path in template_paths
    ]
    while True:
        screenshot = device_service.snapshot()
        server = (
            _server_from_battle_template(template_paths[0])
            if template_paths
            else None
        )
        if server is not None and _battle_reconnect_if_present(
            context,
            device_service,
            recognition,
            screenshot,
            server,
            reconnect_timing,
        ) and active_monotonic(context, clock=monotonic) - started < timeout_seconds:
            continue
        effective_candidates = candidates
        if use_720p_rois:
            try:
                if recognition.image_size(screenshot) == (1280, 720):
                    effective_candidates = [
                        {**candidate, "roi": COMMAND_CARDS_ROI_720P}
                        for candidate in candidates
                    ]
            except AppError:
                pass
        matches = recognition.match_templates(screenshot, effective_candidates)
        attempts += 1
        context.emit(
            "recognition",
            "Command card recognition completed.",
            data={
                "matched": any(match.matched for match in matches),
                "attempt": attempts,
                "matches": [match.to_dict() for match in matches],
            },
        )
        ready_threshold = max(threshold, COMMAND_CARD_READY_CONFIDENCE)
        matched = any(
            match.matched and match.confidence >= ready_threshold
            for match in matches
        )
        if matched and not settled:
            context.sleep(settle_seconds)
            settled = True
            continue
        if matched:
            return screenshot
        if active_monotonic(context, clock=monotonic) - started >= timeout_seconds:
            raise TimeoutError(
                f"Command cards did not become ready within {timeout_seconds:.2f} seconds."
            )
        context.sleep(poll_interval)


def _battle_reconnect_if_present(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    screenshot: bytes,
    server: str,
    timing: float | _TapTiming | None,
) -> bool:
    if timing is None:
        return False
    normalized = (
        timing if isinstance(timing, _TapTiming) else _TapTiming(float(timing))
    )
    return reconnect_if_present(
        context,
        device_service,
        recognition,
        screenshot,
        server,
        action_wait_seconds=normalized.interval,
        random_time=normalized.random_time,
        random_touch=normalized.random_touch,
    )


def _server_from_battle_template(template_path: str) -> str | None:
    parts = template_path.split("/")
    if len(parts) < 3 or parts[0] != "battle" or not parts[1]:
        return None
    return parts[1]


def _required_setting_name(payload: dict[str, Any]) -> str:
    value = payload.get("setting_name")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("setting_name must be a non-empty string.")
    return value.strip()


def _action_delay(payload: dict[str, Any]) -> float:
    value = payload.get("action_delay_seconds", 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("action_delay_seconds must be a number.")
    delay = float(value)
    if delay < 0 or delay > 10:
        raise ValueError("action_delay_seconds must be between 0 and 10.")
    return delay


def _configured_card_wait(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("intervalBFchooseCard must be a number.")
    result = float(value)
    if result < 0 or result > 600:
        raise ValueError("intervalBFchooseCard must be between 0 and 600.")
    return result


def _number(
    payload: dict[str, Any],
    key: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number.")
    result = float(value)
    if result < minimum or result > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}.")
    return result
