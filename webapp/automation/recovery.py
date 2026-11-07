from __future__ import annotations

from time import monotonic
from typing import Any

import cv2
import numpy as np

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
ANNOUNCEMENT_CLOSE_POINT = (1243, 33)
WAIT_MENU_POINT = (1183, 707)
TITLE_START_POINT = (640, 360)


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
        tap_wait_menu = payload.get("tap_wait_menu", False)
        if not isinstance(tap_wait_menu, bool):
            raise ValueError("tap_wait_menu must be a boolean.")
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
                    tap_wait_menu=tap_wait_menu,
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
    tap_wait_menu: bool = False,
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
        dialog_bounds = (
            _detect_white_dialog_bounds(screenshot) if server == "CH" else None
        )
        terms = _match_optional(
            recognition,
            screenshot,
            f"crushRestart/{server}/yhxy.png",
            threshold=0.7 if dialog_bounds is not None else 0.85,
            roi=dialog_bounds,
        )
        if terms is not None and terms.matched:
            action = "accept_terms"
            if dialog_bounds is not None:
                dialog_x, dialog_y, dialog_w, dialog_h = dialog_bounds
                confirm_point = (
                    round(dialog_x + 600 * dialog_w / 980),
                    round(dialog_y + 530 * dialog_h / 620),
                )
            else:
                left, top = terms.top_left
                width, height = terms.size
                confirm_point = (
                    left + round(width * 0.75),
                    top + round(height * 0.5),
                )
            point = randomized_touch_point(
                confirm_point,
                enabled=random_touch,
            )

    if action is None:
        announcement = _match_optional(
            recognition,
            screenshot,
            f"crushRestart/{server}/yxgg.png",
        )
        if announcement is not None and announcement.matched:
            action = "close_announcement"
            close_button = _match_optional(
                recognition,
                screenshot,
                f"battle/{server}/x.png",
            )
            if close_button is not None and close_button.matched:
                point = match_touch_point(close_button, enabled=random_touch)
            else:
                point = randomized_touch_point(
                    ANNOUNCEMENT_CLOSE_POINT,
                    enabled=random_touch,
                )

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
            point = randomized_touch_point(
                TITLE_START_POINT,
                enabled=random_touch,
            )

    if action is None and tap_wait_menu:
        action = "wait_menu"
        point = randomized_touch_point(WAIT_MENU_POINT, enabled=random_touch)

    if action is None or point is None:
        return None
    operation = device_service.tap(*point)
    context.emit(
        "device_action",
        "Advanced game restart navigation.",
        data={"role": action, "operation": operation.to_dict()},
    )
    return action


def _detect_white_dialog_bounds(
    screenshot: bytes,
) -> tuple[int, int, int, int] | None:
    if not screenshot:
        return None
    buffer = np.frombuffer(screenshot, dtype=np.uint8)
    decoded = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if decoded is None:
        return None
    gray = cv2.cvtColor(decoded, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(
        thresh,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    x, y, width, height = cv2.boundingRect(largest)
    if width < 200 or height < 120:
        return None
    return int(x), int(y), int(width), int(height)


def _match_optional(
    recognition: RecognitionService,
    screenshot: bytes,
    template_path: str,
    *,
    threshold: float = 0.85,
    roi: tuple[int, int, int, int] | None = None,
):
    options: dict[str, Any] = {
        "threshold": threshold,
        "scales": (1.0, 0.75, 2 / 3, 0.5),
    }
    if roi is not None:
        options["roi"] = roi
    try:
        return recognition.match_template(
            screenshot,
            template_path,
            **options,
        )
    except AppError as exc:
        if exc.code == ErrorCode.TEMPLATE_NOT_FOUND:
            return None
        raise
