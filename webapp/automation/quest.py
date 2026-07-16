from __future__ import annotations

from time import monotonic
from typing import Any

from webapp.automation.interaction import (
    configured_random_time,
    randomized_touch_point,
    randomized_wait_seconds,
)
from webapp.automation.run import StageHandler
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.quest import QuestRecognizer
from webapp.services.script_data import ScriptDataService


FREE_QUEST_ENTER_JOB_KIND = "battle.enter-free-quest"
_BATTLE_FLOW_STAGES = {"assist", "prepare", "battle", "completion"}


def create_free_quest_entry_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    quest_recognizer: QuestRecognizer,
    detect_stage: StageHandler,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        normalized_name = setting_name.strip()
        timeout_seconds = _number(payload, "timeout_seconds", 60, 0.1, 600)
        poll_interval = _number(payload, "poll_interval", 0.5, 0, 10)
        action_wait_seconds = _number(payload, "action_wait_seconds", 1, 0, 30)
        max_actions = _integer(payload, "max_actions", 20, 1, 200)
        plan = script_data.get_setting_plan(normalized_name)
        server = str(plan["server"]).upper()
        run_options = plan.get("run", {})
        random_touch = bool(run_options.get("random_touch"))
        random_time = configured_random_time(run_options.get("random_time", 0))
        started = monotonic()
        attempts = 0
        actions: list[str] = []

        while monotonic() - started <= timeout_seconds:
            attempts += 1
            context.checkpoint(
                "enter_free_quest",
                progress=min((monotonic() - started) / timeout_seconds, 0.95),
            )
            stage_result = detect_stage(
                context,
                {"setting_name": normalized_name},
            ) or {}
            stage = str(stage_result.get("stage") or "unknown")
            if stage in _BATTLE_FLOW_STAGES:
                context.checkpoint(
                    "complete",
                    progress=1.0,
                    message="Free quest battle flow was reached.",
                )
                return _result(normalized_name, True, stage, None, attempts, actions)

            screenshot = device_service.snapshot()
            quest_report = quest_recognizer.recognize_free_quests(
                screenshot,
                server,
            )
            context.emit(
                "quest_recognition",
                "Visible free quests were recognized.",
                data=quest_report,
            )
            selected_quest = quest_report.get("selected")
            if isinstance(selected_quest, dict):
                _tap_candidate(
                    context,
                    device_service,
                    selected_quest["center"],
                    "free_quest",
                    random_touch,
                )
                actions.append("free_quest")
            elif int(quest_report.get("candidate_count", 0)) > 0:
                return _result(
                    normalized_name,
                    False,
                    "unknown",
                    "visible_quests_cleared",
                    attempts,
                    actions,
                )
            else:
                map_report = quest_recognizer.recognize_free_map(screenshot)
                context.emit(
                    "quest_recognition",
                    "Visible free quest map targets were recognized.",
                    data=map_report,
                )
                selected_map_target = map_report.get("selected")
                if not isinstance(selected_map_target, dict):
                    return _result(
                        normalized_name,
                        False,
                        "unknown",
                        "no_visible_free_quest",
                        attempts,
                        actions,
                    )
                _tap_candidate(
                    context,
                    device_service,
                    selected_map_target["touch"],
                    "map_red_dot",
                    random_touch,
                )
                actions.append("map_red_dot")

            if len(actions) >= max_actions:
                return _result(
                    normalized_name,
                    False,
                    "unknown",
                    "navigation_limit",
                    attempts,
                    actions,
                )
            wait_seconds = action_wait_seconds if actions else poll_interval
            context.sleep(randomized_wait_seconds(wait_seconds, random_time))

        raise TimeoutError(
            f"Free quest battle flow was not reached within {timeout_seconds:.2f} seconds."
        )

    return handler


def register_free_quest_entry_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    quest_recognizer: QuestRecognizer,
    detect_stage: StageHandler,
) -> None:
    if job_manager.has_kind(FREE_QUEST_ENTER_JOB_KIND):
        return
    job_manager.register(
        FREE_QUEST_ENTER_JOB_KIND,
        create_free_quest_entry_handler(
            script_data,
            device_service,
            quest_recognizer,
            detect_stage,
        ),
        requires_device=True,
    )


def _tap_candidate(
    context: RunContext,
    device_service: DeviceService,
    point: list[int],
    role: str,
    random_touch: bool,
) -> None:
    x, y = randomized_touch_point(point, enabled=random_touch)
    operation = device_service.tap(x, y)
    context.emit(
        "device_action",
        "Advanced free quest navigation.",
        data={"role": role, "x": x, "y": y, "operation": operation.to_dict()},
    )


def _result(
    setting_name: str,
    entered: bool,
    stage: str,
    reason: str | None,
    attempts: int,
    actions: list[str],
) -> dict[str, Any]:
    return {
        "setting_name": setting_name,
        "entered": entered,
        "stage": stage,
        "reason": reason,
        "attempts": attempts,
        "actions": list(actions),
    }


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


def _integer(
    payload: dict[str, Any],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer.")
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}.")
    return value
