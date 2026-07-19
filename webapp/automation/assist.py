from __future__ import annotations

from typing import Any

from webapp.automation.interaction import (
    configured_random_time,
    match_touch_point,
    randomized_touch_point,
    randomized_wait_seconds,
)
from webapp.core.errors import AppError, ErrorCode
from webapp.runtime import JobManager, RunContext
from webapp.services.assist import AssistRecognizer
from webapp.services.devices import DeviceService
from webapp.services.script_data import ScriptDataService


ASSIST_SELECT_JOB_KIND = "assist.select"
GRAND_ASSIST_MODES = {"冠位助战", "冠位助战仅礼装"}
ASSIST_SCROLL_X = 700
ASSIST_CLASS_INDEX = {
    "Saber": 1,
    "Archer": 2,
    "Lancer": 3,
    "Rider": 4,
    "Caster": 5,
    "Assassin": 6,
    "Berserker": 7,
    "Alterego": 8,
    "Avenger": 8,
    "Foreigner": 8,
    "MoonCancer": 8,
    "Pretender": 8,
    "Ruler": 8,
    "Shielder": 8,
    "Beast": 8,
}


def create_assist_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    assist_recognizer: AssistRecognizer,
):

    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        plan = script_data.get_setting_plan(setting_name.strip())
        tap_wait_seconds = payload.get("tap_wait_seconds", 0.5)
        if (
            isinstance(tap_wait_seconds, bool)
            or not isinstance(tap_wait_seconds, (int, float))
            or not 0 <= tap_wait_seconds <= 10
        ):
            raise ValueError("tap_wait_seconds must be between 0 and 10.")
        configured_scroll_wait = plan["assist"].get("interval_after_swipe", 0.5)
        if configured_scroll_wait is None:
            configured_scroll_wait = 0.5
        scroll_wait_seconds = payload.get(
            "scroll_wait_seconds",
            configured_scroll_wait,
        )
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
        max_reconnects = payload.get("max_reconnects", 5)
        if (
            isinstance(max_reconnects, bool)
            or not isinstance(max_reconnects, int)
            or not 0 <= max_reconnects <= 100
        ):
            raise ValueError("max_reconnects must be between 0 and 100.")
        max_unavailable = payload.get("max_unavailable", 5)
        if (
            isinstance(max_unavailable, bool)
            or not isinstance(max_unavailable, int)
            or not 0 <= max_unavailable <= 100
        ):
            raise ValueError("max_unavailable must be between 0 and 100.")

        scroll_limit = payload.get(
            "scroll_limit",
            plan["assist"].get("scroll_limit", 0.96),
        )
        if scroll_limit is None:
            scroll_limit = 0.96
        if (
            isinstance(scroll_limit, bool)
            or not isinstance(scroll_limit, (int, float))
            or not 0 <= scroll_limit <= 1
        ):
            raise ValueError("scroll_limit must be between 0 and 1.")
        scroll_limit = float(scroll_limit)
        random_touch = bool(plan["run"].get("random_touch"))
        random_time = configured_random_time(plan["run"].get("random_time", 0))
        reconnects = 0

        def snapshot_without_reconnect() -> bytes:
            nonlocal reconnects
            while True:
                screenshot = device_service.snapshot()
                try:
                    reconnect = assist_recognizer.match_reconnect(
                        screenshot,
                        plan["server"],
                    )
                except AppError as exc:
                    if exc.code == ErrorCode.TEMPLATE_NOT_FOUND:
                        return screenshot
                    raise
                if not reconnect.matched:
                    return screenshot
                if reconnects >= max_reconnects:
                    raise RuntimeError("Assist network reconnect limit was reached.")
                operation = device_service.tap(
                    *match_touch_point(reconnect, enabled=random_touch)
                )
                reconnects += 1
                context.emit(
                    "device_action",
                    "Requested a network reconnection while selecting assist.",
                    data={
                        "role": "reconnect",
                        "reconnect": reconnects,
                        "operation": operation.to_dict(),
                    },
                )
                context.sleep(
                    randomized_wait_seconds(tap_wait_seconds, random_time)
                )

        class_selection = None
        if not plan["assist"].get("all_not_skip"):
            servant_class = plan["assist"].get("servant_class")
            if isinstance(servant_class, str) and servant_class:
                screenshot = snapshot_without_reconnect()
                recommended = assist_recognizer.match_recommended_header(
                    screenshot,
                    plan["server"],
                ).matched
                point = _assist_class_point(servant_class, recommended=recommended)
                for _ in range(2):
                    touch_point = randomized_touch_point(
                        point,
                        enabled=random_touch,
                    )
                    operation = device_service.tap(*touch_point)
                class_selection = {
                    "class": servant_class,
                    "recommended": recommended,
                    "point": list(point),
                    "operation": operation.to_dict(),
                }
                context.emit(
                    "device_action",
                    "Selected the configured assist class.",
                    data={"role": "assist_class", **class_selection},
                )
                context.sleep(
                    randomized_wait_seconds(refresh_wait_seconds, random_time)
                )
        attempts = 0
        scrolls = 0
        scrolls_since_refresh = 0
        refreshes = 0
        unavailable = 0
        empty_lists = 0
        scroll_limit_hits = 0
        grand_boundary_hits = 0
        while True:
            progress = min((scrolls + 1) / (max_scrolls + 2), 0.7)
            context.checkpoint("recognize_assist", progress=progress)
            screenshot = snapshot_without_reconnect()
            recognition = assist_recognizer.recognize(
                screenshot,
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
                selected = dict(recognition["candidates"][0])
                scale = float(selected["scale"])
                selection_point = selected.get("selection_point")
                if not (
                    isinstance(selection_point, list)
                    and len(selection_point) == 2
                    and all(
                        isinstance(coordinate, int) and not isinstance(coordinate, bool)
                        for coordinate in selection_point
                    )
                ):
                    selection_point = [
                        round(selected["anchor"][0] + 270 * scale),
                        round(selected["anchor"][1] - 60 * scale),
                    ]
                tap_point = list(
                    randomized_touch_point(
                        (selection_point[0], selection_point[1]),
                        enabled=random_touch,
                    )
                )
                selected["tap_point"] = tap_point
                context.checkpoint("select_assist", progress=0.75)
                selection_operation = device_service.tap(*tap_point)
                context.emit(
                    "device_action",
                    "Selected assist candidate.",
                    data={
                        "role": "assist_candidate",
                        "x": tap_point[0],
                        "y": tap_point[1],
                    },
                )
                context.sleep(
                    randomized_wait_seconds(tap_wait_seconds, random_time)
                )
                try:
                    not_available = assist_recognizer.match_not_available(
                        snapshot_without_reconnect(),
                        plan["server"],
                    )
                except AppError as exc:
                    if exc.code != ErrorCode.TEMPLATE_NOT_FOUND:
                        raise
                    not_available = None
                if not_available is not None and not_available.matched:
                    if unavailable >= max_unavailable:
                        raise RuntimeError(
                            "Assist unavailable candidate limit was reached."
                        )
                    close_operation = device_service.tap(
                        *match_touch_point(not_available, enabled=random_touch)
                    )
                    unavailable += 1
                    context.emit(
                        "device_action",
                        "Closed an unavailable assist candidate prompt.",
                        data={
                            "role": "assist_unavailable",
                            "unavailable": unavailable,
                            "operation": close_operation.to_dict(),
                        },
                    )
                    context.sleep(
                        randomized_wait_seconds(tap_wait_seconds, random_time)
                    )
                    continue
                context.checkpoint(
                    "complete",
                    progress=1.0,
                    message="Assist selected.",
                )
                return {
                    "setting_name": setting_name.strip(),
                    "attempts": attempts,
                    "scrolls": scrolls,
                    "refreshes": refreshes,
                    "reconnects": reconnects,
                    "unavailable": unavailable,
                    "empty_lists": empty_lists,
                    "scroll_limit_hits": scroll_limit_hits,
                    "grand_boundary_hits": grand_boundary_hits,
                    "scroll_limit": scroll_limit,
                    "class_selection": class_selection,
                    "selected": selected,
                    "tap": selection_operation.to_dict(),
                }
            try:
                no_assist = assist_recognizer.match_no_assist(
                    screenshot,
                    plan["server"],
                )
            except AppError as exc:
                if exc.code != ErrorCode.TEMPLATE_NOT_FOUND:
                    raise
                no_assist = None
            if no_assist is not None and no_assist.matched:
                empty_lists += 1
                scrolls_since_refresh = max_scrolls
                context.emit(
                    "recognition",
                    "Filtered assist list is empty; refresh will be attempted.",
                    data={"role": "assist_empty", "empty_list": empty_lists},
                )
            elif scrolls_since_refresh < max_scrolls:
                if (
                    plan["assist"].get("mode") in GRAND_ASSIST_MODES
                    and plan["assist"].get("no_grand_refresh")
                    and not assist_recognizer.match_grand_marker(
                        screenshot,
                        plan["server"],
                    ).matched
                ):
                    grand_boundary_hits += 1
                    scrolls_since_refresh = max_scrolls
                    context.emit(
                        "recognition",
                        "Grand assist boundary reached; refresh will be attempted.",
                        data={
                            "role": "assist_grand_boundary",
                            "grand_boundary_hit": grand_boundary_hits,
                        },
                    )
                if scrolls_since_refresh < max_scrolls:
                    try:
                        scrollbar = assist_recognizer.match_scrollbar(
                            screenshot,
                            plan["server"],
                        )
                    except AppError as exc:
                        if exc.code != ErrorCode.TEMPLATE_NOT_FOUND:
                            raise
                        scrollbar = None
                    if (
                        scrollbar is not None
                        and scrollbar.matched
                        and scrollbar.top_left[1] >= scroll_limit * 720
                    ):
                        scroll_limit_hits += 1
                        scrolls_since_refresh = max_scrolls
                        context.emit(
                            "recognition",
                            "Assist scroll limit reached; refresh will be attempted.",
                            data={
                                "role": "assist_scroll_limit",
                                "scroll_limit": scroll_limit,
                                "scrollbar_y": scrollbar.top_left[1],
                                "scroll_limit_hit": scroll_limit_hits,
                            },
                        )
            if scrolls_since_refresh < max_scrolls:
                context.checkpoint("scroll_assist", progress=progress)
                operation = device_service.swipe(
                    ASSIST_SCROLL_X,
                    620,
                    ASSIST_SCROLL_X,
                    250,
                    500,
                )
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
                context.sleep(randomized_wait_seconds(scroll_wait_seconds, random_time))
                continue
            if refreshes >= max_refreshes:
                raise RuntimeError("No matching assist candidate was found.")

            context.checkpoint("refresh_assist", progress=progress)
            refresh_button = assist_recognizer.match_refresh_button(
                snapshot_without_reconnect(),
                plan["server"],
            )
            if not refresh_button.matched:
                raise RuntimeError("Assist list refresh button was not recognized.")
            device_service.tap(
                *match_touch_point(refresh_button, enabled=random_touch)
            )
            context.sleep(randomized_wait_seconds(refresh_wait_seconds, random_time))
            refresh_confirmation = assist_recognizer.match_refresh_confirmation(
                snapshot_without_reconnect(),
                plan["server"],
            )
            if not refresh_confirmation.matched:
                raise RuntimeError("Assist list refresh confirmation was not recognized.")
            device_service.tap(
                *match_touch_point(refresh_confirmation, enabled=random_touch)
            )
            refreshes += 1
            scrolls_since_refresh = 0
            context.emit(
                "device_action",
                "Refreshed assist list.",
                data={"role": "assist_refresh", "refresh": refreshes},
            )
            context.sleep(randomized_wait_seconds(refresh_wait_seconds, random_time))

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


def _assist_class_point(class_name: str, *, recommended: bool) -> tuple[int, int]:
    try:
        index = ASSIST_CLASS_INDEX[class_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported assist class: {class_name}") from exc
    source_x = 225 + index * 91 if recommended else 140 + index * 101
    return round(source_x / 1.5), 128
