from __future__ import annotations

from time import monotonic
from typing import Any

from webapp.core.models import MatchResult
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.recognition import RecognitionService


DIAGNOSTIC_JOB_KIND = "diagnostic.template-tap"


def register_diagnostic_job(
    job_manager: JobManager,
    device_service: DeviceService,
    recognition: RecognitionService,
) -> None:
    if job_manager.has_kind(DIAGNOSTIC_JOB_KIND):
        return

    def handler(context: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
        template_path = _required_string(payload, "template_path")
        threshold = _number(payload, "threshold", 0.8, minimum=0.0, maximum=1.0)
        timeout_seconds = _number(payload, "timeout_seconds", 10.0, minimum=0.1, maximum=300.0)
        poll_interval = _number(payload, "poll_interval", 0.5, minimum=0.05, maximum=10.0)
        tap_on_match = payload.get("tap_on_match", True)
        if not isinstance(tap_on_match, bool):
            raise ValueError("tap_on_match must be a boolean.")

        match, attempts = _wait_for_template(
            context,
            device_service,
            recognition,
            template_path,
            threshold,
            timeout_seconds,
            poll_interval,
            step="wait_for_template",
        )
        result: dict[str, Any] = {
            "match": match.to_dict(),
            "attempts": attempts,
            "tapped": False,
        }

        if tap_on_match:
            context.checkpoint("tap_match", progress=0.75)
            operation = device_service.tap(match.center[0], match.center[1])
            context.emit(
                "device_action",
                "Tapped matched template center.",
                data={"x": match.center[0], "y": match.center[1]},
            )
            result["tapped"] = operation.ok
            result["tap"] = operation.to_dict()

        verify_template = payload.get("verify_template_path")
        if verify_template is not None:
            if not isinstance(verify_template, str) or not verify_template.strip():
                raise ValueError("verify_template_path must be a non-empty string.")
            verify_timeout = _number(
                payload,
                "verify_timeout_seconds",
                timeout_seconds,
                minimum=0.1,
                maximum=300.0,
            )
            verify_match, verify_attempts = _wait_for_template(
                context,
                device_service,
                recognition,
                verify_template.strip(),
                threshold,
                verify_timeout,
                poll_interval,
                step="verify_template",
            )
            result["verification"] = verify_match.to_dict()
            result["verification_attempts"] = verify_attempts

        context.checkpoint("complete", progress=1.0, message="Diagnostic completed.")
        return result

    job_manager.register(DIAGNOSTIC_JOB_KIND, handler, requires_device=True)


def _wait_for_template(
    context: RunContext,
    device_service: DeviceService,
    recognition: RecognitionService,
    template_path: str,
    threshold: float,
    timeout_seconds: float,
    poll_interval: float,
    *,
    step: str,
) -> tuple[MatchResult, int]:
    started = monotonic()
    attempts = 0
    while True:
        elapsed = monotonic() - started
        context.checkpoint(step, progress=min(elapsed / timeout_seconds, 0.99))
        screenshot = device_service.snapshot()
        match = recognition.match_template(screenshot, template_path, threshold)
        attempts += 1
        context.emit(
            "recognition",
            "Template recognition completed.",
            data={
                "template_path": template_path,
                "matched": match.matched,
                "confidence": match.confidence,
                "threshold": threshold,
                "attempt": attempts,
            },
        )
        if match.matched:
            return match, attempts
        if monotonic() - started >= timeout_seconds:
            raise TimeoutError(
                f"Template {template_path} did not match within {timeout_seconds:.2f} seconds."
            )
        context.sleep(poll_interval)


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string.")
    return value.strip()


def _number(
    payload: dict[str, Any],
    key: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number.")
    result = float(value)
    if result < minimum or result > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}.")
    return result
