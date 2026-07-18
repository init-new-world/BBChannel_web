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
from webapp.services.digdig import DigdigRecognizer
from webapp.services.script_data import ScriptDataService


DIGDIG_EXECUTE_JOB_KIND = "event.digdig.execute"
DIGDIG_INSPECT_JOB_KIND = "event.digdig.inspect"


def create_digdig_inspect_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: DigdigRecognizer,
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
            "inspect_digdig",
            progress=0.2,
            message="Inspecting the excavation board.",
        )
        report = recognizer.recognize(
            device_service.snapshot(),
            server,
            threshold=float(threshold),
        )
        context.emit(
            "digdig_state",
            "Excavation board state was inspected.",
            data=report,
        )
        context.checkpoint(
            "complete",
            progress=1.0,
            message="Excavation board inspection completed.",
        )
        return {"setting_name": normalized_name, **report}

    return handler


def register_digdig_inspect_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: DigdigRecognizer,
) -> None:
    if job_manager.has_kind(DIGDIG_INSPECT_JOB_KIND):
        return
    job_manager.register(
        DIGDIG_INSPECT_JOB_KIND,
        create_digdig_inspect_handler(
            script_data,
            device_service,
            recognizer,
        ),
        requires_device=True,
    )


def create_digdig_execute_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: DigdigRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        normalized_name = setting_name.strip()
        threshold = _number(payload, "threshold", 0.82, 0, 1)
        timeout_seconds = _number(payload, "timeout_seconds", 30, 0.1, 300)
        poll_interval = _number(payload, "poll_interval", 0.5, 0, 10)
        action_wait_seconds = _number(
            payload,
            "action_wait_seconds",
            1,
            0,
            30,
        )
        max_idle_polls = _integer(payload, "max_idle_polls", 5, 1, 100)
        plan = script_data.get_setting_plan(normalized_name)
        server = str(plan["server"]).upper()
        run_options = plan.get("run", {})
        random_touch = bool(run_options.get("random_touch"))
        random_time = configured_random_time(run_options.get("random_time", 0))
        started = monotonic()
        attempts = 0
        actions: list[str] = []
        phase = "execute"
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
                    "Excavation selection executed."
                    if completed
                    else "Excavation execution stopped."
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

        while monotonic() - started <= timeout_seconds:
            attempts += 1
            context.checkpoint(
                f"execute_digdig_{phase}",
                progress=min((monotonic() - started) / timeout_seconds, 0.95),
            )
            report = recognizer.recognize(
                device_service.snapshot(),
                server,
                threshold=threshold,
            )
            last_report = report
            context.emit(
                "digdig_state",
                "Excavation execution state was recognized.",
                data={"attempt": attempts, "phase": phase, **report},
            )
            state = str(report.get("state") or "unknown")
            status = str(report.get("status") or "unknown")
            action = report.get("recommended_action")

            if phase == "wait_result":
                if state in {"digResult", "reward"}:
                    return finish(
                        completed=True,
                        stopped=False,
                        reason="dig_result" if state == "digResult" else "reward",
                        report=report,
                    )
                if state in {"needConfirm", "checkmark"}:
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="confirmation_required",
                        report=report,
                    )
                idle_polls += 1
                if idle_polls >= max_idle_polls:
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="result_not_detected",
                        report=report,
                    )
                context.sleep(randomized_wait_seconds(poll_interval, random_time))
                continue

            if state != "execute" or status != "actionable" or action != "execute_dig":
                return finish(
                    completed=False,
                    stopped=True,
                    reason="no_actionable_selection",
                    report=report,
                )
            primary = next(
                (
                    match
                    for match in report.get("matches", [])
                    if match.get("name") == "execute"
                ),
                None,
            )
            if not isinstance(primary, dict):
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
            context.emit(
                "device_action",
                "Executed the current excavation selection.",
                data={"role": action, "operation": operation.to_dict()},
            )
            if not operation.ok:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="device_action_failed",
                    report=report,
                )
            actions.append(action)
            phase = "wait_result"
            context.sleep(
                randomized_wait_seconds(action_wait_seconds, random_time)
            )

        raise TimeoutError(
            "Excavation execution did not finish within "
            f"{timeout_seconds:.2f} seconds. Last report: {last_report}"
        )

    return handler


def register_digdig_execute_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: DigdigRecognizer,
) -> None:
    if job_manager.has_kind(DIGDIG_EXECUTE_JOB_KIND):
        return
    job_manager.register(
        DIGDIG_EXECUTE_JOB_KIND,
        create_digdig_execute_handler(
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
