from __future__ import annotations

from typing import Any

from webapp.runtime import JobManager, RunContext
from webapp.services.script_data import ScriptDataService


BATTLE_DRY_RUN_JOB_KIND = "battle.dry-run"


def register_battle_jobs(
    job_manager: JobManager,
    script_data: ScriptDataService,
) -> None:
    if job_manager.has_kind(BATTLE_DRY_RUN_JOB_KIND):
        return

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

    job_manager.register(BATTLE_DRY_RUN_JOB_KIND, dry_run)


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
