from __future__ import annotations

from time import monotonic
from typing import Any

from webapp.automation.program import compile_battle_program
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.recognition import RecognitionService
from webapp.services.script_data import ScriptDataService


BATTLE_DRY_RUN_JOB_KIND = "battle.dry-run"
BATTLE_EXECUTE_SKILLS_JOB_KIND = "battle.execute-skills"


def register_battle_jobs(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService | None = None,
    recognition: RecognitionService | None = None,
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
            _execute_skills_handler(script_data, device_service, recognition),
            requires_device=True,
        )


def _execute_skills_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognition: RecognitionService,
):
    def execute(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = _required_setting_name(payload)
        threshold = _number(payload, "threshold", 0.75, minimum=0.0, maximum=1.0)
        timeout_seconds = _number(
            payload,
            "timeout_seconds",
            15.0,
            minimum=0.1,
            maximum=300.0,
        )
        poll_interval = _number(
            payload,
            "poll_interval",
            0.25,
            minimum=0.01,
            maximum=10.0,
        )
        tap_interval = _number(
            payload,
            "tap_interval_seconds",
            0.15,
            minimum=0.0,
            maximum=10.0,
        )
        program = compile_battle_program(script_data.get_setting_plan(setting_name))
        execution_status = program["execution"]["skills"]
        if not execution_status["ready"]:
            raise ValueError(execution_status["reason"])

        actions = [
            action
            for round_plan in program["rounds"]
            for turn in round_plan["turns"]
            for action in turn["actions"]
        ]
        attack_template = f"battle/{program['server']}/attack.png"
        tap_count = 0
        for action_number, action in enumerate(actions, start=1):
            context.checkpoint(
                f"skill_{action_number}.wait_for_battle",
                progress=(action_number - 1) / max(len(actions), 1),
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
            for step in action["steps"]:
                operation = device_service.tap(step["x"], step["y"])
                tap_count += 1
                context.emit(
                    "device_action",
                    f"Tapped {step['role']}.",
                    data={"role": step["role"], "operation": operation.to_dict()},
                )
                wait_after = max(
                    tap_interval,
                    float(step.get("wait_after_seconds", 0.0)),
                )
                if wait_after:
                    context.sleep(wait_after)

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
