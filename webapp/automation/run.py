from __future__ import annotations

from collections.abc import Callable
from typing import Any

from webapp.runtime import JobManager, RunContext
from webapp.services.script_data import ScriptDataService


FULL_RUN_JOB_KIND = "battle.run"
StageHandler = Callable[[RunContext, dict[str, Any]], dict[str, Any] | None]


def create_full_run_handler(
    script_data: ScriptDataService,
    select_assist: StageHandler,
    prepare_battle: StageHandler,
    execute_battle: StageHandler,
    complete_battle: StageHandler,
):

    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        max_runs = payload.get("max_runs", 1)
        if (
            isinstance(max_runs, bool)
            or not isinstance(max_runs, int)
            or not 1 <= max_runs <= 10000
        ):
            raise ValueError("max_runs must be between 1 and 10000.")
        max_clear_runs = payload.get("max_clear_runs", 100)
        if (
            isinstance(max_clear_runs, bool)
            or not isinstance(max_clear_runs, int)
            or not 1 <= max_clear_runs <= 10000
        ):
            raise ValueError("max_clear_runs must be between 1 and 10000.")

        normalized_name = setting_name.strip()
        run_options = script_data.get_setting_plan(normalized_name)["run"]
        interval_before_fight = _configured_interval(
            run_options.get("interval_before_fight", 0),
            "interval_before_fight",
        )
        interval_after_fight = _configured_interval(
            run_options.get("interval_after_fight", 0),
            "interval_after_fight",
        )
        clear_ap = bool(run_options.get("clear_ap"))
        first_battle_set = bool(run_options.get("first_battle_set"))
        stage_options = {
            name: _stage_options(payload, name)
            for name in ("assist", "prepare", "battle", "completion")
        }
        drop_count = 0
        run_results: list[dict[str, Any]] = []
        stopped = False
        stop_reason = None
        cleared_ap = False
        completed_runs = 0
        clear_runs = 0
        run_number = 1

        while run_number <= max_runs or (clear_ap and clear_runs < max_clear_runs):
            clearing_ap = run_number > max_runs
            progress = min(completed_runs / max(max_runs, 1), 0.95)
            context.checkpoint(
                "run.select_assist",
                progress=progress,
                message=f"Selecting assist for run {run_number}.",
            )
            assist_result = select_assist(
                context,
                {"setting_name": normalized_name, **stage_options["assist"]},
            ) or {}

            context.checkpoint(
                "run.prepare_battle",
                progress=progress,
                message=f"Preparing run {run_number}.",
            )
            prepare_result = prepare_battle(
                context,
                {
                    **stage_options["prepare"],
                    "setting_name": normalized_name,
                    "recover_ap": not clearing_ap,
                },
            ) or {}
            if prepare_result.get("ready") is False:
                prepare_reason = str(
                    prepare_result.get("reason") or "battle_not_ready"
                )
                if clearing_ap and prepare_reason == "ap_empty":
                    cleared_ap = True
                    stop_reason = "ap_cleared"
                else:
                    stopped = True
                    stop_reason = prepare_reason
                break
            if interval_before_fight:
                context.sleep(interval_before_fight)

            context.checkpoint(
                "run.execute_battle",
                progress=progress,
                message=f"Executing run {run_number}.",
            )
            battle_result = execute_battle(
                context,
                {
                    **stage_options["battle"],
                    "setting_name": normalized_name,
                    "initialize_settings": first_battle_set and run_number == 1,
                },
            ) or {}
            if interval_after_fight:
                context.sleep(interval_after_fight)

            context.checkpoint(
                "run.complete_battle",
                progress=progress,
                message=f"Completing run {run_number}.",
            )
            completion_result = complete_battle(
                context,
                {
                    **stage_options["completion"],
                    "setting_name": normalized_name,
                    "repeat": run_number < max_runs
                    or (
                        clear_ap
                        and (not clearing_ap or clear_runs + 1 < max_clear_runs)
                    ),
                    "initial_drop_count": drop_count,
                },
            ) or {}
            raw_drop_count = completion_result.get("drop_count", drop_count)
            if isinstance(raw_drop_count, int) and not isinstance(raw_drop_count, bool):
                drop_count = max(raw_drop_count, 0)
            run_results.append(
                {
                    "run": run_number,
                    "assist": assist_result,
                    "prepare": prepare_result,
                    "battle": battle_result,
                    "completion": completion_result,
                }
            )
            completed_runs += 1
            if clearing_ap:
                clear_runs += 1
            if completion_result.get("stopped"):
                stopped = True
                stop_reason = str(completion_result.get("reason") or "completion_stop")
                break
            run_number += 1

        if clear_ap and not cleared_ap and not stopped and clear_runs >= max_clear_runs:
            stopped = True
            stop_reason = "clear_ap_limit"

        context.checkpoint(
            "complete",
            progress=1.0,
            message="Full run job completed.",
        )
        return {
            "setting_name": normalized_name,
            "runs_completed": completed_runs,
            "max_runs": max_runs,
            "stopped": stopped,
            "reason": stop_reason,
            "cleared_ap": cleared_ap,
            "drop_count": drop_count,
            "runs": run_results,
        }

    return handler


def register_full_run_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    select_assist: StageHandler,
    prepare_battle: StageHandler,
    execute_battle: StageHandler,
    complete_battle: StageHandler,
) -> None:
    if job_manager.has_kind(FULL_RUN_JOB_KIND):
        return
    job_manager.register(
        FULL_RUN_JOB_KIND,
        create_full_run_handler(
            script_data,
            select_assist,
            prepare_battle,
            execute_battle,
            complete_battle,
        ),
        requires_device=True,
    )


def _stage_options(payload: dict[str, Any], stage: str) -> dict[str, Any]:
    value = payload.get(stage, {})
    if not isinstance(value, dict):
        raise ValueError(f"{stage} must be an object.")
    return dict(value)


def _configured_interval(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number.")
    result = float(value)
    if not 0 <= result <= 600:
        raise ValueError(f"{name} must be between 0 and 600.")
    return result
