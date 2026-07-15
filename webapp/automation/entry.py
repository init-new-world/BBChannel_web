from __future__ import annotations

from time import monotonic
from typing import Any

from webapp.core.errors import AppError, ErrorCode
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.recognition import RecognitionService
from webapp.services.script_data import ScriptDataService


BATTLE_PREPARE_JOB_KIND = "battle.prepare"


def register_battle_entry_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognition: RecognitionService,
) -> None:
    if job_manager.has_kind(BATTLE_PREPARE_JOB_KIND):
        return

    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        timeout_seconds = _number(payload, "timeout_seconds", 180, 0.1, 600)
        poll_interval = _number(payload, "poll_interval", 0.5, 0, 10)
        action_wait_seconds = _number(payload, "action_wait_seconds", 0.5, 0, 10)
        plan = script_data.get_setting_plan(setting_name.strip())
        server = str(plan["server"]).upper()
        template_roles = (
            ("battle_ready", f"battle/{server}/attack.png"),
            ("battle_ready", f"battle/{server}/phase_1.png"),
            ("team_decide", f"battle/{server}/teamDecide.png"),
            ("start_task", f"battle/{server}/start_task.png"),
            ("start_battle", f"battle/{server}/start_battle.png"),
        )
        started = monotonic()
        attempts = 0
        actions: list[str] = []

        while monotonic() - started <= timeout_seconds:
            elapsed = monotonic() - started
            context.checkpoint(
                "prepare_battle",
                progress=min(elapsed / timeout_seconds, 0.95),
            )
            screenshot = device_service.snapshot()
            attempts += 1
            matched_role = None
            matched_result = None
            for role, template_path in template_roles:
                try:
                    result = recognition.match_template(
                        screenshot,
                        template_path,
                        threshold=0.85,
                        scales=(1.0, 0.75, 2 / 3, 0.5),
                    )
                except AppError as exc:
                    if exc.code == ErrorCode.TEMPLATE_NOT_FOUND:
                        continue
                    raise
                if result.matched:
                    matched_role = role
                    matched_result = result
                    break

            context.emit(
                "recognition",
                "Battle preparation state checked.",
                data={"attempt": attempts, "state": matched_role},
            )
            if matched_role == "battle_ready":
                context.checkpoint("complete", progress=1.0, message="Battle is ready.")
                return {
                    "setting_name": setting_name.strip(),
                    "ready": True,
                    "actions": actions,
                    "attempts": attempts,
                }
            if matched_role is not None and matched_result is not None:
                operation = device_service.tap(*matched_result.center)
                actions.append(matched_role)
                context.emit(
                    "device_action",
                    "Advanced battle preparation.",
                    data={
                        "role": matched_role,
                        "x": matched_result.center[0],
                        "y": matched_result.center[1],
                        "operation": operation.to_dict(),
                    },
                )
                context.sleep(action_wait_seconds)
                continue
            context.sleep(poll_interval)

        raise TimeoutError(
            f"Battle did not become ready within {timeout_seconds:.2f} seconds."
        )

    job_manager.register(BATTLE_PREPARE_JOB_KIND, handler, requires_device=True)


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
