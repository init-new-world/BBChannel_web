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
EXPBALL_STORAGE_GRID_INSPECT_JOB_KIND = "event.expball.inspect-storage-grid"
EXPBALL_SERVANT_GRID_INSPECT_JOB_KIND = "event.expball.inspect-servant-grid"
EXPBALL_SERVANT_LEVEL_INSPECT_JOB_KIND = "event.expball.inspect-servant-level"
EXPBALL_STORAGE_JOB_KIND = "event.expball.storage"
EXPBALL_SUMMON_JOB_KIND = "event.expball.summon"
EXPBALL_ENHANCE_JOB_KIND = "event.expball.enhance"
_SUMMON_REQUEST_ACTIONS = {"summon_free_ten", "summon_ten"}
_VALID_CARD_STARS = {3, 4, 5}
_ENHANCE_TARGETS = {"equipment", "servant"}
_ENHANCE_ADD_BASE_POINT = (197, 157)
_ENHANCE_FIRST_CARD_POINT = (135, 243)
_ENHANCE_OPEN_SLOTS_POINT = (823, 283)
_ENHANCE_RECOMMEND_POINT = (1090, 163)
_ENHANCE_SERVANT_RECOMMEND_POINT = (1217, 167)
_ENHANCE_EXECUTE_POINT = (1140, 670)
_ENHANCE_SKIP_ANIMATION_POINT = (823, 498)
_ENHANCE_LIMIT_BREAK_POINT = (1050, 557)
_ENHANCE_SKIP_LIMIT_BREAK_POINT = (633, 257)
_ENHANCE_RETURN_FROM_LIMIT_BREAK_POINT = (1047, 285)


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


def create_expball_storage_grid_inspect_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        normalized_name = setting_name.strip()
        threshold = _number(payload, "threshold", 0.75, 0, 1)
        server = str(
            script_data.get_setting_plan(normalized_name)["server"]
        ).upper()
        context.checkpoint(
            "inspect_expball_storage_grid",
            progress=0.2,
            message="Inspecting visible experience-material storage cards.",
        )
        report = recognizer.recognize_storage_grid(
            device_service.snapshot(),
            threshold=threshold,
        )
        context.emit(
            "expball_storage_grid",
            "Visible experience-material storage cards were inspected.",
            data={"server": server, **report},
        )
        context.checkpoint(
            "complete",
            progress=1.0,
            message="Experience-material storage grid inspection completed.",
        )
        return {
            "setting_name": normalized_name,
            "server": server,
            **report,
        }

    return handler


def register_expball_storage_grid_inspect_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
) -> None:
    if job_manager.has_kind(EXPBALL_STORAGE_GRID_INSPECT_JOB_KIND):
        return
    job_manager.register(
        EXPBALL_STORAGE_GRID_INSPECT_JOB_KIND,
        create_expball_storage_grid_inspect_handler(
            script_data,
            device_service,
            recognizer,
        ),
        requires_device=True,
    )


def create_expball_servant_grid_inspect_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        normalized_name = setting_name.strip()
        fp_gold_threshold = _number(payload, "fp_gold_threshold", 0.85, 0, 1)
        server = str(
            script_data.get_setting_plan(normalized_name)["server"]
        ).upper()
        context.checkpoint(
            "inspect_expball_servant_grid",
            progress=0.2,
            message="Inspecting visible servant sale grid cards.",
        )
        report = recognizer.recognize_servant_sale_grid(
            device_service.snapshot(),
            fp_gold_threshold=fp_gold_threshold,
        )
        context.emit(
            "expball_servant_grid",
            "Visible servant sale grid cards were inspected.",
            data={"server": server, **report},
        )
        context.checkpoint(
            "complete",
            progress=1.0,
            message="Servant sale grid inspection completed.",
        )
        return {
            "setting_name": normalized_name,
            "server": server,
            **report,
        }

    return handler


def register_expball_servant_grid_inspect_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
) -> None:
    if job_manager.has_kind(EXPBALL_SERVANT_GRID_INSPECT_JOB_KIND):
        return
    job_manager.register(
        EXPBALL_SERVANT_GRID_INSPECT_JOB_KIND,
        create_expball_servant_grid_inspect_handler(
            script_data,
            device_service,
            recognizer,
        ),
        requires_device=True,
    )


