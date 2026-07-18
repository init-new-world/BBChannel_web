from __future__ import annotations

from typing import Any

from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.digdig import DigdigRecognizer
from webapp.services.script_data import ScriptDataService


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
