from __future__ import annotations

from time import monotonic
from typing import Any

from webapp.automation.run import StageHandler
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.script_data import ScriptDataService


BATTLE_RESTART_GAME_JOB_KIND = "battle.restart-game"


def create_recovery_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    detect_stage: StageHandler,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        normalized_name = setting_name.strip()
        plan = script_data.get_setting_plan(normalized_name)
        if not plan["run"]["game_crash_restart"]:
            return {
                "setting_name": normalized_name,
                "recovered": False,
                "reason": "game_crash_restart_disabled",
                "stage": "unknown",
            }

        package_name = payload.get("package_name")
        if package_name is not None and (
            not isinstance(package_name, str) or not package_name.strip()
        ):
            raise ValueError("package_name must be a non-empty string when provided.")
        timeout_seconds = _number(payload, "timeout_seconds", 300, 0.1, 900)
        poll_interval = _number(payload, "poll_interval", 1, 0, 30)
        launch_wait_seconds = _number(payload, "launch_wait_seconds", 5, 0, 60)

        context.checkpoint("restart_game", progress=0.0)
        operation = device_service.restart_game(
            package_name.strip() if isinstance(package_name, str) else None
        )
        context.emit(
            "device_action",
            "Game restart command was sent.",
            data={"role": "restart_game", "operation": operation.to_dict()},
        )
        context.sleep(launch_wait_seconds)

        started = monotonic()
        attempts = 0
        while monotonic() - started <= timeout_seconds:
            elapsed = monotonic() - started
            context.checkpoint(
                "wait_for_game",
                progress=min(elapsed / timeout_seconds, 0.95),
            )
            stage_result = detect_stage(
                context,
                {"setting_name": normalized_name},
            ) or {}
            attempts += 1
            stage = str(stage_result.get("stage") or "unknown")
            if stage != "unknown":
                context.checkpoint(
                    "complete",
                    progress=1.0,
                    message="Game stage was recovered.",
                )
                return {
                    "setting_name": normalized_name,
                    "recovered": True,
                    "reason": None,
                    "stage": stage,
                    "attempts": attempts,
                    "operation": operation.to_dict(),
                }
            context.sleep(poll_interval)

        raise TimeoutError(
            f"Game stage was not recovered within {timeout_seconds:.2f} seconds."
        )

    return handler


def register_recovery_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    detect_stage: StageHandler,
) -> None:
    if job_manager.has_kind(BATTLE_RESTART_GAME_JOB_KIND):
        return
    job_manager.register(
        BATTLE_RESTART_GAME_JOB_KIND,
        create_recovery_handler(script_data, device_service, detect_stage),
        requires_device=True,
    )


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
