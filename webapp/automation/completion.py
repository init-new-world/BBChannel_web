from __future__ import annotations

import hashlib
from time import monotonic
from typing import Any

from webapp.automation.interaction import (
    configured_random_time,
    match_touch_point,
    randomized_wait_seconds,
)
from webapp.automation.network import reconnect_if_present
from webapp.core.errors import AppError, ErrorCode
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService


BATTLE_COMPLETE_JOB_KIND = "battle.complete"


def create_completion_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognition: RecognitionService,
    resources: ResourceService,
):

    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        repeat = payload.get("repeat", False)
        if not isinstance(repeat, bool):
            raise ValueError("repeat must be a boolean.")
        timeout_seconds = _number(payload, "timeout_seconds", 180, 0.1, 600)
        poll_interval = _number(payload, "poll_interval", 0.5, 0, 10)
        action_wait_seconds = _number(payload, "action_wait_seconds", 0.5, 0, 10)
        initial_drop_count = payload.get("initial_drop_count", 0)
        if (
            isinstance(initial_drop_count, bool)
            or not isinstance(initial_drop_count, int)
            or initial_drop_count < 0
        ):
            raise ValueError("initial_drop_count must be a non-negative integer.")
        plan = script_data.get_setting_plan(setting_name.strip())
        random_touch = bool(plan["run"].get("random_touch"))
        random_time = configured_random_time(plan["run"].get("random_time", 0))
        server = str(plan["server"]).upper()
        drop_limit = int(plan["run"]["drop_stop_num"])
        drop_template = _resolve_drop_template(
            resources,
            plan["run"]["drop_image"],
        )
        started = monotonic()
        attempts = 0
        actions: list[str] = []
        drop_count = initial_drop_count
        observed_drop_frames: set[str] = set()

        while monotonic() - started <= timeout_seconds:
            elapsed = monotonic() - started
            context.checkpoint(
                "complete_battle",
                progress=min(elapsed / timeout_seconds, 0.95),
            )
            screenshot = device_service.snapshot()
            attempts += 1
            if reconnect_if_present(
                context,
                device_service,
                recognition,
                screenshot,
                server,
                action_wait_seconds=action_wait_seconds,
                random_time=random_time,
                random_touch=random_touch,
            ):
                actions.append("reconnect")
                continue
            screenshot_digest = hashlib.sha256(screenshot).hexdigest()
            if (
                drop_limit > 0
                and drop_template is not None
                and screenshot_digest not in observed_drop_frames
            ):
                observed_drop_frames.add(screenshot_digest)
                drop_matches = recognition.match_template_all(
                    screenshot,
                    drop_template,
                    threshold=0.85,
                    scales=(1.0, 0.75, 2 / 3, 0.5),
                    max_results=100,
                )
                drop_count += len(drop_matches)
                context.emit(
                    "recognition",
                    "Configured battle drops counted.",
                    data={
                        "frame_drop_count": len(drop_matches),
                        "drop_count": drop_count,
                        "drop_limit": drop_limit,
                    },
                )
                if drop_count >= drop_limit:
                    context.checkpoint(
                        "complete",
                        progress=1.0,
                        message="Stopped after reaching the configured drop limit.",
                    )
                    return {
                        "setting_name": setting_name.strip(),
                        "complete": False,
                        "stopped": True,
                        "reason": "drop_limit",
                        "drop_count": drop_count,
                        "actions": actions,
                        "attempts": attempts,
                    }
            if plan["run"]["full_friendship_stop"]:
                friendship_markers = (
                    _match_optional(
                        recognition,
                        screenshot,
                        f"battle/{server}/{template_name}.png",
                    )
                    for template_name in ("jblevel10", "jbMax")
                )
                if any(
                    marker is not None and marker.matched
                    for marker in friendship_markers
                ):
                    context.checkpoint(
                        "complete",
                        progress=1.0,
                        message="Stopped after reaching full friendship.",
                    )
                    return {
                        "setting_name": setting_name.strip(),
                        "complete": False,
                        "stopped": True,
                        "reason": "full_friendship",
                        "drop_count": drop_count,
                        "actions": actions,
                        "attempts": attempts,
                    }
            run_again = _match_optional(
                recognition,
                screenshot,
                f"battle/{server}/run_again.png",
            )
            if run_again is not None and run_again.matched:
                if repeat:
                    operation = device_service.tap(
                        *match_touch_point(run_again, enabled=random_touch)
                    )
                    actions.append("run_again")
                    context.emit(
                        "device_action",
                        "Started the next run.",
                        data={"role": "run_again", "operation": operation.to_dict()},
                    )
                    context.sleep(
                        randomized_wait_seconds(action_wait_seconds, random_time)
                    )
                context.checkpoint(
                    "complete",
                    progress=1.0,
                    message="Battle settlement completed.",
                )
                return {
                    "setting_name": setting_name.strip(),
                    "complete": True,
                    "repeated": repeat,
                    "drop_count": drop_count,
                    "actions": actions,
                    "attempts": attempts,
                }

            relationship_up = _match_optional(
                recognition,
                screenshot,
                f"battle/{server}/relationship_up.png",
            )
            if relationship_up is not None and relationship_up.matched:
                operation = device_service.tap(
                    *match_touch_point(relationship_up, enabled=random_touch)
                )
                actions.append("relationship_up")
                context.emit(
                    "device_action",
                    "Advanced friendship level dialog.",
                    data={"role": "relationship_up", "operation": operation.to_dict()},
                )
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue

            add_friend = bool(plan["run"].get("add_friend"))
            friend_action = (
                "apply_for_friend" if add_friend else "finish_without_friend"
            )
            friend_template = "friend_apply_1.png" if add_friend else "friend_apply.png"
            friend_button = _match_optional(
                recognition,
                screenshot,
                f"battle/{server}/{friend_template}",
            )
            if friend_button is not None and friend_button.matched:
                operation = device_service.tap(
                    *match_touch_point(friend_button, enabled=random_touch)
                )
                actions.append(friend_action)
                context.emit(
                    "device_action",
                    "Handled the post-battle friend request.",
                    data={"role": friend_action, "operation": operation.to_dict()},
                )
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue

            next_button = _match_optional(
                recognition,
                screenshot,
                f"battle/{server}/next.png",
            )
            if next_button is not None and next_button.matched:
                operation = device_service.tap(
                    *match_touch_point(next_button, enabled=random_touch)
                )
                actions.append("next")
                context.emit(
                    "device_action",
                    "Advanced battle settlement.",
                    data={"role": "next", "operation": operation.to_dict()},
                )
                context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
                continue

            context.emit(
                "recognition",
                "Battle settlement state checked.",
                data={"attempt": attempts, "state": None},
            )
            context.sleep(poll_interval)

        raise TimeoutError(
            f"Battle settlement did not complete within {timeout_seconds:.2f} seconds."
        )

    return handler


