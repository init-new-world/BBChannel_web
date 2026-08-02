from __future__ import annotations

from typing import Any

from webapp.automation.expball import (
    create_expball_storage_handler,
    create_expball_summon_handler,
)
from webapp.automation.expball_navigation import create_expball_navigate_handler
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.expball import ExpBallRecognizer
from webapp.services.script_data import ScriptDataService


EXPBALL_RUN_JOB_KIND = "event.expball.run"
_OVERFLOW_ACTIONS = {"stop", "storage"}


def create_expball_run_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
):
    navigate_handler = create_expball_navigate_handler(
        script_data,
        device_service,
        recognizer,
    )
    summon_handler = create_expball_summon_handler(
        script_data,
        device_service,
        recognizer,
    )
    storage_handler = create_expball_storage_handler(
        script_data,
        device_service,
        recognizer,
    )
    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = _setting_name(payload)
        max_summons = _integer(payload, "max_summons", 10, 1, 10000)
        max_overflow_cycles = _integer(
            payload,
            "max_overflow_cycles",
            10,
            0,
            1000,
        )
        overflow_action = str(payload.get("overflow_action") or "stop").lower()
        if overflow_action not in _OVERFLOW_ACTIONS:
            raise ValueError("overflow_action must be stop or storage.")

        common_payload: dict[str, Any] = {"setting_name": setting_name}
        for key in (
            "threshold",
            "poll_interval",
            "action_wait_seconds",
            "max_idle_polls",
        ):
            if key in payload:
                common_payload[key] = payload[key]

        navigation_payload = dict(common_payload)
        summon_payload = dict(common_payload)
        storage_payload = dict(common_payload)
        _copy_option(
            payload,
            navigation_payload,
            "navigation_timeout_seconds",
            "timeout_seconds",
        )
        _copy_option(
            payload,
            navigation_payload,
            "max_navigation_actions",
            "max_actions",
        )
        _copy_option(
            payload,
            navigation_payload,
            "max_banner_switches",
            "max_banner_switches",
        )
        _copy_option(
            payload,
            summon_payload,
            "summon_timeout_seconds",
            "timeout_seconds",
        )
        _copy_option(
            payload,
            summon_payload,
            "max_same_state",
            "max_same_state",
        )
        _copy_option(
            payload,
            storage_payload,
            "storage_timeout_seconds",
            "timeout_seconds",
        )

        summons = 0
        overflow_cycles = 0
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
                    "Experience-material automation completed."
                    if completed
                    else "Experience-material automation stopped."
                ),
            )
            return {
                "setting_name": setting_name,
                "completed": completed,
                "stopped": stopped,
                "reason": reason,
                "max_summons": max_summons,
                "summons": summons,
                "overflow_action": overflow_action,
                "overflow_cycles": overflow_cycles,
                "stages": stages,
            }

        while summons < max_summons:
            context.checkpoint(
                "expball_cycle",
                message=(
                    "Running experience-material cycle "
                    f"{overflow_cycles + 1}."
                ),
            )
            current_navigation_payload = dict(navigation_payload)
            current_navigation_payload["destination"] = "summon"
            navigation_result = navigate_handler(
                context,
                current_navigation_payload,
            )
            record("navigate_summon", navigation_result)
            if navigation_result.get("completed") is not True:
                return finish(
                    completed=False,
                    stopped=True,
                    reason=str(
                        navigation_result.get("reason") or "navigation_stopped"
                    ),
                )

            current_summon_payload = dict(summon_payload)
            current_summon_payload["max_summons"] = max_summons - summons
            summon_result = summon_handler(context, current_summon_payload)
            summons += int(summon_result.get("summons") or 0)
            record("summon", summon_result)
            summon_reason = str(summon_result.get("reason") or "summon_stopped")
            if summon_result.get("completed") is True:
                return finish(
                    completed=True,
                    stopped=False,
                    reason=summon_reason,
                )
            if summon_reason != "box_full":
                return finish(
                    completed=False,
                    stopped=True,
                    reason=summon_reason,
                )
            if overflow_action == "stop":
                return finish(
                    completed=False,
                    stopped=True,
                    reason="box_full",
                )
            if overflow_cycles >= max_overflow_cycles:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="overflow_cycle_limit",
                )

            overflow_navigation_payload = dict(navigation_payload)
            overflow_navigation_payload["destination"] = overflow_action
            navigation_result = navigate_handler(
                context,
                overflow_navigation_payload,
            )
            record(f"navigate_{overflow_action}", navigation_result)
            if navigation_result.get("completed") is not True:
                return finish(
                    completed=False,
                    stopped=True,
                    reason=str(
                        navigation_result.get("reason") or "navigation_stopped"
                    ),
                )

            overflow_result = storage_handler(context, storage_payload)
            record(overflow_action, overflow_result)
            if overflow_result.get("completed") is not True:
                return finish(
                    completed=False,
                    stopped=True,
                    reason=str(
                        overflow_result.get("reason") or "overflow_action_stopped"
                    ),
                )
            overflow_cycles += 1

        return finish(
            completed=True,
            stopped=False,
            reason="summon_limit",
        )

    return handler


def register_expball_run_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
) -> None:
    if job_manager.has_kind(EXPBALL_RUN_JOB_KIND):
        return
    job_manager.register(
        EXPBALL_RUN_JOB_KIND,
        create_expball_run_handler(
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


def _copy_option(
    source: dict[str, Any],
    destination: dict[str, Any],
    source_key: str,
    destination_key: str,
) -> None:
    if source_key in source:
        destination[destination_key] = source[source_key]
