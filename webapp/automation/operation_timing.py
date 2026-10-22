from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING

from webapp.runtime.jobs import JobHandler

if TYPE_CHECKING:
    from webapp.services.devices import DeviceService
    from webapp.services.script_data import ScriptDataService


def with_script_operation_timing(
    handler: JobHandler, script_data: ScriptDataService, devices: DeviceService,
) -> JobHandler:
    @wraps(handler)
    def timed_handler(context, payload):
        name = payload.get("setting_name")
        if not isinstance(name, str) or not name.strip() or devices.operation_timing_active():
            return handler(context, payload)
        plan = script_data.get_setting_plan(name.strip())
        if not plan.get("validation", {"ok": True})["ok"]:
            return handler(context, payload)
        run = plan.get("run", {})
        before = run.get("interval_before_operation", run.get("interval_before_fight", 0))
        after = run.get("interval_after_operation", run.get("interval_after_fight", 0.1))
        with devices.operation_timing(context.sleep, before=before, after=after):
            return handler(context, payload)

    return timed_handler
