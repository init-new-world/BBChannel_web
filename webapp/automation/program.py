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
SKILL_TARGET_POINTS = ((320, 420), (640, 420), (960, 420))
NP_POINTS = ((320, 300), (640, 300), (960, 300))


def compile_battle_program(plan: dict[str, Any]) -> dict[str, Any]:
    rounds: list[dict[str, Any]] = []
    action_count = 0
    supported_action_count = 0
    tap_count = 0

    for round_plan in plan["rounds"]:
        turns: list[dict[str, Any]] = []
        for turn in round_plan["turns"]:
            actions = [_compile_action(action) for action in turn["actions"]]
            action_count += len(actions)
            supported_action_count += sum(bool(action["supported"]) for action in actions)
            tap_count += sum(len(action["steps"]) for action in actions)
            turns.append({"turn": turn["turn"], "actions": actions})
        rounds.append({"round": round_plan["round"], "turns": turns})

    return {
        "name": plan["name"],
        "server": plan["server"],
        "base_resolution": {"width": 1280, "height": 720},
        "rounds": rounds,
        "summary": {
            "action_count": action_count,
            "supported_action_count": supported_action_count,
            "unsupported_action_count": action_count - supported_action_count,
            "tap_count": tap_count,
        },
        "validation": plan["validation"],
    }


def _compile_action(action: dict[str, Any]) -> dict[str, Any]:
    action_type = action.get("type")
    if action_type == "skill":
        return _compile_skill(action)
    if action_type == "np":
        return _compile_np(action)
    return _unsupported(action, f"{action_type or 'Unknown'} actions are not compiled yet.")


def _compile_skill(action: dict[str, Any]) -> dict[str, Any]:
    command = action.get("command")
    target: int | None = None
    if isinstance(command, list) and len(command) == 2:
        skill, target = command
    else:
        skill = command
    if isinstance(skill, bool) or not isinstance(skill, int) or not 1 <= skill <= 9:
        return _unsupported(action, "Only servant skill commands 1 through 9 are compiled.")
    if target is not None and (
        isinstance(target, bool) or not isinstance(target, int) or not 1 <= target <= 3
    ):
        return _unsupported(action, "Skill targets must be servant positions 1 through 3.")

    x, y = SERVANT_SKILL_POINTS[skill - 1]
    steps = [_tap(f"servant_skill_{skill}", x, y)]
    if target is not None:
        target_x, target_y = SKILL_TARGET_POINTS[target - 1]
        steps.append(_tap(f"skill_target_{target}", target_x, target_y))
    return _supported(action, steps)


def _compile_np(action: dict[str, Any]) -> dict[str, Any]:
    servant = action.get("servant")
    if isinstance(servant, bool) or not isinstance(servant, int) or not 1 <= servant <= 3:
        return _unsupported(action, "NP servant positions must be 1 through 3.")
    x, y = NP_POINTS[servant - 1]
    return _supported(action, [_tap(f"np_{servant}", x, y)])


def _tap(role: str, x: int, y: int) -> dict[str, Any]:
    return {"type": "tap", "role": role, "x": x, "y": y}


def _supported(source: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {"source": source, "supported": True, "steps": steps, "reason": None}


def _unsupported(source: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"source": source, "supported": False, "steps": [], "reason": reason}
