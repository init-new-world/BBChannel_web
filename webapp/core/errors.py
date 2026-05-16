from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    ADB_NOT_FOUND = "adb_not_found"
    ADB_TIMEOUT = "adb_timeout"
    ADB_NO_DEVICES = "adb_no_devices"
    ADB_DEVICE_OFFLINE = "adb_device_offline"
    ADB_CONNECT_FAILED = "adb_connect_failed"
    DEVICE_NOT_CONNECTED = "device_not_connected"
    SNAPSHOT_FAILED = "snapshot_failed"
    TAP_FAILED = "tap_failed"
    SWIPE_FAILED = "swipe_failed"
    TEMPLATE_NOT_FOUND = "template_not_found"
    TEMPLATE_LOAD_FAILED = "template_load_failed"
    DATA_FILE_NOT_FOUND = "data_file_not_found"
    DATA_FILE_INVALID = "data_file_invalid"
    OPENCV_UNAVAILABLE = "opencv_unavailable"
    MATCH_FAILED = "match_failed"
    MUMU_UNSUPPORTED_PLATFORM = "mumu_unsupported_platform"
    MUMU_DLL_NOT_FOUND = "mumu_dll_not_found"


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_response(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "details": self.details,
            }
        }
