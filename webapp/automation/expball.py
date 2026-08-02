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


EXPBALL_INSPECT_JOB_KIND = "event.expball.inspect"
EXPBALL_STORAGE_JOB_KIND = "event.expball.storage"
EXPBALL_SUMMON_JOB_KIND = "event.expball.summon"
_SUMMON_REQUEST_ACTIONS = {"summon_free_ten", "summon_ten"}


def create_expball_inspect_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        threshold = payload.get("threshold", 0.84)
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not 0 <= threshold <= 1
        ):
            raise ValueError("threshold must be between 0 and 1.")

        normalized_name = setting_name.strip()
        server = str(script_data.get_setting_plan(normalized_name)["server"]).upper()
        context.checkpoint(
            "inspect_expball",
            progress=0.2,
            message="Inspecting the experience-material workflow.",
        )
        report = recognizer.recognize(
            device_service.snapshot(),
            server,
            threshold=float(threshold),
        )
        context.emit(
            "expball_state",
            "Experience-material workflow state was inspected.",
            data=report,
        )
        context.checkpoint(
            "complete",
            progress=1.0,
            message="Experience-material workflow inspection completed.",
        )
        return {"setting_name": normalized_name, **report}

    return handler


def register_expball_inspect_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
) -> None:
    if job_manager.has_kind(EXPBALL_INSPECT_JOB_KIND):
        return
    job_manager.register(
        EXPBALL_INSPECT_JOB_KIND,
        create_expball_inspect_handler(
            script_data,
            device_service,
            recognizer,
        ),
        requires_device=True,
    )


