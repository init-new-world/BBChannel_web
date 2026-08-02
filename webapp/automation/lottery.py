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
from webapp.services.lottery import LotteryRecognizer
from webapp.services.script_data import ScriptDataService


LOTTERY_INSPECT_JOB_KIND = "event.lottery.inspect"
LOTTERY_DRAW_JOB_KIND = "event.lottery.draw"
LOTTERY_GIFTBOX_RECEIVE_JOB_KIND = "event.lottery.receive-giftbox"
OPEN_GIFTBOX_POINT = (860, 565)
OPEN_FILTER_POINT = (1157, 128)
CLEAR_FILTERS_POINT = (225, 637)
SERVANT_EXP_FILTER_POINT = (535, 250)
STAR_FILTER_POINTS = {3: (640, 483), 4: (453, 483), 5: (265, 483)}
APPLY_FILTER_POINT = (1060, 635)
RECEIVE_ALL_POINT = (1150, 222)
CONFIRM_RECEIVE_POINT = (837, 563)


def create_lottery_inspect_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: LotteryRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = _setting_name(payload)
        threshold = _number(payload, "threshold", 0.8, 0, 1)
        server = str(script_data.get_setting_plan(setting_name)["server"]).upper()
        context.checkpoint(
            "inspect_lottery",
            progress=0.2,
            message="Inspecting the unlimited lottery screen.",
        )
        report = recognizer.recognize(
            device_service.snapshot(),
            server,
            threshold=threshold,
        )
        context.emit(
            "lottery_state",
            "Unlimited lottery state was inspected.",
            data=report,
        )
        context.checkpoint(
            "complete",
            progress=1.0,
            message="Unlimited lottery inspection completed.",
        )
        return {"setting_name": setting_name, **report}

    return handler


def register_lottery_inspect_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: LotteryRecognizer,
) -> None:
    if job_manager.has_kind(LOTTERY_INSPECT_JOB_KIND):
        return
    job_manager.register(
        LOTTERY_INSPECT_JOB_KIND,
        create_lottery_inspect_handler(script_data, device_service, recognizer),
        requires_device=True,
    )


def create_lottery_draw_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: LotteryRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = _setting_name(payload)
        threshold = _number(payload, "threshold", 0.8, 0, 1)
        timeout_seconds = _number(payload, "timeout_seconds", 3600, 0.1, 21600)
        poll_interval = _number(payload, "poll_interval", 0.25, 0, 10)
        action_wait_seconds = _number(
            payload,
            "action_wait_seconds",
            0.4,
            0,
            30,
        )
        max_draw_actions = _integer(
            payload,
            "max_draw_actions",
            10000,
            1,
            100000,
        )
        max_idle_polls = _integer(payload, "max_idle_polls", 5, 1, 100)
        plan = script_data.get_setting_plan(setting_name)
        server = str(plan["server"]).upper()
        run_options = plan.get("run", {})
        random_touch = bool(run_options.get("random_touch"))
        random_time = configured_random_time(run_options.get("random_time", 0))
        started = monotonic()
        attempts = 0
        draw_count = 0
        idle_polls = 0
        actions: list[str] = []
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
                    "Unlimited lottery draw completed."
                    if completed
                    else "Unlimited lottery draw stopped."
                ),
            )
            return {
                "setting_name": setting_name,
                "completed": completed,
                "stopped": stopped,
                "reason": reason,
                "attempts": attempts,
                "draw_count": draw_count,
                "actions": list(actions),
                "last_report": report,
            }

        while monotonic() - started <= timeout_seconds:
            attempts += 1
            context.checkpoint(
                "draw_lottery",
                progress=min((monotonic() - started) / timeout_seconds, 0.95),
            )
            report = recognizer.recognize(
                device_service.snapshot(),
                server,
                threshold=threshold,
            )
            last_report = report
            context.emit(
                "lottery_state",
                "Unlimited lottery state was recognized.",
                data={"attempt": attempts, **report},
            )
            status = str(report.get("status") or "unknown")
            reason = str(report.get("reason") or "unknown")

            if status == "complete":
                return finish(
                    completed=True,
                    stopped=False,
                    reason=reason,
                    report=report,
                )
            if status == "blocked":
                return finish(
                    completed=False,
                    stopped=True,
                    reason=reason,
                    report=report,
                )
            if status != "actionable":
                idle_polls += 1
                if idle_polls >= max_idle_polls:
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="no_actionable_state",
                        report=report,
                    )
                context.sleep(randomized_wait_seconds(poll_interval, random_time))
                continue

            idle_polls = 0
            action = report.get("recommended_action")
            action_point = report.get("action_point")
            if (
                not isinstance(action, str)
                or not isinstance(action_point, list)
                or len(action_point) != 2
            ):
                return finish(
                    completed=False,
                    stopped=True,
                    reason="invalid_recognition_result",
                    report=report,
                )
            if action == "draw" and draw_count >= max_draw_actions:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="draw_limit",
                    report=report,
                )

            x, y = randomized_touch_point(action_point, enabled=random_touch)
            operation = device_service.tap(x, y)
            actions.append(action)
            if action == "draw":
                draw_count += 1
            context.emit(
                "device_action",
                "Executed an unlimited lottery action.",
                data={
                    "role": action,
                    "state": report.get("state"),
                    "operation": operation.to_dict(),
                },
            )
            context.sleep(
                randomized_wait_seconds(action_wait_seconds, random_time)
            )

        raise TimeoutError(
            "Unlimited lottery draw did not finish within "
            f"{timeout_seconds:.2f} seconds. Last report: {last_report}"
        )

    return handler


