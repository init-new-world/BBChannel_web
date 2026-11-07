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
_VALID_CARD_STARS = {3, 4, 5}
_SELL_TARGETS = {"exp", "servant", "command_code"}
_UNIFIED_LOCK_POINT = (32, 368)
_COMMAND_CODE_TAB_POINT = (475, 128)
_QP_FULL_CONFIRM_POINT = (920, 560)


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
        grid_threshold = _number(payload, "grid_threshold", 0.75, 0, 1)
        fp_gold_threshold = _number(payload, "fp_gold_threshold", 0.85, 0, 1)
        inscribed_threshold = _number(payload, "inscribed_threshold", 0.7, 0, 1)
        empty_threshold = _number(payload, "empty_threshold", 0.8, 0, 1)
        locker_threshold = _number(payload, "locker_threshold", 0.7, 0, 1)
        sell_target = str(payload.get("sell_target") or "exp").strip().lower()
        if sell_target not in _SELL_TARGETS:
            raise ValueError("sell_target must be exp, servant, or command_code.")
        lock_gold_servants = _boolean(payload, "lock_gold_servants", True)
        include_fp_gold = _boolean(payload, "include_fp_gold", True)
        select_servant_cards = _boolean(payload, "select_servant_cards", False)
        lock_inscribed_command_codes = _boolean(
            payload,
            "lock_inscribed_command_codes",
            True,
        )
        switch_command_code_tab = _boolean(
            payload,
            "switch_command_code_tab",
            True,
        )
        auto_select = _boolean(payload, "auto_select", False)
        allow_qp_full = _boolean(payload, "allow_qp_full", False)
        stars = _parse_card_stars(payload)
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
        selected_slots: list[int] = []
        locked_slots: list[int] = []
        last_screenshot = b""

        def inspect(phase: str) -> dict[str, Any]:
            nonlocal attempts, last_screenshot
            attempts += 1
            context.checkpoint(f"sell_expball_{phase}", progress=min(attempts / 4, 0.95))
            last_screenshot = device_service.snapshot()
            report = recognizer.recognize(
                last_screenshot,
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
                "sell_target": sell_target,
                "completed": completed,
                "stopped": stopped,
                "reason": reason,
                "attempts": attempts,
                "actions": list(actions),
                "selected_slots": list(selected_slots),
                "selected_count": len(selected_slots),
                "locked_slots": list(locked_slots),
                "locked_count": len(locked_slots),
                "last_report": report,
            }

        def tap_point(
            point: tuple[int, int] | list[int],
            action: str,
            extra: dict[str, Any] | None = None,
        ) -> bool:
            x, y = randomized_touch_point(point, enabled=random_touch)
            operation = device_service.tap(x, y)
            context.emit(
                "device_action",
                "Executed an experience-material sale action.",
                data={
                    "role": action,
                    **(extra or {}),
                    "operation": operation.to_dict(),
                },
            )
            if not operation.ok:
                return False
            actions.append(action)
            context.sleep(
                randomized_wait_seconds(action_wait_seconds, random_time)
            )
            return True

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

        report = inspect("submit")
        if report.get("flow") != "sell":
            return finish(
                completed=False,
                stopped=True,
                reason="outside_sell_flow",
                report=report,
            )
        if sell_target == "servant":
            servant_grid = recognizer.recognize_servant_sale_grid(
                last_screenshot,
                fp_gold_threshold=fp_gold_threshold,
            )
            context.emit(
                "expball_servant_grid",
                "Visible servant sale grid cards were inspected.",
                data={"server": server, **servant_grid},
            )
            if lock_gold_servants:
                slots_to_lock = [
                    slot
                    for slot in servant_grid.get("slots", [])
                    if isinstance(slot, dict) and slot.get("need_lock") is True
                ]
                if slots_to_lock:
                    if not tap_point(
                        _UNIFIED_LOCK_POINT,
                        "enable_unified_lock",
                    ):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    for slot in slots_to_lock:
                        slot_center = slot.get("center")
                        if not isinstance(slot_center, list) or len(slot_center) != 2:
                            return finish(
                                completed=False,
                                stopped=True,
                                reason="invalid_recognition_result",
                                report=report,
                            )
                        if not tap_point(
                            slot_center,
                            "lock_gold_servant",
                            {"slot": slot.get("slot")},
                        ):
                            return finish(
                                completed=False,
                                stopped=True,
                                reason="device_action_failed",
                                report=report,
                            )
                        locked_slots.append(int(slot["slot"]))
                    if not tap_point(
                        _UNIFIED_LOCK_POINT,
                        "disable_unified_lock",
                    ):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    report = inspect("submit")
                    if report.get("flow") != "sell":
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="outside_sell_flow",
                            report=report,
                        )
            if select_servant_cards:
                sellable_slots = [
                    slot
                    for slot in servant_grid.get("slots", [])
                    if isinstance(slot, dict)
                    and (
                        slot.get("frame_type") in {"bronze", "silver"}
                        or (include_fp_gold and slot.get("fp_gold") is not None)
                    )
                ]
                if not sellable_slots:
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="no_matching_servants",
                        report=report,
                    )
                for slot in sellable_slots:
                    slot_center = slot.get("center")
                    if not isinstance(slot_center, list) or len(slot_center) != 2:
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="invalid_recognition_result",
                            report=report,
                        )
                    if not tap_point(
                        slot_center,
                        "select_sell_servant_card",
                        {
                            "slot": slot.get("slot"),
                            "frame_type": slot.get("frame_type"),
                            "fp_gold": slot.get("fp_gold"),
                        },
                    ):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    selected_slots.append(int(slot["slot"]))
                report = inspect("submit")
                if report.get("flow") != "sell":
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="outside_sell_flow",
                        report=report,
                    )
        elif sell_target == "command_code":
            current_match_names = {
                match.get("name")
                for match in report.get("matches", [])
                if isinstance(match, dict)
            }
            if switch_command_code_tab and "fmwz_1" not in current_match_names:
                if not tap_point(
                    _COMMAND_CODE_TAB_POINT,
                    "switch_command_code_tab",
                ):
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="device_action_failed",
                        report=report,
                    )
                report = inspect("submit")
                if report.get("flow") != "sell":
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="outside_sell_flow",
                        report=report,
                    )
            command_code_grid = recognizer.recognize_command_code_sale_grid(
                last_screenshot,
                server,
                inscribed_threshold=inscribed_threshold,
                empty_threshold=empty_threshold,
                locker_threshold=locker_threshold,
            )
            context.emit(
                "expball_command_code_grid",
                "Visible command-code sale grid cards were inspected.",
                data=command_code_grid,
            )
            if (
                command_code_grid.get("empty") is True
                or command_code_grid.get("first_slot_locked") is True
            ):
                return finish(
                    completed=True,
                    stopped=False,
                    reason="no_sellable_command_codes",
                    report=report,
                )
            if lock_inscribed_command_codes:
                inscribed_slots = [
                    slot
                    for slot in command_code_grid.get("slots", [])
                    if isinstance(slot, dict) and slot.get("inscribed") is True
                ]
                if inscribed_slots:
                    if not tap_point(
                        _UNIFIED_LOCK_POINT,
                        "enable_unified_lock",
                    ):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    for slot in inscribed_slots:
                        slot_center = slot.get("center")
                        if not isinstance(slot_center, list) or len(slot_center) != 2:
                            return finish(
                                completed=False,
                                stopped=True,
                                reason="invalid_recognition_result",
                                report=report,
                            )
                        if not tap_point(
                            slot_center,
                            "lock_inscribed_command_code",
                            {"slot": slot.get("slot")},
                        ):
                            return finish(
                                completed=False,
                                stopped=True,
                                reason="device_action_failed",
                                report=report,
                            )
                        locked_slots.append(int(slot["slot"]))
                    if not tap_point(
                        _UNIFIED_LOCK_POINT,
                        "disable_unified_lock",
                    ):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    report = inspect("submit")
                    if report.get("flow") != "sell":
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="outside_sell_flow",
                            report=report,
                        )
                    command_code_grid = recognizer.recognize_command_code_sale_grid(
                        last_screenshot,
                        server,
                        inscribed_threshold=inscribed_threshold,
                        empty_threshold=empty_threshold,
                        locker_threshold=locker_threshold,
                    )
                    context.emit(
                        "expball_command_code_grid",
                        "Visible command-code sale grid cards were inspected.",
                        data=command_code_grid,
                    )
                    if (
                        command_code_grid.get("empty") is True
                        or command_code_grid.get("first_slot_locked") is True
                    ):
                        return finish(
                            completed=True,
                            stopped=False,
                            reason="no_sellable_command_codes",
                            report=report,
                        )
            if auto_select:
                current_match_names = {
                    match.get("name")
                    for match in report.get("matches", [])
                    if isinstance(match, dict)
                }
                if "autoSell" in current_match_names:
                    if not tap_match(
                        report,
                        "autoSell",
                        "auto_select_sell_cards",
                    ):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    report = inspect("submit")
                    if report.get("flow") != "sell":
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="outside_sell_flow",
                            report=report,
                        )
        elif stars is not None:
            grid_report = recognizer.recognize_storage_grid(
                last_screenshot,
                threshold=grid_threshold,
            )
            context.emit(
                "expball_storage_grid",
                "Visible experience-material sale cards were inspected.",
                data={"server": server, "stars": list(stars), **grid_report},
            )
            matching_slots = [
                slot
                for slot in grid_report.get("slots", [])
                if isinstance(slot, dict) and slot.get("star") in stars
            ]
            if not matching_slots:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="no_matching_cards",
                    report=report,
                )
            for slot in matching_slots:
                slot_center = slot.get("center")
                if not isinstance(slot_center, list) or len(slot_center) != 2:
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="invalid_recognition_result",
                        report=report,
                    )
                x, y = randomized_touch_point(
                    slot_center,
                    enabled=random_touch,
                )
                operation = device_service.tap(x, y)
                context.emit(
                    "device_action",
                    "Selected an experience-material card for sale.",
                    data={
                        "role": "select_sell_card",
                        "slot": slot.get("slot"),
                        "star": slot.get("star"),
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
                actions.append("select_sell_card")
                selected_slots.append(int(slot["slot"]))
                context.sleep(
                    randomized_wait_seconds(action_wait_seconds, random_time)
                )
            report = inspect("submit")
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
            or "jd" not in initial_match_names
        ):
            return finish(
                completed=False,
                stopped=True,
                reason="no_actionable_selection",
                report=report,
            )
        if not tap_match(report, "jd", "submit_sell_selection"):
            return finish(
                completed=False,
                stopped=True,
                reason="device_action_failed",
                report=report,
            )

        report = inspect("execute")
        match_names = {
            match.get("name")
            for match in report.get("matches", [])
            if isinstance(match, dict)
        }
        if report.get("flow") != "sell" or "destroy" not in match_names:
            return finish(
                completed=False,
                stopped=True,
                reason="confirmation_not_detected",
                report=report,
            )
        if not tap_match(report, "destroy", "execute_sell"):
            return finish(
                completed=False,
                stopped=True,
                reason="device_action_failed",
                report=report,
            )

        report = inspect("result")
        match_names = {
            match.get("name")
            for match in report.get("matches", [])
            if isinstance(match, dict)
        }
        if "qpfull" in match_names:
            if not allow_qp_full:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="qp_full",
                    report=report,
                )
            if not tap_point(_QP_FULL_CONFIRM_POINT, "confirm_qp_full"):
                return finish(
                    completed=False,
                    stopped=True,
                    reason="device_action_failed",
                    report=report,
                )
            report = inspect("result")
            match_names = {
                match.get("name")
                for match in report.get("matches", [])
                if isinstance(match, dict)
            }
        if "ljbhclose" not in match_names:
            return finish(
                completed=False,
                stopped=True,
                reason="sale_result_not_detected",
                report=report,
            )
        if not tap_match(report, "ljbhclose", "close_sell_result"):
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


def _boolean(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean.")
    return value


def _parse_card_stars(payload: dict[str, Any]) -> tuple[int, ...] | None:
    if "stars" not in payload or payload["stars"] is None:
        return None
    raw = payload["stars"]
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ValueError("stars must be a non-empty list of 3, 4, or 5.")
    result: list[int] = []
    for item in raw:
        if (
            isinstance(item, bool)
            or not isinstance(item, int)
            or item not in _VALID_CARD_STARS
        ):
            raise ValueError("stars must contain only 3, 4, or 5.")
        if item not in result:
            result.append(item)
    return tuple(result)