def register_completion_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognition: RecognitionService,
    resources: ResourceService,
) -> None:
    if job_manager.has_kind(BATTLE_COMPLETE_JOB_KIND):
        return
    job_manager.register(
        BATTLE_COMPLETE_JOB_KIND,
        create_completion_handler(
            script_data,
            device_service,
            recognition,
            resources,
        ),
        requires_device=True,
    )


def _match_optional(
    recognition: RecognitionService,
    screenshot: bytes,
    template_path: str,
):
    try:
        return recognition.match_template(
            screenshot,
            template_path,
            threshold=0.85,
            scales=(1.0, 0.75, 2 / 3, 0.5),
        )
    except AppError as exc:
        if exc.code == ErrorCode.TEMPLATE_NOT_FOUND:
            return None
        raise


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


def _resolve_drop_template(
    resources: ResourceService,
    configured_path: object,
) -> str | None:
    if not isinstance(configured_path, str) or not configured_path.strip():
        return None
    filename = configured_path.strip().replace("\\", "/").rsplit("/", 1)[-1]
    if not filename:
        return None
    index = resources.template_index(prefix="drop", query=filename, limit=200)
    matches = [
        str(entry["path"])
        for entry in index["entries"]
        if str(entry["path"]).rsplit("/", 1)[-1].casefold() == filename.casefold()
    ]
    return matches[0] if matches else None