def create_expball_summon_handler(
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
        timeout_seconds = _number(payload, "timeout_seconds", 600, 0.1, 3600)
        poll_interval = _number(payload, "poll_interval", 0.5, 0, 10)
        action_wait_seconds = _number(
            payload,
            "action_wait_seconds",
            1,
            0,
            30,
        )
        max_summons = _integer(payload, "max_summons", 10, 1, 10000)
        max_same_state = _integer(
            payload,
            "max_same_state",
            min(max_summons, 20),
            1,
            20,
        )
        max_idle_polls = _integer(payload, "max_idle_polls", 3, 1, 100)
        plan = script_data.get_setting_plan(normalized_name)
        server = str(plan["server"]).upper()
        run_options = plan.get("run", {})
        random_touch = bool(run_options.get("random_touch"))
        random_time = configured_random_time(run_options.get("random_time", 0))
        started = monotonic()
        attempts = 0
        summons = 0
        actions: list[str] = []
        phase = "request"
        pending_free_summon = False
        result_counted = False
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
                    "Friendship-point summoning completed."
                    if completed
                    else "Friendship-point summoning stopped."
                ),
            )
            return _summon_result(
                normalized_name,
                completed=completed,
                stopped=stopped,
                reason=reason,
                attempts=attempts,
                summons=summons,
                actions=actions,
                report=report,
            )

        def tap_match(
            report: dict[str, Any],
            name: str,
            role: str,
        ) -> bool:
            target = next(
                (
                    match
                    for match in report.get("matches", [])
                    if isinstance(match, dict) and match.get("name") == name
                ),
                None,
            )
            if not isinstance(target, dict):
                return False
            center = target.get("center")
            if not isinstance(center, list) or len(center) != 2:
                return False
            x, y = randomized_touch_point(
                center,
                enabled=random_touch,
                size=target.get("size"),
            )
            operation = device_service.tap(x, y)
            context.emit(
                "device_action",
                "Executed a friendship-point summon action.",
                data={
                    "role": role,
                    "state": report.get("state"),
                    "phase": phase,
                    "operation": operation.to_dict(),
                },
            )
            if not operation.ok:
                return False
            actions.append(role)
            context.sleep(
                randomized_wait_seconds(action_wait_seconds, random_time)
            )
            return True

        while monotonic() - started <= timeout_seconds:
            attempts += 1
            context.checkpoint(
                "summon_expball",
                progress=min((monotonic() - started) / timeout_seconds, 0.95),
            )
            report = recognizer.recognize(
                device_service.snapshot(),
                server,
                threshold=threshold,
            )
            last_report = report
            context.emit(
                "expball_state",
                "Friendship-point summon state was recognized.",
                data={"attempt": attempts, "phase": phase, **report},
            )
            state = str(report.get("state") or "unknown")
            flow = str(report.get("flow") or "unknown")
            status = str(report.get("status") or "unknown")
            action = report.get("recommended_action")
            matches = {
                match.get("name"): match
                for match in report.get("matches", [])
                if isinstance(match, dict) and isinstance(match.get("name"), str)
            }

            if "boxfull" in matches or action == "handle_full_box":
                return finish(
                    completed=False,
                    stopped=True,
                    reason="box_full",
                    report=report,
                )
            if status == "blocked":
                return finish(
                    completed=False,
                    stopped=True,
                    reason=str(report.get("reason") or "blocked"),
                    report=report,
                )
            action_state = (phase, state)
            if action_state == last_state:
                same_state_count += 1
            else:
                last_state = action_state
                same_state_count = 1
            if same_state_count > max_same_state:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="state_stalled",
                    report=report,
                )
            acted = False
            if phase == "request":
                if flow not in {"summon", "unknown"}:
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="outside_summon_flow",
                        report=report,
                    )
                if "bianhuan" in matches and "close" in matches:
                    if not tap_match(report, "close", "recover_summon_page"):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    acted = True
                elif (
                    isinstance(action, str)
                    and action in _SUMMON_REQUEST_ACTIONS
                    and state in matches
                ):
                    if not tap_match(report, state, action):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    pending_free_summon = action == "summon_free_ten"
                    result_counted = False
                    phase = "confirm"
                    acted = True
            elif phase == "confirm":
                if "decide" in matches:
                    if not tap_match(report, "decide", "confirm_summon"):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    phase = "result"
                    acted = True
            elif phase == "result" and "bianhuan" in matches:
                if not result_counted:
                    summons += 1
                    result_counted = True
                if pending_free_summon:
                    if "close" in matches:
                        if not tap_match(
                            report,
                            "close",
                            "close_summon_result",
                        ):
                            return finish(
                                completed=False,
                                stopped=True,
                                reason="device_action_failed",
                                report=report,
                            )
                        phase = "request"
                        pending_free_summon = False
                        result_counted = False
                        acted = True
                        if summons >= max_summons:
                            return finish(
                                completed=True,
                                stopped=False,
                                reason="summon_limit",
                                report=report,
                            )
                elif summons >= max_summons:
                    return finish(
                        completed=True,
                        stopped=False,
                        reason="summon_limit",
                        report=report,
                    )
                elif "again10_1" in matches or "again10" in matches:
                    target_name = (
                        "again10_1" if "again10_1" in matches else "again10"
                    )
                    if not tap_match(report, target_name, "summon_again"):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    phase = "confirm"
                    result_counted = False
                    acted = True
                elif "again10_0" in matches:
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="summon_unavailable",
                        report=report,
                    )

            if acted:
                idle_polls = 0
                continue
            idle_polls += 1
            if idle_polls >= max_idle_polls:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="no_actionable_summon",
                    report=report,
                )
            context.sleep(randomized_wait_seconds(poll_interval, random_time))

        raise TimeoutError(
            "Friendship-point summoning did not finish within "
            f"{timeout_seconds:.2f} seconds. Last report: {last_report}"
        )

    return handler


def register_expball_summon_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
) -> None:
    if job_manager.has_kind(EXPBALL_SUMMON_JOB_KIND):
        return
    job_manager.register(
        EXPBALL_SUMMON_JOB_KIND,
        create_expball_summon_handler(
            script_data,
            device_service,
            recognizer,
        ),
        requires_device=True,
    )


