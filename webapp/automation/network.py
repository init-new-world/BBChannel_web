from __future__ import annotations

from typing import Any

from webapp.automation.interaction import match_touch_point, randomized_wait_seconds
from webapp.core.errors import AppError, ErrorCode


def reconnect_if_present(
    context: Any,
    device_service: Any,
    recognition: Any,
    screenshot: bytes,
    server: str,
    *,
    action_wait_seconds: float,
    random_time: float,
    random_touch: bool,
) -> bool:
    try:
        match = recognition.match_template(
            screenshot,
            f"battle/{server.upper()}/reconnect.png",
            threshold=0.85,
            scales=(1.0, 0.75, 2 / 3, 0.5),
        )
    except AppError as exc:
        if exc.code == ErrorCode.TEMPLATE_NOT_FOUND:
            return False
        raise
    if not match.matched:
        return False

    operation = device_service.tap(
        *match_touch_point(match, enabled=random_touch)
    )
    context.emit(
        "device_action",
        "Requested a network reconnection.",
        data={"role": "reconnect", "operation": operation.to_dict()},
    )
    context.sleep(randomized_wait_seconds(action_wait_seconds, random_time))
    return True
