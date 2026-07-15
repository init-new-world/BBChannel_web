from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from time import monotonic
from typing import Any

from webapp.automation.interaction import (
    configured_random_time,
    match_touch_point,
    randomized_touch_point,
    randomized_wait_seconds,
)
from webapp.automation.program import (
    ATTACK_POINT,
    COMMAND_CARD_BACK_POINT,
    FACE_CARD_POINTS,
    NP_POINTS,
    compile_battle_program,
)
from webapp.automation.strategy import StrategySelectionError, select_command_cards
from webapp.runtime import JobManager, RunContext
from webapp.services.cards import CommandCardRecognizer
from webapp.services.devices import DeviceService
from webapp.services.recognition import RecognitionService
from webapp.services.script_data import ScriptDataService


BATTLE_DRY_RUN_JOB_KIND = "battle.dry-run"
BATTLE_EXECUTE_PLAN_JOB_KIND = "battle.execute-plan"
BATTLE_EXECUTE_SKILLS_JOB_KIND = "battle.execute-skills"


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
    screenshot = device_service.snapshot()
    menu_button = recognition.match_template(
        screenshot,
        f"battle/{server}/fight_menu_button.png",
        threshold=0.85,
        scales=(1.0, 0.75, 2 / 3, 0.5),
    )
    if not menu_button.matched:
        raise RuntimeError("Battle menu button was not recognized.")
    device_service.tap(*match_touch_point(menu_button, enabled=random_touch))
    actions = ["open_menu"]
    context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))

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
    if len(toggles) != 3:
        raise RuntimeError(
            f"Expected three battle settings toggles but recognized {len(toggles)}."
        )

    initial_states = [enabled for enabled, _match in toggles]
    for index, ((enabled, match), desired) in enumerate(
        zip(toggles, (True, True, False), strict=True),
        start=1,
    ):
        if enabled == desired:
            continue
        device_service.tap(*match_touch_point(match, enabled=random_touch))
        actions.append(f"toggle_{index}")
        context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))

    screenshot = device_service.snapshot()
    back_button = recognition.match_template(
        screenshot,
        f"battle/{server}/back.png",
        threshold=0.85,
        scales=(1.0, 0.75, 2 / 3, 0.5),
    )
    if not back_button.matched:
        raise RuntimeError("Battle menu back button was not recognized.")
    device_service.tap(*match_touch_point(back_button, enabled=random_touch))
    actions.append("close_menu")
    context.emit(
        "battle_settings",
        "Initial battle settings were normalized.",
        data={"states": initial_states, "actions": actions},
    )
    context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
    return {
        "changed": any(
            state != desired
            for state, desired in zip(initial_states, (True, True, False), strict=True)
        ),
        "states": initial_states,
        "actions": actions,
    }


def _distinct_toggle_matches(candidates):
    selected = []
    for candidate in sorted(candidates, key=lambda item: item[1].confidence, reverse=True):
        if any(_match_iou(candidate[1], existing[1]) > 0.3 for existing in selected):
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda item: (item[1].center[1], item[1].center[0]))


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
    available = Counter(
        card["code"]
        for card in cards
        if isinstance(card.get("code"), str)
    )
    return any(
        all(available[code] >= count for code, count in Counter(need).items())
        for need in need_cards
    )


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
    tap_interval: float,
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
        )
        recognized = card_recognizer.recognize(
            screenshot,
            server,
            servants,
            threshold=threshold,
        )
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
        )
        tap_count += _execute_steps(
            context,
            device_service,
            [runtime["skill_step"]],
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
) -> dict[str, Any]:
    server = server.upper()
    attack_path = f"battle/{server}/attack.png"
    phase_paths = [f"battle/{server}/phase_{round_number}.png" for round_number in range(1, 4)]
    finish_paths = [
        f"battle/{server}/battleFinish.png",
        f"battle/{server}/battleFinish1.png",
        f"battle/{server}/fight_end.png",
    ]
    candidates = [
        {
            "template_path": path,
            "threshold": threshold,
            "scales": (1.0, 0.75, 2 / 3, 0.5),
        }
        for path in [attack_path, *phase_paths, *finish_paths]
    ]
    started = monotonic()
    attempts = 0
    while True:
        screenshot = device_service.snapshot()
        matches = recognition.match_templates(screenshot, candidates)
        attempts += 1
        by_path = {
            candidate["template_path"]: match
            for candidate, match in zip(candidates, matches, strict=True)
        }
        if any(by_path[path].matched for path in finish_paths):
            result = {"state": "finished", "round": None}
        else:
            matched_rounds = [
                round_number
                for round_number, path in enumerate(phase_paths, start=1)
                if by_path[path].matched
            ]
            result = (
                {"state": "battle", "round": matched_rounds[0]}
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
        if monotonic() - started >= timeout_seconds:
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
            ),
            requires_device=True,
        )


