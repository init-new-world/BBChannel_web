from __future__ import annotations

from time import monotonic
from typing import Any

from webapp.automation.expball import (
    create_expball_enhance_handler,
    create_expball_storage_handler,
)
from webapp.automation.expball_navigation import create_expball_navigate_handler
from webapp.automation.expball_sell import create_expball_sell_handler
from webapp.automation.interaction import (
    configured_random_time,
    randomized_touch_point,
    randomized_wait_seconds,
)
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.expball import ExpBallRecognizer
from webapp.services.lottery import (
    RECEIVE_SELECTED_POINT,
    LotteryRecognizer,
    normalize_giftbox_max_counts,
)
from webapp.services.script_data import ScriptDataService


LOTTERY_INSPECT_JOB_KIND = "event.lottery.inspect"
LOTTERY_GIFTBOX_STACKS_INSPECT_JOB_KIND = "event.lottery.inspect-giftbox-stacks"
LOTTERY_DRAW_JOB_KIND = "event.lottery.draw"
LOTTERY_GIFTBOX_RECEIVE_JOB_KIND = "event.lottery.receive-giftbox"
LOTTERY_NAVIGATE_JOB_KIND = "event.lottery.navigate"
LOTTERY_RUN_JOB_KIND = "event.lottery.run"
OPEN_GIFTBOX_POINT = (860, 565)
OPEN_FILTER_POINT = (1157, 128)
CLEAR_FILTERS_POINT = (225, 637)
SERVANT_EXP_FILTER_POINT = (535, 250)
STAR_FILTER_POINTS = {3: (640, 483), 4: (453, 483), 5: (265, 483)}
APPLY_FILTER_POINT = (1060, 635)
RECEIVE_ALL_POINT = (1150, 222)
CONFIRM_RECEIVE_POINT = (837, 563)
CLOSE_GIFTBOX_POINT = (105, 43)
BOX_FULL_STORAGE_POINT = (933, 463)
BOX_FULL_SELL_POINT = (347, 463)
BOX_FULL_ENHANCE_POINT = (636, 463)
GIFTBOX_SCROLL_START = (467, 667)
GIFTBOX_SCROLL_END = (467, 267)
GIFTBOX_SCROLL_DURATION_MS = 500
OPEN_MENU_POINT = (1183, 650)
OPEN_TERMINAL_POINT = (137, 597)
OPEN_REWARDS_POINT = (1183, 40)
OPEN_EVENT_POINT = (743, 140)
REWARD_SLOT_POINTS = {0: (640, 183), 1: (640, 370), 2: (640, 527)}
_LOTTERY_OVERFLOW_ACTIONS = {
    "stop",
    "storage",
    "sell",
    "storage_then_sell",
    "servant_enhancement",
}
_DRAW_PAGE_STATES = {
    "confirm_reset",
    "close_dialog",
    "drawing",
    "draw_1",
    "draw_10",
    "pool_empty",
    "reset",
    "result_close",
}


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


def create_lottery_giftbox_stacks_inspect_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: LotteryRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = _setting_name(payload)
        threshold = _number(payload, "threshold", 0.7, 0, 1)
        stars = _stars(payload.get("stars", [3, 4, 5]))
        max_stack_counts = normalize_giftbox_max_counts(
            payload.get("max_stack_counts")
        )
        server = str(script_data.get_setting_plan(setting_name)["server"]).upper()
        context.checkpoint(
            "inspect_lottery_giftbox_stacks",
            progress=0.2,
            message="Inspecting unlimited lottery giftbox EXP stacks.",
        )
        report = recognizer.recognize_giftbox_stacks(
            device_service.snapshot(),
            server,
            stars=stars,
            max_counts=max_stack_counts,
            threshold=threshold,
        )
        context.emit(
            "lottery_giftbox_stacks",
            "Unlimited lottery giftbox EXP stacks were inspected.",
            data=report,
        )
        context.checkpoint(
            "complete",
            progress=1.0,
            message="Unlimited lottery giftbox stack inspection completed.",
        )
        return {"setting_name": setting_name, **report}

    return handler