def register_lottery_draw_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: LotteryRecognizer,
) -> None:
    if job_manager.has_kind(LOTTERY_DRAW_JOB_KIND):
        return
    job_manager.register(
        LOTTERY_DRAW_JOB_KIND,
        create_lottery_draw_handler(script_data, device_service, recognizer),
        requires_device=True,
    )


def create_lottery_giftbox_receive_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: LotteryRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = _setting_name(payload)
        stars = _stars(payload.get("stars", [3, 4, 5]))
        threshold = _number(payload, "threshold", 0.8, 0, 1)
        timeout_seconds = _number(payload, "timeout_seconds", 600, 0.1, 3600)
        poll_interval = _number(payload, "poll_interval", 0.25, 0, 10)
        action_wait_seconds = _number(
            payload,
            "action_wait_seconds",
            0.4,
            0,
            30,
        )
        max_actions = _integer(payload, "max_actions", 200, 1, 10000)
        max_idle_polls = _integer(payload, "max_idle_polls", 10, 1, 100)
        plan = script_data.get_setting_plan(setting_name)
        server = str(plan["server"]).upper()
        run_options = plan.get("run", {})
        random_touch = bool(run_options.get("random_touch"))
        random_time = configured_random_time(run_options.get("random_time", 0))
        started = monotonic()
        attempts = 0
        idle_polls = 0
        receive_batches = 0
        filter_reset = False
        filter_applied = False
        actions: list[str] = []
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
                    "Unlimited lottery giftbox receiving completed."
                    if completed
                    else "Unlimited lottery giftbox receiving stopped."
                ),
            )
            return {
                "setting_name": setting_name,
                "completed": completed,
                "stopped": stopped,
                "reason": reason,
                "stars": stars,
                "attempts": attempts,
                "receive_batches": receive_batches,
                "actions": list(actions),
                "last_report": report,
            }

        while monotonic() - started <= timeout_seconds:
            attempts += 1
            context.checkpoint(
                "receive_lottery_giftbox",
                progress=min((monotonic() - started) / timeout_seconds, 0.95),
            )
            report = recognizer.recognize_giftbox(
                device_service.snapshot(),
                server,
                threshold=threshold,
            )
            last_report = report
            context.emit(
                "lottery_giftbox_state",
                "Unlimited lottery giftbox state was recognized.",
                data={"attempt": attempts, **report},
            )
            state = str(report.get("state") or "unknown")
            status = str(report.get("status") or "unknown")
            reason = str(report.get("reason") or "unknown")

            if status == "blocked":
                return finish(
                    completed=False,
                    stopped=True,
                    reason=reason,
                    report=report,
                )
            if status == "complete" and filter_applied:
                return finish(
                    completed=True,
                    stopped=False,
                    reason=reason,
                    report=report,
                )

            action = None
            point = None
            if state == "giftbox_full":
                action, point = "open_giftbox", OPEN_GIFTBOX_POINT
            elif state in {"giftbox", "giftbox_loaded", "receive_all_on", "receive_all_off"}:
                if not filter_applied:
                    action, point = "open_filter", OPEN_FILTER_POINT
                elif report.get("receive_all_enabled") is True:
                    action, point = "receive_all", RECEIVE_ALL_POINT
                elif report.get("receive_all_enabled") is False:
                    return finish(
                        completed=True,
                        stopped=False,
                        reason="giftbox_empty",
                        report=report,
                    )
            elif state == "filter_dialog":
                if not filter_reset:
                    action, point = "clear_filters", CLEAR_FILTERS_POINT
                    filter_reset = True
                elif report.get("servant_exp_enabled") is False:
                    action, point = "enable_servant_exp", SERVANT_EXP_FILTER_POINT
                elif report.get("servant_exp_enabled") is True:
                    star_filters = report.get("star_filters")
                    if isinstance(star_filters, dict):
                        for star in (3, 4, 5):
                            current = star_filters.get(star)
                            expected = star in stars
                            if isinstance(current, bool) and current != expected:
                                action = f"toggle_star_{star}"
                                point = STAR_FILTER_POINTS[star]
                                break
                        else:
                            if all(
                                isinstance(star_filters.get(star), bool)
                                for star in (3, 4, 5)
                            ):
                                action, point = "apply_filter", APPLY_FILTER_POINT
                                filter_applied = True
            elif state == "receive_confirm":
                action, point = "confirm_receive", CONFIRM_RECEIVE_POINT
                receive_batches += 1

            if action is None or point is None:
                idle_polls += 1
                if idle_polls >= max_idle_polls:
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="no_actionable_giftbox_state",
                        report=report,
                    )
                context.sleep(randomized_wait_seconds(poll_interval, random_time))
                continue
            if len(actions) >= max_actions:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="action_limit",
                    report=report,
                )

            idle_polls = 0
            x, y = randomized_touch_point(point, enabled=random_touch)
            operation = device_service.tap(x, y)
            actions.append(action)
            context.emit(
                "device_action",
                "Executed an unlimited lottery giftbox action.",
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
            "Unlimited lottery giftbox receiving did not finish within "
            f"{timeout_seconds:.2f} seconds. Last report: {last_report}"
        )

    return handler


def register_lottery_giftbox_receive_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: LotteryRecognizer,
) -> None:
    if job_manager.has_kind(LOTTERY_GIFTBOX_RECEIVE_JOB_KIND):
        return
    job_manager.register(
        LOTTERY_GIFTBOX_RECEIVE_JOB_KIND,
        create_lottery_giftbox_receive_handler(
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


def _stars(value: object) -> list[int]:
    if (
        not isinstance(value, list)
        or not value
        or any(
            isinstance(star, bool)
            or not isinstance(star, int)
            or star not in {3, 4, 5}
            for star in value
        )
    ):
        raise ValueError("stars must be a non-empty list containing 3, 4, or 5.")
    return sorted(set(value))
