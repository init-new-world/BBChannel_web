from __future__ import annotations

from time import monotonic
from typing import Any

from webapp.automation.interaction import (
    configured_random_time,
    match_touch_point,
    randomized_touch_point,
    randomized_wait_seconds,
)
from webapp.automation.run import StageHandler
from webapp.core.errors import AppError, ErrorCode
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.recognition import RecognitionService
from webapp.services.script_data import ScriptDataService


BATTLE_RESTART_GAME_JOB_KIND = "battle.restart-game"


def create_recovery_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    detect_stage: StageHandler,
    recognition: RecognitionService | None = None,
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
        action_wait_seconds = _number(payload, "action_wait_seconds", 1, 0, 30)
        random_time = configured_random_time(plan["run"].get("random_time", 0))
        random_touch = bool(plan["run"].get("random_touch"))
        server = str(plan["server"]).upper()

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
        actions: list[str] = []
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
                    "actions": actions,
                    "operation": operation.to_dict(),
                }
            if recognition is not None:
                screenshot = device_service.snapshot()
                action = _navigate_startup_page(
                    context,
                    device_service,
                    recognition,
                    screenshot,
                    server,
                    random_touch=random_touch,
                )
                if action is not None:
                    actions.append(action)
                    context.sleep(
                        randomized_wait_seconds(action_wait_seconds, random_time)
                    )
                    continue
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
    recognition: RecognitionService | None = None,
) -> None:
    if job_manager.has_kind(BATTLE_RESTART_GAME_JOB_KIND):
        return
    job_manager.register(
        BATTLE_RESTART_GAME_JOB_KIND,
        create_recovery_handler(
            script_data,
            device_service,
            detect_stage,
            recognition,
        ),
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


def _navigate_startup_page(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    screenshot: bytes,
    server: str,
    *,
    random_touch: bool,
) -> str | None:
    action: str | None = None
    point: tuple[int, int] | None = None

    reconnect = _match_optional(
        recognition,
        screenshot,
        f"battle/{server}/reconnect.png",
    )
    if reconnect is not None and reconnect.matched:
        action = "reconnect"
        point = match_touch_point(reconnect, enabled=random_touch)

    if action is None:
        terms = _match_optional(
            recognition,
            screenshot,
            f"crushRestart/{server}/yhxy.png",
        )
        if terms is not None and terms.matched:
            left, top = terms.top_left
            width, height = terms.size
            action = "accept_terms"
            point = randomized_touch_point(
                (left + round(width * 0.75), top + round(height * 0.5)),
                enabled=random_touch,
            )

    if action is None:
        announcement = _match_optional(
            recognition,
            screenshot,
            f"crushRestart/{server}/yxgg.png",
        )
        if announcement is not None and announcement.matched:
            close_button = _match_optional(
                recognition,
                screenshot,
                f"battle/{server}/x.png",
            )
            if close_button is not None and close_button.matched:
                action = "close_announcement"
                point = match_touch_point(close_button, enabled=random_touch)

    if action is None:
        enter_battle = _match_optional(
            recognition,
            screenshot,
            f"crushRestart/{server}/enterBattle.png",
        )
        if enter_battle is not None and enter_battle.matched:
            action = "enter_battle"
            point = match_touch_point(enter_battle, enabled=random_touch)

    if action is None:
        title_menu = _match_optional(
            recognition,
            screenshot,
            f"crushRestart/{server}/menu.png",
        )
        if title_menu is not None and title_menu.matched:
            action = "title_start"
            point = randomized_touch_point((640, 360), enabled=random_touch)

    if action is None or point is None:
        return None
    operation = device_service.tap(*point)
    context.emit(
        "device_action",
        "Advanced game restart navigation.",
        data={"role": action, "operation": operation.to_dict()},
    )
    return action


def _match_optional(
    recognition: RecognitionService,
    screenshot: bytes,
    template_path: str,
):
    try:
        return recognition.match_template(
            screenshot,
            template_path,
            threshold=0.85,
            scales=(1.0, 0.75, 2 / 3, 0.5),
        )
    except AppError as exc:
        if exc.code == ErrorCode.TEMPLATE_NOT_FOUND:
            return None
        raise