def create_expball_storage_handler(
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
        timeout_seconds = _number(payload, "timeout_seconds", 120, 0.1, 3600)
        poll_interval = _number(payload, "poll_interval", 0.5, 0, 10)
        action_wait_seconds = _number(
            payload,
            "action_wait_seconds",
            1,
            0,
            30,
        )
        max_idle_polls = _integer(payload, "max_idle_polls", 3, 1, 100)
        plan = script_data.get_setting_plan(normalized_name)
        server = str(plan["server"]).upper()
        run_options = plan.get("run", {})
        random_touch = bool(run_options.get("random_touch"))
        random_time = configured_random_time(run_options.get("random_time", 0))
        started = monotonic()
        attempts = 0
        actions: list[str] = []
        phase = "submit"
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
                    "Experience materials were stored."
                    if completed
                    else "Experience-material storage stopped."
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
                f"store_expball_{phase}",
                progress=min((monotonic() - started) / timeout_seconds, 0.95),
            )
            report = recognizer.recognize(
                device_service.snapshot(),
                server,
                threshold=threshold,
            )
            last_report = report
            context.emit(
                "expball_state",
                "Experience-material storage state was recognized.",
                data={"attempt": attempts, "phase": phase, **report},
            )
            status = str(report.get("status") or "unknown")
            flow = str(report.get("flow") or "unknown")
            matches = {
                match.get("name"): match
                for match in report.get("matches", [])
                if isinstance(match, dict) and isinstance(match.get("name"), str)
            }

            if status == "blocked":
                return finish(
                    completed=False,
                    stopped=True,
                    reason=str(report.get("reason") or "blocked"),
                    report=report,
                )
            if phase == "verify" and "in_store" in matches:
                return finish(
                    completed=True,
                    stopped=False,
                    reason="stored",
                    report=report,
                )

            if phase == "submit" and flow != "storage" and "in_store" not in matches:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="outside_storage_flow",
                    report=report,
                )

            target_name = {
                "submit": "jd",
                "execute": "zxStore",
                "close": "ljbhclose",
            }.get(phase)
            target = matches.get(target_name) if target_name is not None else None
            initial_controls_ready = phase != "submit" or "in_store" in matches
            if not isinstance(target, dict) or not initial_controls_ready:
                idle_polls += 1
                if idle_polls >= max_idle_polls:
                    return finish(
                        completed=False,
                        stopped=True,
                        reason=(
                            "no_actionable_selection"
                            if phase == "submit" and "in_store" in matches
                            else "storage_controls_missing"
                        ),
                        report=report,
                    )
                context.sleep(randomized_wait_seconds(poll_interval, random_time))
                continue

            center = target.get("center")
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
                size=target.get("size"),
            )
            operation = device_service.tap(x, y)
            action = {
                "submit": "submit_storage_selection",
                "execute": "execute_storage",
                "close": "close_storage_result",
            }[phase]
            context.emit(
                "device_action",
                "Executed an experience-material storage action.",
                data={
                    "role": action,
                    "phase": phase,
                    "operation": operation.to_dict(),
                },
            )
            if not operation.ok:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="device_action_failed",
                    report=report,
                )
            actions.append(action)
            phase = {
                "submit": "execute",
                "execute": "close",
                "close": "verify",
            }[phase]
            idle_polls = 0
            context.sleep(
                randomized_wait_seconds(action_wait_seconds, random_time)
            )

        raise TimeoutError(
            "Experience-material storage did not finish within "
            f"{timeout_seconds:.2f} seconds. Last report: {last_report}"
        )

    return handler


def register_expball_storage_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
) -> None:
    if job_manager.has_kind(EXPBALL_STORAGE_JOB_KIND):
        return
    job_manager.register(
        EXPBALL_STORAGE_JOB_KIND,
        create_expball_storage_handler(
            script_data,
            device_service,
            recognizer,
        ),
        requires_device=True,
    )


def _summon_result(
    setting_name: str,
    *,
    completed: bool,
    stopped: bool,
    reason: str,
    attempts: int,
    summons: int,
    actions: list[str],
    report: dict[str, Any],
) -> dict[str, Any]:
    return {
        "setting_name": setting_name,
        "completed": completed,
        "stopped": stopped,
        "reason": reason,
        "attempts": attempts,
        "summons": summons,
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
