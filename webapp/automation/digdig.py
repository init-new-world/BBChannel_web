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
from webapp.services.digdig import (
    DigdigRecognizer,
    normalize_digdig_extra_targets,
    normalize_digdig_piece_targets,
)
from webapp.services.script_data import ScriptDataService


DIGDIG_BOARD_GRID_INSPECT_JOB_KIND = "event.digdig.inspect-board-grid"
DIGDIG_EXECUTE_JOB_KIND = "event.digdig.execute"
DIGDIG_INSPECT_JOB_KIND = "event.digdig.inspect"
DIGDIG_RUN_JOB_KIND = "event.digdig.run"

_DIGDIG_TOUCH_TARGETS: dict[str, tuple[list[int], list[int]]] = {
    "free_dig": ([1070, 200], [86, 26]),
    "execute_dig": ([840, 563], [200, 53]),
    "go_ahead": ([640, 637], [200, 53]),
    "checkmark": ([205, 416], [25, 26]),
    "confirm": ([468, 508], [123, 43]),
    "reset_board": ([1202, 200], [90, 26]),
}


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


def create_digdig_board_grid_inspect_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: DigdigRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        normalized_name = setting_name.strip()
        threshold = _number(payload, "threshold", 0.7, 0, 1)
        server = str(
            script_data.get_setting_plan(normalized_name)["server"]
        ).upper()
        context.checkpoint(
            "inspect_digdig_board_grid",
            progress=0.2,
            message="Inspecting the 28-cell excavation board grid.",
        )
        report = recognizer.recognize_board_grid(
            device_service.snapshot(),
            server,
            threshold=threshold,
        )
        context.emit(
            "digdig_board_grid",
            "Excavation board grid and intersection slots were inspected.",
            data=report,
        )
        context.checkpoint(
            "complete",
            progress=1.0,
            message="Excavation board grid inspection completed.",
        )
        return {"setting_name": normalized_name, **report}

    return handler


