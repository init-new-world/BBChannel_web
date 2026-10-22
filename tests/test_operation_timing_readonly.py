import pytest

from tests.test_operation_timing import timed_device


def test_legacy_invalid_timing_does_not_block_capture_but_cannot_actuate(timed_device):
    devices, trace = timed_device
    with devices.operation_timing(trace.append, before="legacy", after=None):
        assert devices.snapshot() == b"frame"
        with pytest.raises(ValueError, match="operation"):
            devices.tap(20, 30)
    assert trace == ["snapshot"]
    assert not devices.operation_timing_active()
