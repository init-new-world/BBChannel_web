from __future__ import annotations

from time import monotonic
from typing import Any

from webapp.automation.interaction import (
    configured_random_time,
    match_touch_point,
    randomized_touch_point,
    randomized_wait_seconds,
)
from webapp.automation.network import reconnect_if_present
from webapp.core.errors import AppError, ErrorCode
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.recognition import RecognitionService
from webapp.services.script_data import ScriptDataService
from webapp.services.team import TeamRecognizer


BATTLE_PREPARE_JOB_KIND = "battle.prepare"
CRAWL_TOWER_TRIGGER_POINT = (297, 677)
CRAWL_TOWER_TRIGGER_SIZE = (60, 47)


def create_battle_entry_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognition: RecognitionService,
    team_recognizer: TeamRecognizer | None = None,
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
        team_check_mode = payload.get("team_check_mode", "warn")
        if team_check_mode not in {"off", "warn", "strict"}:
            raise ValueError("team_check_mode must be off, warn, or strict.")
        crawl_tower = payload.get("crawl_tower", False)
        if not isinstance(crawl_tower, bool):
            raise ValueError("crawl_tower must be a boolean.")
        plan = script_data.get_setting_plan(setting_name.strip())
        random_touch = bool(plan["run"].get("random_touch"))
        random_time = configured_random_time(plan["run"].get("random_time", 0))
        server = str(plan["server"]).upper()
        template_roles = (
            ("battle_ready", f"battle/{server}/attack.png", 0.85),
            ("battle_ready", f"battle/{server}/phase_1.png", 0.95),
            ("apple_decide", f"battle/{server}/apple_decide.png", 0.85),
            ("apple_close", f"battle/{server}/apple_close.png", 0.85),
            ("auto_formation", f"battle/CrawlTower/{server}/zdbc.png", 0.85),
            ("team_decide", f"battle/{server}/teamDecide.png", 0.85),
            ("start_task", f"battle/{server}/start_task.png", 0.8),
            ("start_battle", f"battle/{server}/start_battle.png", 0.85),
        )
        started = monotonic()
        attempts = 0
        actions: list[str] = []
        team_verification = None
        auto_formation_confirmed = False

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
            for role, template_path, role_threshold in template_roles:
                try:
                    result = recognition.match_template(
                        screenshot,
                        template_path,
                        threshold=role_threshold,
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
                    "team_verification": team_verification,
                }
            if (
                matched_role == "team_decide"
                and crawl_tower
                and not auto_formation_confirmed
            ):
                touch_x, touch_y = randomized_touch_point(
                    CRAWL_TOWER_TRIGGER_POINT,
                    enabled=random_touch,
                    size=CRAWL_TOWER_TRIGGER_SIZE,
                )
                operation = device_service.tap(touch_x, touch_y)
                actions.append("auto_formation_trigger")
                context.emit(
                    "device_action",
                    "Opened CrawlTower auto-formation dialog.",
                    data={
                        "role": "auto_formation_trigger",
                        "x": CRAWL_TOWER_TRIGGER_POINT[0],
                        "y": CRAWL_TOWER_TRIGGER_POINT[1],
                        "operation": operation.to_dict(),
                    },
                )
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue
            if (
                matched_role == "team_decide"
                and not crawl_tower
                and team_recognizer is not None
                and team_check_mode != "off"
                and team_verification is None
            ):
                team_verification = team_recognizer.recognize(screenshot, plan)
                context.emit(
                    "team_verification",
                    "Battle team verification completed.",
                    data=team_verification,
                )
                if not team_verification["ok"] and team_check_mode == "strict":
                    return {
                        "setting_name": setting_name.strip(),
                        "ready": False,
                        "reason": "team_mismatch",
                        "actions": actions,
                        "attempts": attempts,
                        "team_verification": team_verification,
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
                    device_service=device_service,
                    context=context,
                    wait_seconds=randomized_wait_seconds(action_wait_seconds, random_time),
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
                if matched_role == "auto_formation":
                    auto_formation_confirmed = True
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
    team_recognizer: TeamRecognizer | None = None,
) -> None:
    if job_manager.has_kind(BATTLE_PREPARE_JOB_KIND):
        return
    job_manager.register(
        BATTLE_PREPARE_JOB_KIND,
        create_battle_entry_handler(
            script_data,
            device_service,
            recognition,
            team_recognizer,
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


APPLE_SCROLL_DOWN = (1014, 453, 1014, 620, 200)
APPLE_SCROLL_UP = (1014, 267, 1014, 60, 200)


def _available_apple(
    recognition: RecognitionService,
    screenshot: bytes,
    server: str,
    *,
    preferred: str,
    allow_other: bool,
    device_service: DeviceService | None = None,
    context: RunContext | None = None,
    wait_seconds: float = 0.0,
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
    current_screenshot = screenshot
    current_scroll = "top"
    for apple_name in candidates:
        template_path = templates[apple_name]
        result = _match_apple_template(recognition, current_screenshot, template_path)
        if result is None:
            continue
        if not result.matched and device_service is not None and hasattr(device_service, "swipe"):
            target_scroll = "bottom" if apple_name in {"blue", "copper"} else "top"
            if target_scroll != current_scroll:
                swipe_args = APPLE_SCROLL_DOWN if target_scroll == "bottom" else APPLE_SCROLL_UP
                try:
                    operation = device_service.swipe(*swipe_args)
                except AppError:
                    operation = None
                if operation is not None:
                    current_scroll = target_scroll
                    if context is not None:
                        context.emit(
                            "device_action",
                            "Scrolled AP recovery list.",
                            data={
                                "role": f"apple_scroll_{target_scroll}",
                                "apple": apple_name,
                                "operation": operation.to_dict(),
                            },
                        )
                        if wait_seconds > 0:
                            context.sleep(wait_seconds)
                    current_screenshot = device_service.snapshot()
                    result = _match_apple_template(recognition, current_screenshot, template_path)
                    if result is None:
                        continue
        if result.matched and _apple_color_available(
            recognition,
            current_screenshot,
            template_path,
            result,
        ):
            return apple_name, result
    return None


def _match_apple_template(
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


def _apple_color_available(
    recognition: RecognitionService,
    screenshot: bytes,
    template_path: str,
    result: Any,
) -> bool:
    if getattr(result, "color_available", None) is False:
        return False
    color_check = getattr(recognition, "check_color_half_mode", None)
    if callable(color_check):
        try:
            return bool(color_check(screenshot, template_path, result))
        except AppError:
            return True
    return True
