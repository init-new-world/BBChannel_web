from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any


SERVANT_SKILL_POINTS = (
    (70, 590),
    (163, 590),
    (256, 590),
    (382, 590),
    (474, 590),
    (567, 590),
    (694, 590),
    (786, 590),
    (879, 590),
)
SKILL_TARGET_POINTS = ((350, 440), (640, 440), (970, 440))
SKILL_TARGET_POINTS_2 = ((476, 440), (805, 440))
SKILL_TARGET_POINTS_1 = ((640, 440),)
CRAWL_TOWER_MODES = frozenset({"off", "script", "autonomous"})
MASTER_SKILL_MENU_POINT = (1217, 320)
MASTER_SKILL_POINTS = ((905, 310), (997, 310), (1089, 310))
SKILL_DIALOG_WAIT_SECONDS = 0.5
MASTER_SKILL_MENU_WAIT_SECONDS = 0.5
ORDER_CHANGE_WAIT_SECONDS = 0.7
NP_POINTS = ((430, 200), (650, 200), (870, 200))
ATTACK_POINT = (1150, 600)
COMMAND_CARD_BACK_POINT = (1201, 683)
FACE_CARD_POINTS = ((150, 500), (375, 500), (650, 500), (900, 500), (1175, 500))
SPACE_ISHTAR_CHOICE_POINTS = ((327, 433), (639, 433), (951, 433))
EMIYA_CHOICE_POINTS = ((483, 433), (795, 433))
COMMAND_SPELL_MENU_POINT = (1060, 82)
COMMAND_SPELL_NP_CHARGE_POINT = (637, 343)
COMMAND_SPELL_HEAL_POINT = (637, 523)
COMMAND_SPELL_CONFIRM_POINT = (793, 430)
EXCHANGE_POINTS = tuple((137 + 200 * position, 352) for position in range(6))
EXCHANGE_CONFIRM_POINT = (607, 625)
ENEMY_POINTS = tuple(
    (141 + 200 * (position % 3), 39 + 99 * (position // 3))
    for position in range(6)
)
TWO_CHOICE_POINTS = {0: (640, 423), 1: (960, 423)}
CARD_TYPE_CHOICE_POINTS = {"Q": (537, 422), "A": (767, 422), "B": (1000, 422)}
NAMED_SERVANT_OPTION_POINTS: dict[str, dict[Any, tuple[int, int]]] = {
    "Kukulkan": TWO_CHOICE_POINTS,
    "Barghest": TWO_CHOICE_POINTS,
    "Soujyuro": CARD_TYPE_CHOICE_POINTS,
    "BBDubai": {0: (483, 390), 1: (795, 390)},
    "Hakuno": {"T": (537, 422), "D": (767, 422), "R": (1000, 422)},
    "VanGoghMiner": CARD_TYPE_CHOICE_POINTS,
    "Dante": {"A": (640, 423), "B": (960, 423)},
    "Gyokuto": {"All": (640, 423), "One": (960, 423)},
    "Charlotte": {"技": (537, 422), "暴": (767, 422), "宝": (1000, 422)},
    "Flora": {"T": (640, 423), "D": (960, 423)},
}


def resolve_skill_target_point(
    target: int,
    servant_positions: Sequence[int | None] | None = None,
) -> tuple[int, int]:
    if isinstance(target, bool) or not isinstance(target, int) or not 1 <= target <= 3:
        raise ValueError("Skill target must be servant position 1 through 3.")
    if servant_positions is None or len(servant_positions) < 3:
        return SKILL_TARGET_POINTS[target - 1]
    frontline = list(servant_positions[:3])
    none_count = frontline.count(None)
    if none_count == 0:
        return SKILL_TARGET_POINTS[target - 1]
    if none_count == 1:
        adjusted = target
        if (frontline[1] is None or frontline[2] is None) and adjusted == 3:
            adjusted = 2
        elif frontline[0] is None and adjusted in (2, 3):
            adjusted -= 1
        adjusted = min(max(adjusted, 1), 2)
        return SKILL_TARGET_POINTS_2[adjusted - 1]
    return SKILL_TARGET_POINTS_1[0]


def build_autonomous_skill_commands(
    servant_names: Sequence[str] | None = None,
    servant_positions: Sequence[int | None] | None = None,
    *,
    default_target: int = 1,
    available_skills: Sequence[bool] | None = None,
    unopened_skills: Sequence[set[int] | Sequence[int]] | None = None,
    frontline_servant_names: Sequence[str | None] | None = None,
) -> list[Any]:
    if (
        isinstance(default_target, bool)
        or not isinstance(default_target, int)
        or not 1 <= default_target <= 3
    ):
        raise ValueError("default_target must be between 1 and 3.")
    commands: list[Any] = []
    for index in range(9):
        if (
            available_skills is not None
            and index < len(available_skills)
            and not available_skills[index]
        ):
            continue
        skill = index + 1
        slot_index = index // 3
        remainder = index % 3
        servant_slot = (
            servant_positions[slot_index]
            if servant_positions is not None and slot_index < len(servant_positions)
            else slot_index
        )
        if (
            unopened_skills is not None
            and isinstance(servant_slot, int)
            and not isinstance(servant_slot, bool)
            and 0 <= servant_slot < len(unopened_skills)
            and remainder in unopened_skills[servant_slot]
        ):
            continue
        servant_name = ""
        if (
            frontline_servant_names is not None
            and slot_index < len(frontline_servant_names)
            and isinstance(frontline_servant_names[slot_index], str)
            and frontline_servant_names[slot_index]
        ):
            servant_name = str(frontline_servant_names[slot_index])
        elif (
            servant_slot not in (None, -1)
            and servant_names is not None
            and 0 <= servant_slot < len(servant_names)
        ):
            servant_name = servant_names[servant_slot]
        if servant_name == "库库尔坎":
            if remainder == 1:
                commands.append(["Kukulkan", skill, 1, default_target])
            else:
                commands.append(["Kukulkan", skill, 1])
        elif servant_name == "UDK-巴格斯特" and remainder == 2:
            commands.append(["Barghest", skill, 1])
        elif servant_name == "静希草十郎" and remainder == 2:
            commands.append(["Soujyuro", skill, "B"])
        elif servant_name == "BB迪拜" and remainder == 2:
            commands.append(["BBDubai", skill, 0])
        elif servant_name in ("岸波白野(女性)", "岸波白野(男性)") and remainder == 2:
            commands.append(["Hakuno", skill, "R"])
        elif servant_name in ("岸波白野(女性)", "岸波白野(男性)") and remainder == 0:
            commands.append(["Hakuno", skill, []])
        elif servant_name == "梵高〔矿工〕" and remainder == 0:
            commands.append(["VanGoghMiner", skill, "B"])
        elif servant_name == "太空伊什塔尔" and remainder == 1:
            commands.append([-skill, 3])
        elif servant_name == "卫宫" and remainder == 2:
            commands.append([-skill, 2])
        elif servant_name == "但丁·阿利吉耶里" and remainder == 1:
            commands.append(["Dante", skill, "B"])
        elif servant_name == "玉兔" and remainder == 1:
            commands.append(["Gyokuto", skill, "All"])
        elif servant_name == "夏洛特·科黛" and remainder == 2:
            commands.append(["Charlotte", skill, "技"])
        elif servant_name == "芙萝拉" and remainder == 2:
            commands.append(["Flora", skill, "T"])
        else:
            commands.append([skill, default_target])
    return commands


def build_complex_skill_commands(
    extra_skills: Sequence[Any],
    free_skills: Sequence[Any],
    *,
    default_target: int = 1,
) -> list[Any]:
    if (
        isinstance(default_target, bool)
        or not isinstance(default_target, int)
        or not 1 <= default_target <= 3
    ):
        raise ValueError("default_target must be between 1 and 3.")
    commands: list[Any] = []
    for item in extra_skills:
        if isinstance(item, int) and not isinstance(item, bool) and 1 <= item <= 9:
            commands.append([item, default_target])
        else:
            commands.append(deepcopy(item))
    commands.extend(deepcopy(item) for item in free_skills)
    return commands


def compile_skill_command(command: Any) -> dict[str, Any]:
    return _compile_skill({"type": "skill", "command": deepcopy(command)})


def _plan_servant_names(plan: dict[str, Any]) -> list[str]:
    names = [""] * 6
    for servant in plan.get("servants", []):
        if not isinstance(servant, dict):
            continue
        slot = servant.get("slot")
        name = servant.get("name")
        if (
            isinstance(slot, int)
            and not isinstance(slot, bool)
            and 0 <= slot < 6
            and isinstance(name, str)
        ):
            names[slot] = name
    return names


def _normalize_crawl_tower_rounds(
    plan: dict[str, Any],
    crawl_tower_mode: str,
) -> list[dict[str, Any]]:
    if crawl_tower_mode == "off":
        return plan["rounds"]
    if crawl_tower_mode == "script":
        normalized_rounds: list[dict[str, Any]] = []
        for round_plan in plan["rounds"]:
            normalized_turns: list[dict[str, Any]] = []
            for turn in round_plan["turns"]:
                normalized_actions: list[dict[str, Any]] = []
                for action in turn["actions"]:
                    command = action.get("command")
                    if (
                        action.get("type") == "skill"
                        and isinstance(command, int)
                        and not isinstance(command, bool)
                        and 1 <= command <= 9
                    ):
                        normalized_actions.append(
                            {**action, "command": [command, 1]}
                        )
                    else:
                        normalized_actions.append(action)
                normalized_turns.append({**turn, "actions": normalized_actions})
            normalized_extra_skill = [
                [command, 1]
                if (
                    isinstance(command, int)
                    and not isinstance(command, bool)
                    and 1 <= command <= 9
                )
                else command
                for command in round_plan.get("extra_skill", [])
            ]
            normalized_rounds.append(
                {
                    **round_plan,
                    "turns": normalized_turns,
                    "extra_skill": normalized_extra_skill,
                }
            )
        return normalized_rounds

    autonomous_skills = build_autonomous_skill_commands(
        _plan_servant_names(plan),
        default_target=1,
    )
    autonomous_actions = [
        *[{"type": "skill", "command": command} for command in autonomous_skills],
        *[{"type": "np", "servant": servant} for servant in (1, 2, 3)],
    ]
    return [
        {
            "round": round_number,
            "turns": [
                {
                    "turn": 0,
                    "actions": deepcopy(autonomous_actions),
                    "nps": [1, 2, 3],
                    "strategy": None,
                    "condition": None,
                }
            ],
            "extra_skill": deepcopy(autonomous_skills),
            "extra_strategy": None,
        }
        for round_number in range(1, 4)
    ]


def compile_battle_program(
    plan: dict[str, Any],
    *,
    crawl_tower_mode: str = "off",
) -> dict[str, Any]:
    if crawl_tower_mode not in CRAWL_TOWER_MODES:
        raise ValueError("crawl_tower_mode must be off, script, or autonomous.")
    rounds: list[dict[str, Any]] = []
    action_count = 0
    supported_action_count = 0
    tap_count = 0
    execution_tap_count = 0
    extra_action_count = 0
    extra_tap_count = 0
    extra_unsupported_action_count = 0
    source_types: list[object] = []
    command_phases: list[dict[str, Any]] = []
    no_chain = bool(plan.get("run", {}).get("no_chain")) and crawl_tower_mode != "autonomous"
    source_rounds = _normalize_crawl_tower_rounds(plan, crawl_tower_mode)

    for round_plan in source_rounds:
        turns: list[dict[str, Any]] = []
        for turn in round_plan["turns"]:
            actions = [_compile_action(action) for action in turn["actions"]]
            command_phase = _compile_command_phase(turn, no_chain=no_chain)
            action_count += len(actions)
            supported_action_count += sum(bool(action["supported"]) for action in actions)
            tap_count += sum(len(action["steps"]) for action in actions)
            execution_tap_count += sum(
                len(action["steps"])
                for action in actions
                if action["source"].get("type") == "skill"
            )
            execution_tap_count += sum(
                int(step.get("selection_count", 1)) for step in command_phase["steps"]
            )
            source_types.extend(action["source"].get("type") for action in actions)
            command_phases.append(command_phase)
            turns.append(
                {
                    "turn": turn["turn"],
                    "actions": actions,
                    "command_phase": command_phase,
                    "condition": turn.get("condition"),
                }
            )
        extra_source_actions = [
            {"type": "skill", "command": command}
            for command in round_plan.get("extra_skill", [])
        ]
        if round_plan.get("extra_strategy"):
            extra_source_actions.append(
                {
                    "type": "strategy",
                    "strategies": round_plan["extra_strategy"],
                }
            )
        extra_actions = [_compile_action(action) for action in extra_source_actions]
        extra_command_phase = _compile_command_phase(
            {
                "strategy": round_plan.get("extra_strategy"),
                "nps": [1, 2, 3] if crawl_tower_mode == "autonomous" else [],
            },
            no_chain=no_chain,
        )
        extra_action_count += len(extra_actions)
        extra_unsupported_action_count += sum(
            not bool(action["supported"]) for action in extra_actions
        )
        extra_tap_count += sum(len(action["steps"]) for action in extra_actions)
        extra_tap_count += sum(
            int(step.get("selection_count", 1))
            for step in extra_command_phase["steps"]
        )
        source_types.extend(action["source"].get("type") for action in extra_actions)
        command_phases.append(extra_command_phase)
        rounds.append(
            {
                "round": round_plan["round"],
                "turns": turns,
                "extra_turn": {
                    "actions": extra_actions,
                    "command_phase": extra_command_phase,
                    "condition": (
                        round_plan["extra_condition"]
                        if round_plan.get("extra_condition") is not None
                        else (turns[-1]["condition"] if turns else None)
                    ),
                },
            }
        )

    unsupported_action_count = action_count - supported_action_count
    total_unsupported_action_count = (
        unsupported_action_count + extra_unsupported_action_count
    )
    validation_ok = bool(plan.get("validation", {}).get("ok", True))
    skill_execution = _skill_execution_status(
        action_count + extra_action_count,
        total_unsupported_action_count,
        source_types,
        validation_ok,
    )
    battle_execution = _battle_execution_status(
        len(command_phases),
        total_unsupported_action_count,
        source_types,
        command_phases,
        validation_ok,
    )
    return {
        "name": plan["name"],
        "server": plan["server"],
        "base_resolution": {"width": 1280, "height": 720},
        "rounds": rounds,
        "summary": {
            "action_count": action_count,
            "supported_action_count": supported_action_count,
            "unsupported_action_count": unsupported_action_count,
            "tap_count": tap_count,
            "execution_tap_count": execution_tap_count,
            "extra_action_count": extra_action_count,
            "extra_tap_count": extra_tap_count,
        },
        "execution": {"skills": skill_execution, "battle": battle_execution},
        "validation": plan["validation"],
    }


def _skill_execution_status(
    action_count: int,
    unsupported_action_count: int,
    source_types: list[object],
    validation_ok: bool,
) -> dict[str, Any]:
    if not validation_ok:
        return {"ready": False, "reason": "Script validation failed."}
    if action_count == 0:
        return {"ready": False, "reason": "Program contains no actions."}
    if unsupported_action_count:
        return {"ready": False, "reason": "Program contains unsupported actions."}
    if any(action_type != "skill" for action_type in source_types):
        return {"ready": False, "reason": "Program contains non-skill actions."}
    return {"ready": True, "reason": None}


def _battle_execution_status(
    turn_count: int,
    unsupported_action_count: int,
    source_types: list[object],
    command_phases: list[dict[str, Any]],
    validation_ok: bool,
) -> dict[str, Any]:
    if not validation_ok:
        return {"ready": False, "reason": "Script validation failed."}
    if turn_count == 0:
        return {"ready": False, "reason": "Program contains no turns."}
    if unsupported_action_count or any(not phase["supported"] for phase in command_phases):
        return {"ready": False, "reason": "Program contains unsupported actions."}
    if any(
        action_type not in {"skill", "np", "strategy", "replace"}
        for action_type in source_types
    ):
        return {"ready": False, "reason": "Program contains unsupported action types."}
    return {"ready": True, "reason": None}


def _compile_command_phase(
    turn: dict[str, Any],
    *,
    no_chain: bool = False,
) -> dict[str, Any]:
    if turn.get("strategy"):
        strategies = turn["strategy"]
        return {
            "supported": True,
            "steps": [
                _tap("attack", *ATTACK_POINT),
                {
                    "type": "strategy",
                    "role": "command_card_strategy",
                    "strategies": strategies,
                    "preselected_nps": [],
                    "selection_count": 3,
                },
            ],
            "reason": None,
        }

    nps = turn.get("nps") if isinstance(turn.get("nps"), list) else []
    if len(nps) > 3:
        return {
            "supported": False,
            "steps": [],
            "reason": "A turn cannot select more than three Noble Phantasms.",
        }

    if no_chain and len(nps) == 1:
        return {
            "supported": True,
            "steps": [
                _tap("attack", *ATTACK_POINT),
                {
                    "type": "strategy",
                    "role": "command_card_no_chain",
                    "strategies": [],
                    "preselected_nps": nps,
                    "avoid_chain": True,
                    "selection_count": 3,
                },
            ],
            "reason": None,
        }

    steps = [_tap("attack", *ATTACK_POINT)]
    for servant in nps:
        np_action = _compile_np({"type": "np", "servant": servant})
        if not np_action["supported"]:
            return {
                "supported": False,
                "steps": [],
                "reason": np_action["reason"],
            }
        steps.extend(np_action["steps"])
    for index, (x, y) in enumerate(FACE_CARD_POINTS[: 3 - len(nps)], start=1):
        steps.append(_tap(f"face_card_{index}", x, y))
    return {"supported": True, "steps": steps, "reason": None}


def _compile_action(action: dict[str, Any]) -> dict[str, Any]:
    action_type = action.get("type")
    if action_type == "skill":
        return _compile_skill(action)
    if action_type == "np":
        return _compile_np(action)
    if action_type == "strategy":
        return _supported(action, [])
    if action_type == "replace":
        return _compile_replace(action)
    return _unsupported(action, f"{action_type or 'Unknown'} actions are not compiled yet.")


def _compile_replace(action: dict[str, Any]) -> dict[str, Any]:
    replacements = action.get("replacements")
    if not isinstance(replacements, dict) or not replacements:
        return _unsupported(action, "Replacement mappings must be a non-empty object.")
    for destination, source in replacements.items():
        try:
            destination_position = int(destination)
        except (TypeError, ValueError):
            return _unsupported(action, "Replacement positions must be numbered 1 through 6.")
        if isinstance(destination, bool) or not 1 <= destination_position <= 6:
            return _unsupported(action, "Replacement positions must be numbered 1 through 6.")
        if source is None:
            continue
        if isinstance(source, bool) or not isinstance(source, int) or not 1 <= source <= 6:
            return _unsupported(action, "Replacement sources must be numbered 1 through 6 or null.")
    return _supported(action, [])


def _compile_skill(action: dict[str, Any]) -> dict[str, Any]:
    command = action.get("command")
    enemy_target = _compile_enemy_target(action, command)
    if enemy_target is not None:
        return enemy_target
    exchange = _compile_servant_exchange(action, command)
    if exchange is not None:
        return exchange
    control = _compile_skill_control(action, command)
    if control is not None:
        return control
    command_spell = _compile_command_spell(action, command)
    if command_spell is not None:
        return command_spell
    named_servant_skill = _compile_named_servant_skill(action, command)
    if named_servant_skill is not None:
        return named_servant_skill
    special_skill = _compile_special_skill(action, command)
    if special_skill is not None:
        return special_skill

    target: int | None = None
    if isinstance(command, list) and len(command) == 2:
        skill, target = command
    else:
        skill = command
    if isinstance(skill, bool) or not isinstance(skill, int) or not 1 <= skill <= 12:
        return _unsupported(action, "Skill commands must be numbered 1 through 12.")
    if target is not None and (
        isinstance(target, bool) or not isinstance(target, int) or not 1 <= target <= 3
    ):
        return _unsupported(action, "Skill targets must be servant positions 1 through 3.")

    if skill <= 9:
        x, y = SERVANT_SKILL_POINTS[skill - 1]
        steps = [
            _tap(
                f"servant_skill_{skill}",
                x,
                y,
                wait_after_seconds=(
                    SKILL_DIALOG_WAIT_SECONDS if target is not None else None
                ),
            )
        ]
    else:
        menu_x, menu_y = MASTER_SKILL_MENU_POINT
        x, y = MASTER_SKILL_POINTS[skill - 10]
        steps = [
            _tap(
                "master_skill_menu",
                menu_x,
                menu_y,
                wait_after_seconds=MASTER_SKILL_MENU_WAIT_SECONDS,
            ),
            _tap(
                f"master_skill_{skill}",
                x,
                y,
                wait_after_seconds=(
                    SKILL_DIALOG_WAIT_SECONDS if target is not None else None
                ),
            ),
        ]
    if target is not None:
        target_x, target_y = SKILL_TARGET_POINTS[target - 1]
        steps.append(_tap(f"skill_target_{target}", target_x, target_y))
    return _supported(action, steps)


def _compile_enemy_target(
    action: dict[str, Any],
    command: Any,
) -> dict[str, Any] | None:
    if not (
        isinstance(command, list)
        and len(command) == 2
        and command[0] == 13
    ):
        return None
    target = command[1]
    if isinstance(target, bool) or not isinstance(target, int) or not 1 <= target <= 6:
        return _unsupported(action, "Enemy targets must be numbered 1 through 6.")
    x, y = ENEMY_POINTS[target - 1]
    return _supported(action, [_tap(f"enemy_target_{target}", x, y)])


def _compile_servant_exchange(
    action: dict[str, Any],
    command: Any,
) -> dict[str, Any] | None:
    if (
        not isinstance(command, list)
        or len(command) != 3
        or isinstance(command[0], bool)
        or not isinstance(command[0], int)
    ):
        return None
    skill, left, right = command
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (left, right)):
        return _unsupported(action, "Order change commands require three numeric positions.")
    if not 10 <= skill <= 12:
        return _unsupported(action, "Order change must use master skill 10 through 12.")
    if not 1 <= left <= 6 or not 1 <= right <= 6 or left == right:
        return _unsupported(action, "Order change positions must be distinct positions 1 through 6.")
    skill_x, skill_y = MASTER_SKILL_POINTS[skill - 10]
    left_x, left_y = EXCHANGE_POINTS[left - 1]
    right_x, right_y = EXCHANGE_POINTS[right - 1]
    confirm_x, confirm_y = EXCHANGE_CONFIRM_POINT
    result = _supported(
        action,
        [
            _tap(
                "master_skill_menu",
                *MASTER_SKILL_MENU_POINT,
                wait_after_seconds=MASTER_SKILL_MENU_WAIT_SECONDS,
            ),
            _tap(
                f"master_skill_{skill}",
                skill_x,
                skill_y,
                wait_after_seconds=ORDER_CHANGE_WAIT_SECONDS,
            ),
            _tap(f"exchange_position_{left}", left_x, left_y),
            _tap(f"exchange_position_{right}", right_x, right_y),
            *[
                _tap(f"exchange_confirm_{attempt}", confirm_x, confirm_y)
                for attempt in range(1, 4)
            ],
        ],
    )
    result["state_change"] = {
        "type": "servant_exchange",
        "positions": [left, right],
    }
    return result


def _compile_skill_control(
    action: dict[str, Any],
    command: Any,
) -> dict[str, Any] | None:
    if not isinstance(command, list) or not command:
        return None
    if command[0] == "End":
        result = _supported(action, [])
        result["control"] = {"type": "condition_end"}
        return result
    if command[0] != "Start":
        return None
    if len(command) not in {3, 4} or not isinstance(command[1], (bool, int)):
        return _unsupported(action, "Conditional skill blocks require Start, mode, and checks.")
    checks = command[2]
    if not isinstance(checks, (list, tuple)):
        return _unsupported(action, "Conditional skill checks must be a list.")
    control: dict[str, Any] = {
        "type": "condition_start",
        "execute_when_matched": bool(command[1]),
        "check_cards": bool(checks) and any(checks),
        "checks": deepcopy(checks),
    }
    if len(command) == 4:
        np_checks = _compile_np_condition(command[3])
        if np_checks is None:
            return _unsupported(
                action,
                "Conditional skill NP checks must be ['np', [enabled, '≥'|'≤', 0..300], ...].",
            )
        control["check_np"] = any(check["enabled"] for check in np_checks)
        control["np_checks"] = np_checks
    result = _supported(action, [])
    result["control"] = control
    return result


def _compile_np_condition(condition: Any) -> list[dict[str, Any]] | None:
    if (
        not isinstance(condition, (list, tuple))
        or len(condition) != 4
        or condition[0] != "np"
    ):
        return None
    checks: list[dict[str, Any]] = []
    for servant, entry in enumerate(condition[1:], start=1):
        if not isinstance(entry, (list, tuple)) or len(entry) != 3:
            return None
        enabled, operator, threshold = entry
        if not isinstance(enabled, (bool, int)) or enabled not in (0, 1):
            return None
        if not isinstance(operator, str) or operator not in {"≥", "≤"}:
            return None
        if isinstance(threshold, bool) or not isinstance(threshold, int) or not 0 <= threshold <= 300:
            return None
        checks.append(
            {
                "servant": servant,
                "enabled": bool(enabled),
                "operator": operator,
                "value": threshold,
            }
        )
    return checks


def _compile_command_spell(
    action: dict[str, Any],
    command: Any,
) -> dict[str, Any] | None:
    if (
        not isinstance(command, list)
        or len(command) != 2
        or not isinstance(command[0], str)
    ):
        return None
    spell_options = {
        "令咒·宝具解放": ("command_spell_np_charge", COMMAND_SPELL_NP_CHARGE_POINT),
        "令咒·灵基修复": ("command_spell_heal", COMMAND_SPELL_HEAL_POINT),
    }
    spell = spell_options.get(command[0])
    if spell is None:
        return None
    target = command[1]
    if isinstance(target, bool) or not isinstance(target, int) or not 1 <= target <= 3:
        return _unsupported(action, "Command spell targets must be servant positions 1 through 3.")
    target_x, target_y = SKILL_TARGET_POINTS[target - 1]
    spell_role, spell_point = spell
    return _supported(
        action,
        [
            _tap("command_spell_menu", *COMMAND_SPELL_MENU_POINT, wait_after_seconds=1.0),
            _tap(
                spell_role,
                *spell_point,
                wait_after_seconds=1.0,
            ),
            _tap(
                "command_spell_confirm",
                *COMMAND_SPELL_CONFIRM_POINT,
                wait_after_seconds=1.0,
            ),
            _tap(f"command_spell_target_{target}", target_x, target_y),
        ],
    )


def _compile_named_servant_skill(
    action: dict[str, Any],
    command: Any,
) -> dict[str, Any] | None:
    if (
        not isinstance(command, list)
        or not command
        or not isinstance(command[0], str)
        or command[0] not in NAMED_SERVANT_OPTION_POINTS
    ):
        return None

    name = command[0]
    expected_lengths = {3, 4} if name == "Kukulkan" else {3}
    if len(command) not in expected_lengths:
        return _unsupported(action, f"{name} skill commands have an invalid length.")
    skill = command[1]
    if isinstance(skill, bool) or not isinstance(skill, int) or not 1 <= skill <= 9:
        return _unsupported(action, "Named servant skills must be numbered 1 through 9.")

    option = command[2]
    if name == "Hakuno" and skill % 3 == 1:
        if not isinstance(option, list) or any(
            not isinstance(need, list)
            or any(not isinstance(card, str) or not card for card in need)
            for need in option
        ):
            return _unsupported(action, "Hakuno card needs must be a list of card-code lists.")
        skill_step = _tap(
            f"servant_skill_{skill}",
            *SERVANT_SKILL_POINTS[skill - 1],
            wait_after_seconds=SKILL_DIALOG_WAIT_SECONDS,
        )
        if not option:
            return _supported(action, [skill_step])
        result = _supported(action, [])
        result["runtime"] = {
            "type": "hakuno_card_reroll",
            "need_cards": option,
            "skill_step": skill_step,
            "max_rerolls": 3,
        }
        return result
    if name == "Hakuno" and skill % 3 != 0:
        return _unsupported(action, "Hakuno option selection only applies to first or third skills.")
    if name in {"Kukulkan", "Barghest", "BBDubai"} and isinstance(option, bool):
        return _unsupported(action, f"{name} skill option must be 0 or 1.")
    try:
        option_point = NAMED_SERVANT_OPTION_POINTS[name].get(option)
    except TypeError:
        option_point = None
    if option_point is None:
        return _unsupported(action, f"Unknown {name} skill option.")

    skill_x, skill_y = SERVANT_SKILL_POINTS[skill - 1]
    steps = [
        _tap(
            f"servant_skill_{skill}",
            skill_x,
            skill_y,
            wait_after_seconds=SKILL_DIALOG_WAIT_SECONDS,
        ),
        _tap(f"{name}_option_{option}", *option_point),
    ]
    if len(command) == 4:
        target = command[3]
        if isinstance(target, bool) or not isinstance(target, int) or not 1 <= target <= 3:
            return _unsupported(action, "Kukulkan targets must be servant positions 1 through 3.")
        steps.append(_tap(f"skill_target_{target}", *SKILL_TARGET_POINTS[target - 1]))
    return _supported(action, steps)


def _compile_special_skill(
    action: dict[str, Any],
    command: Any,
) -> dict[str, Any] | None:
    if not (
        isinstance(command, list)
        and len(command) == 2
        and isinstance(command[0], int)
        and not isinstance(command[0], bool)
        and command[0] < 0
    ):
        return None
    skill = abs(command[0])
    option = command[1]
    if not 1 <= skill <= 9:
        return _unsupported(action, "Special servant skills must be numbered -1 through -9.")
    choice_points = SPACE_ISHTAR_CHOICE_POINTS if command[0] % 3 else EMIYA_CHOICE_POINTS
    if isinstance(option, bool) or not isinstance(option, int) or not 1 <= option <= len(choice_points):
        return _unsupported(action, "Special skill option is outside the available range.")
    skill_x, skill_y = SERVANT_SKILL_POINTS[skill - 1]
    option_x, option_y = choice_points[option - 1]
    return _supported(
        action,
        [
            _tap(
                f"servant_skill_{skill}",
                skill_x,
                skill_y,
                wait_after_seconds=SKILL_DIALOG_WAIT_SECONDS,
            ),
            _tap(f"special_skill_option_{option}", option_x, option_y),
        ],
    )


def _compile_np(action: dict[str, Any]) -> dict[str, Any]:
    servant = action.get("servant")
    if isinstance(servant, bool) or not isinstance(servant, int) or not 1 <= servant <= 3:
        return _unsupported(action, "NP servant positions must be 1 through 3.")
    x, y = NP_POINTS[servant - 1]
    return _supported(action, [_tap(f"np_{servant}", x, y)])


def _tap(
    role: str,
    x: int,
    y: int,
    *,
    wait_after_seconds: float | None = None,
) -> dict[str, Any]:
    step = {"type": "tap", "role": role, "x": x, "y": y}
    if wait_after_seconds is not None:
        step["wait_after_seconds"] = wait_after_seconds
    return step


def _supported(source: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {"source": source, "supported": True, "steps": steps, "reason": None}


def _unsupported(source: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"source": source, "supported": False, "steps": [], "reason": reason}
