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
        stage_options = {
            name: _stage_options(payload, name)
            for name in ("assist", "prepare", "battle", "completion")
        }
        drop_count = 0
        run_results: list[dict[str, Any]] = []
        stopped = False
        stop_reason = None

        for run_number in range(1, max_runs + 1):
            context.checkpoint(
                "run.select_assist",
                progress=(run_number - 1) / max_runs,
                message=f"Selecting assist for run {run_number}.",
            )
            assist_result = select_assist(
                context,
                {"setting_name": normalized_name, **stage_options["assist"]},
            ) or {}

            context.checkpoint(
                "run.prepare_battle",
                progress=(run_number - 0.75) / max_runs,
                message=f"Preparing run {run_number}.",
            )
            prepare_result = prepare_battle(
                context,
                {"setting_name": normalized_name, **stage_options["prepare"]},
            ) or {}
            if prepare_result.get("ready") is False:
                stopped = True
                stop_reason = str(prepare_result.get("reason") or "battle_not_ready")
                run_results.append(
                    {
                        "run": run_number,
                        "assist": assist_result,
                        "prepare": prepare_result,
                    }
                )
                break
            if interval_before_fight:
                context.sleep(interval_before_fight)

            context.checkpoint(
                "run.execute_battle",
                progress=(run_number - 0.5) / max_runs,
                message=f"Executing run {run_number}.",
            )
            battle_result = execute_battle(
                context,
                {"setting_name": normalized_name, **stage_options["battle"]},
            ) or {}
            if interval_after_fight:
                context.sleep(interval_after_fight)

            context.checkpoint(
                "run.complete_battle",
                progress=(run_number - 0.25) / max_runs,
                message=f"Completing run {run_number}.",
            )
            completion_result = complete_battle(
                context,
                {
                    **stage_options["completion"],
                    "setting_name": normalized_name,
                    "repeat": run_number < max_runs,
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
            if completion_result.get("stopped"):
                stopped = True
                stop_reason = str(completion_result.get("reason") or "completion_stop")
                break

        context.checkpoint(
            "complete",
            progress=1.0,
            message="Full run job completed.",
        )
        return {
            "setting_name": normalized_name,
            "runs_completed": len(run_results),
            "max_runs": max_runs,
            "stopped": stopped,
            "reason": stop_reason,
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
