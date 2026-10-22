from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from tests.test_device_service import FakeBackend
from webapp.core.models import OperationResult
from webapp.runtime import JobDatabase, JobManager
from webapp.runtime.jobs import JobCancelled, UnknownJobKindError
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog


@pytest.fixture
def timed_device():
    trace = []

    class Backend(FakeBackend):
        def snapshot(self, device_id):
            trace.append("snapshot")
            return b"frame"

        def tap(self, device_id, x, y):
            trace.append("tap")
            return OperationResult(ok=True, action="tap")

        def swipe(self, *args):
            trace.append("swipe")
            return OperationResult(ok=True, action="swipe")

    devices = DeviceService([Backend()], EventLog())
    devices.connect("fake", "dev1")
    yield devices, trace
    devices.close()


def test_operation_delays_surround_each_action_but_not_capture_or_manual_calls(timed_device):
    devices, trace = timed_device
    with devices.operation_timing(trace.append, before=0.2, after=0.3):
        devices.tap(20, 30)
        devices.snapshot()
        devices.swipe(20, 30, 50, 60, 700)
    devices.tap(20, 30)

    assert trace == [0.2, "tap", 0.3, "snapshot", 0.2, "swipe", 0.3, "tap"]
    assert not devices.operation_timing_active()


@pytest.mark.parametrize("after", [0, 0.05, 0.1])
def test_original_post_operation_minimum_is_one_tenth_second(timed_device, after):
    devices, trace = timed_device
    with devices.operation_timing(trace.append, before=0, after=after):
        devices.tap(20, 30)
    assert trace == [0, "tap", 0.1]


@pytest.mark.parametrize("phase", ["before", "after"])
@pytest.mark.parametrize("invalid", [None, True, "0.5", -1, 601, float("nan"), float("inf")])
def test_invalid_operation_timing_is_rejected_before_device_actions(timed_device, phase, invalid):
    devices, trace = timed_device
    with pytest.raises(ValueError, match="operation"):
        with devices.operation_timing(trace.append, **{phase: invalid}):
            devices.tap(20, 30)
    assert trace == []
    assert not devices.operation_timing_active()


@pytest.mark.parametrize("cancel_at", [0.2, 0.3])
def test_cancellation_during_operation_wait_cleans_up_context(timed_device, cancel_at):
    devices, trace = timed_device

    def sleep(seconds):
        trace.append(seconds)
        if seconds == cancel_at:
            raise JobCancelled()

    with pytest.raises(JobCancelled):
        with devices.operation_timing(sleep, before=0.2, after=0.3):
            devices.tap(20, 30)
    assert trace == ([0.2] if cancel_at == 0.2 else [0.2, "tap", 0.3])
    assert not devices.operation_timing_active()
    devices.tap(20, 30)
    assert trace[-1] == "tap"


def test_nested_timing_restores_outer_scope_and_does_not_leak_to_another_thread(timed_device):
    devices, trace = timed_device
    with devices.operation_timing(trace.append, before=0.2, after=0.3):
        with devices.operation_timing(trace.append, before=0.4, after=0.5):
            devices.tap(20, 30)
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(devices.tap, 20, 30).result()
        devices.tap(20, 30)
    assert trace == [0.4, "tap", 0.5, "tap", 0.2, "tap", 0.3]


def test_failed_action_does_not_send_a_success_wait_and_resets_scope(timed_device, monkeypatch):
    devices, trace = timed_device

    def fail(*args):
        trace.append("failed tap")
        raise RuntimeError("Tap failed")

    monkeypatch.setattr(devices._backends["fake"], "tap", fail)
    with pytest.raises(RuntimeError, match="Tap failed"):
        with devices.operation_timing(trace.append, before=0.2, after=0.3):
            devices.tap(20, 30)
    assert trace == [0.2, "failed tap"]
    assert not devices.operation_timing_active()


