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
    detect_stage: StageHandler | None = None,
    recover_game: StageHandler | None = None,
    enter_free_quest: StageHandler | None = None,
    enter_main_story: StageHandler | None = None,
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
        entry_mode = payload.get("entry_mode", "current")
        if entry_mode not in {"current", "free_quest", "main_story"}:
            raise ValueError(
                "entry_mode must be current, free_quest, or main_story."
            )
        max_restarts = payload.get("max_restarts", 3)
        if (
            isinstance(max_restarts, bool)
            or not isinstance(max_restarts, int)
            or not 0 <= max_restarts <= 20
        ):
            raise ValueError("max_restarts must be between 0 and 20.")

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
        game_crash_restart = bool(run_options.get("game_crash_restart"))
        stage_options = {
            name: _stage_options(payload, name)
            for name in (
                "entry",
                "assist",
                "prepare",
                "battle",
                "completion",
                "recovery",
            )
        }
        drop_count = 0
        run_results: list[dict[str, Any]] = []
        stopped = False
        stop_reason = None
        cleared_ap = False
        completed_runs = 0
        clear_runs = 0
        run_number = 1
        entry_result: dict[str, Any] | None = None
        restart_count = 0
        recoveries: list[dict[str, Any]] = []
        resume_stage: str | None = None
        battle_settings_initialized = False
        resume = payload.get("resume", True)
        if not isinstance(resume, bool):
            raise ValueError("resume must be a boolean.")

        battle_stages = {"assist", "prepare", "battle", "completion"}

        def execute_stage(
            stage_name: str,
            stage_handler: StageHandler,
            stage_payload: dict[str, Any],
        ) -> tuple[dict[str, Any], str | None]:
            nonlocal restart_count
            try:
                return stage_handler(context, stage_payload) or {}, None
            except TimeoutError as exc:
                if (
                    not game_crash_restart
                    or recover_game is None
                    or restart_count >= max_restarts
                ):
                    raise
                context.checkpoint(
                    "run.recover_game",
                    progress=min(completed_runs / max(max_runs, 1), 0.95),
                    message=f"Recovering after {stage_name} timeout.",
                )
                recovered = recover_game(
                    context,
                    {
                        **stage_options["recovery"],
                        "setting_name": normalized_name,
                    },
                ) or {}
                restart_count += 1
                recovered_stage = str(recovered.get("stage") or "unknown")
                recoveries.append(
                    {
                        "trigger_stage": stage_name,
                        "error": str(exc),
                        **recovered,
                    }
                )
                if recovered.get("recovered") is False:
                    raise RuntimeError(
                        str(recovered.get("reason") or "Game recovery failed.")
                    ) from exc
                if recovered_stage not in battle_stages:
                    raise RuntimeError(
                        "Game recovery did not reach the battle flow."
                    ) from exc
                return {}, recovered_stage

        initial_stage = "assist"
        if entry_mode == "free_quest":
            if enter_free_quest is None:
                raise RuntimeError("Free quest entry is not available.")
            context.checkpoint(
                "run.enter_free_quest",
                progress=0.0,
                message="Entering a visible free quest.",
            )
            entry_result = enter_free_quest(
                context,
                {
                    **stage_options["entry"],
                    "setting_name": normalized_name,
                },
            ) or {}
            initial_stage = str(entry_result.get("stage") or "unknown")
            if not entry_result.get("entered"):
                stopped = True
                stop_reason = str(
                    entry_result.get("reason") or "free_quest_entry_failed"
                )
        elif entry_mode == "main_story":
            if enter_main_story is None:
                raise RuntimeError("Main story entry is not available.")
            context.checkpoint(
                "run.enter_main_story",
                progress=0.0,
                message="Entering a visible main story quest.",
            )
            entry_result = enter_main_story(
                context,
                {
                    **stage_options["entry"],
                    "setting_name": normalized_name,
                },
            ) or {}
            initial_stage = str(entry_result.get("stage") or "unknown")
            if not entry_result.get("entered"):
                stopped = True
                stop_reason = str(
                    entry_result.get("reason") or "main_story_entry_failed"
                )
        elif resume and detect_stage is not None:
            detected = detect_stage(context, {"setting_name": normalized_name}) or {}
            initial_stage = str(detected.get("stage") or "unknown")
            if (
                initial_stage == "unknown"
                and game_crash_restart
                and recover_game is not None
                and restart_count < max_restarts
            ):
                recovered = recover_game(
                    context,
                    {
                        **stage_options["recovery"],
                        "setting_name": normalized_name,
                    },
                ) or {}
                restart_count += 1
                initial_stage = str(recovered.get("stage") or "unknown")
                recoveries.append(
                    {
                        "trigger_stage": "initial",
                        "error": "Current battle flow stage was not recognized.",
                        **recovered,
                    }
                )
            if initial_stage not in battle_stages:
                raise RuntimeError("Current battle flow stage was not recognized.")

        if stopped:
            context.checkpoint(
                "complete",
                progress=1.0,
                message="Full run stopped before entering battle.",
            )
            return {
                "setting_name": normalized_name,
                "runs_completed": 0,
                "max_runs": max_runs,
                "stopped": True,
                "reason": stop_reason,
                "cleared_ap": False,
                "drop_count": 0,
                "entry": entry_result,
                "restart_count": restart_count,
                "recoveries": recoveries,
                "runs": [],
            }
        if initial_stage not in battle_stages:
            raise RuntimeError("Quest entry did not reach the battle flow.")

        current_run_results: dict[str, dict[str, Any]] = {
            "assist": {},
            "prepare": {"ready": True},
            "battle": {},
        }
        while run_number <= max_runs or (clear_ap and clear_runs < max_clear_runs):
            clearing_ap = run_number > max_runs
            current_stage = resume_stage or (
                initial_stage if run_number == 1 else "assist"
            )
            resume_stage = None
            progress = min(completed_runs / max(max_runs, 1), 0.95)
            assist_result = current_run_results["assist"]
            if current_stage == "assist":
                context.checkpoint(
                    "run.select_assist",
                    progress=progress,
                    message=f"Selecting assist for run {run_number}.",
                )
                assist_result, resume_stage = execute_stage(
                    "assist",
                    select_assist,
                    {"setting_name": normalized_name, **stage_options["assist"]},
                )
                if resume_stage is not None:
                    continue
                current_run_results["assist"] = assist_result

            prepare_result = current_run_results["prepare"]
            if current_stage in {"assist", "prepare"}:
                context.checkpoint(
                    "run.prepare_battle",
                    progress=progress,
                    message=f"Preparing run {run_number}.",
                )
                prepare_result, resume_stage = execute_stage(
                    "prepare",
                    prepare_battle,
                    {
                        **stage_options["prepare"],
                        "setting_name": normalized_name,
                        "recover_ap": not clearing_ap,
                        "team_check_mode": (
                            stage_options["prepare"].get("team_check_mode", "warn")
                            if run_number == 1
                            else "off"
                        ),
                    },
                )
                if resume_stage is not None:
                    continue
                current_run_results["prepare"] = prepare_result
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
            battle_result = current_run_results["battle"]
            if current_stage != "completion":
                if interval_before_fight:
                    context.sleep(interval_before_fight)
                context.checkpoint(
                    "run.execute_battle",
                    progress=progress,
                    message=f"Executing run {run_number}.",
                )
                initialize_settings = (
                    first_battle_set
                    and run_number == 1
                    and not battle_settings_initialized
                )
                if initialize_settings:
                    battle_settings_initialized = True
                battle_result, resume_stage = execute_stage(
                    "battle",
                    execute_battle,
                    {
                        **stage_options["battle"],
                        "setting_name": normalized_name,
                        "initialize_settings": initialize_settings,
                    },
                )
                if resume_stage is not None:
                    continue
                current_run_results["battle"] = battle_result
                if interval_after_fight:
                    context.sleep(interval_after_fight)

            context.checkpoint(
                "run.complete_battle",
                progress=progress,
                message=f"Completing run {run_number}.",
            )
            completion_result, resume_stage = execute_stage(
                "completion",
                complete_battle,
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
            )
            if resume_stage is not None:
                continue
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
            current_run_results = {
                "assist": {},
                "prepare": {"ready": True},
                "battle": {},
            }

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
            "entry": entry_result,
            "restart_count": restart_count,
            "recoveries": recoveries,
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
    detect_stage: StageHandler | None = None,
    recover_game: StageHandler | None = None,
    enter_free_quest: StageHandler | None = None,
    enter_main_story: StageHandler | None = None,
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
            detect_stage,
            recover_game,
            enter_free_quest,
            enter_main_story,
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
