from __future__ import annotations

from typing import Any

from webapp.automation.expball import (
    create_expball_enhance_handler,
    create_expball_storage_handler,
    create_expball_summon_handler,
)
from webapp.automation.expball_navigation import create_expball_navigate_handler
from webapp.automation.expball_sell import create_expball_sell_handler
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.expball import ExpBallRecognizer
from webapp.services.script_data import ScriptDataService


EXPBALL_RUN_JOB_KIND = "event.expball.run"
_OVERFLOW_ACTIONS = {
    "stop",
    "storage",
    "sell",
    "storage_then_sell",
    "equipment_enhancement",
    "servant_enhancement",
}
_VALID_CARD_STARS = {3, 4, 5}


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
    sell_handler = create_expball_sell_handler(
        script_data,
        device_service,
        recognizer,
    )
    enhance_handler = create_expball_enhance_handler(
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
            5,
            1,
            100,
        )
        store_first_raw = payload.get("store_first", False)
        if not isinstance(store_first_raw, bool):
            raise ValueError("store_first must be a boolean.")
        auto_store_ce_bombs_raw = payload.get("auto_store_ce_bombs", False)
        if not isinstance(auto_store_ce_bombs_raw, bool):
            raise ValueError("auto_store_ce_bombs must be a boolean.")
        auto_store_ce_bombs = auto_store_ce_bombs_raw
        servant_enhance_interval = _integer(
            payload,
            "servant_enhance_interval",
            1,
            1,
            100,
        )
        overflow_actions = _parse_overflow_actions(payload, store_first_raw)
        overflow_action = (
            overflow_actions[0]
            if len(overflow_actions) == 1
            else ("stop" if not overflow_actions else overflow_actions[0])
        )
        if payload.get("overflow_action") is not None and not payload.get(
            "overflow_actions"
        ):
            overflow_action = str(payload.get("overflow_action") or "stop").lower()
            if store_first_raw and overflow_action in {"stop", "storage", "sell"}:
                overflow_action = "storage_then_sell"
        stars = _parse_card_stars(payload)
        storage_stars = _parse_card_stars(payload, key="storage_stars") or stars
        sell_stars = _parse_card_stars(payload, key="sell_stars") or stars
        storage_target = (
            str(payload.get("storage_target") or "exp").strip().lower()
        )
        sell_target = str(payload.get("sell_target") or "exp").strip().lower()
        if (
            any(
                action in {"storage", "storage_then_sell"}
                for action in overflow_actions
            )
            and storage_target != "ce_bomb"
            and storage_stars is None
        ):
            raise ValueError(
                "overflow_action requires stars to be configured for automatic storage or sell."
            )
        if (
            any(
                action in {"sell", "storage_then_sell"}
                for action in overflow_actions
            )
            and sell_target not in {"servant", "command_code"}
            and sell_stars is None
        ):
            raise ValueError(
                "overflow_action requires stars to be configured for automatic storage or sell."
            )

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
        overflow_payload = dict(common_payload)
        if stars is not None:
            overflow_payload["stars"] = list(stars)
        _copy_option(
            payload,
            overflow_payload,
            "grid_threshold",
            "grid_threshold",
        )
        storage_overflow_payload = dict(overflow_payload)
        if storage_stars is not None:
            storage_overflow_payload["stars"] = list(storage_stars)
        for key in (
            "storage_target",
            "require_locked_and_marked",
            "locker_threshold",
            "mark_threshold",
        ):
            _copy_option(payload, storage_overflow_payload, key, key)
        ce_bomb_storage_payload = dict(common_payload)
        ce_bomb_storage_payload["storage_target"] = "ce_bomb"
        ce_bomb_storage_payload["require_locked_and_marked"] = True
        for key in ("locker_threshold", "mark_threshold"):
            _copy_option(payload, ce_bomb_storage_payload, key, key)
        sell_overflow_payload = dict(overflow_payload)
        if sell_stars is not None:
            sell_overflow_payload["stars"] = list(sell_stars)
        for key in (
            "sell_target",
            "lock_gold_servants",
            "include_fp_gold",
            "select_servant_cards",
            "fp_gold_threshold",
            "lock_inscribed_command_codes",
            "inscribed_threshold",
            "empty_threshold",
            "locker_threshold",
            "switch_command_code_tab",
            "auto_select",
            "allow_qp_full",
        ):
            _copy_option(payload, sell_overflow_payload, key, key)
        equipment_enhance_payload = dict(overflow_payload)
        equipment_enhance_payload["target"] = "equipment"
        for key in (
            "selection_mode",
            "material_select_mode",
            "select_base_first",
            "max_batches",
            "eat_3star",
            "eat3star",
            "eat_4star",
            "eat4star",
            "allow_high_star_materials",
            "lock_full_ce_bombs",
            "mark_full_ce_bombs",
            "stop_when_ce_grid_full",
            "locker_threshold",
            "mark_threshold",
        ):
            _copy_option(payload, equipment_enhance_payload, key, key)
        if auto_store_ce_bombs:
            equipment_enhance_payload.setdefault("lock_full_ce_bombs", True)
            equipment_enhance_payload.setdefault("mark_full_ce_bombs", True)
            equipment_enhance_payload.setdefault("stop_when_ce_grid_full", True)
        servant_enhance_payload = dict(overflow_payload)
        servant_enhance_payload["target"] = "servant"
        for key in (
            "selection_mode",
            "material_select_mode",
            "select_base_first",
            "max_batches",
            "target_level",
            "level_threshold",
            "servant_target",
            "servant_targets",
            "servant_target_threshold",
            "max_base_scrolls",
            "auto_limit_break",
        ):
            _copy_option(payload, servant_enhance_payload, key, key)
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
        for key in ("banner_direction", "l_or_r"):
            _copy_option(payload, navigation_payload, key, key)
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
        for key in (
            "draw_100",
            "draw100by100",
            "lock_targets",
            "lock_lily",
            "lock_habe",
            "lock_hakuno",
            "lock_enough_stop",
            "lock_threshold",
        ):
            _copy_option(payload, summon_payload, key, key)

        summons = 0
        overflow_cycles = 0
        storage_full = False
        servant_targets_completed = False
        locked_cards: list[dict[str, Any]] = []
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
                "locked_cards": list(locked_cards),
                "locked_count": len(locked_cards),
                "overflow_action": overflow_action,
                "overflow_actions": list(overflow_actions),
                "servant_enhance_interval": servant_enhance_interval,
                "auto_store_ce_bombs": auto_store_ce_bombs,
                "overflow_cycles": overflow_cycles,
                "storage_full": storage_full,
                "stages": stages,
            }

        while summons < max_summons:
            context.checkpoint(
                "expball_cycle",
                message="Running experience-material summon cycle.",
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
            cycle_locked = summon_result.get("locked_cards")
            if isinstance(cycle_locked, list):
                locked_cards.extend(
                    item for item in cycle_locked if isinstance(item, dict)
                )
            updated_lock_targets = summon_result.get("lock_targets")
            if isinstance(updated_lock_targets, list) and updated_lock_targets:
                summon_payload["lock_targets"] = updated_lock_targets
                for flag_key in ("lock_lily", "lock_habe", "lock_hakuno"):
                    summon_payload.pop(flag_key, None)
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
            if not overflow_actions or overflow_actions == ("stop",):
                return finish(
                    completed=False,
                    stopped=True,
                    reason="box_full",
                )
            if overflow_cycles >= max_overflow_cycles:
                return finish(
                    completed=False,
                    stopped=True,
                    reason="overflow_limit",
                )

            for action in overflow_actions:
                if action == "storage_then_sell":
                    if not storage_full:
                        store_nav_payload = dict(navigation_payload)
                        store_nav_payload["destination"] = "storage"
                        store_nav_result = navigate_handler(
                            context,
                            store_nav_payload,
                        )
                        record("navigate_storage", store_nav_result)
                        if store_nav_result.get("completed") is not True:
                            return finish(
                                completed=False,
                                stopped=True,
                                reason=str(
                                    store_nav_result.get("reason")
                                    or "navigation_stopped"
                                ),
                            )
                        storage_result = storage_handler(
                            context,
                            dict(storage_overflow_payload),
                        )
                        record("storage", storage_result)
                        if storage_result.get("completed") is True:
                            continue
                        if storage_result.get("reason") != "storage_full":
                            return finish(
                                completed=False,
                                stopped=True,
                                reason=str(
                                    storage_result.get("reason")
                                    or "storage_stopped"
                                ),
                            )
                        storage_full = True

                    sell_nav_payload = dict(navigation_payload)
                    sell_nav_payload["destination"] = "sell"
                    sell_nav_result = navigate_handler(
                        context,
                        sell_nav_payload,
                    )
                    record("navigate_sell", sell_nav_result)
                    if sell_nav_result.get("completed") is not True:
                        return finish(
                            completed=False,
                            stopped=True,
                            reason=str(
                                sell_nav_result.get("reason")
                                or "navigation_stopped"
                            ),
                        )
                    sell_result = sell_handler(
                        context,
                        dict(sell_overflow_payload),
                    )
                    record("sell", sell_result)
                    if sell_result.get("completed") is not True:
                        return finish(
                            completed=False,
                            stopped=True,
                            reason=str(
                                sell_result.get("reason") or "sell_stopped"
                            ),
                        )
                    continue

                if action == "storage":
                    if storage_full:
                        if len(overflow_actions) > 1:
                            continue
                        return finish(
                            completed=False,
                            stopped=True,
                            reason="storage_full",
                        )
                    overflow_nav_payload = dict(navigation_payload)
                    overflow_nav_payload["destination"] = "storage"
                    overflow_nav_result = navigate_handler(
                        context,
                        overflow_nav_payload,
                    )
                    record("navigate_storage", overflow_nav_result)
                    if overflow_nav_result.get("completed") is not True:
                        return finish(
                            completed=False,
                            stopped=True,
                            reason=str(
                                overflow_nav_result.get("reason")
                                or "navigation_stopped"
                            ),
                        )
                    overflow_result = storage_handler(
                        context,
                        dict(storage_overflow_payload),
                    )
                    record("storage", overflow_result)
                    if overflow_result.get("reason") == "storage_full":
                        storage_full = True
                        if len(overflow_actions) > 1:
                            continue
                    if overflow_result.get("completed") is not True:
                        return finish(
                            completed=False,
                            stopped=True,
                            reason=str(
                                overflow_result.get("reason")
                                or "storage_stopped"
                            ),
                        )
                    continue

                if action == "sell":
                    overflow_nav_payload = dict(navigation_payload)
                    overflow_nav_payload["destination"] = "sell"
                    overflow_nav_result = navigate_handler(
                        context,
                        overflow_nav_payload,
                    )
                    record("navigate_sell", overflow_nav_result)
                    if overflow_nav_result.get("completed") is not True:
                        return finish(
                            completed=False,
                            stopped=True,
                            reason=str(
                                overflow_nav_result.get("reason")
                                or "navigation_stopped"
                            ),
                        )
                    overflow_result = sell_handler(
                        context,
                        dict(sell_overflow_payload),
                    )
                    record("sell", overflow_result)
                    if overflow_result.get("completed") is not True:
                        return finish(
                            completed=False,
                            stopped=True,
                            reason=str(
                                overflow_result.get("reason") or "sell_stopped"
                            ),
                        )
                    continue

                if action == "equipment_enhancement":
                    overflow_nav_payload = dict(navigation_payload)
                    overflow_nav_payload["destination"] = (
                        "equipment_enhancement"
                    )
                    overflow_nav_result = navigate_handler(
                        context,
                        overflow_nav_payload,
                    )
                    record(
                        "navigate_equipment_enhancement",
                        overflow_nav_result,
                    )
                    if overflow_nav_result.get("completed") is not True:
                        return finish(
                            completed=False,
                            stopped=True,
                            reason=str(
                                overflow_nav_result.get("reason")
                                or "navigation_stopped"
                            ),
                        )
                    overflow_result = enhance_handler(
                        context,
                        dict(equipment_enhance_payload),
                    )
                    record("equipment_enhancement", overflow_result)
                    if overflow_result.get("completed") is not True:
                        return finish(
                            completed=False,
                            stopped=True,
                            reason=str(
                                overflow_result.get("reason")
                                or "equipment_enhancement_stopped"
                            ),
                        )
                    grid_full = (
                        overflow_result.get("reason") == "ce_bomb_grid_full"
                    )
                    has_locked_bombs = bool(
                        overflow_result.get("locked_ce_bomb_slots")
                        or overflow_result.get("marked_ce_bomb_slots")
                    )
                    if not storage_full and (
                        grid_full
                        or (auto_store_ce_bombs and has_locked_bombs)
                    ):
                        store_nav_payload = dict(navigation_payload)
                        store_nav_payload["destination"] = "storage"
                        store_nav_result = navigate_handler(
                            context,
                            store_nav_payload,
                        )
                        record("navigate_storage", store_nav_result)
                        if store_nav_result.get("completed") is not True:
                            return finish(
                                completed=False,
                                stopped=True,
                                reason=str(
                                    store_nav_result.get("reason")
                                    or "navigation_stopped"
                                ),
                            )
                        ce_store_result = storage_handler(
                            context,
                            dict(ce_bomb_storage_payload),
                        )
                        record("storage", ce_store_result)
                        if ce_store_result.get("reason") == "storage_full":
                            storage_full = True
                        elif ce_store_result.get("completed") is not True:
                            return finish(
                                completed=False,
                                stopped=True,
                                reason=str(
                                    ce_store_result.get("reason")
                                    or "storage_stopped"
                                ),
                            )
                        elif grid_full:
                            resume_nav_payload = dict(navigation_payload)
                            resume_nav_payload["destination"] = (
                                "equipment_enhancement"
                            )
                            resume_nav_result = navigate_handler(
                                context,
                                resume_nav_payload,
                            )
                            record(
                                "navigate_equipment_enhancement",
                                resume_nav_result,
                            )
                            if resume_nav_result.get("completed") is not True:
                                return finish(
                                    completed=False,
                                    stopped=True,
                                    reason=str(
                                        resume_nav_result.get("reason")
                                        or "navigation_stopped"
                                    ),
                                )
                            resume_payload = dict(equipment_enhance_payload)
                            resume_payload["stop_when_ce_grid_full"] = False
                            resume_result = enhance_handler(
                                context,
                                resume_payload,
                            )
                            record("equipment_enhancement", resume_result)
                            if resume_result.get("completed") is not True:
                                return finish(
                                    completed=False,
                                    stopped=True,
                                    reason=str(
                                        resume_result.get("reason")
                                        or "equipment_enhancement_stopped"
                                    ),
                                )
                    continue

                if action == "servant_enhancement":
                    if servant_targets_completed:
                        continue
                    if (
                        "equipment_enhancement" in overflow_actions
                        and servant_enhance_interval > 1
                        and overflow_cycles % servant_enhance_interval != 0
                    ):
                        continue
                    overflow_nav_payload = dict(navigation_payload)
                    overflow_nav_payload["destination"] = "servant_enhancement"
                    overflow_nav_result = navigate_handler(
                        context,
                        overflow_nav_payload,
                    )
                    record(
                        "navigate_servant_enhancement",
                        overflow_nav_result,
                    )
                    if overflow_nav_result.get("completed") is not True:
                        return finish(
                            completed=False,
                            stopped=True,
                            reason=str(
                                overflow_nav_result.get("reason")
                                or "navigation_stopped"
                            ),
                        )
                    overflow_result = enhance_handler(
                        context,
                        dict(servant_enhance_payload),
                    )
                    record("servant_enhancement", overflow_result)
                    if overflow_result.get("completed") is not True:
                        return finish(
                            completed=False,
                            stopped=True,
                            reason=str(
                                overflow_result.get("reason")
                                or "servant_enhancement_stopped"
                            ),
                        )
                    if overflow_result.get("reason") == "target_level_reached":
                        servant_targets_completed = True
                        if len(overflow_actions) == 1:
                            return finish(
                                completed=True,
                                stopped=False,
                                reason="target_level_reached",
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


def _parse_overflow_actions(
    payload: dict[str, Any],
    store_first: bool,
) -> tuple[str, ...]:
    raw_list = payload.get("overflow_actions")
    if raw_list is not None:
        if isinstance(raw_list, str):
            items = [
                part.strip().lower()
                for part in raw_list.split(",")
                if part.strip()
            ]
        elif isinstance(raw_list, (list, tuple)):
            items = []
            for item in raw_list:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError(
                        "overflow_actions entries must be non-empty strings."
                    )
                items.append(item.strip().lower())
        else:
            raise ValueError(
                "overflow_actions must be a list or comma-separated string."
            )
        deduped: list[str] = []
        for item in items:
            if item not in _OVERFLOW_ACTIONS:
                raise ValueError(
                    "overflow_actions entries must be stop, storage, sell, "
                    "storage_then_sell, equipment_enhancement, or servant_enhancement."
                )
            if item == "stop":
                continue
            if item not in deduped:
                deduped.append(item)
        if store_first and "sell" in deduped and "storage" not in deduped:
            sell_idx = deduped.index("sell")
            deduped[sell_idx] = "storage_then_sell"
        return tuple(deduped) if deduped else ("stop",)

    overflow_action = str(payload.get("overflow_action") or "stop").strip().lower()
    if store_first and overflow_action in {"stop", "storage", "sell"}:
        overflow_action = "storage_then_sell"
    if overflow_action not in _OVERFLOW_ACTIONS:
        raise ValueError(
            "overflow_action must be stop, storage, sell, "
            "storage_then_sell, equipment_enhancement, or servant_enhancement."
        )
    return (overflow_action,)


def _parse_card_stars(
    payload: dict[str, Any],
    *,
    key: str = "stars",
) -> tuple[int, ...] | None:
    if key not in payload or payload[key] is None:
        return None
    raw = payload[key]
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ValueError(f"{key} must be a non-empty list of 3, 4, or 5.")
    result: list[int] = []
    for item in raw:
        if (
            isinstance(item, bool)
            or not isinstance(item, int)
            or item not in _VALID_CARD_STARS
        ):
            raise ValueError(f"{key} must contain only 3, 4, or 5.")
        if item not in result:
            result.append(item)
    return tuple(result)
