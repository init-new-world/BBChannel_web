from webapp.automation.recovery import create_recovery_handler


class _ScriptData:
    def __init__(self, enabled=True):
        self.enabled = enabled

    def get_setting_plan(self, _name):
        return {"run": {"game_crash_restart": self.enabled}}


class _Operation:
    def to_dict(self):
        return {"ok": True, "action": "restart_game"}


class _Device:
    def __init__(self):
        self.packages = []

    def restart_game(self, package_name=None):
        self.packages.append(package_name)
        return _Operation()


class _Context:
    def __init__(self):
        self.events = []

    def checkpoint(self, step, **_options):
        self.events.append(("checkpoint", step))

    def emit(self, event_type, message, **options):
        self.events.append((event_type, message, options))

    def sleep(self, _seconds):
        return None


def test_recovery_restarts_game_and_waits_for_recognized_stage():
    device = _Device()
    stages = iter(("unknown", "prepare"))

    def detect(_context, _payload):
        return {"stage": next(stages)}

    handler = create_recovery_handler(_ScriptData(), device, detect)

    result = handler(
        _Context(),
        {
            "setting_name": "demo",
            "package_name": "com.example.fgo",
            "launch_wait_seconds": 0,
            "poll_interval": 0,
            "timeout_seconds": 1,
        },
    )

    assert result["recovered"] is True
    assert result["stage"] == "prepare"
    assert result["attempts"] == 2
    assert device.packages == ["com.example.fgo"]


def test_recovery_does_not_restart_when_setting_is_disabled():
    device = _Device()
    handler = create_recovery_handler(
        _ScriptData(enabled=False),
        device,
        lambda _context, _payload: {"stage": "assist"},
    )

    result = handler(_Context(), {"setting_name": "demo"})

    assert result == {
        "setting_name": "demo",
        "recovered": False,
        "reason": "game_crash_restart_disabled",
        "stage": "unknown",
    }
    assert device.packages == []