def create_battle_execute_plan_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognition: RecognitionService,
    card_recognizer: CommandCardRecognizer | None,
):
    def execute(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = _required_setting_name(payload)
        threshold, timeout_seconds, poll_interval, tap_interval = _execution_options(
            payload
        )
        plan = script_data.get_setting_plan(setting_name)
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
        program = compile_battle_program(plan)
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
            action.get("runtime", {}).get("type") == "hakuno_card_reroll"
            for round_plan in program["rounds"]
            for action in round_plan["extra_turn"]["actions"]
        )
        if needs_card_recognition and card_recognizer is None:
            raise ValueError("Command card recognition is not configured.")
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
        servant_positions = _servant_positions(plan["servants"])
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

        for turn_number, (round_number, turn) in enumerate(turns, start=1):
            skill_actions = [
                action
                for action in turn["actions"]
                if action["source"].get("type") == "skill"
            ]
            execute_conditional_skills = True
            for skill_number, action in enumerate(skill_actions, start=1):
                control = action.get("control")
                if control and control["type"] == "condition_start":
                    matched = True
                    if control["check_cards"]:
                        condition = turn.get("condition")
                        if not isinstance(condition, list) or not condition:
                            raise ValueError("Conditional skill block has no card condition.")
                        _wait_for_battle_ready(
                            context,
                            device_service,
                            recognition,
                            attack_template,
                            threshold,
                            timeout_seconds,
                            poll_interval,
                        )
                        matched, condition_taps = _evaluate_card_condition(
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
                        )
                        tap_count += condition_taps
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
                )
                tap_count += _execute_steps(
                    context,
                    device_service,
                    action["steps"],
                    tap_interval,
                )
                state_change = action.get("state_change")
                if state_change and state_change["type"] == "servant_exchange":
                    _apply_servant_exchange(
                        servant_positions,
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
            _wait_for_battle_ready(
                context,
                device_service,
                recognition,
                attack_template,
                threshold,
                timeout_seconds,
                poll_interval,
            )
            command_steps = turn["command_phase"]["steps"]
            tap_count += _execute_steps(
                context,
                device_service,
                command_steps[:1],
                tap_interval,
            )
            command_screenshot = _wait_for_command_cards(
                context,
                device_service,
                recognition,
                card_templates,
                threshold,
                timeout_seconds,
                poll_interval,
            )
            for step in command_steps[1:]:
                if step.get("type") == "tap":
                    tap_count += _execute_steps(
                        context,
                        device_service,
                        [step],
                        tap_interval,
                    )
                    continue
                if step.get("type") == "strategy":
                    tap_count += _execute_strategy_step(
                        context,
                        device_service,
                        card_recognizer,
                        command_screenshot,
                        program["server"],
                        _frontline_servants(servant_positions),
                        step,
                        threshold,
                        tap_interval,
                    )
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
                context.emit(
                    "servant_replacement",
                    "Post-turn servant positions were updated.",
                    data={
                        "replacements": action["source"]["replacements"],
                        "frontline": _frontline_servants(servant_positions),
                    },
                )

            compiled_round = compiled_rounds[round_number]
            extra_turn = compiled_round["extra_turn"]
            if (
                turn["turn"] == last_turns[round_number]
                and extra_turn["actions"]
            ):
                for extra_number in range(1, 11):
                    transition = _wait_for_battle_transition(
                        context,
                        device_service,
                        recognition,
                        program["server"],
                        threshold,
                        timeout_seconds,
                        poll_interval,
                    )
                    if transition["state"] == "finished":
                        battle_finished = True
                        break
                    if transition["round"] != round_number:
                        break
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
                    )
                else:
                    raise RuntimeError(
                        f"Round {round_number} exceeded the 10 configured extra-turn limit."
                    )
            if battle_finished:
                break

        context.checkpoint("complete", progress=1.0, message="Battle execution completed.")
        return {
            "setting_name": setting_name,
            "turn_count": len(turns),
            "action_count": program["summary"]["action_count"],
            "tap_count": tap_count,
        }

    return execute


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
    tap_interval: float,
) -> int:
    tap_count = 0
    skill_actions = [
        action
        for action in turn["actions"]
        if action["source"].get("type") == "skill"
    ]
    for action in skill_actions:
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
        )
        tap_count += _execute_steps(
            context,
            device_service,
            action["steps"],
            tap_interval,
        )
        state_change = action.get("state_change")
        if state_change and state_change["type"] == "servant_exchange":
            _apply_servant_exchange(servant_positions, state_change["positions"])
            context.emit(
                "servant_exchange",
                "Runtime servant positions were exchanged.",
                data={
                    "positions": state_change["positions"],
                    "frontline": _frontline_servants(servant_positions),
                },
            )

    _wait_for_battle_ready(
        context,
        device_service,
        recognition,
        attack_template,
        threshold,
        timeout_seconds,
        poll_interval,
    )
    command_steps = turn["command_phase"]["steps"]
    tap_count += _execute_steps(
        context,
        device_service,
        command_steps[:1],
        tap_interval,
    )
    command_screenshot = _wait_for_command_cards(
        context,
        device_service,
        recognition,
        card_templates,
        threshold,
        timeout_seconds,
        poll_interval,
    )
    for step in command_steps[1:]:
        if step.get("type") == "tap":
            tap_count += _execute_steps(
                context,
                device_service,
                [step],
                tap_interval,
            )
        elif step.get("type") == "strategy":
            tap_count += _execute_strategy_step(
                context,
                device_service,
                card_recognizer,
                command_screenshot,
                server,
                _frontline_servants(servant_positions),
                step,
                threshold,
                tap_interval,
            )
    return tap_count


