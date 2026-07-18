from __future__ import annotations

from time import monotonic
from typing import Any

from webapp.automation.interaction import (
    configured_random_time,
    randomized_touch_point,
    randomized_wait_seconds,
)
from webapp.runtime import JobManager, RunContext
from webapp.services.chocolate import ChocolateRecognizer
from webapp.services.devices import DeviceService
from webapp.services.script_data import ScriptDataService


CHOCOLATE_INSPECT_JOB_KIND = "event.chocolate.inspect"
CHOCOLATE_RUN_JOB_KIND = "event.chocolate.run"


def create_chocolate_inspect_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ChocolateRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        threshold = payload.get("threshold", 0.82)
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not 0 <= threshold <= 1
        ):
            raise ValueError("threshold must be between 0 and 1.")

        normalized_name = setting_name.strip()
        server = str(script_data.get_setting_plan(normalized_name)["server"]).upper()
        context.checkpoint(
            "inspect_chocolate",
            progress=0.2,
            message="Inspecting the Valentine event screen.",
        )
        report = recognizer.recognize(
            device_service.snapshot(),
            server,
            threshold=float(threshold),
        )
        context.emit(
            "chocolate_state",
            "Valentine event state was inspected.",
            data=report,
        )
        context.checkpoint(
            "complete",
            progress=1.0,
            message="Valentine event inspection completed.",
        )
        return {"setting_name": normalized_name, **report}

    return handler


def register_chocolate_inspect_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ChocolateRecognizer,
) -> None:
    if job_manager.has_kind(CHOCOLATE_INSPECT_JOB_KIND):
        return
    job_manager.register(
        CHOCOLATE_INSPECT_JOB_KIND,
        create_chocolate_inspect_handler(
            script_data,
            device_service,
            recognizer,
        ),
        requires_device=True,
    )


def create_chocolate_run_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ChocolateRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        normalized_name = setting_name.strip()
        threshold = _number(payload, "threshold", 0.82, 0, 1)
        timeout_seconds = _number(payload, "timeout_seconds", 300, 0.1, 3600)
        poll_interval = _number(payload, "poll_interval", 0.5, 0, 10)
        action_wait_seconds = _number(
            payload,
            "action_wait_seconds",
            1,
            0,
            30,
        )
        max_actions = _integer(payload, "max_actions", 200, 1, 10000)
        max_same_state = _integer(payload, "max_same_state", 3, 1, 20)
        max_idle_polls = _integer(payload, "max_idle_polls", 3, 1, 100)
        plan = script_data.get_setting_plan(normalized_name)
        server = str(plan["server"]).upper()
        run_options = plan.get("run", {})
        random_touch = bool(run_options.get("random_touch"))
        random_time = configured_random_time(run_options.get("random_time", 0))
        started = monotonic()
        attempts = 0
        actions: list[str] = []
        last_state = None
        same_state_count = 0
        idle_polls = 0
        last_report: dict[str, Any] | None = None

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
                    "Valentine event automation completed."
                    if completed
                    else "Valentine event automation stopped."
                ),
            )
            return _run_result(
                normalized_name,
                completed=completed,
                stopped=stopped,
                reason=reason,
                attempts=attempts,
                actions=actions,
                report=report,
            )

        while monotonic() - started <= timeout_seconds:
            attempts += 1
            context.checkpoint(
                "run_chocolate",
                progress=min((monotonic() - started) / timeout_seconds, 0.95),
            )
            report = recognizer.recognize(
                device_service.snapshot(),
                server,
                threshold=threshold,
            )
            last_report = report
            context.emit(
                "chocolate_state",
                "Valentine event state was recognized.",
                data={"attempt": attempts, **report},
            )
            state = str(report.get("state") or "unknown")
            status = str(report.get("status") or "unknown")
            reason = report.get("reason")

            if status == "blocked":
                completed = reason == "materials_exhausted"
                return finish(
                    completed=completed,
                    stopped=not completed,
                    reason=str(reason or "blocked"),
                    report=report,
                )

            if status != "actionable":
                idle_polls += 1
                if idle_polls >= max_idle_polls:
                    return finish(
                        completed=state == "receive_all_off",
                        stopped=state != "receive_all_off",
                        reason=(
                            "no_claimable_rewards"
                            if state == "receive_all_off"
                            else "no_actionable_state"
                        ),
                        report=report,
                    )
                context.sleep(
                    randomized_wait_seconds(poll_interval, random_time)
                )
                continue

            idle_polls = 0
            if state == last_state:
                same_state_count += 1
            else:
                last_state = state
                same_state_count = 1
            if same_state_count > max_same_state:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="state_stalled",
                    report=report,
                )
            if len(actions) >= max_actions:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="navigation_limit",
                    report=report,
                )

            action = report.get("recommended_action")
            primary = next(
                (
                    match
                    for match in report.get("matches", [])
                    if match.get("name") == state
                ),
                None,
            )
            if not isinstance(action, str) or not isinstance(primary, dict):
                return finish(
                    completed=False,
                    stopped=True,
                    reason="invalid_recognition_result",
                    report=report,
                )
            center = primary.get("center")
            if not isinstance(center, list) or len(center) != 2:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="invalid_recognition_result",
                    report=report,
                )
            x, y = randomized_touch_point(
                center,
                enabled=random_touch,
                size=primary.get("size"),
            )
            operation = device_service.tap(x, y)
            actions.append(action)
            context.emit(
                "device_action",
                "Executed a Valentine event action.",
                data={
                    "role": action,
                    "state": state,
                    "operation": operation.to_dict(),
                },
            )
            context.sleep(
                randomized_wait_seconds(action_wait_seconds, random_time)
            )

        raise TimeoutError(
            "Valentine event automation did not finish within "
            f"{timeout_seconds:.2f} seconds. Last report: {last_report}"
        )

    return handler


def register_chocolate_run_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ChocolateRecognizer,
) -> None:
    if job_manager.has_kind(CHOCOLATE_RUN_JOB_KIND):
        return
    job_manager.register(
        CHOCOLATE_RUN_JOB_KIND,
        create_chocolate_run_handler(
            script_data,
            device_service,
            recognizer,
        ),
        requires_device=True,
    )


def _run_result(
    setting_name: str,
    *,
    completed: bool,
    stopped: bool,
    reason: str,
    attempts: int,
    actions: list[str],
    report: dict[str, Any],
) -> dict[str, Any]:
    return {
        "setting_name": setting_name,
        "completed": completed,
        "stopped": stopped,
        "reason": reason,
        "attempts": attempts,
        "actions": list(actions),
        "last_report": report,
    }


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