def register_lottery_giftbox_stacks_inspect_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: LotteryRecognizer,
) -> None:
    if job_manager.has_kind(LOTTERY_GIFTBOX_STACKS_INSPECT_JOB_KIND):
        return
    job_manager.register(
        LOTTERY_GIFTBOX_STACKS_INSPECT_JOB_KIND,
        create_lottery_giftbox_stacks_inspect_handler(
            script_data,
            device_service,
            recognizer,
        ),
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
        long_touch_draw = _boolean_alias(
            payload,
            ("long_touch_draw", "longTouchDraw"),
            False,
        )
        long_touch_duration_ms = _integer(
            payload,
            "long_touch_duration_ms",
            10000,
            100,
            30000,
        )
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
                "long_touch_draw": long_touch_draw,
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
            if action == "draw" and long_touch_draw:
                operation = device_service.swipe(
                    x,
                    y,
                    x,
                    y,
                    duration_ms=long_touch_duration_ms,
                )
                recorded_action = "long_touch_draw"
            else:
                operation = device_service.tap(x, y)
                recorded_action = action
            actions.append(recorded_action)
            if action == "draw":
                draw_count += 1
            context.emit(
                "device_action",
                "Executed an unlimited lottery action.",
                data={
                    "role": recorded_action,
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


def create_lottery_navigate_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: LotteryRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = _setting_name(payload)
        threshold = _number(payload, "threshold", 0.8, 0, 1)
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
        pay_slot = _integer(payload, "pay_slot", 1, 0, 2)
        plan = script_data.get_setting_plan(setting_name)
        server = str(plan["server"]).upper()
        run_options = plan.get("run", {})
        random_touch = bool(run_options.get("random_touch"))
        random_time = configured_random_time(run_options.get("random_time", 0))
        started = monotonic()
        attempts = 0
        idle_polls = 0
        actions: list[str] = []
        last_action_state: str | None = None
        reward_flow_started = False
        event_opened = False
        terminal_opened = False
        last_report: dict[str, Any] | None = None

        def finish(reason: str, report: dict[str, Any]) -> dict[str, Any]:
            context.checkpoint(
                "complete",
                progress=1.0,
                message="Navigation to the unlimited lottery completed.",
            )
            return {
                "setting_name": setting_name,
                "completed": True,
                "reason": reason,
                "attempts": attempts,
                "actions": list(actions),
                "last_report": report,
            }

        while monotonic() - started <= timeout_seconds:
            attempts += 1
            context.checkpoint(
                "navigate_lottery",
                progress=min((monotonic() - started) / timeout_seconds, 0.95),
            )
            screenshot = device_service.snapshot()
            draw_report = recognizer.recognize(
                screenshot,
                server,
                threshold=threshold,
            )
            if str(draw_report.get("state") or "unknown") in _DRAW_PAGE_STATES:
                return finish("draw_page", draw_report)

            report = recognizer.recognize_navigation(
                screenshot,
                server,
                threshold=threshold,
            )
            last_report = report
            state = str(report.get("state") or "unknown")
            context.emit(
                "lottery_navigation_state",
                "Unlimited lottery navigation state was recognized.",
                data={"attempt": attempts, **report},
            )

            action = None
            point = None
            if state in {"giftbox", "giftbox_loaded"}:
                action, point = "close_giftbox", CLOSE_GIFTBOX_POINT
            elif state == "choose_pay" and not reward_flow_started:
                action = f"select_reward_slot_{pay_slot}"
                point = REWARD_SLOT_POINTS[pay_slot]
                reward_flow_started = True
            elif state == "pay" and not reward_flow_started:
                action, point = "open_rewards", OPEN_REWARDS_POINT
                reward_flow_started = True
            elif state == "menu_expanded" and not terminal_opened:
                action, point = "open_terminal", OPEN_TERMINAL_POINT
                terminal_opened = True
            elif state == "menu_available":
                action, point = "open_menu", OPEN_MENU_POINT
            elif state == "unknown" and reward_flow_started and not event_opened:
                action, point = "open_event", OPEN_EVENT_POINT
                event_opened = True

            action_state = f"{state}:{action}"
            if action is None or point is None or action_state == last_action_state:
                idle_polls += 1
                if idle_polls >= max_idle_polls:
                    return {
                        "setting_name": setting_name,
                        "completed": False,
                        "reason": "no_actionable_navigation_state",
                        "attempts": attempts,
                        "actions": list(actions),
                        "last_report": report,
                    }
                context.sleep(randomized_wait_seconds(poll_interval, random_time))
                continue
            if len(actions) >= max_actions:
                return {
                    "setting_name": setting_name,
                    "completed": False,
                    "reason": "action_limit",
                    "attempts": attempts,
                    "actions": list(actions),
                    "last_report": report,
                }

            idle_polls = 0
            last_action_state = action_state
            x, y = randomized_touch_point(point, enabled=random_touch)
            operation = device_service.tap(x, y)
            actions.append(action)
            context.emit(
                "device_action",
                "Executed an unlimited lottery navigation action.",
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
            "Navigation to the unlimited lottery did not finish within "
            f"{timeout_seconds:.2f} seconds. Last report: {last_report}"
        )

    return handler


def register_lottery_navigate_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: LotteryRecognizer,
) -> None:
    if job_manager.has_kind(LOTTERY_NAVIGATE_JOB_KIND):
        return
    job_manager.register(
        LOTTERY_NAVIGATE_JOB_KIND,
        create_lottery_navigate_handler(
            script_data,
            device_service,
            recognizer,
        ),
        requires_device=True,
    )


def create_lottery_giftbox_receive_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: LotteryRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = _setting_name(payload)
        max_stack_counts = normalize_giftbox_max_counts(
            payload.get("max_stack_counts")
        )
        has_active_max_counts = any(
            limit is not None for limit in max_stack_counts.values()
        )
        one_key_stars = (
            _stars(payload.get("one_key_stars"))
            if "one_key_stars" in payload and payload["one_key_stars"] is not None
            else None
        )
        if "stars" in payload and payload["stars"] is not None:
            stars = _stars(payload.get("stars"))
        elif has_active_max_counts:
            stars = [
                star
                for star, limit in sorted(max_stack_counts.items())
                if limit is not None
            ]
        elif one_key_stars is not None:
            stars = list(one_key_stars)
        else:
            stars = [3, 4, 5]
        threshold = _number(payload, "threshold", 0.8, 0, 1)
        stack_threshold = _number(payload, "stack_threshold", 0.7, 0, 1)
        max_select_batch = _integer(payload, "max_select_batch", 40, 1, 99)
        max_empty_pages = _integer(payload, "max_empty_pages", 6, 1, 50)
        first_round_count_raw = payload.get("first_round_count", False)
        if not isinstance(first_round_count_raw, bool):
            raise ValueError("first_round_count must be a boolean.")
        first_round_count = first_round_count_raw
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
        selected_stacks = 0
        selected_in_batch = 0
        empty_page_count = 0
        final_receive_submitted = False
        one_key_phase_done = not bool(one_key_stars and has_active_max_counts)
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
                "one_key_stars": (
                    list(one_key_stars) if one_key_stars is not None else None
                ),
                "max_stack_counts": {
                    str(star): max_stack_counts[star] for star in (3, 4, 5)
                },
                "attempts": attempts,
                "receive_batches": receive_batches,
                "selected_stacks": selected_stacks,
                "actions": list(actions),
                "last_report": report,
            }

        while monotonic() - started <= timeout_seconds:
            attempts += 1
            context.checkpoint(
                "receive_lottery_giftbox",
                progress=min((monotonic() - started) / timeout_seconds, 0.95),
            )
            screenshot = device_service.snapshot()
            report = recognizer.recognize_giftbox(
                screenshot,
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
            if status == "complete" and filter_applied and not has_active_max_counts:
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
                elif not one_key_phase_done:
                    if report.get("receive_all_enabled") is True:
                        action, point = "receive_all", RECEIVE_ALL_POINT
                    elif report.get("receive_all_enabled") is False:
                        one_key_phase_done = True
                        filter_applied = False
                        filter_reset = False
                        action, point = "open_filter", OPEN_FILTER_POINT
                elif has_active_max_counts:
                    if final_receive_submitted:
                        return finish(
                            completed=True,
                            stopped=False,
                            reason="giftbox_filtered_complete",
                            report=report,
                        )
                    if report.get("receive_all_enabled") is False and selected_in_batch == 0:
                        return finish(
                            completed=True,
                            stopped=False,
                            reason="giftbox_empty",
                            report=report,
                        )
                    stack_report = recognizer.recognize_giftbox_stacks(
                        screenshot,
                        server,
                        stars=stars,
                        max_counts=max_stack_counts,
                        threshold=stack_threshold,
                    )
                    report["stack_report"] = stack_report
                    context.emit(
                        "lottery_giftbox_stacks",
                        "Unlimited lottery giftbox EXP stacks were recognized.",
                        data={"attempt": attempts, **stack_report},
                    )
                    touch_points = [
                        pt
                        for pt in stack_report.get("touch_points", [])
                        if isinstance(pt, list) and len(pt) == 2
                    ]
                    if touch_points:
                        empty_page_count = 0
                        for pt in touch_points:
                            if len(actions) >= max_actions:
                                return finish(
                                    completed=False,
                                    stopped=True,
                                    reason="action_limit",
                                    report=report,
                                )
                            tx, ty = randomized_touch_point(pt, enabled=random_touch)
                            op = device_service.tap(tx, ty)
                            actions.append("select_giftbox_stack")
                            selected_stacks += 1
                            selected_in_batch += 1
                            context.emit(
                                "device_action",
                                "Selected an EXP stack in the giftbox.",
                                data={
                                    "role": "select_giftbox_stack",
                                    "state": state,
                                    "operation": op.to_dict(),
                                },
                            )
                            context.sleep(
                                randomized_wait_seconds(0.1, random_time)
                            )
                    else:
                        empty_page_count += 1

                    scrollbar = stack_report.get("scrollbar") or {}
                    at_bottom = bool(scrollbar.get("at_bottom")) or not bool(
                        scrollbar.get("matched")
                    )
                    if selected_in_batch >= max_select_batch:
                        action, point = "receive_selected", RECEIVE_SELECTED_POINT
                        receive_batches += 1
                        selected_in_batch = 0
                    elif at_bottom or (
                        not first_round_count
                        and empty_page_count >= max_empty_pages
                    ):
                        if selected_in_batch > 0:
                            action, point = "receive_selected", RECEIVE_SELECTED_POINT
                            receive_batches += 1
                            selected_in_batch = 0
                            final_receive_submitted = True
                        else:
                            return finish(
                                completed=True,
                                stopped=False,
                                reason="giftbox_filtered_complete",
                                report=report,
                            )
                    else:
                        if len(actions) >= max_actions:
                            return finish(
                                completed=False,
                                stopped=True,
                                reason="action_limit",
                                report=report,
                            )
                        idle_polls = 0
                        swipe_op = device_service.swipe(
                            *GIFTBOX_SCROLL_START,
                            *GIFTBOX_SCROLL_END,
                            duration_ms=GIFTBOX_SCROLL_DURATION_MS,
                        )
                        actions.append("scroll_giftbox")
                        context.emit(
                            "device_action",
                            "Scrolled the giftbox list.",
                            data={
                                "role": "scroll_giftbox",
                                "state": state,
                                "operation": swipe_op.to_dict(),
                            },
                        )
                        context.sleep(
                            randomized_wait_seconds(action_wait_seconds, random_time)
                        )
                        continue
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
                active_filter_stars = (
                    one_key_stars
                    if (not one_key_phase_done and one_key_stars is not None)
                    else stars
                )
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
                            expected = star in active_filter_stars
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


def create_lottery_run_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: LotteryRecognizer,
    expball_recognizer: ExpBallRecognizer | None = None,
):
    draw_handler = create_lottery_draw_handler(
        script_data,
        device_service,
        recognizer,
    )
    giftbox_handler = create_lottery_giftbox_receive_handler(
        script_data,
        device_service,
        recognizer,
    )
    navigate_handler = create_lottery_navigate_handler(
        script_data,
        device_service,
        recognizer,
    )
    storage_handler = (
        create_expball_storage_handler(
            script_data,
            device_service,
            expball_recognizer,
        )
        if expball_recognizer is not None
        else None
    )
    sell_handler = (
        create_expball_sell_handler(
            script_data,
            device_service,
            expball_recognizer,
        )
        if expball_recognizer is not None
        else None
    )
    enhance_handler = (
        create_expball_enhance_handler(
            script_data,
            device_service,
            expball_recognizer,
        )
        if expball_recognizer is not None
        else None
    )
    expball_navigate_handler = (
        create_expball_navigate_handler(
            script_data,
            device_service,
            expball_recognizer,
        )
        if expball_recognizer is not None
        else None
    )

    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = _setting_name(payload)
        max_giftbox_cycles = _integer(
            payload,
            "max_giftbox_cycles",
            100,
            0,
            10000,
        )
        max_overflow_cycles = _integer(
            payload,
            "max_overflow_cycles",
            5,
            1,
            100,
        )
        first_round_count_raw = payload.get("first_round_count", False)
        if not isinstance(first_round_count_raw, bool):
            raise ValueError("first_round_count must be a boolean.")
        first_round_count = first_round_count_raw
        draw_pool = _boolean_alias(payload, ("draw_pool", "drawPool"), True)
        tidy_giftbox = _boolean_alias(
            payload,
            ("tidy_giftbox", "tidyGiftbox"),
            True,
        )
        if not draw_pool and not tidy_giftbox:
            raise ValueError(
                "At least one of draw_pool or tidy_giftbox must be enabled."
            )
        store_first_raw = payload.get("store_first", False)
        if not isinstance(store_first_raw, bool):
            raise ValueError("store_first must be a boolean.")
        overflow_actions = _parse_lottery_overflow_actions(
            payload,
            store_first_raw,
        )
        overflow_action = (
            overflow_actions[0] if overflow_actions else "stop"
        )
        if payload.get("overflow_action") is not None and not payload.get(
            "overflow_actions"
        ):
            overflow_action = (
                str(payload.get("overflow_action") or "stop").strip().lower()
            )
            if store_first_raw and overflow_action in {
                "stop",
                "storage",
                "sell",
            }:
                overflow_action = "storage_then_sell"
        overflow_stars = (
            _stars(payload.get("overflow_stars"))
            if "overflow_stars" in payload and payload["overflow_stars"] is not None
            else None
        )
        storage_stars = (
            _stars(payload.get("storage_stars"))
            if "storage_stars" in payload and payload["storage_stars"] is not None
            else overflow_stars
        )
        sell_stars = (
            _stars(payload.get("sell_stars"))
            if "sell_stars" in payload and payload["sell_stars"] is not None
            else overflow_stars
        )
        storage_target = (
            str(payload.get("storage_target") or "exp").strip().lower()
        )
        sell_target = str(payload.get("sell_target") or "exp").strip().lower()
        if (
            any(
                act in {"storage", "storage_then_sell"}
                for act in overflow_actions
            )
            and storage_target != "ce_bomb"
            and storage_stars is None
        ):
            raise ValueError(
                "overflow_action requires overflow_stars to be configured for storage or sell."
            )
        if (
            any(
                act in {"sell", "storage_then_sell"}
                for act in overflow_actions
            )
            and sell_target not in {"servant", "command_code"}
            and sell_stars is None
        ):
            raise ValueError(
                "overflow_action requires overflow_stars to be configured for storage or sell."
            )
        if overflow_actions != ("stop",) and expball_recognizer is None:
            raise ValueError(
                "overflow_action requires expball_recognizer to be configured."
            )
        action_wait_seconds = _number(
            payload,
            "action_wait_seconds",
            0.4,
            0,
            30,
        )
        plan = script_data.get_setting_plan(setting_name)
        run_options = plan.get("run", {})
        random_touch = bool(run_options.get("random_touch"))
        random_time = configured_random_time(run_options.get("random_time", 0))
        common_payload: dict[str, Any] = {"setting_name": setting_name}
        for key in (
            "threshold",
            "poll_interval",
            "action_wait_seconds",
            "max_idle_polls",
        ):
            if key in payload:
                common_payload[key] = payload[key]

        draw_payload = dict(common_payload)
        giftbox_payload = dict(common_payload)
        navigate_payload = dict(common_payload)
        overflow_payload = dict(common_payload)
        if overflow_stars is not None:
            overflow_payload["stars"] = list(overflow_stars)
        _copy_option(
            payload,
            overflow_payload,
            "grid_threshold",
            "grid_threshold",
        )
        storage_overflow_payload = dict(overflow_payload)
        if storage_stars is not None:
            storage_overflow_payload["stars"] = list(storage_stars)
        for key in (
            "storage_target",
            "require_locked_and_marked",
            "locker_threshold",
            "mark_threshold",
        ):
            _copy_option(payload, storage_overflow_payload, key, key)
        sell_overflow_payload = dict(overflow_payload)
        if sell_stars is not None:
            sell_overflow_payload["stars"] = list(sell_stars)
        for key in (
            "sell_target",
            "lock_gold_servants",
            "include_fp_gold",
            "select_servant_cards",
            "fp_gold_threshold",
            "lock_inscribed_command_codes",
            "inscribed_threshold",
            "empty_threshold",
            "locker_threshold",
            "switch_command_code_tab",
            "auto_select",
            "allow_qp_full",
        ):
            _copy_option(payload, sell_overflow_payload, key, key)
        servant_enhance_payload = dict(overflow_payload)
        servant_enhance_payload["target"] = "servant"
        servant_enhance_payload["selection_mode"] = str(
            payload.get("material_select_mode")
            or payload.get("selection_mode")
            or "auto"
        )
        for key in (
            "material_select_mode",
            "select_base_first",
            "max_batches",
            "target_level",
            "level_threshold",
            "servant_target",
            "servant_targets",
            "servant_target_threshold",
            "max_base_scrolls",
            "auto_limit_break",
        ):
            _copy_option(payload, servant_enhance_payload, key, key)
        if overflow_action == "storage":
            overflow_payload = storage_overflow_payload
        if overflow_action == "sell":
            overflow_payload = sell_overflow_payload
        if overflow_action == "servant_enhancement":
            overflow_payload = servant_enhance_payload
        _copy_option(
            payload,
            draw_payload,
            "draw_timeout_seconds",
            "timeout_seconds",
        )
        _copy_option(
            payload,
            giftbox_payload,
            "giftbox_timeout_seconds",
            "timeout_seconds",
        )
        _copy_option(
            payload,
            navigate_payload,
            "navigation_timeout_seconds",
            "timeout_seconds",
        )
        _copy_option(payload, draw_payload, "max_draw_actions", "max_draw_actions")
        for key in (
            "long_touch_draw",
            "longTouchDraw",
            "long_touch_duration_ms",
        ):
            _copy_option(payload, draw_payload, key, key)
        _copy_option(
            payload,
            giftbox_payload,
            "max_giftbox_actions",
            "max_actions",
        )
        _copy_option(
            payload,
            navigate_payload,
            "max_navigation_actions",
            "max_actions",
        )
        if "stars" in payload:
            giftbox_payload["stars"] = payload["stars"]
        for key in (
            "one_key_stars",
            "max_stack_counts",
            "stack_threshold",
            "max_select_batch",
            "max_empty_pages",
        ):
            if key in payload:
                giftbox_payload[key] = payload[key]
        if "pay_slot" in payload:
            navigate_payload["pay_slot"] = payload["pay_slot"]

        giftbox_cycles = 0
        overflow_cycles = 0
        storage_full = False
        servant_targets_completed = False
        first_filter_pass = True
        draw_count = 0
        receive_batches = 0
        selected_stacks = 0
        stages: list[dict[str, Any]] = []

        def record(stage: str, result: dict[str, Any]) -> None:
            stages.append({"stage": stage, "result": result})

        def finish(
            *,
            completed: bool,
            stopped: bool,
            reason: str,
        ) -> dict[str, Any]:
            context.checkpoint(
                "complete",
                progress=1.0,
                message=(
                    "Unlimited lottery automation completed."
                    if completed
                    else "Unlimited lottery automation stopped."
                ),
            )
            return {
                "setting_name": setting_name,
                "completed": completed,
                "stopped": stopped,
                "reason": reason,
                "draw_pool": draw_pool,
                "tidy_giftbox": tidy_giftbox,
                "giftbox_cycles": giftbox_cycles,
                "overflow_action": overflow_action,
                "overflow_actions": list(overflow_actions),
                "overflow_cycles": overflow_cycles,
                "storage_full": storage_full,
                "draw_count": draw_count,
                "receive_batches": receive_batches,
                "selected_stacks": selected_stacks,
                "stages": stages,
            }

        while True:
            context.checkpoint(
                "lottery_cycle",
                message=f"Running unlimited lottery cycle {giftbox_cycles + 1}.",
            )
            if draw_pool:
                draw_result = draw_handler(context, draw_payload)
                draw_count += int(draw_result.get("draw_count") or 0)
                record("draw", draw_result)
                draw_reason = str(draw_result.get("reason") or "draw_stopped")
                if draw_result.get("completed") is True:
                    return finish(
                        completed=True,
                        stopped=False,
                        reason=draw_reason,
                    )
                if draw_reason != "giftbox_full":
                    return finish(
                        completed=False,
                        stopped=True,
                        reason=draw_reason,
                    )
                if not tidy_giftbox:
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="giftbox_full",
                    )
            if giftbox_cycles >= max_giftbox_cycles:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="giftbox_cycle_limit",
                )

            current_giftbox_payload = dict(giftbox_payload)
            if first_round_count and first_filter_pass:
                current_giftbox_payload["first_round_count"] = True
            giftbox_result = giftbox_handler(context, current_giftbox_payload)
            receive_batches += int(giftbox_result.get("receive_batches") or 0)
            selected_stacks += int(giftbox_result.get("selected_stacks") or 0)
            record("receive_giftbox", giftbox_result)
            if giftbox_result.get("completed") is True:
                first_filter_pass = False
                if not draw_pool:
                    giftbox_cycles += 1
                    return finish(
                        completed=True,
                        stopped=False,
                        reason=str(
                            giftbox_result.get("reason") or "giftbox_empty"
                        ),
                    )
            if giftbox_result.get("completed") is not True:
                giftbox_reason = str(
                    giftbox_result.get("reason") or "giftbox_receive_stopped"
                )
                if (
                    giftbox_reason == "inventory_full"
                    and overflow_actions != ("stop",)
                ):
                    if overflow_cycles >= max_overflow_cycles:
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="overflow_limit",
                        )
                    opened_from_dialog = False
                    for stage_action in overflow_actions:
                        if (
                            stage_action == "servant_enhancement"
                            and servant_targets_completed
                        ):
                            continue
                        if stage_action == "storage" and storage_full:
                            if len(overflow_actions) > 1:
                                continue
                            return finish(
                                completed=False,
                                stopped=True,
                                reason="storage_full",
                            )
                        active_action = stage_action
                        if stage_action == "storage_then_sell":
                            active_action = "sell" if storage_full else "storage"
                        if active_action == "storage":
                            overflow_point = BOX_FULL_STORAGE_POINT
                            active_overflow_handler = storage_handler
                            active_overflow_payload = storage_overflow_payload
                        elif active_action == "sell":
                            overflow_point = BOX_FULL_SELL_POINT
                            active_overflow_handler = sell_handler
                            active_overflow_payload = sell_overflow_payload
                        else:
                            overflow_point = BOX_FULL_ENHANCE_POINT
                            active_overflow_handler = enhance_handler
                            active_overflow_payload = servant_enhance_payload

                        if not opened_from_dialog:
                            overflow_role = f"open_overflow_{active_action}"
                            tx, ty = randomized_touch_point(
                                overflow_point,
                                enabled=random_touch,
                            )
                            op = device_service.tap(tx, ty)
                            context.emit(
                                "device_action",
                                "Opened inventory overflow handler from full-box dialog.",
                                data={
                                    "role": overflow_role,
                                    "state": "inventory_full",
                                    "operation": op.to_dict(),
                                },
                            )
                            if not op.ok:
                                return finish(
                                    completed=False,
                                    stopped=True,
                                    reason="device_action_failed",
                                )
                            context.sleep(
                                randomized_wait_seconds(
                                    action_wait_seconds,
                                    random_time,
                                )
                            )
                            opened_from_dialog = True
                        else:
                            assert expball_navigate_handler is not None
                            stage_nav_payload = dict(common_payload)
                            stage_nav_payload["destination"] = active_action
                            stage_nav_result = expball_navigate_handler(
                                context,
                                stage_nav_payload,
                            )
                            record(
                                f"navigate_overflow_{active_action}",
                                stage_nav_result,
                            )
                            if stage_nav_result.get("completed") is not True:
                                return finish(
                                    completed=False,
                                    stopped=True,
                                    reason=str(
                                        stage_nav_result.get("reason")
                                        or "navigation_stopped"
                                    ),
                                )

                        assert active_overflow_handler is not None
                        overflow_result = active_overflow_handler(
                            context,
                            dict(active_overflow_payload),
                        )
                        record(f"overflow_{active_action}", overflow_result)
                        if overflow_result.get("reason") == "storage_full":
                            storage_full = True
                        if (
                            stage_action == "storage_then_sell"
                            and active_action == "storage"
                            and overflow_result.get("completed") is not True
                            and overflow_result.get("reason") == "storage_full"
                        ):
                            assert expball_navigate_handler is not None
                            assert sell_handler is not None
                            sell_nav_payload = dict(common_payload)
                            sell_nav_payload["destination"] = "sell"
                            sell_nav_result = expball_navigate_handler(
                                context,
                                sell_nav_payload,
                            )
                            record("navigate_overflow_sell", sell_nav_result)
                            if sell_nav_result.get("completed") is not True:
                                return finish(
                                    completed=False,
                                    stopped=True,
                                    reason=str(
                                        sell_nav_result.get("reason")
                                        or "navigation_stopped"
                                    ),
                                )
                            overflow_result = sell_handler(
                                context,
                                dict(sell_overflow_payload),
                            )
                            record("overflow_sell", overflow_result)
                            active_action = "sell"
                        if (
                            stage_action == "storage"
                            and overflow_result.get("reason")
                            in {"storage_full", "no_matching_cards"}
                            and len(overflow_actions) > 1
                        ):
                            continue
                        if (
                            active_action == "sell"
                            and overflow_result.get("reason")
                            == "no_matching_cards"
                            and len(overflow_actions) > 1
                        ):
                            continue
                        if overflow_result.get("completed") is not True:
                            return finish(
                                completed=False,
                                stopped=True,
                                reason=str(
                                    overflow_result.get("reason")
                                    or f"{active_action}_stopped"
                                ),
                            )
                        if (
                            active_action == "servant_enhancement"
                            and overflow_result.get("reason")
                            == "target_level_reached"
                        ):
                            servant_targets_completed = True
                    overflow_cycles += 1
                else:
                    return finish(
                        completed=False,
                        stopped=True,
                        reason=giftbox_reason,
                    )

            if draw_pool:
                navigate_result = navigate_handler(context, navigate_payload)
                record("navigate", navigate_result)
                if navigate_result.get("completed") is not True:
                    return finish(
                        completed=False,
                        stopped=True,
                        reason=str(
                            navigate_result.get("reason") or "navigation_stopped"
                        ),
                    )
            giftbox_cycles += 1

    return handler