def _servant_positions(servants: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    positions: list[dict[str, Any] | None] = [None] * 6
    for servant in servants:
        slot = servant.get("slot")
        if (
            isinstance(slot, int)
            and not isinstance(slot, bool)
            and 0 <= slot < len(positions)
            and servant.get("name")
        ):
            positions[slot] = dict(servant)
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
    tap_interval: float,
) -> int:
    if card_recognizer is None:
        raise ValueError("Command card recognition is not configured.")
    recognized = card_recognizer.recognize(
        screenshot,
        server,
        servants,
        threshold=threshold,
    )
    context.emit(
        "card_recognition",
        "Command cards were classified.",
        data=recognized,
    )
    if not recognized["complete"]:
        raise ValueError(
            f"Recognized {recognized['recognized_count']} of 5 command cards."
        )
    selected = select_command_cards(
        step["strategies"],
        recognized["cards"],
        preselected_nps=step.get("preselected_nps", []),
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
    return _execute_steps(context, device_service, tap_steps, tap_interval)


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
    tap_interval: float,
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
    )
    recognized = card_recognizer.recognize(
        screenshot,
        server,
        servants,
        threshold=threshold,
    )
    if not recognized["complete"]:
        raise ValueError(
            f"Recognized {recognized['recognized_count']} of 5 command cards."
        )
    try:
        select_command_cards(condition, recognized["cards"])
        matched = True
        reason = None
    except StrategySelectionError as exc:
        matched = False
        reason = str(exc)
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


def _execute_skills_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognition: RecognitionService,
    card_recognizer: CommandCardRecognizer | None,
):
    def execute(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = _required_setting_name(payload)
        threshold, timeout_seconds, poll_interval, tap_interval = _execution_options(
            payload
        )
        plan = script_data.get_setting_plan(setting_name)
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
        attack_template = f"battle/{program['server']}/attack.png"
        card_templates = [
            f"battle/{program['server']}/{card_type}.png"
            for card_type in ("Arts", "Buster", "Quick")
        ]
        servant_positions = _servant_positions(plan["servants"])
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
            )
            tap_count += _execute_steps(
                context,
                device_service,
                action["steps"],
                tap_interval,
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
        _number(payload, "timeout_seconds", 15.0, minimum=0.1, maximum=300.0),
        _number(payload, "poll_interval", 0.25, minimum=0.01, maximum=10.0),
        _number(payload, "tap_interval_seconds", 0.15, minimum=0.0, maximum=10.0),
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
        if wait_after:
            context.sleep(wait_after)
    return len(steps)


def _wait_for_battle_ready(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    template_path: str,
    threshold: float,
    timeout_seconds: float,
    poll_interval: float,
) -> None:
    started = monotonic()
    attempts = 0
    while True:
        screenshot = device_service.snapshot()
        match = recognition.match_template(screenshot, template_path, threshold)
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
            return
        if monotonic() - started >= timeout_seconds:
            raise TimeoutError(
                f"Battle controls did not become ready within {timeout_seconds:.2f} seconds."
            )
        context.sleep(poll_interval)


def _wait_for_command_cards(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    template_paths: list[str],
    threshold: float,
    timeout_seconds: float,
    poll_interval: float,
) -> bytes:
    started = monotonic()
    attempts = 0
    candidates = [
        {"template_path": template_path, "threshold": threshold}
        for template_path in template_paths
    ]
    while True:
        screenshot = device_service.snapshot()
        matches = recognition.match_templates(screenshot, candidates)
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
        if any(match.matched for match in matches):
            return screenshot
        if monotonic() - started >= timeout_seconds:
            raise TimeoutError(
                f"Command cards did not become ready within {timeout_seconds:.2f} seconds."
            )
        context.sleep(poll_interval)


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
