from __future__ import annotations

from typing import Any

from webapp.runtime import JobManager, RunContext
from webapp.services.assist import AssistRecognizer
from webapp.services.devices import DeviceService
from webapp.services.script_data import ScriptDataService


ASSIST_SELECT_JOB_KIND = "assist.select"


def register_assist_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    assist_recognizer: AssistRecognizer,
) -> None:
    if job_manager.has_kind(ASSIST_SELECT_JOB_KIND):
        return

    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        tap_wait_seconds = payload.get("tap_wait_seconds", 0.5)
        if (
            isinstance(tap_wait_seconds, bool)
            or not isinstance(tap_wait_seconds, (int, float))
            or not 0 <= tap_wait_seconds <= 10
        ):
            raise ValueError("tap_wait_seconds must be between 0 and 10.")

        plan = script_data.get_setting_plan(setting_name.strip())
        context.checkpoint("recognize_assist", progress=0.25)
        recognition = assist_recognizer.recognize(
            device_service.snapshot(),
            plan["assist"],
            server=plan["server"],
        )
        context.emit(
            "recognition",
            "Assist candidate recognition completed.",
            data={
                "attempt": 1,
                "candidate_count": recognition["candidate_count"],
                "servant_name": recognition["servant_name"],
            },
        )
        if not recognition["candidates"]:
            raise RuntimeError("No matching assist candidate was found.")

        selected = dict(recognition["candidates"][0])
        scale = float(selected["scale"])
        tap_point = [
            round(selected["anchor"][0] + 270 * scale),
            round(selected["anchor"][1] - 60 * scale),
        ]
        selected["tap_point"] = tap_point
        context.checkpoint("select_assist", progress=0.75)
        operation = device_service.tap(*tap_point)
        context.emit(
            "device_action",
            "Selected assist candidate.",
            data={"role": "assist_candidate", "x": tap_point[0], "y": tap_point[1]},
        )
        context.sleep(float(tap_wait_seconds))
        context.checkpoint("complete", progress=1.0, message="Assist selected.")
        return {
            "setting_name": setting_name.strip(),
            "attempts": 1,
            "scrolls": 0,
            "selected": selected,
            "tap": operation.to_dict(),
        }

    job_manager.register(ASSIST_SELECT_JOB_KIND, handler, requires_device=True)