def register_digdig_board_grid_inspect_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: DigdigRecognizer,
) -> None:
    if job_manager.has_kind(DIGDIG_BOARD_GRID_INSPECT_JOB_KIND):
        return
    job_manager.register(
        DIGDIG_BOARD_GRID_INSPECT_JOB_KIND,
        create_digdig_board_grid_inspect_handler(
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


def create_digdig_run_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: DigdigRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        normalized_name = setting_name.strip()

        target_piece_ids = normalize_digdig_piece_targets(
            payload.get("target_pieces")
        )
        target_extra_ids = normalize_digdig_extra_targets(
            payload.get("target_extras")
        )
        default_one_key = not target_piece_ids and not target_extra_ids
        one_key = payload.get("one_key", default_one_key)
        if not isinstance(one_key, bool):
            raise ValueError("one_key must be a boolean.")
        if not one_key and not target_piece_ids and not target_extra_ids:
            raise ValueError(
                "Enable one_key or select at least one target piece or extra material."
            )

        reset_board = payload.get("reset_board", True)
        if not isinstance(reset_board, bool):
            raise ValueError("reset_board must be a boolean.")
        threshold = _number(payload, "threshold", 0.82, 0, 1)
        board_threshold = _number(payload, "board_threshold", 0.7, 0, 1)
        max_cycles = _integer(payload, "max_cycles", 1, 1, 200)
        timeout_seconds = _number(payload, "timeout_seconds", 60, 0.1, 600)
        poll_interval = _number(payload, "poll_interval", 0.5, 0, 10)
        action_wait_seconds = _number(
            payload,
            "action_wait_seconds",
            0.8,
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
        cycles_completed = 0
        dug_cells: list[int] = []
        matched_intersections: list[int] = []
        last_report: dict[str, Any] | None = None
        last_board_report: dict[str, Any] | None = None

        def check_timeout() -> None:
            if monotonic() - started > timeout_seconds:
                raise TimeoutError(
                    "Excavation automation did not finish within "
                    f"{timeout_seconds:.2f} seconds. Last report: {last_report}"
                )

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
                    "Excavation automation completed."
                    if completed
                    else "Excavation automation stopped."
                ),
            )
            return {
                "setting_name": normalized_name,
                "mode": "one_key" if one_key else "filter",
                "one_key": one_key,
                "target_piece_ids": target_piece_ids,
                "target_extra_ids": target_extra_ids,
                "completed": completed,
                "stopped": stopped,
                "reason": reason,
                "cycles_completed": cycles_completed,
                "dug_cells": list(dug_cells),
                "matched_intersections": list(matched_intersections),
                "attempts": attempts,
                "actions": list(actions),
                "last_report": last_report,
                "last_board_report": last_board_report,
            }

        def tap_target(
            role: str,
            center: list[int],
            size: list[int] | None = None,
        ) -> bool:
            check_timeout()
            x, y = randomized_touch_point(
                center,
                enabled=random_touch,
                size=size,
            )
            operation = device_service.tap(x, y)
            context.emit(
                "device_action",
                f"Executed excavation action {role}.",
                data={"role": role, "operation": operation.to_dict()},
            )
            if not operation.ok:
                return False
            actions.append(role)
            context.sleep(
                randomized_wait_seconds(action_wait_seconds, random_time)
            )
            return True

        def inspect_state(phase_label: str) -> dict[str, Any]:
            nonlocal attempts, last_report
            check_timeout()
            attempts += 1
            context.checkpoint(
                f"run_digdig_{phase_label}",
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
                "Excavation state was recognized.",
                data={"attempt": attempts, "phase": phase_label, **report},
            )
            return report

        def inspect_board(phase_label: str) -> dict[str, Any]:
            nonlocal attempts, last_board_report
            check_timeout()
            attempts += 1
            context.checkpoint(
                f"run_digdig_{phase_label}",
                progress=min((monotonic() - started) / timeout_seconds, 0.95),
            )
            board_report = recognizer.recognize_board_grid(
                device_service.snapshot(),
                server,
                threshold=board_threshold,
            )
            last_board_report = board_report
            context.emit(
                "digdig_board_grid",
                "Excavation board grid was recognized.",
                data={"attempt": attempts, "phase": phase_label, **board_report},
            )
            return board_report

        def execute_button_target(
            report: dict[str, Any],
        ) -> tuple[list[int], list[int] | None]:
            primary = next(
                (
                    match
                    for match in report.get("matches", [])
                    if match.get("name") == "execute"
                ),
                None,
            )
            if isinstance(primary, dict):
                center = primary.get("center")
                size = primary.get("size")
                if isinstance(center, list) and len(center) == 2:
                    return center, size if isinstance(size, list) else None
            return _DIGDIG_TOUCH_TARGETS["execute_dig"]

        def dismiss_result_overlay() -> tuple[bool, str | None]:
            center, size = _DIGDIG_TOUCH_TARGETS["go_ahead"]
            for _ in range(max_idle_polls):
                if not tap_target("go_ahead", center, size):
                    return False, "device_action_failed"
                report = inspect_state("dismiss_result")
                if str(report.get("state") or "unknown") not in {
                    "digResult",
                    "reward",
                }:
                    return True, None
                context.sleep(randomized_wait_seconds(poll_interval, random_time))
            return True, None

        def handle_confirm_dialog(state: str, phase_prefix: str) -> bool:
            if state == "needConfirm":
                check_center, check_size = _DIGDIG_TOUCH_TARGETS["checkmark"]
                if not tap_target("checkmark", check_center, check_size):
                    return False
                inspect_state(f"{phase_prefix}_checkmark")
            confirm_center, confirm_size = _DIGDIG_TOUCH_TARGETS["confirm"]
            return tap_target("confirm", confirm_center, confirm_size)

        if one_key:
            free_center, free_size = _DIGDIG_TOUCH_TARGETS["free_dig"]
            while cycles_completed < max_cycles:
                execute_report: dict[str, Any] | None = None
                for _ in range(max_idle_polls):
                    if not tap_target("free_dig", free_center, free_size):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                        )
                    report = inspect_state("wait_free_dig_execute")
                    if str(report.get("state") or "unknown") == "execute":
                        execute_report = report
                        break
                    context.sleep(
                        randomized_wait_seconds(poll_interval, random_time)
                    )
                if execute_report is None:
                    return finish(
                        completed=cycles_completed > 0,
                        stopped=cycles_completed == 0,
                        reason="execute_not_detected",
                    )

                exec_center, exec_size = execute_button_target(execute_report)
                if not tap_target("execute_dig", exec_center, exec_size):
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="device_action_failed",
                    )

                result_detected = False
                for _ in range(max_idle_polls):
                    report = inspect_state("wait_one_key_result")
                    state = str(report.get("state") or "unknown")
                    if state in {"digResult", "reward"}:
                        ok, err = dismiss_result_overlay()
                        if not ok:
                            return finish(
                                completed=False,
                                stopped=True,
                                reason=err or "device_action_failed",
                            )
                        cycles_completed += 1
                        result_detected = True
                        break
                    if state in {"needConfirm", "checkmark"}:
                        if not handle_confirm_dialog(state, "one_key"):
                            return finish(
                                completed=False,
                                stopped=True,
                                reason="device_action_failed",
                            )
                        continue
                    context.sleep(
                        randomized_wait_seconds(poll_interval, random_time)
                    )
                if not result_detected:
                    return finish(
                        completed=cycles_completed > 0,
                        stopped=cycles_completed == 0,
                        reason="tools_exhausted",
                    )

            return finish(
                completed=True,
                stopped=False,
                reason="max_cycles_reached",
            )

        while cycles_completed < max_cycles:
            board_report = inspect_board(f"cycle_{cycles_completed + 1}_board")
            dug_slots: set[int] = {
                int(slot_entry["slot"])
                for slot_entry in board_report.get("slots", [])
                if slot_entry.get("dug")
            }
            dug_in_cycle = 0

            def dig_cell(slot: int) -> tuple[bool, str | None]:
                nonlocal dug_in_cycle
                x, y, width, height = recognizer.board_cell_roi(slot)
                cell_center = [x + width // 2, y + height // 2]
                cell_size = [max(width - 26, 1), max(height - 26, 1)]
                if not tap_target(f"dig_cell_{slot}", cell_center, cell_size):
                    return False, "device_action_failed"
                for _ in range(max_idle_polls):
                    report = inspect_state(f"wait_cell_{slot}")
                    state = str(report.get("state") or "unknown")
                    if state in {"digResult", "reward"}:
                        ok, err = dismiss_result_overlay()
                        if not ok:
                            return False, err or "device_action_failed"
                        dug_slots.add(slot)
                        dug_cells.append(slot)
                        dug_in_cycle += 1
                        return True, None
                    if state in {"needConfirm", "checkmark"}:
                        if not handle_confirm_dialog(state, f"cell_{slot}"):
                            return False, "device_action_failed"
                        continue
                    if state == "execute":
                        exec_center, exec_size = execute_button_target(report)
                        if not tap_target("execute_dig", exec_center, exec_size):
                            return False, "device_action_failed"
                        continue
                    context.sleep(
                        randomized_wait_seconds(poll_interval, random_time)
                    )
                return False, "tools_exhausted"

            for slot_entry in board_report.get("slots", []):
                slot = int(slot_entry["slot"])
                piece_id = slot_entry.get("piece_id")
                if slot not in dug_slots and piece_id in target_piece_ids:
                    ok, err = dig_cell(slot)
                    if not ok:
                        has_progress = bool(dug_cells) or cycles_completed > 0
                        return finish(
                            completed=has_progress and err == "tools_exhausted",
                            stopped=not (has_progress and err == "tools_exhausted"),
                            reason=err or "tools_exhausted",
                        )

            if target_extra_ids:
                if dug_in_cycle > 0:
                    board_report = inspect_board(
                        f"cycle_{cycles_completed + 1}_extra"
                    )
                tools_exhausted = False
                for index in range(18):
                    top_left = index + index // 6
                    surrounding = [
                        top_left,
                        top_left + 1,
                        top_left + 7,
                        top_left + 8,
                    ]
                    dug_surrounding = [
                        slot for slot in surrounding if slot in dug_slots
                    ]
                    if len(dug_surrounding) == 4:
                        continue
                    if len(dug_surrounding) == 0:
                        probe_slot = surrounding[3]
                        ok, err = dig_cell(probe_slot)
                        if not ok:
                            if err != "tools_exhausted":
                                return finish(
                                    completed=False,
                                    stopped=True,
                                    reason=err or "device_action_failed",
                                )
                            tools_exhausted = True
                            break
                        board_report = inspect_board(
                            f"cycle_{cycles_completed + 1}_probe_{index}"
                        )
                    intersections = board_report.get("intersections", [])
                    intersection_entry = (
                        intersections[index]
                        if index < len(intersections)
                        else {}
                    )
                    if intersection_entry.get("material_id") in target_extra_ids:
                        matched_intersections.append(index)
                        for slot in surrounding:
                            if slot in dug_slots:
                                continue
                            ok, err = dig_cell(slot)
                            if not ok:
                                if err != "tools_exhausted":
                                    return finish(
                                        completed=False,
                                        stopped=True,
                                        reason=err or "device_action_failed",
                                    )
                                tools_exhausted = True
                                break
                        if tools_exhausted:
                            break
                if tools_exhausted:
                    has_progress = bool(dug_cells) or cycles_completed > 0
                    return finish(
                        completed=has_progress,
                        stopped=not has_progress,
                        reason="tools_exhausted",
                    )

            should_reset = reset_board or (cycles_completed + 1 < max_cycles)
            if should_reset:
                reset_center, reset_size = _DIGDIG_TOUCH_TARGETS["reset_board"]
                reset_execute_report: dict[str, Any] | None = None
                for _ in range(max_idle_polls):
                    if not tap_target("reset_board", reset_center, reset_size):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                        )
                    report = inspect_state("wait_reset_execute")
                    if str(report.get("state") or "unknown") == "execute":
                        reset_execute_report = report
                        break
                    context.sleep(
                        randomized_wait_seconds(poll_interval, random_time)
                    )
                if reset_execute_report is None:
                    return finish(
                        completed=cycles_completed > 0,
                        stopped=cycles_completed == 0,
                        reason="reset_confirm_not_detected",
                    )
                exec_center, exec_size = execute_button_target(
                    reset_execute_report
                )
                if not tap_target("execute_reset", exec_center, exec_size):
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="device_action_failed",
                    )

            cycles_completed += 1

        return finish(
            completed=True,
            stopped=False,
            reason="max_cycles_reached",
        )

    return handler


def register_digdig_run_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: DigdigRecognizer,
) -> None:
    if job_manager.has_kind(DIGDIG_RUN_JOB_KIND):
        return
    job_manager.register(
        DIGDIG_RUN_JOB_KIND,
        create_digdig_run_handler(
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
