from __future__ import annotations

from typing import Any

from webapp.automation.expball import create_expball_storage_handler
from webapp.automation.expball_navigation import create_expball_navigate_handler
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.expball import ExpBallRecognizer
from webapp.services.script_data import ScriptDataService


EXPBALL_STORE_ALL_JOB_KIND = "event.expball.store-all"


def create_expball_store_all_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
):
    navigate_handler = create_expball_navigate_handler(
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
        navigation_payload["destination"] = "storage"
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
            storage_payload,
            "storage_timeout_seconds",
            "timeout_seconds",
        )
        stages: list[dict[str, Any]] = []

        def record(stage: str, result: dict[str, Any]) -> None:
            stages.append({"stage": stage, "result": result})

        def finish(
            *,
            completed: bool,
            reason: str,
        ) -> dict[str, Any]:
            context.checkpoint(
                "complete",
                progress=1.0,
                message=(
                    "Experience materials were stored."
                    if completed
                    else "Store-all workflow stopped."
                ),
            )
            return {
                "setting_name": setting_name,
                "completed": completed,
                "stopped": not completed,
                "reason": reason,
                "stages": stages,
            }

        navigation_result = navigate_handler(context, navigation_payload)
        record("navigate_storage", navigation_result)
        if navigation_result.get("completed") is not True:
            return finish(
                completed=False,
                reason=str(
                    navigation_result.get("reason") or "navigation_stopped"
                ),
            )

        storage_result = storage_handler(context, storage_payload)
        record("storage", storage_result)
        completed = storage_result.get("completed") is True
        return finish(
            completed=completed,
            reason=str(storage_result.get("reason") or "storage_stopped"),
        )

    return handler


def register_expball_store_all_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognizer: ExpBallRecognizer,
) -> None:
    if job_manager.has_kind(EXPBALL_STORE_ALL_JOB_KIND):
        return
    job_manager.register(
        EXPBALL_STORE_ALL_JOB_KIND,
        create_expball_store_all_handler(
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


def _copy_option(
    source: dict[str, Any],
    destination: dict[str, Any],
    source_key: str,
    destination_key: str,
) -> None:
    if source_key in source:
        destination[destination_key] = source[source_key]