def register_lottery_run_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: LotteryRecognizer,
    expball_recognizer: ExpBallRecognizer | None = None,
) -> None:
    if job_manager.has_kind(LOTTERY_RUN_JOB_KIND):
        return
    job_manager.register(
        LOTTERY_RUN_JOB_KIND,
        create_lottery_run_handler(
            script_data,
            device_service,
            recognizer,
            expball_recognizer=expball_recognizer,
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


def _copy_option(
    source: dict[str, Any],
    destination: dict[str, Any],
    source_key: str,
    destination_key: str,
) -> None:
    if source_key in source:
        destination[destination_key] = source[source_key]


def _boolean_alias(
    payload: dict[str, Any],
    keys: tuple[str, ...],
    default: bool,
) -> bool:
    for key in keys:
        if key in payload and payload[key] is not None:
            value = payload[key]
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean.")
            return value
    return default


def _parse_lottery_overflow_actions(
    payload: dict[str, Any],
    store_first: bool,
) -> tuple[str, ...]:
    raw_list = payload.get("overflow_actions")
    if raw_list is not None:
        if isinstance(raw_list, str):
            items = [
                part.strip().lower()
                for part in raw_list.split(",")
                if part.strip()
            ]
        elif isinstance(raw_list, (list, tuple)):
            items = []
            for item in raw_list:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError(
                        "overflow_actions entries must be non-empty strings."
                    )
                items.append(item.strip().lower())
        else:
            raise ValueError(
                "overflow_actions must be a list or comma-separated string."
            )
        deduped: list[str] = []
        for item in items:
            if item not in _LOTTERY_OVERFLOW_ACTIONS:
                raise ValueError(
                    "overflow_actions entries must be stop, storage, sell, "
                    "storage_then_sell, or servant_enhancement."
                )
            if item == "stop":
                continue
            if item not in deduped:
                deduped.append(item)
        if store_first and "sell" in deduped and "storage" not in deduped:
            sell_idx = deduped.index("sell")
            deduped[sell_idx] = "storage_then_sell"
        return tuple(deduped) if deduped else ("stop",)

    overflow_action = (
        str(payload.get("overflow_action") or "stop").strip().lower()
    )
    if store_first and overflow_action in {"stop", "storage", "sell"}:
        overflow_action = "storage_then_sell"
    if overflow_action not in _LOTTERY_OVERFLOW_ACTIONS:
        raise ValueError(
            "overflow_action must be stop, storage, sell, "
            "storage_then_sell, or servant_enhancement."
        )
    return (overflow_action,)
