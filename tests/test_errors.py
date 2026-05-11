from webapp.core.errors import AppError, ErrorCode
from webapp.core.models import Capability, ConnectionState, MatchResult


def test_app_error_serializes_to_api_shape():
    error = AppError(
        ErrorCode.ADB_NOT_FOUND,
        "ADB executable was not found.",
        {"searched": ["adb", "adb.exe"]},
    )

    assert error.to_response() == {
        "error": {
            "code": "adb_not_found",
            "message": "ADB executable was not found.",
            "details": {"searched": ["adb", "adb.exe"]},
        }
    }


def test_error_code_contains_known_codes():
    assert ErrorCode.DEVICE_NOT_CONNECTED.value == "device_not_connected"
    assert ErrorCode.TEMPLATE_NOT_FOUND.value == "template_not_found"
    assert ErrorCode.MUMU_UNSUPPORTED_PLATFORM.value == "mumu_unsupported_platform"


def test_core_models_are_json_safe_dicts():
    capability = Capability(name="adb", available=False, reason="ADB missing")
    state = ConnectionState(connected=True, backend="adb", device_id="emulator-5554")
    match = MatchResult(
        template_path="battle/CH/start_battle.png",
        matched=True,
        confidence=0.91,
        threshold=0.85,
        top_left=[10, 20],
        size=[30, 40],
        center=[25, 40],
    )

    assert capability.to_dict() == {
        "name": "adb",
        "available": False,
        "reason": "ADB missing",
    }
    assert state.to_dict() == {
        "connected": True,
        "backend": "adb",
        "device_id": "emulator-5554",
    }
    assert match.to_dict()["center"] == [25, 40]
