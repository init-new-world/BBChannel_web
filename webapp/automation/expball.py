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
EXPBALL_COMMAND_CODE_GRID_INSPECT_JOB_KIND = (
    "event.expball.inspect-command-code-grid"
)
EXPBALL_CE_BOMB_GRID_INSPECT_JOB_KIND = "event.expball.inspect-ce-bomb-grid"
EXPBALL_SERVANT_LEVEL_INSPECT_JOB_KIND = "event.expball.inspect-servant-level"
EXPBALL_SERVANT_TARGET_INSPECT_JOB_KIND = (
    "event.expball.inspect-servant-target"
)
EXPBALL_SUMMON_LOCK_INSPECT_JOB_KIND = (
    "event.expball.inspect-summon-lock-targets"
)
EXPBALL_STORAGE_JOB_KIND = "event.expball.storage"
EXPBALL_SUMMON_JOB_KIND = "event.expball.summon"
EXPBALL_ENHANCE_JOB_KIND = "event.expball.enhance"
_SUMMON_REQUEST_ACTIONS = {"summon_free_ten", "summon_ten"}
_SUMMON_LOCK_CARD_POINT = (32, 178)
_SUMMON_CLOSE_DETAIL_POINT = (43, 43)
_VALID_CARD_STARS = {3, 4, 5}
_STORAGE_TARGETS = {"exp", "ce_bomb"}
_ENHANCE_TARGETS = {"equipment", "servant"}
_CE_UNIFIED_LOCK_POINT = (32, 358)
_CE_UNIFIED_MARK_POINT = (32, 477)
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
_SERVANT_LIST_SWIPE_START = (527, 617)
_SERVANT_LIST_SWIPE_END = (527, 190)
_SERVANT_LIST_SWIPE_DURATION_MS = 500


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


def create_expball_command_code_grid_inspect_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        normalized_name = setting_name.strip()
        inscribed_threshold = _number(payload, "inscribed_threshold", 0.7, 0, 1)
        empty_threshold = _number(payload, "empty_threshold", 0.8, 0, 1)
        locker_threshold = _number(payload, "locker_threshold", 0.7, 0, 1)
        server = str(
            script_data.get_setting_plan(normalized_name)["server"]
        ).upper()
        context.checkpoint(
            "inspect_expball_command_code_grid",
            progress=0.2,
            message="Inspecting visible command-code sale grid cards.",
        )
        report = recognizer.recognize_command_code_sale_grid(
            device_service.snapshot(),
            server,
            inscribed_threshold=inscribed_threshold,
            empty_threshold=empty_threshold,
            locker_threshold=locker_threshold,
        )
        context.emit(
            "expball_command_code_grid",
            "Visible command-code sale grid cards were inspected.",
            data=report,
        )
        context.checkpoint(
            "complete",
            progress=1.0,
            message="Command-code sale grid inspection completed.",
        )
        return {
            "setting_name": normalized_name,
            **report,
        }

    return handler


def register_expball_command_code_grid_inspect_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
) -> None:
    if job_manager.has_kind(EXPBALL_COMMAND_CODE_GRID_INSPECT_JOB_KIND):
        return
    job_manager.register(
        EXPBALL_COMMAND_CODE_GRID_INSPECT_JOB_KIND,
        create_expball_command_code_grid_inspect_handler(
            script_data,
            device_service,
            recognizer,
        ),
        requires_device=True,
    )


def create_expball_ce_bomb_grid_inspect_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        normalized_name = setting_name.strip()
        locker_threshold = _number(payload, "locker_threshold", 0.7, 0, 1)
        mark_threshold = _number(payload, "mark_threshold", 0.6, 0, 1)
        server = str(
            script_data.get_setting_plan(normalized_name)["server"]
        ).upper()
        context.checkpoint(
            "inspect_expball_ce_bomb_grid",
            progress=0.2,
            message="Inspecting visible craft-essence bomb grid cards.",
        )
        report = recognizer.recognize_ce_bomb_grid(
            device_service.snapshot(),
            server,
            locker_threshold=locker_threshold,
            mark_threshold=mark_threshold,
        )
        context.emit(
            "expball_ce_bomb_grid",
            "Visible craft-essence bomb grid cards were inspected.",
            data=report,
        )
        context.checkpoint(
            "complete",
            progress=1.0,
            message="Craft-essence bomb grid inspection completed.",
        )
        return {
            "setting_name": normalized_name,
            **report,
        }

    return handler


