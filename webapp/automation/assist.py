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
from webapp.services.assist import AssistRecognizer, validate_assist_special_filter
from webapp.services.devices import DeviceService
from webapp.services.script_data import ScriptDataService


ASSIST_SELECT_JOB_KIND = "assist.select"
GRAND_ASSIST_MODES = {"冠位助战", "冠位助战仅礼装"}
ASSIST_SCROLL_X = 700
ASSIST_SCROLL_START_Y = 620
ASSIST_SCROLL_END_Y = 380
ASSIST_LEVEL_SCROLL_END_Y = 407
ASSIST_SCROLL_DURATION_MS = 700
ASSIST_SKILL_TOGGLE_POINT = (847, 130)
ASSIST_SORT_ORDER_POINT = (1153, 128)
MAX_ASSIST_CLASS_ATTEMPTS = 3
MAX_ASSIST_SORT_ATTEMPTS = 3
MAX_ASSIST_REFRESH_COOLDOWN_RETRIES = 6
ASSIST_REFRESH_COOLDOWN_WAIT_SECONDS = 2.5
MAX_ASSIST_CONNECTING_WAITS = 16
ASSIST_CONNECTING_POLL_SECONDS = 0.5
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
        if not plan.get("validation", {"ok": True})["ok"]:
            raise ValueError(f"Setting {setting_name.strip()} has validation errors.")
        default_special_filter = (
            plan.get("pre_run", {})
            .get("assist_report", {})
            .get("default_special_filter", "any")
        )
        special_filter = validate_assist_special_filter(
            payload.get("special_filter", default_special_filter),
            plan["assist"].get("mode"),
        )
        if special_filter != "any":
            plan["assist"] = {**plan["assist"], "special_filter": special_filter}
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
        max_scrolls = payload.get("max_scrolls", 12)
        if (
            isinstance(max_scrolls, bool)
            or not isinstance(max_scrolls, int)
            or not 0 <= max_scrolls <= 100
        ):
            raise ValueError("max_scrolls must be between 0 and 100.")
        max_refreshes = payload.get("max_refreshes", 20)
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
        preferred_apple = payload.get("apple", "gold")
        if preferred_apple not in {"gold", "silver", "blue", "copper"}:
            raise ValueError("apple must be gold, silver, blue, or copper.")
        recover_ap = payload.get("recover_ap", True)
        if not isinstance(recover_ap, bool):
            raise ValueError("recover_ap must be a boolean.")
        max_ap_actions = payload.get("max_ap_actions", 10)
        if (
            isinstance(max_ap_actions, bool)
            or not isinstance(max_ap_actions, int)
            or not 1 <= max_ap_actions <= 100
        ):
            raise ValueError("max_ap_actions must be between 1 and 100.")

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
        append_levels = plan["assist"].get("append_skill_levels", [])
        check_append = (
            plan["assist"].get("mode") not in {"不识别", "仅礼装", "冠位助战仅礼装"}
            and any(append_levels)
        )
        reconnects = 0
        ap_actions: list[str] = []

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

        def ensure_skill_view(view: str, screenshot: bytes) -> bytes:
            for attempt in range(6):
                context.checkpoint("assist_skill_view")
                marker = assist_recognizer.match_skill_view(screenshot, plan["server"])
                if marker is not None and marker["view"] == view:
                    return screenshot
                if attempt == 5:
                    break
                wait_after_toggle = 0.5
                if marker is not None:
                    operation = device_service.tap(*randomized_touch_point(
                        ASSIST_SKILL_TOGGLE_POINT, enabled=random_touch,
                    ))
                    wait_after_toggle = 1.2
                    context.emit(
                        "device_action", "Switched assist skill display.",
                        data={"role": "assist_skill_view", "target": view, "operation": operation.to_dict()},
                    )
                context.sleep(randomized_wait_seconds(max(wait_after_toggle, tap_wait_seconds), random_time))
                screenshot = snapshot_without_reconnect()
            raise RuntimeError(f"Assist {view} skill view could not be confirmed.")

        while True:
            screenshot = snapshot_without_reconnect()
            apple_close = _optional_assist_match(
                assist_recognizer,
                "match_apple_close",
                screenshot,
                plan["server"],
            )
            apple_decide = _optional_assist_match(
                assist_recognizer,
                "match_apple_decide",
                screenshot,
                plan["server"],
            )
            if apple_close is not None and apple_close.matched:
                if not recover_ap:
                    operation = device_service.tap(
                        *match_touch_point(apple_close, enabled=random_touch)
                    )
                    ap_actions.append("apple_close")
                    context.emit(
                        "device_action",
                        "Closed AP recovery before assist selection.",
                        data={
                            "role": "apple_close",
                            "operation": operation.to_dict(),
                        },
                    )
                    return {
                        "setting_name": setting_name.strip(),
                        "ready": False,
                        "reason": "ap_empty",
                        "ap_actions": ap_actions,
                        "reconnects": reconnects,
                        "selected": None,
                    }
                if len(ap_actions) >= max_ap_actions:
                    raise RuntimeError("Assist AP recovery action limit was reached.")
                apple_match = _available_assist_apple(
                    assist_recognizer,
                    screenshot,
                    plan["server"],
                    preferred=preferred_apple,
                    allow_other=bool(plan["run"].get("allow_other_apple")),
                    device_service=device_service,
                    snapshot=snapshot_without_reconnect,
                    context=context,
                    wait_seconds=randomized_wait_seconds(tap_wait_seconds, random_time),
                )
                if apple_match is None:
                    raise RuntimeError("No available AP recovery item was recognized.")
                apple_name, match = apple_match
                operation = device_service.tap(
                    *match_touch_point(match, enabled=random_touch)
                )
                action = f"apple_{apple_name}"
                ap_actions.append(action)
                context.emit(
                    "device_action",
                    "Selected AP recovery item before assist selection.",
                    data={"role": action, "operation": operation.to_dict()},
                )
            elif apple_decide is not None and apple_decide.matched:
                if len(ap_actions) >= max_ap_actions:
                    raise RuntimeError("Assist AP recovery action limit was reached.")
                operation = device_service.tap(
                    *match_touch_point(apple_decide, enabled=random_touch)
                )
                ap_actions.append("apple_decide")
                context.emit(
                    "device_action",
                    "Confirmed AP recovery before assist selection.",
                    data={
                        "role": "apple_decide",
                        "operation": operation.to_dict(),
                    },
                )
            else:
                break
            context.sleep(randomized_wait_seconds(tap_wait_seconds, random_time))

        class_selection = None
        servant_class = plan["assist"].get("servant_class")
        if (
            isinstance(servant_class, str) and servant_class
            and plan["assist"].get("mode") not in {"不识别", "仅礼装", "冠位助战仅礼装"}
        ):
            screenshot = snapshot_without_reconnect()
            recommended = assist_recognizer.match_recommended_header(
                screenshot,
                plan["server"],
            ).matched
            point = _assist_class_point(servant_class, recommended=recommended)
            selected_class = assist_recognizer.selected_class_index(screenshot, recommended=recommended)
            keep_current = (
                selected_class in {9, ASSIST_CLASS_INDEX[servant_class]}
                or selected_class in {0, -1} and plan["assist"].get("all_not_skip", True)
            )
            if not keep_current:
                for attempt in range(1, MAX_ASSIST_CLASS_ATTEMPTS + 1):
                    context.checkpoint("select_assist_class", progress=0)
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
                        "Tapped the configured assist class.",
                        data={"role": "assist_class", "attempt": attempt, **class_selection},
                    )
                    context.sleep(
                        randomized_wait_seconds(refresh_wait_seconds, random_time)
                    )
                    screenshot = snapshot_without_reconnect()
                    recommended = assist_recognizer.match_recommended_header(screenshot, plan["server"]).matched
                    selected_class = assist_recognizer.selected_class_index(screenshot, recommended=recommended)
                    if selected_class == ASSIST_CLASS_INDEX[servant_class]:
                        context.emit(
                            "recognition",
                            "Confirmed the configured assist class.",
                            data={"role": "assist_class_confirmed", "class": servant_class, "attempts": attempt},
                        )
                        break
                else:
                    raise RuntimeError("Assist class selection was not confirmed after three attempts.")
        required_servant_level = plan["assist"].get("servant_level", 1)
        check_servant_level = (
            plan["assist"].get("mode") not in {"不识别", "仅礼装", "冠位助战仅礼装"}
            and isinstance(required_servant_level, int)
            and not isinstance(required_servant_level, bool)
            and required_servant_level > 1
        )
        if check_servant_level:
            sort_order = _optional_assist_match(
                assist_recognizer,
                "match_sort_order",
                snapshot_without_reconnect(),
                plan["server"],
            )
            if sort_order is not None and not sort_order.get("matched"):
                for attempt in range(1, MAX_ASSIST_SORT_ATTEMPTS + 1):
                    context.checkpoint("select_assist_sort_order", progress=0)
                    touch_point = randomized_touch_point(
                        ASSIST_SORT_ORDER_POINT,
                        enabled=random_touch,
                    )
                    operation = device_service.tap(*touch_point)
                    context.emit(
                        "device_action",
                        "Tapped assist sort order button for servant level recognition.",
                        data={
                            "role": "assist_sort_order",
                            "attempt": attempt,
                            "point": list(touch_point),
                            "operation": operation.to_dict(),
                        },
                    )
                    context.sleep(
                        randomized_wait_seconds(tap_wait_seconds, random_time)
                    )
                    sort_order = _optional_assist_match(
                        assist_recognizer,
                        "match_sort_order",
                        snapshot_without_reconnect(),
                        plan["server"],
                    )
                    if sort_order is None or sort_order.get("matched"):
                        context.emit(
                            "recognition",
                            "Confirmed assist sort order for servant level recognition.",
                            data={
                                "role": "assist_sort_order_confirmed",
                                "order": (
                                    sort_order.get("order")
                                    if isinstance(sort_order, dict)
                                    else None
                                ),
                                "attempts": attempt,
                            },
                        )
                        break
                else:
                    raise RuntimeError(
                        "Assist list sort order must be Login Order or Level Order when servant_level > 1."
                    )
        attempts = 0
        scrolls = 0
        scrolls_since_refresh = 0
        refreshes = 0
        unavailable = 0
        empty_lists = 0
        scroll_limit_hits = 0
        grand_boundary_hits = 0
        friend_boundary_hits = 0
        connecting_waits = 0
        while True:
            progress = min((scrolls + 1) / (max_scrolls + 2), 0.7)
            context.checkpoint("recognize_assist", progress=progress)
            screenshot = snapshot_without_reconnect()
            connecting = _optional_assist_match(
                assist_recognizer,
                "match_connecting",
                screenshot,
                plan["server"],
            )
            if (
                connecting is not None
                and connecting.matched
                and connecting_waits < MAX_ASSIST_CONNECTING_WAITS
            ):
                connecting_waits += 1
                poll_wait = (
                    ASSIST_CONNECTING_POLL_SECONDS
                    if refresh_wait_seconds > 0
                    else 0.0
                )
                context.sleep(randomized_wait_seconds(poll_wait, random_time))
                continue
            connecting_waits = 0
            empty_match = _optional_assist_match(
                assist_recognizer, "match_no_assist", screenshot, plan["server"],
            ) if check_append else None
            if empty_match is not None and empty_match.matched:
                recognition = {"candidate_count": 0, "candidates": [], "servant_name": plan["assist"].get("servant_name")}
            else:
                if check_append:
                    screenshot = ensure_skill_view("main", screenshot)
                recognition = assist_recognizer.recognize(
                    screenshot,
                    plan["assist"],
                    server=plan["server"],
                )
            if check_append and recognition["candidates"]:
                main_screenshot = screenshot
                identities = [
                    assist_recognizer.candidate_identity(screenshot, candidate)
                    for candidate in recognition["candidates"]
                ]
                same_row = getattr(assist_recognizer, "same_candidate_row", None)

                def _matches_row(
                    before_candidate: dict[str, Any],
                    before_identity: str,
                    after_screenshot: bytes,
                    after_candidate: dict[str, Any],
                ) -> bool:
                    if callable(same_row):
                        return bool(same_row(main_screenshot, before_candidate, after_screenshot, after_candidate))
                    return assist_recognizer.candidate_identity(after_screenshot, after_candidate) == before_identity

                screenshot = ensure_skill_view("append", screenshot)
                accepted = []
                for candidate, identity in zip(recognition["candidates"], identities, strict=True):
                    context.checkpoint("recognize_append_skills", progress=progress)
                    if not _matches_row(candidate, identity, screenshot, candidate):
                        context.emit("recognition", "Support row changed during skill display transition.",
                                     data={"role": "assist_identity_changed", "anchor": candidate["anchor"]})
                        continue
                    result = assist_recognizer.check_append_skills(
                        screenshot, candidate, append_levels, server=plan["server"],
                    )
                    context.emit(
                        "recognition", "Assist append skill recognition completed.",
                        data={"role": "assist_append_skills", "anchor": candidate["anchor"], **result},
                    )
                    if result["matched"]:
                        accepted.append((candidate, result, identity))
                screenshot = ensure_skill_view("main", screenshot)
                if not accepted:
                    recognition = {
                        **recognition,
                        "candidate_count": 0,
                        "candidates": [],
                    }
                else:
                    restored = assist_recognizer.recognize(screenshot, plan["assist"], server=plan["server"])
                    candidates = []
                    for candidate in restored["candidates"]:
                        previous = next((result for original, result, original_identity in accepted if
                            _matches_row(original, original_identity, screenshot, candidate)
                            and original.get("template_path") == candidate.get("template_path")
                            and all(abs(before - after) <= 6 for before, after in zip(
                                original["anchor"], candidate["anchor"], strict=True,
                            ))
                        ), None)
                        if previous is not None:
                            candidates.append({**candidate, "checks": {
                                **candidate.get("checks", {}),
                                "append_skill_levels": previous["levels"],
                                "append_skill_confidences": previous.get("confidences", []),
                            }})
                    if not candidates:
                        context.emit(
                            "recognition",
                            "Restored main skill view did not retain accepted append candidates.",
                            data={
                                "role": "assist_append_restore_dropped",
                                "accepted_anchors": [orig["anchor"] for orig, _, _ in accepted],
                                "restored_anchors": [cand["anchor"] for cand in restored["candidates"]],
                            },
                        )
                    recognition = {**restored, "candidate_count": len(candidates), "candidates": candidates}
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
                    "friend_boundary_hits": friend_boundary_hits,
                    "scroll_limit": scroll_limit,
                    "class_selection": class_selection,
                    "ap_actions": ap_actions,
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
                if plan["assist"].get("friend_only") and scrolls_since_refresh >= 2:
                    friend_marker = _optional_assist_match(
                        assist_recognizer, "match_friend_marker", screenshot, plan["server"],
                    )
                    if friend_marker is not None and not friend_marker.matched:
                        friend_boundary_hits += 1
                        scrolls_since_refresh = max_scrolls
                        context.emit(
                            "recognition",
                            "No friends remain after scrolling; refresh will be attempted.",
                            data={"role": "assist_friend_boundary", "friend_boundary_hit": friend_boundary_hits},
                        )
                if (
                    scrolls_since_refresh < max_scrolls
                    and plan["assist"].get("mode") in GRAND_ASSIST_MODES
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
                scroll_end_y = (
                    ASSIST_LEVEL_SCROLL_END_Y
                    if check_servant_level
                    else ASSIST_SCROLL_END_Y
                )
                operation = device_service.swipe(
                    ASSIST_SCROLL_X,
                    ASSIST_SCROLL_START_Y,
                    ASSIST_SCROLL_X,
                    scroll_end_y,
                    ASSIST_SCROLL_DURATION_MS,
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

            refresh_confirmation = None
            for cooldown_attempt in range(MAX_ASSIST_REFRESH_COOLDOWN_RETRIES + 1):
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
                confirm_screen = snapshot_without_reconnect()
                refresh_confirmation = assist_recognizer.match_refresh_confirmation(
                    confirm_screen,
                    plan["server"],
                )
                if refresh_confirmation.matched:
                    break
                refresh_close = _optional_assist_match(
                    assist_recognizer,
                    "match_refresh_close",
                    confirm_screen,
                    plan["server"],
                )
                if (
                    refresh_close is None
                    or not refresh_close.matched
                    or cooldown_attempt >= MAX_ASSIST_REFRESH_COOLDOWN_RETRIES
                ):
                    raise RuntimeError(
                        "Assist list refresh confirmation was not recognized."
                    )
                close_operation = device_service.tap(
                    *match_touch_point(refresh_close, enabled=random_touch)
                )
                context.emit(
                    "device_action",
                    "Closed assist refresh cooldown prompt.",
                    data={
                        "role": "assist_refresh_cooldown",
                        "attempt": cooldown_attempt + 1,
                        "operation": close_operation.to_dict(),
                    },
                )
                cooldown_wait = (
                    max(ASSIST_REFRESH_COOLDOWN_WAIT_SECONDS, refresh_wait_seconds)
                    if refresh_wait_seconds > 0
                    else 0.0
                )
                context.sleep(randomized_wait_seconds(cooldown_wait, random_time))
            assert refresh_confirmation is not None
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


def _optional_assist_match(
    recognizer: AssistRecognizer,
    method_name: str,
    *args: Any,
):
    method = getattr(recognizer, method_name, None)
    if method is None:
        return None
    try:
        return method(*args)
    except AppError as exc:
        if exc.code == ErrorCode.TEMPLATE_NOT_FOUND:
            return None
        raise


APPLE_SCROLL_DOWN = (1014, 453, 1014, 620, 200)
APPLE_SCROLL_UP = (1014, 267, 1014, 60, 200)


def _available_assist_apple(
    recognizer: AssistRecognizer,
    screenshot: bytes,
    server: str,
    *,
    preferred: str,
    allow_other: bool,
    device_service: DeviceService | None = None,
    snapshot: Any = None,
    context: RunContext | None = None,
    wait_seconds: float = 0.0,
):
    candidates = [preferred]
    if allow_other:
        candidates.extend(
            apple
            for apple in ("gold", "silver", "blue", "copper")
            if apple != preferred
        )
    current_screenshot = screenshot
    current_scroll = "top"
    for apple in candidates:
        match = _optional_assist_match(
            recognizer,
            "match_apple",
            current_screenshot,
            server,
            apple,
        )
        if (
            (match is None or not match.matched)
            and getattr(match, "color_available", None) is not False
            and device_service is not None
            and hasattr(device_service, "swipe")
        ):
            target_scroll = "bottom" if apple in {"blue", "copper"} else "top"
            if target_scroll != current_scroll:
                swipe_args = APPLE_SCROLL_DOWN if target_scroll == "bottom" else APPLE_SCROLL_UP
                try:
                    operation = device_service.swipe(*swipe_args)
                except AppError:
                    operation = None
                if operation is not None:
                    current_scroll = target_scroll
                    if context is not None:
                        context.emit(
                            "device_action",
                            "Scrolled AP recovery list before assist selection.",
                            data={
                                "role": f"apple_scroll_{target_scroll}",
                                "apple": apple,
                                "operation": operation.to_dict(),
                            },
                        )
                        if wait_seconds > 0:
                            context.sleep(wait_seconds)
                    current_screenshot = (
                        snapshot() if callable(snapshot) else device_service.snapshot()
                    )
                    match = _optional_assist_match(
                        recognizer,
                        "match_apple",
                        current_screenshot,
                        server,
                        apple,
                    )
        if (
            match is not None
            and match.matched
            and getattr(match, "color_available", None) is not False
        ):
            return apple, match
    return None
