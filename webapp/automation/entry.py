from __future__ import annotations

from time import monotonic
from typing import Any

from webapp.automation.interaction import (
    configured_random_time,
    match_touch_point,
    randomized_wait_seconds,
)
from webapp.automation.network import reconnect_if_present
from webapp.core.errors import AppError, ErrorCode
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.recognition import RecognitionService
from webapp.services.script_data import ScriptDataService


BATTLE_PREPARE_JOB_KIND = "battle.prepare"


def create_battle_entry_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognition: RecognitionService,
):

    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        timeout_seconds = _number(payload, "timeout_seconds", 180, 0.1, 600)
        poll_interval = _number(payload, "poll_interval", 0.5, 0, 10)
        action_wait_seconds = _number(payload, "action_wait_seconds", 0.5, 0, 10)
        preferred_apple = payload.get("apple", "gold")
        if preferred_apple not in {"gold", "silver", "blue", "copper"}:
            raise ValueError("apple must be gold, silver, blue, or copper.")
        recover_ap = payload.get("recover_ap", True)
        if not isinstance(recover_ap, bool):
            raise ValueError("recover_ap must be a boolean.")
        plan = script_data.get_setting_plan(setting_name.strip())
        random_touch = bool(plan["run"].get("random_touch"))
        random_time = configured_random_time(plan["run"].get("random_time", 0))
        server = str(plan["server"]).upper()
        template_roles = (
            ("battle_ready", f"battle/{server}/attack.png"),
            ("battle_ready", f"battle/{server}/phase_1.png"),
            ("apple_decide", f"battle/{server}/apple_decide.png"),
            ("apple_close", f"battle/{server}/apple_close.png"),
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
            if reconnect_if_present(
                context,
                device_service,
                recognition,
                screenshot,
                server,
                action_wait_seconds=action_wait_seconds,
                random_time=random_time,
                random_touch=random_touch,
            ):
                actions.append("reconnect")
                continue
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
            if matched_role == "apple_close" and matched_result is not None:
                if not recover_ap:
                    operation = device_service.tap(
                        *match_touch_point(matched_result, enabled=random_touch)
                    )
                    actions.append("apple_close")
                    context.emit(
                        "device_action",
                        "Closed AP recovery dialog.",
                        data={"role": "apple_close", "operation": operation.to_dict()},
                    )
                    return {
                        "setting_name": setting_name.strip(),
                        "ready": False,
                        "reason": "ap_empty",
                        "actions": actions,
                        "attempts": attempts,
                    }
                apple_match = _available_apple(
                    recognition,
                    screenshot,
                    server,
                    preferred=preferred_apple,
                    allow_other=plan["run"]["allow_other_apple"],
                )
                if apple_match is None:
                    raise RuntimeError("No available AP recovery item was recognized.")
                apple_name, apple_result = apple_match
                operation = device_service.tap(
                    *match_touch_point(apple_result, enabled=random_touch)
                )
                action = f"apple_{apple_name}"
                actions.append(action)
                context.emit(
                    "device_action",
                    "Selected AP recovery item.",
                    data={"role": action, "operation": operation.to_dict()},
                )
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue
            if matched_role is not None and matched_result is not None:
                operation = device_service.tap(
                    *match_touch_point(matched_result, enabled=random_touch)
                )
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
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue
            context.sleep(poll_interval)

        raise TimeoutError(
            f"Battle did not become ready within {timeout_seconds:.2f} seconds."
        )

    return handler


def register_battle_entry_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognition: RecognitionService,
) -> None:
    if job_manager.has_kind(BATTLE_PREPARE_JOB_KIND):
        return
    job_manager.register(
        BATTLE_PREPARE_JOB_KIND,
        create_battle_entry_handler(script_data, device_service, recognition),
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


def _available_apple(
    recognition: RecognitionService,
    screenshot: bytes,
    server: str,
    *,
    preferred: str,
    allow_other: bool,
):
    templates = {
        "gold": f"battle/{server}/gold.png",
        "silver": f"battle/{server}/silver.png",
        "blue": "battle/public/blue.png",
        "copper": f"battle/{server}/copper.png",
    }
    candidates = [preferred]
    if allow_other:
        candidates.extend(
            apple_name
            for apple_name in ("gold", "silver", "blue", "copper")
            if apple_name != preferred
        )
    for apple_name in candidates:
        template_path = templates[apple_name]
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
            return apple_name, result
    return None
