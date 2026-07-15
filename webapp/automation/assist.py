from __future__ import annotations

from typing import Any

from webapp.runtime import JobManager, RunContext
from webapp.services.assist import AssistRecognizer
from webapp.services.devices import DeviceService
from webapp.services.script_data import ScriptDataService


ASSIST_SELECT_JOB_KIND = "assist.select"


def create_assist_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    assist_recognizer: AssistRecognizer,
):

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
        scroll_wait_seconds = payload.get("scroll_wait_seconds", 0.5)
        if (
            isinstance(scroll_wait_seconds, bool)
            or not isinstance(scroll_wait_seconds, (int, float))
            or not 0 <= scroll_wait_seconds <= 10
        ):
            raise ValueError("scroll_wait_seconds must be between 0 and 10.")
        max_scrolls = payload.get("max_scrolls", 8)
        if (
            isinstance(max_scrolls, bool)
            or not isinstance(max_scrolls, int)
            or not 0 <= max_scrolls <= 100
        ):
            raise ValueError("max_scrolls must be between 0 and 100.")
        max_refreshes = payload.get("max_refreshes", 1)
        if (
            isinstance(max_refreshes, bool)
            or not isinstance(max_refreshes, int)
            or not 0 <= max_refreshes <= 100
        ):
            raise ValueError("max_refreshes must be between 0 and 100.")
        refresh_wait_seconds = payload.get("refresh_wait_seconds", 1.0)
        if (
            isinstance(refresh_wait_seconds, bool)
            or not isinstance(refresh_wait_seconds, (int, float))
            or not 0 <= refresh_wait_seconds <= 10
        ):
            raise ValueError("refresh_wait_seconds must be between 0 and 10.")

        plan = script_data.get_setting_plan(setting_name.strip())
        attempts = 0
        scrolls = 0
        scrolls_since_refresh = 0
        refreshes = 0
        while True:
            progress = min((scrolls + 1) / (max_scrolls + 2), 0.7)
            context.checkpoint("recognize_assist", progress=progress)
            recognition = assist_recognizer.recognize(
                device_service.snapshot(),
                plan["assist"],
                server=plan["server"],
            )
            attempts += 1
            context.emit(
                "recognition",
                "Assist candidate recognition completed.",
                data={
                    "attempt": attempts,
                    "candidate_count": recognition["candidate_count"],
                    "servant_name": recognition["servant_name"],
                },
            )
            if recognition["candidates"]:
                break
            if scrolls_since_refresh < max_scrolls:
                context.checkpoint("scroll_assist", progress=progress)
                operation = device_service.swipe(1120, 620, 1120, 250, 500)
                scrolls += 1
                scrolls_since_refresh += 1
                context.emit(
                    "device_action",
                    "Scrolled assist list.",
                    data={
                        "role": "assist_scroll",
                        "scroll": scrolls,
                        "operation": operation.to_dict(),
                    },
                )
                context.sleep(float(scroll_wait_seconds))
                continue
            if refreshes >= max_refreshes:
                raise RuntimeError("No matching assist candidate was found.")

            context.checkpoint("refresh_assist", progress=progress)
            refresh_button = assist_recognizer.match_refresh_button(
                device_service.snapshot(),
                plan["server"],
            )
            if not refresh_button.matched:
                raise RuntimeError("Assist list refresh button was not recognized.")
            device_service.tap(*refresh_button.center)
            context.sleep(float(refresh_wait_seconds))
            refresh_confirmation = assist_recognizer.match_refresh_confirmation(
                device_service.snapshot(),
                plan["server"],
            )
            if not refresh_confirmation.matched:
                raise RuntimeError("Assist list refresh confirmation was not recognized.")
            device_service.tap(*refresh_confirmation.center)
            refreshes += 1
            scrolls_since_refresh = 0
            context.emit(
                "device_action",
                "Refreshed assist list.",
                data={"role": "assist_refresh", "refresh": refreshes},
            )
            context.sleep(float(refresh_wait_seconds))

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
            "attempts": attempts,
            "scrolls": scrolls,
            "refreshes": refreshes,
            "selected": selected,
            "tap": operation.to_dict(),
        }

    return handler


def register_assist_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    assist_recognizer: AssistRecognizer,
) -> None:
    if job_manager.has_kind(ASSIST_SELECT_JOB_KIND):
        return
    job_manager.register(
        ASSIST_SELECT_JOB_KIND,
        create_assist_handler(script_data, device_service, assist_recognizer),
        requires_device=True,
    )
