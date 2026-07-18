from __future__ import annotations

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


EXPBALL_SELL_JOB_KIND = "event.expball.sell"


def create_expball_sell_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        normalized_name = setting_name.strip()
        threshold = _number(payload, "threshold", 0.84, 0, 1)
        action_wait_seconds = _number(
            payload,
            "action_wait_seconds",
            1,
            0,
            30,
        )
        plan = script_data.get_setting_plan(normalized_name)
        server = str(plan["server"]).upper()
        run_options = plan.get("run", {})
        random_touch = bool(run_options.get("random_touch"))
        random_time = configured_random_time(run_options.get("random_time", 0))
        attempts = 0
        actions: list[str] = []

        def inspect(phase: str) -> dict[str, Any]:
            nonlocal attempts
            attempts += 1
            context.checkpoint(f"sell_expball_{phase}", progress=attempts / 4)
            report = recognizer.recognize(
                device_service.snapshot(),
                server,
                threshold=threshold,
            )
            context.emit(
                "expball_state",
                "Experience-material sale state was recognized.",
                data={"attempt": attempts, "phase": phase, **report},
            )
            return report

        def finish(
            *,
            completed: bool,
            stopped: bool,
            reason: str,
            report: dict[str, Any],
        ) -> dict[str, Any]:
            context.checkpoint(
                "complete",
                progress=1.0,
                message=(
                    "Current experience-material selection was sold."
                    if completed
                    else "Experience-material sale stopped."
                ),
            )
            return {
                "setting_name": normalized_name,
                "completed": completed,
                "stopped": stopped,
                "reason": reason,
                "attempts": attempts,
                "actions": list(actions),
                "last_report": report,
            }

        def tap_match(
            report: dict[str, Any],
            name: str,
            action: str,
        ) -> bool:
            match = next(
                (
                    candidate
                    for candidate in report.get("matches", [])
                    if candidate.get("name") == name
                ),
                None,
            )
            if not isinstance(match, dict):
                return False
            center = match.get("center")
            if not isinstance(center, list) or len(center) != 2:
                return False
            x, y = randomized_touch_point(
                center,
                enabled=random_touch,
                size=match.get("size"),
            )
            operation = device_service.tap(x, y)
            context.emit(
                "device_action",
                "Executed an experience-material sale action.",
                data={"role": action, "operation": operation.to_dict()},
            )
            if not operation.ok:
                return False
            actions.append(action)
            context.sleep(
                randomized_wait_seconds(action_wait_seconds, random_time)
            )
            return True

        report = inspect("execute")
        if report.get("flow") != "sell":
            return finish(
                completed=False,
                stopped=True,
                reason="outside_sell_flow",
                report=report,
            )
        initial_match_names = {
            match.get("name")
            for match in report.get("matches", [])
            if isinstance(match, dict)
        }
        if (
            report.get("status") != "actionable"
            or "destroy" not in initial_match_names
        ):
            return finish(
                completed=False,
                stopped=True,
                reason="no_actionable_selection",
                report=report,
            )
        if not tap_match(report, "destroy", "execute_sell"):
            return finish(
                completed=False,
                stopped=True,
                reason="device_action_failed",
                report=report,
            )

        report = inspect("confirm")
        match_names = {
            match.get("name")
            for match in report.get("matches", [])
            if isinstance(match, dict)
        }
        if "qpfull" in match_names:
            return finish(
                completed=False,
                stopped=True,
                reason="qp_full",
                report=report,
            )
        if report.get("flow") != "confirmation" or "sure" not in match_names:
            return finish(
                completed=False,
                stopped=True,
                reason="confirmation_not_detected",
                report=report,
            )
        if not tap_match(report, "sure", "confirm_sell"):
            return finish(
                completed=False,
                stopped=True,
                reason="device_action_failed",
                report=report,
            )

        report = inspect("verify")
        if report.get("flow") == "sell" or (
            report.get("status") == "blocked"
            and report.get("reason") == "no_matching_target"
        ):
            return finish(
                completed=True,
                stopped=False,
                reason="sold",
                report=report,
            )
        return finish(
            completed=False,
            stopped=True,
            reason="sale_result_not_detected",
            report=report,
        )

    return handler


def register_expball_sell_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
) -> None:
    if job_manager.has_kind(EXPBALL_SELL_JOB_KIND):
        return
    job_manager.register(
        EXPBALL_SELL_JOB_KIND,
        create_expball_sell_handler(
            script_data,
            device_service,
            recognizer,
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