def test_script_timing_wrapper_applies_once_to_nested_stages(timed_device):
    from webapp.automation.operation_timing import with_script_operation_timing

    devices, trace = timed_device
    loads = []
    script_data = SimpleNamespace(get_setting_plan=lambda name: (loads.append(name) or {
        "run": {"interval_before_operation": 0.2, "interval_after_operation": 0.3},
    }))
    context = SimpleNamespace(sleep=trace.append)

    def stage(context, payload):
        devices.tap(20, 30)
        return {"ready": True}

    inner = with_script_operation_timing(stage, script_data, devices)
    outer = with_script_operation_timing(inner, script_data, devices)
    assert outer(context, {"setting_name": " demo "}) == {"ready": True}
    assert trace == [0.2, "tap", 0.3]
    assert loads == ["demo"]
    assert not devices.operation_timing_active()


def test_job_handler_wrapping_preserves_device_lease_and_result(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        manager.register("probe", lambda context, payload: {"value": payload["value"]}, requires_device=True)
        manager.wrap_handler("probe", lambda handler: lambda context, payload: {**handler(context, payload), "wrapped": True})
        assert manager.requires_device("probe") is True
        job = manager.start("probe", {"value": 7}, device_key="fake:dev1")
        result = manager.wait(job.job_id, timeout=3)
    assert result.result == {"value": 7, "wrapped": True}


def test_wrapping_an_unknown_job_does_not_register_it(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        with pytest.raises(UnknownJobKindError):
            manager.wrap_handler("missing", lambda handler: handler)
        assert manager.registered_kinds() == []


@pytest.mark.parametrize("run", [{}, {"interval_before_fight": 0, "interval_after_fight": 0}])
def test_script_wrapper_applies_original_default_and_legacy_minimum(timed_device, run):
    from webapp.automation.operation_timing import with_script_operation_timing

    devices, trace = timed_device
    script_data = SimpleNamespace(get_setting_plan=lambda name: {"run": run})
    context = SimpleNamespace(sleep=trace.append)
    handler = with_script_operation_timing(lambda context, payload: devices.tap(20, 30), script_data, devices)
    handler(context, {"setting_name": "demo"})
    assert trace == [0, "tap", 0.1]


def test_app_scopes_profile_operations_without_delaying_manual_api_calls(tmp_path, timed_device, monkeypatch):
    import json

    from webapp.app import create_app
    from webapp.automation.run import create_full_run_handler
    from webapp.runtime import RunContext
    from webapp.services.script_data import ScriptDataService

    devices, trace = timed_device
    data = tmp_path / "data"
    (data / "settings").mkdir(parents=True)
    (data / "settings" / "demo.json").write_text(json.dumps({
        "server": "CH", "round1_turns": 1, "intervalBF": 0.2, "intervalAF": 0.3,
    }))
    (data / "servant_info_CH.json").write_text("{}")
    monkeypatch.setattr(RunContext, "sleep", lambda self, seconds: trace.append(seconds))
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        def handler(context, payload):
            devices.tap(20, 30)
            return {"ready": True}

        manager.register("battle.probe", handler, requires_device=True)
        manager.register("diagnostic.probe", handler, requires_device=True)
        def stage(context, payload):
            devices.tap(20, 30)
            return {"complete": True}

        manager.register(
            "battle.run", create_full_run_handler(ScriptDataService(data), stage, stage, stage, stage),
            requires_device=True,
        )
        create_app(assets_dir=tmp_path / "assets", data_dir=data, device_service=devices, job_manager=manager)
        job = manager.start("battle.probe", {"setting_name": "demo"}, device_key="fake:dev1")
        result = manager.wait(job.job_id, timeout=3)
        diagnostic = manager.start("diagnostic.probe", {"setting_name": "demo"}, device_key="fake:dev1")
        assert manager.wait(diagnostic.job_id, timeout=3).result == {"ready": True}
        full_run = manager.start("battle.run", {"setting_name": "demo"}, device_key="fake:dev1")
        assert manager.wait(full_run.job_id, timeout=3).result["runs_completed"] == 1
    assert result.result == {"ready": True}
    devices.tap(20, 30)
    assert trace == [0.2, "tap", 0.3, "tap"] + [0.2, "tap", 0.3] * 4 + ["tap"]
