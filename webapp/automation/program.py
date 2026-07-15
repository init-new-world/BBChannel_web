from __future__ import annotations

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
MASTER_SKILL_MENU_POINT = (1131, 320)
MASTER_SKILL_POINTS = ((850, 310), (940, 310), (1020, 310))
NP_POINTS = ((500, 110), (650, 200), (870, 200))
ATTACK_POINT = (1150, 600)
COMMAND_CARD_BACK_POINT = (1250, 683)
FACE_CARD_POINTS = ((150, 500), (375, 500), (650, 500), (900, 500), (1175, 500))
SPACE_ISHTAR_CHOICE_POINTS = ((327, 433), (639, 433), (951, 433))
EMIYA_CHOICE_POINTS = ((483, 433), (795, 433))
COMMAND_SPELL_MENU_POINT = (1060, 82)
COMMAND_SPELL_NP_CHARGE_POINT = (637, 343)
COMMAND_SPELL_CONFIRM_POINT = (793, 430)


def compile_battle_program(plan: dict[str, Any]) -> dict[str, Any]:
    rounds: list[dict[str, Any]] = []
    action_count = 0
    supported_action_count = 0
    tap_count = 0
    execution_tap_count = 0
    source_types: list[object] = []
    command_phases: list[dict[str, Any]] = []

    for round_plan in plan["rounds"]:
        turns: list[dict[str, Any]] = []
        for turn in round_plan["turns"]:
            actions = [_compile_action(action) for action in turn["actions"]]
            command_phase = _compile_command_phase(turn)
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
        rounds.append({"round": round_plan["round"], "turns": turns})

    unsupported_action_count = action_count - supported_action_count
    skill_execution = _skill_execution_status(
        action_count,
        unsupported_action_count,
        source_types,
    )
    battle_execution = _battle_execution_status(
        len(command_phases),
        unsupported_action_count,
        source_types,
        command_phases,
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
        },
        "execution": {"skills": skill_execution, "battle": battle_execution},
        "validation": plan["validation"],
    }


def _skill_execution_status(
    action_count: int,
    unsupported_action_count: int,
    source_types: list[object],
) -> dict[str, Any]:
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
) -> dict[str, Any]:
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


def _compile_command_phase(turn: dict[str, Any]) -> dict[str, Any]:
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
                    "preselected_nps": turn.get("nps", []),
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
    control = _compile_skill_control(action, command)
    if control is not None:
        return control
    command_spell = _compile_command_spell(action, command)
    if command_spell is not None:
        return command_spell
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
        steps = [_tap(f"servant_skill_{skill}", x, y)]
    else:
        menu_x, menu_y = MASTER_SKILL_MENU_POINT
        x, y = MASTER_SKILL_POINTS[skill - 10]
        steps = [
            _tap("master_skill_menu", menu_x, menu_y, wait_after_seconds=1.5),
            _tap(f"master_skill_{skill}", x, y),
        ]
    if target is not None:
        target_x, target_y = SKILL_TARGET_POINTS[target - 1]
        steps.append(_tap(f"skill_target_{target}", target_x, target_y))
    return _supported(action, steps)


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
    if len(command) != 3 or not isinstance(command[1], (bool, int)):
        return _unsupported(action, "Conditional skill blocks require Start, mode, and checks.")
    checks = command[2]
    if not isinstance(checks, (list, tuple)):
        return _unsupported(action, "Conditional skill checks must be a list.")
    result = _supported(action, [])
    result["control"] = {
        "type": "condition_start",
        "execute_when_matched": bool(command[1]),
        "check_cards": bool(checks) and any(checks),
    }
    return result


def _compile_command_spell(
    action: dict[str, Any],
    command: Any,
) -> dict[str, Any] | None:
    if not (
        isinstance(command, list)
        and len(command) == 2
        and command[0] == "令咒·宝具解放"
    ):
        return None
    target = command[1]
    if isinstance(target, bool) or not isinstance(target, int) or not 1 <= target <= 3:
        return _unsupported(action, "Command spell targets must be servant positions 1 through 3.")
    target_x, target_y = SKILL_TARGET_POINTS[target - 1]
    return _supported(
        action,
        [
            _tap("command_spell_menu", *COMMAND_SPELL_MENU_POINT, wait_after_seconds=1.0),
            _tap(
                "command_spell_np_charge",
                *COMMAND_SPELL_NP_CHARGE_POINT,
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
                wait_after_seconds=1.0,
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