def create_expball_servant_level_inspect_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        normalized_name = setting_name.strip()
        threshold = _number(payload, "threshold", 0.6, 0, 1)
        server = str(
            script_data.get_setting_plan(normalized_name)["server"]
        ).upper()
        context.checkpoint(
            "inspect_expball_servant_level",
            progress=0.2,
            message="Inspecting servant enhancement level digits.",
        )
        report = recognizer.recognize_servant_level(
            device_service.snapshot(),
            threshold=threshold,
        )
        context.emit(
            "expball_servant_level",
            "Servant enhancement level digits were inspected.",
            data={"server": server, **report},
        )
        context.checkpoint(
            "complete",
            progress=1.0,
            message="Servant enhancement level inspection completed.",
        )
        return {
            "setting_name": normalized_name,
            "server": server,
            **report,
        }

    return handler


def register_expball_servant_level_inspect_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
) -> None:
    if job_manager.has_kind(EXPBALL_SERVANT_LEVEL_INSPECT_JOB_KIND):
        return
    job_manager.register(
        EXPBALL_SERVANT_LEVEL_INSPECT_JOB_KIND,
        create_expball_servant_level_inspect_handler(
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
        grid_threshold = _number(payload, "grid_threshold", 0.75, 0, 1)
        stars = _parse_card_stars(payload)
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
        selected_slots: list[int] = []
        selection_applied = False
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
                "selected_slots": list(selected_slots),
                "selected_count": len(selected_slots),
                "last_report": report,
            }

        while monotonic() - started <= timeout_seconds:
            attempts += 1
            context.checkpoint(
                f"store_expball_{phase}",
                progress=min((monotonic() - started) / timeout_seconds, 0.95),
            )
            screenshot = device_service.snapshot()
            report = recognizer.recognize(
                screenshot,
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

            if (
                phase == "submit"
                and stars is not None
                and not selection_applied
                and "in_store" in matches
            ):
                grid_report = recognizer.recognize_storage_grid(
                    screenshot,
                    threshold=grid_threshold,
                )
                context.emit(
                    "expball_storage_grid",
                    "Visible experience-material storage cards were inspected.",
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
                        "Selected an experience-material card for storage.",
                        data={
                            "role": "select_storage_card",
                            "phase": phase,
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
                    actions.append("select_storage_card")
                    selected_slots.append(int(slot["slot"]))
                    context.sleep(
                        randomized_wait_seconds(action_wait_seconds, random_time)
                    )
                selection_applied = True
                idle_polls = 0
                continue

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


def create_expball_enhance_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        normalized_name = setting_name.strip()
        target = str(payload.get("target") or "equipment").strip().lower()
        if target not in _ENHANCE_TARGETS:
            raise ValueError("target must be equipment or servant.")
        selection_mode_raw = (
            payload.get("selection_mode")
            if payload.get("selection_mode") is not None
            else payload.get("material_select_mode")
        )
        stars = _parse_card_stars(payload)
        if selection_mode_raw is None:
            selection_mode = "grid" if stars is not None else "auto"
        else:
            selection_mode = str(selection_mode_raw).strip().lower()
        if selection_mode not in {"auto", "grid"}:
            raise ValueError("selection_mode must be auto or grid.")
        target_level: int | None = None
        if payload.get("target_level") is not None:
            target_level = _integer(payload, "target_level", 100, 1, 120)
        auto_limit_break_raw = payload.get("auto_limit_break")
        if auto_limit_break_raw is None:
            auto_limit_break = bool(target == "servant")
        elif not isinstance(auto_limit_break_raw, bool):
            raise ValueError("auto_limit_break must be a boolean.")
        else:
            auto_limit_break = auto_limit_break_raw
        max_batches = _integer(payload, "max_batches", 1, 1, 1000)
        threshold = _number(payload, "threshold", 0.84, 0, 1)
        grid_threshold = _number(payload, "grid_threshold", 0.75, 0, 1)
        level_threshold = _number(payload, "level_threshold", 0.6, 0, 1)
        timeout_seconds = _number(payload, "timeout_seconds", 180, 0.1, 3600)
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
        batches_completed = 0
        limit_breaks_completed = 0
        actions: list[str] = []
        selected_slots: list[int] = []
        materials_selected = False
        grid_cards_tapped = False
        pending_animation_skip = False
        pending_limit_break_animation_skip = False
        in_limit_break = False
        idle_polls = 0
        last_report: dict[str, Any] | None = None
        last_level_report: dict[str, Any] | None = None

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
                    "Enhancement automation completed."
                    if completed
                    else "Enhancement automation stopped."
                ),
            )
            return {
                "setting_name": normalized_name,
                "target": target,
                "selection_mode": selection_mode,
                "material_select_mode": selection_mode,
                "target_level": target_level,
                "auto_limit_break": auto_limit_break,
                "max_batches": max_batches,
                "batches_completed": batches_completed,
                "limit_breaks_completed": limit_breaks_completed,
                "completed": completed,
                "stopped": stopped,
                "reason": reason,
                "attempts": attempts,
                "actions": list(actions),
                "selected_slots": list(selected_slots),
                "selected_count": len(selected_slots),
                "servant_level": last_level_report,
                "last_level_report": last_level_report,
                "last_report": report,
            }

        def tap_point(
            point: list[int] | tuple[int, int],
            role: str,
            *,
            size: list[int] | tuple[int, int] | None = None,
            extra: dict[str, Any] | None = None,
        ) -> bool:
            x, y = randomized_touch_point(
                point,
                enabled=random_touch,
                size=size,
            )
            operation = device_service.tap(x, y)
            event_data: dict[str, Any] = {
                "role": role,
                "target": target,
                "batches_completed": batches_completed,
                "limit_breaks_completed": limit_breaks_completed,
                "operation": operation.to_dict(),
            }
            if extra:
                event_data.update(extra)
            context.emit(
                "device_action",
                "Executed an enhancement automation action.",
                data=event_data,
            )
            if not operation.ok:
                return False
            actions.append(role)
            context.sleep(
                randomized_wait_seconds(action_wait_seconds, random_time)
            )
            return True

        def inspect_level_if_needed(
            screenshot: bytes,
            matches: dict[str, dict[str, Any]],
        ) -> bool:
            nonlocal last_level_report
            if (
                target != "servant"
                or target_level is None
                or any(
                    overlay in matches
                    for overlay in (
                        "exlevel",
                        "feedjd",
                        "qhjd2",
                        "xzdx",
                        "tysd",
                        "qhjd",
                        "qdjqh",
                        "gotoqhcz",
                    )
                )
                or not (
                    "help" in matches
                    or "slot" in matches
                    or "sbzl" in matches
                    or "ljzl" in matches
                )
            ):
                return False
            level_report = recognizer.recognize_servant_level(
                screenshot,
                threshold=level_threshold,
            )
            last_level_report = level_report
            context.emit(
                "expball_servant_level",
                "Servant enhancement level digits were inspected.",
                data={
                    "server": server,
                    "target_level": target_level,
                    **level_report,
                },
            )
            current_level = level_report.get("current_level")
            valid = level_report.get("valid", True)
            if not valid or not isinstance(current_level, int):
                return False
            if current_level >= target_level:
                return True
            if auto_limit_break and ("sbzl" in matches or "ljzl" in matches):
                return False
            return bool(level_report.get("is_max_level") is True)

        while monotonic() - started <= timeout_seconds:
            attempts += 1
            context.checkpoint(
                "enhance_expball",
                progress=min((monotonic() - started) / timeout_seconds, 0.95),
            )
            screenshot = device_service.snapshot()
            report = recognizer.recognize(
                screenshot,
                server,
                threshold=threshold,
            )
            last_report = report
            context.emit(
                "expball_state",
                "Enhancement workflow state was recognized.",
                data={
                    "attempt": attempts,
                    "target": target,
                    "batches_completed": batches_completed,
                    "limit_breaks_completed": limit_breaks_completed,
                    **report,
                },
            )
            status = str(report.get("status") or "unknown")
            flow = str(report.get("flow") or "unknown")
            matches = {
                match.get("name"): match
                for match in report.get("matches", [])
                if isinstance(match, dict) and isinstance(match.get("name"), str)
            }

            if pending_limit_break_animation_skip:
                if any(
                    name in matches
                    for name in (
                        "gotoqhcz",
                        "help",
                        "slot",
                        "exlevel",
                        "sbzl",
                        "ljzl",
                    )
                ):
                    pending_limit_break_animation_skip = False
                    materials_selected = False
                    grid_cards_tapped = False
                else:
                    if not tap_point(
                        _ENHANCE_SKIP_LIMIT_BREAK_POINT,
                        "skip_limit_break_animation",
                    ):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    idle_polls = 0
                    continue

            if pending_animation_skip:
                if any(
                    name in matches
                    for name in ("help", "slot", "exlevel", "sbzl", "ljzl")
                ):
                    pending_animation_skip = False
                    materials_selected = False
                    grid_cards_tapped = False
                    if inspect_level_if_needed(screenshot, matches):
                        return finish(
                            completed=True,
                            stopped=False,
                            reason="target_level_reached",
                            report=report,
                        )
                    if batches_completed >= max_batches and not (
                        auto_limit_break
                        and ("sbzl" in matches or "ljzl" in matches)
                    ):
                        return finish(
                            completed=True,
                            stopped=False,
                            reason="batch_limit",
                            report=report,
                        )
                else:
                    if not tap_point(
                        _ENHANCE_SKIP_ANIMATION_POINT,
                        "skip_enhancement_animation",
                    ):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    idle_polls = 0
                    continue

            if status == "blocked":
                return finish(
                    completed=False,
                    stopped=True,
                    reason=str(report.get("reason") or "blocked"),
                    report=report,
                )
            if "qpfull" in matches:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="qp_full",
                    report=report,
                )
            if "ljbhclose" in matches or "sure" in matches:
                modal_key = "sure" if "sure" in matches else "ljbhclose"
                close_target = matches[modal_key]
                close_center = close_target.get("center") or (640, 563)
                role = (
                    "close_empty_materials_dialog"
                    if modal_key == "sure"
                    else "close_empty_materials"
                )
                if not tap_point(
                    close_center,
                    role,
                    size=close_target.get("size"),
                ):
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="device_action_failed",
                        report=report,
                    )
                return finish(
                    completed=True,
                    stopped=False,
                    reason="materials_exhausted",
                    report=report,
                )

            if flow in {"summon", "sell", "storage"}:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="outside_enhancement_flow",
                    report=report,
                )

            if (
                not materials_selected
                and not in_limit_break
                and inspect_level_if_needed(screenshot, matches)
            ):
                return finish(
                    completed=True,
                    stopped=False,
                    reason="target_level_reached",
                    report=report,
                )

            acted = False
            if "gotoqhcz" in matches:
                goto_target = matches["gotoqhcz"]
                goto_center = (
                    goto_target.get("center")
                    or _ENHANCE_RETURN_FROM_LIMIT_BREAK_POINT
                )
                if not tap_point(
                    goto_center,
                    "return_to_servant_enhancement",
                    size=goto_target.get("size"),
                ):
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="device_action_failed",
                        report=report,
                    )
                in_limit_break = False
                materials_selected = False
                grid_cards_tapped = False
                acted = True
            elif "qhjd2" in matches:
                confirm_target = matches["qhjd2"]
                confirm_center = confirm_target.get("center") or (840, 590)
                if in_limit_break:
                    if not tap_point(
                        confirm_center,
                        "confirm_limit_break",
                        size=confirm_target.get("size"),
                    ):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    limit_breaks_completed += 1
                    pending_limit_break_animation_skip = True
                    in_limit_break = False
                else:
                    if not tap_point(
                        confirm_center,
                        "confirm_enhancement",
                        size=confirm_target.get("size"),
                    ):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    batches_completed += 1
                    pending_animation_skip = True
                materials_selected = False
                grid_cards_tapped = False
                acted = True
            elif "qdjqh" in matches:
                if not tap_point(
                    _ENHANCE_EXECUTE_POINT,
                    "execute_limit_break",
                ):
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="device_action_failed",
                        report=report,
                    )
                in_limit_break = True
                acted = True
            elif "ljzl" in matches or "sbzl" in matches:
                if not auto_limit_break:
                    return finish(
                        completed=False,
                        stopped=True,
                        reason=(
                            "grail_limit"
                            if "ljzl" in matches
                            else "ascension_limit"
                        ),
                        report=report,
                    )
                limit_key = "ljzl" if "ljzl" in matches else "sbzl"
                limit_target = matches[limit_key]
                limit_center = (
                    limit_target.get("center") or _ENHANCE_LIMIT_BREAK_POINT
                )
                if not tap_point(
                    limit_center,
                    "open_limit_break",
                    size=limit_target.get("size"),
                ):
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="device_action_failed",
                        report=report,
                    )
                in_limit_break = True
                materials_selected = False
                grid_cards_tapped = False
                acted = True
            elif "feedjd" in matches:
                feed_target = matches["feedjd"]
                feed_center = feed_target.get("center") or (840, 633)
                if not tap_point(
                    feed_center,
                    "confirm_auto_select",
                    size=feed_target.get("size"),
                ):
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="device_action_failed",
                        report=report,
                    )
                materials_selected = True
                acted = True
            elif "xzdx" in matches:
                if not tap_point(
                    _ENHANCE_FIRST_CARD_POINT,
                    "select_base_card",
                ):
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="device_action_failed",
                        report=report,
                    )
                materials_selected = False
                grid_cards_tapped = False
                acted = True
            elif "tysd" in matches or "qhjd" in matches:
                if not grid_cards_tapped:
                    if stars is not None:
                        grid_report = recognizer.recognize_storage_grid(
                            screenshot,
                            threshold=grid_threshold,
                        )
                        context.emit(
                            "expball_storage_grid",
                            "Visible experience-material cards were inspected.",
                            data={
                                "server": server,
                                "stars": list(stars),
                                **grid_report,
                            },
                        )
                        matching_slots = [
                            slot
                            for slot in grid_report.get("slots", [])
                            if isinstance(slot, dict)
                            and slot.get("star") in stars
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
                            if (
                                not isinstance(slot_center, list)
                                or len(slot_center) != 2
                            ):
                                return finish(
                                    completed=False,
                                    stopped=True,
                                    reason="invalid_recognition_result",
                                    report=report,
                                )
                            if not tap_point(
                                slot_center,
                                "select_material_card",
                                extra={
                                    "slot": slot.get("slot"),
                                    "star": slot.get("star"),
                                },
                            ):
                                return finish(
                                    completed=False,
                                    stopped=True,
                                    reason="device_action_failed",
                                    report=report,
                                )
                            selected_slots.append(int(slot["slot"]))
                    else:
                        if not tap_point(
                            _ENHANCE_FIRST_CARD_POINT,
                            "select_material_card",
                        ):
                            return finish(
                                completed=False,
                                stopped=True,
                                reason="device_action_failed",
                                report=report,
                            )
                    grid_cards_tapped = True
                    acted = True
                if "qhjd" in matches:
                    submit_target = matches["qhjd"]
                    submit_center = submit_target.get("center") or (1155, 672)
                    if not tap_point(
                        submit_center,
                        "confirm_material_selection",
                        size=submit_target.get("size"),
                    ):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    materials_selected = True
                    grid_cards_tapped = False
                    acted = True
            elif "exlevel" in matches:
                if not tap_point(
                    _ENHANCE_ADD_BASE_POINT,
                    "open_base_selection",
                ):
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="device_action_failed",
                        report=report,
                    )
                materials_selected = False
                grid_cards_tapped = False
                acted = True
            elif "slot" in matches and not materials_selected:
                if selection_mode == "grid":
                    slot_target = matches["slot"]
                    slot_center = (
                        slot_target.get("center") or _ENHANCE_OPEN_SLOTS_POINT
                    )
                    if not tap_point(
                        slot_center,
                        "open_material_slots",
                        size=slot_target.get("size"),
                    ):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    grid_cards_tapped = False
                    acted = True
                else:
                    recommend_point = (
                        _ENHANCE_SERVANT_RECOMMEND_POINT
                        if target == "servant" and server != "JP"
                        else _ENHANCE_RECOMMEND_POINT
                    )
                    if not tap_point(
                        recommend_point,
                        "auto_select_materials",
                    ):
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="device_action_failed",
                            report=report,
                        )
                    acted = True
            elif "help" in matches or (
                "slot" in matches and materials_selected
            ):
                if not tap_point(
                    _ENHANCE_EXECUTE_POINT,
                    "execute_enhancement",
                ):
                    return finish(
                        completed=False,
                        stopped=True,
                        reason="device_action_failed",
                        report=report,
                    )
                acted = True

            if acted:
                idle_polls = 0
                continue
            idle_polls += 1
            if idle_polls >= max_idle_polls:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="no_actionable_enhancement",
                    report=report,
                )
            context.sleep(randomized_wait_seconds(poll_interval, random_time))

        raise TimeoutError(
            "Enhancement automation did not finish within "
            f"{timeout_seconds:.2f} seconds. Last report: {last_report}"
        )

    return handler


def register_expball_enhance_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
) -> None:
    if job_manager.has_kind(EXPBALL_ENHANCE_JOB_KIND):
        return
    job_manager.register(
        EXPBALL_ENHANCE_JOB_KIND,
        create_expball_enhance_handler(
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