def register_expball_ce_bomb_grid_inspect_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
) -> None:
    if job_manager.has_kind(EXPBALL_CE_BOMB_GRID_INSPECT_JOB_KIND):
        return
    job_manager.register(
        EXPBALL_CE_BOMB_GRID_INSPECT_JOB_KIND,
        create_expball_ce_bomb_grid_inspect_handler(
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


def create_expball_servant_target_inspect_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        normalized_name = setting_name.strip()
        raw_target = payload.get("target")
        if raw_target is not None and not isinstance(raw_target, str):
            raise ValueError("target must be a string when provided.")
        threshold = _number(payload, "threshold", 0.85, 0, 1)
        scroll_end_threshold = _number(
            payload,
            "scroll_end_threshold",
            0.8,
            0,
            1,
        )
        server = str(
            script_data.get_setting_plan(normalized_name)["server"]
        ).upper()
        context.checkpoint(
            "inspect_expball_servant_target",
            progress=0.2,
            message="Inspecting servant enhancement target selection.",
        )
        report = recognizer.recognize_servant_target(
            device_service.snapshot(),
            server,
            target=raw_target,
            threshold=threshold,
            scroll_end_threshold=scroll_end_threshold,
        )
        context.emit(
            "expball_servant_target",
            "Servant enhancement target selection was inspected.",
            data=report,
        )
        context.checkpoint(
            "complete",
            progress=1.0,
            message="Servant enhancement target inspection completed.",
        )
        return {
            "setting_name": normalized_name,
            **report,
        }

    return handler


def register_expball_servant_target_inspect_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
) -> None:
    if job_manager.has_kind(EXPBALL_SERVANT_TARGET_INSPECT_JOB_KIND):
        return
    job_manager.register(
        EXPBALL_SERVANT_TARGET_INSPECT_JOB_KIND,
        create_expball_servant_target_inspect_handler(
            script_data,
            device_service,
            recognizer,
        ),
        requires_device=True,
    )


def create_expball_summon_lock_inspect_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
):
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        normalized_name = setting_name.strip()
        threshold = _number(payload, "threshold", 0.8, 0, 1)
        raw_targets = payload.get("targets")
        if raw_targets is not None and not isinstance(
            raw_targets,
            (list, tuple),
        ):
            raise ValueError("targets must be a list of lock target names.")
        server = str(
            script_data.get_setting_plan(normalized_name)["server"]
        ).upper()
        context.checkpoint(
            "inspect_expball_summon_lock_targets",
            progress=0.2,
            message="Inspecting friendship-point summon lock target cards.",
        )
        report = recognizer.recognize_summon_lock_targets(
            device_service.snapshot(),
            targets=raw_targets,
            threshold=threshold,
        )
        context.emit(
            "expball_summon_lock_targets",
            "Friendship-point summon lock target cards were inspected.",
            data={"server": server, **report},
        )
        context.checkpoint(
            "complete",
            progress=1.0,
            message="Friendship-point summon lock target inspection completed.",
        )
        return {
            "setting_name": normalized_name,
            "server": server,
            **report,
        }

    return handler


