from __future__ import annotations

from time import monotonic
from typing import Any

from webapp.automation.interaction import (
    configured_random_time,
    randomized_touch_point,
    randomized_wait_seconds,
)
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.expball import ExpBallRecognizer
from webapp.services.script_data import ScriptDataService


EXPBALL_NAVIGATE_JOB_KIND = "event.expball.navigate"

_DESTINATION_STATES = {
    "summon": "summon_page",
    "sell": "sell_page",
    "storage": "storage_page",
}

_OPEN_MENU_POINT = (1183, 650)
_CLOSE_PAGE_POINT = (105, 43)
_CLOSE_DIALOG_POINT = (1243, 33)
_OPEN_FROM_FULL_POINT = (347, 477)
_PREVIOUS_SUMMON_BANNER_POINT = (30, 360)
_MENU_DESTINATIONS = {
    "summon": ("open_summon", (640, 615)),
    "sell": ("open_shop", (807, 598)),
    "storage": ("open_formation", (303, 597)),
}
_SUBMENU_DESTINATIONS = {
    ("sell", "sell_menu"): ("open_sell", (1127, 417)),
    ("storage", "storage_menu"): ("open_storage", (1127, 587)),
}


def create_expball_navigate_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = _setting_name(payload)
        destination = str(payload.get("destination") or "summon").strip().lower()
        if destination not in _DESTINATION_STATES:
            raise ValueError("destination must be summon, sell, or storage.")
        threshold = _number(payload, "threshold", 0.84, 0, 1)
        timeout_seconds = _number(payload, "timeout_seconds", 120, 0.1, 600)
        poll_interval = _number(payload, "poll_interval", 0.25, 0, 10)
        action_wait_seconds = _number(
            payload,
            "action_wait_seconds",
            0.4,
            0,
            30,
        )
        max_actions = _integer(payload, "max_actions", 30, 1, 100)
        max_idle_polls = _integer(payload, "max_idle_polls", 20, 1, 200)
        max_banner_switches = _integer(
            payload,
            "max_banner_switches",
            20,
            1,
            100,
        )
        plan = script_data.get_setting_plan(setting_name)
        server = str(plan["server"]).upper()
        run_options = plan.get("run", {})
        random_touch = bool(run_options.get("random_touch"))
        random_time = configured_random_time(run_options.get("random_time", 0))
        started = monotonic()
        attempts = 0
        idle_polls = 0
        banner_switches = 0
        menu_destination_selected = False
        actions: list[str] = []
        last_action_state: str | None = None
        last_report: dict[str, Any] | None = None

        def finish(
            *,
            completed: bool,
            reason: str,
            report: dict[str, Any],
        ) -> dict[str, Any]:
            context.checkpoint(
                "complete",
                progress=1.0,
                message=(
                    "Experience-material destination was reached."
                    if completed
                    else "Experience-material navigation stopped."
                ),
            )
            return {
                "setting_name": setting_name,
                "destination": destination,
                "completed": completed,
                "stopped": not completed,
                "reason": reason,
                "attempts": attempts,
                "actions": list(actions),
                "last_report": report,
            }

        while monotonic() - started <= timeout_seconds:
            attempts += 1
            context.checkpoint(
                "navigate_expball",
                progress=min((monotonic() - started) / timeout_seconds, 0.95),
            )
            report = recognizer.recognize_navigation(
                device_service.snapshot(),
                server,
                threshold=threshold,
            )
            last_report = report
            state = str(report.get("state") or "unknown")
            context.emit(
                "expball_navigation_state",
                "Experience-material navigation state was recognized.",
                data={"attempt": attempts, "destination": destination, **report},
            )

            if state == _DESTINATION_STATES[destination]:
                return finish(
                    completed=True,
                    reason="destination_reached",
                    report=report,
                )

            action: str | None = None
            point: tuple[int, int] | None = None
            if state == "menu_available":
                action, point = "open_menu", _OPEN_MENU_POINT
            elif state == "menu_expanded":
                action, point = _MENU_DESTINATIONS[destination]
                menu_destination_selected = True
            elif (destination, state) in _SUBMENU_DESTINATIONS:
                action, point = _SUBMENU_DESTINATIONS[(destination, state)]
            elif (
                destination == "summon"
                and menu_destination_selected
                and state == "summon_picker"
            ):
                if banner_switches >= max_banner_switches:
                    return finish(
                        completed=False,
                        reason="summon_banner_limit",
                        report=report,
                    )
                action, point = (
                    "previous_summon_banner",
                    _PREVIOUS_SUMMON_BANNER_POINT,
                )
                banner_switches += 1
            elif state == "inventory_full":
                if destination != "sell":
                    return finish(
                        completed=False,
                        reason="inventory_full",
                        report=report,
                    )
                action, point = "open_sell_from_full", _OPEN_FROM_FULL_POINT
            elif state == "dialog_close":
                action, point = "close_dialog", _CLOSE_DIALOG_POINT
            elif state in {
                "summon_picker",
                "back",
                "enhancement_back",
                "summon_page",
                "sell_page",
                "storage_page",
                "sell_menu",
                "storage_menu",
            }:
                action, point = "close_current_page", _CLOSE_PAGE_POINT

            action_state = f"{state}:{action}"
            repeatable = action == "previous_summon_banner"
            if (
                action is None
                or point is None
                or (action_state == last_action_state and not repeatable)
            ):
                idle_polls += 1
                if idle_polls >= max_idle_polls:
                    return finish(
                        completed=False,
                        reason="no_actionable_navigation_state",
                        report=report,
                    )
                context.sleep(randomized_wait_seconds(poll_interval, random_time))
                continue
            if len(actions) >= max_actions:
                return finish(
                    completed=False,
                    reason="action_limit",
                    report=report,
                )

            x, y = randomized_touch_point(point, enabled=random_touch)
            operation = device_service.tap(x, y)
            context.emit(
                "device_action",
                "Executed an experience-material navigation action.",
                data={
                    "role": action,
                    "state": state,
                    "destination": destination,
                    "operation": operation.to_dict(),
                },
            )
            if not operation.ok:
                return finish(
                    completed=False,
                    reason="device_action_failed",
                    report=report,
                )
            actions.append(action)
            idle_polls = 0
            last_action_state = action_state
            context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))

        raise TimeoutError(
            "Experience-material navigation did not finish within "
            f"{timeout_seconds:.2f} seconds. Last report: {last_report}"
        )

    return handler


def register_expball_navigate_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
) -> None:
    if job_manager.has_kind(EXPBALL_NAVIGATE_JOB_KIND):
        return
    job_manager.register(
        EXPBALL_NAVIGATE_JOB_KIND,
        create_expball_navigate_handler(
            script_data,
            device_service,
            recognizer,
        ),
        requires_device=True,
    )


def _setting_name(payload: dict[str, Any]) -> str:
    setting_name = payload.get("setting_name")
    if not isinstance(setting_name, str) or not setting_name.strip():
        raise ValueError("setting_name must be a non-empty string.")
    return setting_name.strip()


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


def _integer(
    payload: dict[str, Any],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer.")
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}.")
    return value