def register_expball_summon_lock_inspect_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
) -> None:
    if job_manager.has_kind(EXPBALL_SUMMON_LOCK_INSPECT_JOB_KIND):
        return
    job_manager.register(
        EXPBALL_SUMMON_LOCK_INSPECT_JOB_KIND,
        create_expball_summon_lock_inspect_handler(
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
        lock_threshold = _number(payload, "lock_threshold", 0.8, 0, 1)
        lock_targets = _parse_summon_lock_targets(payload)
        lock_enough_stop_raw = payload.get("lock_enough_stop", False)
        if not isinstance(lock_enough_stop_raw, bool):
            raise ValueError("lock_enough_stop must be a boolean.")
        lock_enough_stop = lock_enough_stop_raw
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
        locked_cards: list[dict[str, Any]] = []
        phase = "request"
        pending_free_summon = False
        result_counted = False
        result_locked = False
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
                locked_cards=locked_cards,
                lock_targets=lock_targets,
                lock_enough_stop=lock_enough_stop,
                report=report,
            )

        def tap_point(
            point: list[int] | tuple[int, int],
            role: str,
            *,
            state_name: str | None = None,
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
                "state": state_name,
                "phase": phase,
                "operation": operation.to_dict(),
            }
            if extra:
                event_data.update(extra)
            context.emit(
                "device_action",
                "Executed a friendship-point summon action.",
                data=event_data,
            )
            if not operation.ok:
                return False
            actions.append(role)
            context.sleep(
                randomized_wait_seconds(action_wait_seconds, random_time)
            )
            return True

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
            return tap_point(
                center,
                role,
                state_name=str(report.get("state") or "unknown"),
                size=target.get("size"),
            )

        while monotonic() - started <= timeout_seconds:
            attempts += 1
            context.checkpoint(
                "summon_expball",
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

            if (
                lock_targets
                and lock_enough_stop
                and not any(item["remaining"] != 0 for item in lock_targets)
            ):
                return finish(
                    completed=True,
                    stopped=False,
                    reason="lock_target_reached",
                    report=report,
                )

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
                    result_locked = False
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
                active_targets = [
                    str(item["target"])
                    for item in lock_targets
                    if item["remaining"] != 0
                ]
                if active_targets and not result_locked:
                    lock_report = recognizer.recognize_summon_lock_targets(
                        screenshot,
                        targets=active_targets,
                        threshold=lock_threshold,
                    )
                    context.emit(
                        "expball_summon_lock_targets",
                        "Friendship-point summon lock target cards were inspected.",
                        data={
                            "attempt": attempts,
                            "summons": summons,
                            "server": server,
                            **lock_report,
                        },
                    )
                    for match_item in lock_report.get("matches", []):
                        if not isinstance(match_item, dict):
                            continue
                        matched_target = str(match_item.get("target") or "")
                        target_entry = next(
                            (
                                item
                                for item in lock_targets
                                if item["target"].lower()
                                == matched_target.lower()
                                and item["remaining"] != 0
                            ),
                            None,
                        )
                        if target_entry is None:
                            continue
                        card_center = match_item.get("center")
                        if (
                            not isinstance(card_center, list)
                            or len(card_center) != 2
                        ):
                            return finish(
                                completed=False,
                                stopped=True,
                                reason="invalid_recognition_result",
                                report=report,
                            )
                        if not tap_point(
                            card_center,
                            "open_summon_card_detail",
                            state_name=state,
                            size=match_item.get("size"),
                            extra={"target": target_entry["target"]},
                        ):
                            return finish(
                                completed=False,
                                stopped=True,
                                reason="device_action_failed",
                                report=report,
                            )
                        if not tap_point(
                            _SUMMON_LOCK_CARD_POINT,
                            "lock_summon_card",
                            state_name=state,
                            extra={"target": target_entry["target"]},
                        ):
                            return finish(
                                completed=False,
                                stopped=True,
                                reason="device_action_failed",
                                report=report,
                            )
                        if not tap_point(
                            _SUMMON_CLOSE_DETAIL_POINT,
                            "close_summon_card_detail",
                            state_name=state,
                            extra={"target": target_entry["target"]},
                        ):
                            return finish(
                                completed=False,
                                stopped=True,
                                reason="device_action_failed",
                                report=report,
                            )
                        locked_cards.append(
                            {
                                "target": target_entry["target"],
                                "center": [
                                    int(card_center[0]),
                                    int(card_center[1]),
                                ],
                                "template_path": match_item.get(
                                    "template_path"
                                ),
                            }
                        )
                        target_entry["locked"] = (
                            int(target_entry.get("locked", 0)) + 1
                        )
                        if int(target_entry["remaining"]) > 0:
                            target_entry["remaining"] = (
                                int(target_entry["remaining"]) - 1
                            )
                    result_locked = True
                    if lock_enough_stop and not any(
                        item["remaining"] != 0 for item in lock_targets
                    ):
                        return finish(
                            completed=True,
                            stopped=False,
                            reason="lock_target_reached",
                            report=report,
                        )
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
                        result_locked = False
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
                    result_locked = False
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
        storage_target = (
            str(payload.get("storage_target") or "exp").strip().lower()
        )
        if storage_target not in _STORAGE_TARGETS:
            raise ValueError("storage_target must be exp or ce_bomb.")
        require_locked_and_marked_raw = payload.get(
            "require_locked_and_marked",
            True,
        )
        if not isinstance(require_locked_and_marked_raw, bool):
            raise ValueError("require_locked_and_marked must be a boolean.")
        require_locked_and_marked = require_locked_and_marked_raw
        threshold = _number(payload, "threshold", 0.84, 0, 1)
        grid_threshold = _number(payload, "grid_threshold", 0.75, 0, 1)
        locker_threshold = _number(payload, "locker_threshold", 0.7, 0, 1)
        mark_threshold = _number(payload, "mark_threshold", 0.6, 0, 1)
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
                "storage_target": storage_target,
                "require_locked_and_marked": require_locked_and_marked,
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
                and storage_target == "ce_bomb"
                and not selection_applied
                and "in_store" in matches
            ):
                ce_grid_report = recognizer.recognize_ce_bomb_grid(
                    screenshot,
                    server,
                    locker_threshold=locker_threshold,
                    mark_threshold=mark_threshold,
                )
                context.emit(
                    "expball_ce_bomb_grid",
                    "Visible craft-essence bomb storage cards were inspected.",
                    data={
                        "storage_target": storage_target,
                        "require_locked_and_marked": require_locked_and_marked,
                        **ce_grid_report,
                    },
                )
                matching_slots = [
                    slot
                    for slot in ce_grid_report.get("slots", [])
                    if isinstance(slot, dict)
                    and (
                        slot.get("need_store") is True
                        if require_locked_and_marked
                        else slot.get("full_level") is True
                    )
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
                        "Selected a craft-essence bomb card for storage.",
                        data={
                            "role": "select_ce_bomb_storage_card",
                            "phase": phase,
                            "slot": slot.get("slot"),
                            "full_level": slot.get("full_level"),
                            "locked": slot.get("locked"),
                            "marked": slot.get("marked"),
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
                    actions.append("select_ce_bomb_storage_card")
                    selected_slots.append(int(slot["slot"]))
                    context.sleep(
                        randomized_wait_seconds(action_wait_seconds, random_time)
                    )
                selection_applied = True
                idle_polls = 0
                continue

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
        lock_full_ce_bombs_raw = payload.get("lock_full_ce_bombs", False)
        if not isinstance(lock_full_ce_bombs_raw, bool):
            raise ValueError("lock_full_ce_bombs must be a boolean.")
        lock_full_ce_bombs = lock_full_ce_bombs_raw
        mark_full_ce_bombs_raw = payload.get("mark_full_ce_bombs", False)
        if not isinstance(mark_full_ce_bombs_raw, bool):
            raise ValueError("mark_full_ce_bombs must be a boolean.")
        mark_full_ce_bombs = mark_full_ce_bombs_raw
        if selection_mode_raw is None:
            selection_mode = (
                "grid"
                if (
                    stars is not None
                    or lock_full_ce_bombs
                    or mark_full_ce_bombs
                )
                else "auto"
            )
        else:
            selection_mode = str(selection_mode_raw).strip().lower()
        if selection_mode not in {"auto", "grid"}:
            raise ValueError("selection_mode must be auto or grid.")
        target_level: int | None = None
        if payload.get("target_level") is not None:
            target_level = _integer(payload, "target_level", 100, 1, 120)
        servant_targets = _parse_servant_targets(payload, target_level)
        servant_target_threshold = _number(
            payload,
            "servant_target_threshold",
            0.85,
            0,
            1,
        )
        max_base_scrolls = _integer(payload, "max_base_scrolls", 10, 1, 100)
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
        locker_threshold = _number(payload, "locker_threshold", 0.7, 0, 1)
        mark_threshold = _number(payload, "mark_threshold", 0.6, 0, 1)
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
        locked_ce_bomb_slots: list[int] = []
        marked_ce_bomb_slots: list[int] = []
        selected_servant_targets: list[str] = []
        completed_servant_targets: list[str] = []
        missing_servant_targets: list[str] = []
        current_target_index = 0
        base_servant_selected = not bool(
            target == "servant" and servant_targets
        )
        base_scrolls = 0
        scroll_end_hits = 0
        materials_selected = False
        grid_cards_tapped = False
        ce_bombs_checked = False
        pending_animation_skip = False
        pending_limit_break_animation_skip = False
        in_limit_break = False
        idle_polls = 0
        last_report: dict[str, Any] | None = None
        last_level_report: dict[str, Any] | None = None
        last_servant_target_report: dict[str, Any] | None = None

        def active_servant_entry() -> dict[str, Any] | None:
            if target != "servant" or current_target_index >= len(servant_targets):
                return None
            return servant_targets[current_target_index]

        def active_target_level() -> int | None:
            entry = active_servant_entry()
            if entry is not None and entry.get("target_level") is not None:
                return int(entry["target_level"])
            return target_level

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
            entry = active_servant_entry()
            return {
                "setting_name": normalized_name,
                "target": target,
                "selection_mode": selection_mode,
                "material_select_mode": selection_mode,
                "target_level": active_target_level(),
                "servant_target": (
                    entry["target"]
                    if entry is not None
                    else (
                        selected_servant_targets[-1]
                        if selected_servant_targets
                        else None
                    )
                ),
                "servant_targets": [dict(item) for item in servant_targets],
                "selected_servant_targets": list(selected_servant_targets),
                "completed_servant_targets": list(completed_servant_targets),
                "missing_servant_targets": list(missing_servant_targets),
                "auto_limit_break": auto_limit_break,
                "lock_full_ce_bombs": lock_full_ce_bombs,
                "mark_full_ce_bombs": mark_full_ce_bombs,
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
                "locked_ce_bomb_slots": list(locked_ce_bomb_slots),
                "marked_ce_bomb_slots": list(marked_ce_bomb_slots),
                "servant_level": last_level_report,
                "last_level_report": last_level_report,
                "servant_target_report": last_servant_target_report,
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
            effective_level = active_target_level()
            if (
                target != "servant"
                or not base_servant_selected
                or effective_level is None
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
                    "target_level": effective_level,
                    **level_report,
                },
            )
            current_level = level_report.get("current_level")
            valid = level_report.get("valid", True)
            if not valid or not isinstance(current_level, int):
                return False
            if current_level >= effective_level:
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
                    ce_bombs_checked = False
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
                    ce_bombs_checked = False
                    if inspect_level_if_needed(screenshot, matches):
                        entry = active_servant_entry()
                        if entry is not None:
                            completed_servant_targets.append(entry["target"])
                            if current_target_index + 1 < len(servant_targets):
                                current_target_index += 1
                                base_servant_selected = False
                                base_scrolls = 0
                                scroll_end_hits = 0
                            else:
                                return finish(
                                    completed=True,
                                    stopped=False,
                                    reason="target_level_reached",
                                    report=report,
                                )
                        else:
                            return finish(
                                completed=True,
                                stopped=False,
                                reason="target_level_reached",
                                report=report,
                            )
                    if (
                        batches_completed >= max_batches
                        and base_servant_selected
                        and not (
                            auto_limit_break
                            and ("sbzl" in matches or "ljzl" in matches)
                        )
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
                entry = active_servant_entry()
                if entry is not None:
                    completed_servant_targets.append(entry["target"])
                    if current_target_index + 1 < len(servant_targets):
                        current_target_index += 1
                        base_servant_selected = False
                        base_scrolls = 0
                        scroll_end_hits = 0
                    else:
                        return finish(
                            completed=True,
                            stopped=False,
                            reason="target_level_reached",
                            report=report,
                        )
                else:
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
                ce_bombs_checked = False
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
                ce_bombs_checked = False
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
                ce_bombs_checked = False
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
                entry = active_servant_entry()
                if entry is not None:
                    target_name = str(entry["target"])
                    target_report = recognizer.recognize_servant_target(
                        screenshot,
                        server,
                        target=target_name,
                        threshold=servant_target_threshold,
                        scroll_end_threshold=threshold,
                    )
                    last_servant_target_report = target_report
                    context.emit(
                        "expball_servant_target",
                        "Servant enhancement target selection was inspected.",
                        data={
                            "target_index": current_target_index,
                            "scroll_count": base_scrolls,
                            "scroll_end_hits": scroll_end_hits,
                            **target_report,
                        },
                    )
                    if target_report.get("matched") is True:
                        target_center = (
                            target_report.get("center")
                            or _ENHANCE_FIRST_CARD_POINT
                        )
                        if not tap_point(
                            target_center,
                            "select_base_card",
                            extra={"servant_target": target_name},
                        ):
                            return finish(
                                completed=False,
                                stopped=True,
                                reason="device_action_failed",
                                report=report,
                            )
                        selected_servant_targets.append(target_name)
                        base_servant_selected = True
                        base_scrolls = 0
                        scroll_end_hits = 0
                        materials_selected = False
                        grid_cards_tapped = False
                        ce_bombs_checked = False
                        acted = True
                    else:
                        if target_report.get("scroll_end") is True:
                            scroll_end_hits += 1
                        if (
                            scroll_end_hits >= 2
                            or base_scrolls >= max_base_scrolls
                        ):
                            missing_servant_targets.append(target_name)
                            if current_target_index + 1 < len(servant_targets):
                                current_target_index += 1
                                base_scrolls = 0
                                scroll_end_hits = 0
                                idle_polls = 0
                                continue
                            return finish(
                                completed=bool(completed_servant_targets),
                                stopped=not bool(completed_servant_targets),
                                reason=(
                                    "target_level_reached"
                                    if completed_servant_targets
                                    else "servant_not_found"
                                ),
                                report=report,
                            )
                        start_x, start_y = randomized_touch_point(
                            _SERVANT_LIST_SWIPE_START,
                            enabled=random_touch,
                        )
                        end_x, end_y = randomized_touch_point(
                            _SERVANT_LIST_SWIPE_END,
                            enabled=random_touch,
                        )
                        operation = device_service.swipe(
                            start_x,
                            start_y,
                            end_x,
                            end_y,
                            duration_ms=_SERVANT_LIST_SWIPE_DURATION_MS,
                        )
                        base_scrolls += 1
                        context.emit(
                            "device_action",
                            "Scrolled the servant selection list.",
                            data={
                                "role": "scroll_servant_list",
                                "target": target,
                                "servant_target": target_name,
                                "scroll_count": base_scrolls,
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
                        actions.append("scroll_servant_list")
                        context.sleep(
                            randomized_wait_seconds(
                                action_wait_seconds,
                                random_time,
                            )
                        )
                        acted = True
                else:
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
                    base_servant_selected = True
                    materials_selected = False
                    grid_cards_tapped = False
                    ce_bombs_checked = False
                    acted = True
            elif "tysd" in matches or "qhjd" in matches:
                if not grid_cards_tapped:
                    ce_grid_report: dict[str, Any] | None = None
                    if (
                        target == "equipment"
                        and (lock_full_ce_bombs or mark_full_ce_bombs)
                        and not ce_bombs_checked
                    ):
                        ce_grid_report = recognizer.recognize_ce_bomb_grid(
                            screenshot,
                            server,
                            locker_threshold=locker_threshold,
                            mark_threshold=mark_threshold,
                        )
                        context.emit(
                            "expball_ce_bomb_grid",
                            "Visible craft-essence bomb grid cards were inspected.",
                            data={
                                "lock_full_ce_bombs": lock_full_ce_bombs,
                                "mark_full_ce_bombs": mark_full_ce_bombs,
                                **ce_grid_report,
                            },
                        )
                        need_lock_slots = (
                            [
                                slot
                                for slot in ce_grid_report.get("slots", [])
                                if isinstance(slot, dict)
                                and slot.get("need_lock") is True
                            ]
                            if lock_full_ce_bombs
                            else []
                        )
                        need_mark_slots = (
                            [
                                slot
                                for slot in ce_grid_report.get("slots", [])
                                if isinstance(slot, dict)
                                and slot.get("need_mark") is True
                            ]
                            if mark_full_ce_bombs
                            else []
                        )
                        if need_lock_slots:
                            if not tap_point(
                                _CE_UNIFIED_LOCK_POINT,
                                "enable_ce_unified_lock",
                            ):
                                return finish(
                                    completed=False,
                                    stopped=True,
                                    reason="device_action_failed",
                                    report=report,
                                )
                            for slot in need_lock_slots:
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
                                    "lock_full_ce_bomb",
                                    extra={"slot": slot.get("slot")},
                                ):
                                    return finish(
                                        completed=False,
                                        stopped=True,
                                        reason="device_action_failed",
                                        report=report,
                                    )
                                locked_ce_bomb_slots.append(int(slot["slot"]))
                            if not need_mark_slots:
                                if not tap_point(
                                    _CE_UNIFIED_LOCK_POINT,
                                    "disable_ce_unified_lock",
                                ):
                                    return finish(
                                        completed=False,
                                        stopped=True,
                                        reason="device_action_failed",
                                        report=report,
                                    )
                        if need_mark_slots:
                            if not tap_point(
                                _CE_UNIFIED_MARK_POINT,
                                "enable_ce_unified_mark",
                            ):
                                return finish(
                                    completed=False,
                                    stopped=True,
                                    reason="device_action_failed",
                                    report=report,
                                )
                            for slot in need_mark_slots:
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
                                    "mark_full_ce_bomb",
                                    extra={"slot": slot.get("slot")},
                                ):
                                    return finish(
                                        completed=False,
                                        stopped=True,
                                        reason="device_action_failed",
                                        report=report,
                                    )
                                marked_ce_bomb_slots.append(int(slot["slot"]))
                            if not tap_point(
                                _CE_UNIFIED_MARK_POINT,
                                "disable_ce_unified_mark",
                            ):
                                return finish(
                                    completed=False,
                                    stopped=True,
                                    reason="device_action_failed",
                                    report=report,
                                )
                        ce_bombs_checked = True
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
                        material_point: list[int] | tuple[int, int] = (
                            _ENHANCE_FIRST_CARD_POINT
                        )
                        if (
                            ce_grid_report is not None
                            and 1 in locked_ce_bomb_slots
                        ):
                            fallback_slot = next(
                                (
                                    slot
                                    for slot in ce_grid_report.get("slots", [])
                                    if isinstance(slot, dict)
                                    and slot.get("full_level") is not True
                                    and slot.get("locked") is not True
                                    and int(slot.get("slot", 0))
                                    not in locked_ce_bomb_slots
                                ),
                                None,
                            )
                            if (
                                isinstance(fallback_slot, dict)
                                and isinstance(fallback_slot.get("center"), list)
                                and len(fallback_slot["center"]) == 2
                            ):
                                material_point = fallback_slot["center"]
                        if not tap_point(
                            material_point,
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
                    ce_bombs_checked = False
                    acted = True
            elif "exlevel" in matches or (
                not base_servant_selected
                and ("help" in matches or "slot" in matches)
            ):
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
                base_servant_selected = not bool(
                    target == "servant" and active_servant_entry() is not None
                )
                base_scrolls = 0
                scroll_end_hits = 0
                materials_selected = False
                grid_cards_tapped = False
                ce_bombs_checked = False
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
                    ce_bombs_checked = False
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
    locked_cards: list[dict[str, Any]],
    lock_targets: list[dict[str, Any]],
    lock_enough_stop: bool,
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
        "locked_cards": list(locked_cards),
        "locked_count": len(locked_cards),
        "lock_targets": [dict(item) for item in lock_targets],
        "lock_enough_stop": lock_enough_stop,
        "last_report": report,
    }


def _parse_summon_lock_targets(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen_targets: set[str] = set()

    def add_entry(
        target_name: str,
        count: int = 0,
        remaining: int | None = None,
        locked: int = 0,
    ) -> None:
        cleaned = target_name.strip()
        if not cleaned:
            raise ValueError(
                "Each lock target must specify a non-empty target name."
            )
        key = cleaned.lower()
        if key in seen_targets:
            return
        seen_targets.add(key)
        normalized_count = int(count) if int(count) > 0 else 0
        normalized_remaining = (
            int(remaining)
            if remaining is not None
            else (normalized_count if normalized_count > 0 else -1)
        )
        entries.append(
            {
                "target": cleaned,
                "count": normalized_count,
                "remaining": normalized_remaining,
                "locked": int(locked),
            }
        )

    raw_targets = payload.get("lock_targets")
    if raw_targets is not None:
        if not isinstance(raw_targets, (list, tuple)):
            raise ValueError("lock_targets must be a list of targets.")
        for item in raw_targets:
            if isinstance(item, str):
                text = item.strip()
                if ":" in text:
                    name_part, count_part = text.rsplit(":", 1)
                    try:
                        parsed_count = int(count_part.strip())
                    except ValueError as exc:
                        raise ValueError(
                            "lock_targets count suffix must be an integer."
                        ) from exc
                    if parsed_count < 0:
                        raise ValueError(
                            "lock_targets count must be 0 or greater."
                        )
                    add_entry(name_part, parsed_count)
                else:
                    add_entry(text, 0)
            elif isinstance(item, dict):
                raw_name = (
                    item.get("target")
                    if item.get("target") is not None
                    else item.get("path")
                )
                if not isinstance(raw_name, str) or not raw_name.strip():
                    raise ValueError(
                        "Each lock_targets object must have a non-empty target."
                    )
                raw_count = (
                    item.get("count")
                    if item.get("count") is not None
                    else item.get("need_num", 0)
                )
                if isinstance(raw_count, bool) or not isinstance(
                    raw_count,
                    int,
                ):
                    raise ValueError(
                        "lock_targets count must be an integer."
                    )
                if raw_count < 0:
                    raise ValueError(
                        "lock_targets count must be 0 or greater."
                    )
                raw_remaining = item.get("remaining")
                if raw_remaining is not None and (
                    isinstance(raw_remaining, bool)
                    or not isinstance(raw_remaining, int)
                    or raw_remaining < -1
                ):
                    raise ValueError(
                        "lock_targets remaining must be an integer >= -1."
                    )
                raw_locked = item.get("locked", 0)
                if (
                    isinstance(raw_locked, bool)
                    or not isinstance(raw_locked, int)
                    or raw_locked < 0
                ):
                    raise ValueError(
                        "lock_targets locked must be a non-negative integer."
                    )
                add_entry(
                    raw_name,
                    raw_count,
                    remaining=raw_remaining,
                    locked=raw_locked,
                )
            else:
                raise ValueError(
                    "Each lock_targets item must be a string or object."
                )

    for flag_key, target_name in (
        ("lock_lily", "lily"),
        ("lock_habe", "habe"),
        ("lock_hakuno", "hakuno"),
    ):
        flag_val = payload.get(flag_key, False)
        if not isinstance(flag_val, bool):
            raise ValueError(f"{flag_key} must be a boolean.")
        if flag_val:
            add_entry(target_name, 0)

    return entries


def _parse_servant_targets(
    payload: dict[str, Any],
    default_target_level: int | None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_entry(name: str, level: int | None) -> None:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("servant_targets entries must be non-empty.")
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        entries.append(
            {
                "target": cleaned,
                "target_level": level if level is not None else default_target_level,
            }
        )

    def parse_str_entry(raw_text: str) -> None:
        text = raw_text.strip()
        if not text:
            raise ValueError("servant_target must be a non-empty string.")
        if ":" in text:
            name_part, level_part = text.rsplit(":", 1)
            if level_part.strip():
                try:
                    parsed_level = int(level_part.strip())
                except ValueError as exc:
                    raise ValueError(
                        "servant_targets level suffix must be an integer."
                    ) from exc
                if not 1 <= parsed_level <= 120:
                    raise ValueError(
                        "servant_targets level must be between 1 and 120."
                    )
                add_entry(name_part, parsed_level)
                return
        add_entry(text, None)

    raw_single = payload.get("servant_target")
    if raw_single is not None:
        if not isinstance(raw_single, str) or not raw_single.strip():
            raise ValueError("servant_target must be a non-empty string.")
        parse_str_entry(raw_single)

    raw_list = payload.get("servant_targets")
    if raw_list is not None:
        if not isinstance(raw_list, (list, tuple)):
            raise ValueError("servant_targets must be a list of targets.")
        for item in raw_list:
            if isinstance(item, str):
                parse_str_entry(item)
            elif isinstance(item, dict):
                raw_name = (
                    item.get("target")
                    if item.get("target") is not None
                    else item.get("path")
                )
                if not isinstance(raw_name, str) or not raw_name.strip():
                    raise ValueError(
                        "Each servant_targets object must have a non-empty target."
                    )
                raw_level = (
                    item.get("target_level")
                    if item.get("target_level") is not None
                    else item.get("level")
                )
                if raw_level is not None:
                    if isinstance(raw_level, bool) or not isinstance(
                        raw_level,
                        int,
                    ):
                        raise ValueError(
                            "servant_targets target_level must be an integer."
                        )
                    if not 1 <= raw_level <= 120:
                        raise ValueError(
                            "servant_targets target_level must be between 1 and 120."
                        )
                add_entry(raw_name, raw_level)
            else:
                raise ValueError(
                    "Each servant_targets item must be a string or object."
                )

    return entries


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
